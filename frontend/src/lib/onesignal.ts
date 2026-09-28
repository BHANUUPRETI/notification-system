/**
 * OneSignal Web SDK integration.
 *
 * The backend can send Web Push through either raw VAPID (pywebpush) or
 * OneSignal. The browser has to subscribe through the *matching* transport, so
 * this module loads the OneSignal Web SDK, asks for permission, and returns the
 * subscription id the backend needs to target that device.
 *
 * The SDK is loaded lazily and only when the backend reports OneSignal as the
 * active backend - a VAPID-only deployment never downloads it.
 *
 * API differences between OneSignal SDK versions are handled defensively:
 * v15 exposes getSubscriptionId() on the root, v16 moved it under
 * OneSignal.User.PushSubscription.
 */

const SDK_SRC = "https://cdn.onesignal.com/sdks/web/v16/OneSignalSDK.page.js";

/** Minimal shape of the parts of the SDK we touch. */
interface OneSignalLike {
  init: (options: Record<string, unknown>) => Promise<void>;
  login?: (externalId: string) => Promise<void>;
  logout?: () => Promise<void>;
  getSubscriptionId?: () => Promise<string | null>;
  setConsentGiven?: (granted: boolean) => void;
  setConsentRequired?: (required: boolean) => void;
  Notifications?: {
    requestPermission?: () => Promise<boolean>;
    permission?: boolean;
    addEventListener?: (event: string, cb: (payload: unknown) => void) => void;
  };
  User?: {
    PushSubscription?: { id?: string | null };
    AddAlias?: (label: string, id: string) => void;
  };
  Slidedown?: { promptPush?: (options?: unknown) => Promise<void> };
}

declare global {
  interface Window {
    /** OneSignal v16 queues pre-load calls on this plain array. */
    OneSignalDeferred?: OneSignalQueue;
    OneSignal?: OneSignalLike;
  }
}

/** A plain array of callbacks the SDK drains once it has loaded. */
type OneSignalQueue = Array<(sdk: OneSignalLike) => void>;

let sdkPromise: Promise<OneSignalLike> | null = null;
let initializedAppId: string | null = null;
let currentExternalId: string | null = null;

/** True when the SDK has already been injected into the page. */
export function isOneSignalLoaded(): boolean {
  return typeof window !== "undefined" && window.OneSignal !== undefined;
}

function loadScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${SDK_SRC}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = SDK_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load the OneSignal SDK."));
    document.head.appendChild(script);
  });
}

function deferred(): OneSignalQueue {
  window.OneSignalDeferred = window.OneSignalDeferred ?? [];
  return window.OneSignalDeferred;
}

/** Resolve once the SDK is live, whether it is already loaded or arrives later. */
function whenReady(timeoutMs = 10_000): Promise<OneSignalLike> {
  if (window.OneSignal) return Promise.resolve(window.OneSignal);
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error("Timed out waiting for the OneSignal SDK. Check your ad blocker.")),
      timeoutMs,
    );
    deferred().push((sdk) => {
      clearTimeout(timer);
      resolve(sdk);
    });
  });
}

/**
 * Load the SDK and return a handle to it. Safe to call repeatedly - the script
 * is only injected once and the promise is cached.
 */
export async function loadOneSignal(): Promise<OneSignalLike> {
  if (sdkPromise) return sdkPromise;

  // The queue has to exist before the script runs, so nothing is missed.
  deferred();

  sdkPromise = (async () => {
    await loadScript();
    return whenReady();
  })();

  try {
    return await sdkPromise;
  } catch (error) {
    sdkPromise = null; // allow a retry
    throw error;
  }
}

function initOptions(appId: string): Record<string, unknown> {
  return {
    appId,
    // OneSignal needs to know where its worker lives when the SDK is served
    // from a different origin or sub-path.
    serviceWorkerPath: "/OneSignalSDKWorker.js",
    serviceWorkerParam: { scope: "/" },
    notifyButton: { enable: false },
    welcomeNotification: { disable: true },
  };
}

