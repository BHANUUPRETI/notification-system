/**
 * Web Push subscription helpers.
 *
 * Uses the native Push API + VAPID (what the Django backend sends with
 * pywebpush). If no VAPID public key is published by the backend, the
 * subscribe button explains what is missing instead of failing silently.
 */

import { api, type PushSubscriptionInput } from "./api";

export function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
  return output;
}

export function isPushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window;
}

export function permissionState(): NotificationPermission | "unsupported" {
  if (!isPushSupported()) return "unsupported";
  return Notification.permission;
}

export async function getSubscription(): Promise<PushSubscription | null> {
  if (!isPushSupported()) return null;
  const reg = await navigator.serviceWorker.ready;
  return reg.pushManager.getSubscription();
}

export async function subscribe(vapidPublicKey: string): Promise<PushSubscription> {
  if (!isPushSupported()) throw new Error("This browser does not support Web Push.");
  const reg = await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  if (existing) return existing;

  return reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey) as BufferSource,
  });
}

function toInput(subscription: PushSubscription): PushSubscriptionInput {
  const json = subscription.toJSON() as { endpoint?: string; keys?: Record<string, string> };
  return {
    endpoint: json.endpoint ?? subscription.endpoint,
    keys: {
      p256dh: json.keys?.p256dh ?? "",
      auth: json.keys?.auth ?? "",
    },
  };
}

export async function registerAndSubscribe(
  vapidPublicKey: string,
): Promise<{ subscription: PushSubscription; registered: boolean }> {
  if (!vapidPublicKey) {
    throw new Error(
      "No VAPID public key available. Run `python manage.py generate_vapid_keys` and set VAPID_PUBLIC_KEY on the backend.",
    );
  }
  const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  await navigator.serviceWorker.ready;
  const subscription = await subscribe(vapidPublicKey);
  await api("/api/push/subscribe/", {
    method: "POST",
    body: { ...toInput(subscription), provider: "webpush" },
  });
  return { subscription, registered: true };
}

export async function unsubscribe(): Promise<void> {
  if (!isPushSupported()) return;
  const subscription = await getSubscription();
  if (subscription) {
    await api("/api/push/unsubscribe/", {
      method: "POST",
      body: { endpoint: subscription.endpoint },
    });
    await subscription.unsubscribe();
  }
}