/** Initialise the SDK for *appId* and tag it with the signed-in user id. */
export async function initOneSignal(appId: string, externalId?: string): Promise<OneSignalLike> {
  const sdk = await loadOneSignal();

  // OneSignal.init() is a page-lifetime operation. Re-running it every time the
  // authenticated user changes can leave the SDK in an inconsistent state.
  if (initializedAppId !== appId) {
    if (sdk.init) await sdk.init(initOptions(appId));
    initializedAppId = appId;
    currentExternalId = null;
  }

  if (externalId && currentExternalId !== externalId) {
    // Re-associate the existing browser subscription with the currently signed-in
    // app user. This must happen on every account switch/login; it does NOT ask
    // the browser for notification permission again.
    try {
      if (sdk.login) await sdk.login(externalId);
      if (sdk.User?.AddAlias) sdk.User.AddAlias("external_id", externalId);
      currentExternalId = externalId;
    } catch {
      // Aliasing/login is retried on the next dashboard visit. A failure here
      // must not crash the rest of the account page.
    }
  }
  return sdk;
}

/** Read the subscription id across SDK versions. */
async function readSubscriptionId(sdk: OneSignalLike): Promise<string | null> {
  const v16 = sdk.User?.PushSubscription?.id;
  if (v16) return v16;
  if (typeof sdk.getSubscriptionId === "function") return sdk.getSubscriptionId();
  return null;
}

export interface OneSignalResult {
  playerId: string;
  optedIn: boolean;
}

/**
 * Ask for permission and return the OneSignal subscription id.
 * The caller is responsible for storing it via /api/push/subscribe/.
 */
export async function subscribeOneSignal(
  appId: string,
  externalId: string,
): Promise<OneSignalResult> {
  const sdk = await initOneSignal(appId, externalId);

  // v16 gates permission behind explicit consent calls.
  try {
    sdk.setConsentRequired?.(true);
    sdk.setConsentGiven?.(true);
  } catch {
    // v15 has no consent API; ignore.
  }

  const notifications = sdk.Notifications;
  let granted = notifications?.permission === true;
  if (!granted && notifications?.requestPermission) {
    granted = await notifications.requestPermission();
  }
  if (!granted) {
    return { playerId: "", optedIn: false };
  }

  // A prompt may need one more tick before the id exists.
  let playerId = await readSubscriptionId(sdk);
  for (let attempt = 0; attempt < 20 && !playerId; attempt += 1) {
    await new Promise((r) => setTimeout(r, 250));
    playerId = await readSubscriptionId(sdk);
  }
  if (!playerId) {
    throw new Error("OneSignal did not return a subscription id.");
  }
  return { playerId, optedIn: true };
}

/**
 * Restore an existing OneSignal browser subscription after a normal page load
 * or app login. Unlike subscribeOneSignal(), this helper NEVER requests browser
 * permission. It only initializes OneSignal, logs in the current app user and
 * reads the subscription that the browser already owns.
 */
export async function restoreOneSignalSubscription(
  appId: string,
  externalId: string,
): Promise<OneSignalResult> {
  const sdk = await initOneSignal(appId, externalId);
  const browserGranted =
    sdk.Notifications?.permission === true ||
    (typeof Notification !== "undefined" && Notification.permission === "granted");

  if (!browserGranted) return { playerId: "", optedIn: false };

  let playerId = await readSubscriptionId(sdk);
  for (let attempt = 0; attempt < 20 && !playerId; attempt += 1) {
    await new Promise((r) => setTimeout(r, 250));
    playerId = await readSubscriptionId(sdk);
  }

  return { playerId: playerId ?? "", optedIn: Boolean(playerId) };
}

/**
 * Current subscription id, or null when the browser is not subscribed.
 * Loads the SDK if it has not been injected yet, so this is the correct check
 * when OneSignal is the active transport.
 */
export async function getOneSignalPlayerId(): Promise<string | null> {
  const sdk = await loadOneSignal();
  return readSubscriptionId(sdk);
}

/** Stop notifications for this device. */
export async function logoutOneSignal(): Promise<void> {
  if (!isOneSignalLoaded()) return;
  const sdk = await loadOneSignal();
  try {
    await sdk.logout?.();
    currentExternalId = null;
  } catch {
    // Already logged out.
    currentExternalId = null;
  }
}
/**
 * The backend keys subscriptions by `endpoint`, so a OneSignal player id needs
 * a stable synthetic https key. It is never fetched - it exists only so the
 * uniqueness constraint works.
 */
export function oneSignalEndpoint(playerId: string): string {
  return `https://onesignal.app/player/${playerId}`;
}
