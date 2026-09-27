"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, ApiError, type PublicConfig, type User } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/Toast";
import { getSubscription, isPushSupported, permissionState, registerAndSubscribe, unsubscribe } from "@/lib/push";
import {
  getOneSignalPlayerId,
  isOneSignalLoaded,
  logoutOneSignal,
  oneSignalEndpoint,
  subscribeOneSignal,
} from "@/lib/onesignal";
import { Spinner, Toggle } from "@/components/ui";

type PushBackend = "onesignal" | "vapid" | "none";

export default function DashboardPage() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [phone, setPhone] = useState("");
  const [savingPhone, setSavingPhone] = useState(false);
  const [pushState, setPushState] = useState<string>("checking");
  const [pushBusy, setPushBusy] = useState(false);
  const pushBackend: PushBackend = config?.push?.backend ?? (config?.vapid_public_key ? "vapid" : "none");

  useEffect(() => {
    api<PublicConfig>("/api/config/", { auth: false }).then(setConfig).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!user || !config) return;
    setPhone(user.profile.phone_e164);
    let cancelled = false;
    (async () => {
      if (!isPushSupported()) {
        if (!cancelled) setPushState("unsupported");
        return;
      }
      // The browser has to be checked through whichever transport the backend
      // is actually configured to send on - otherwise a returning OneSignal
      // user would be told their notifications are off.
      const backend = config.push?.backend ?? (config.vapid_public_key ? "vapid" : "none");
      if (backend === "onesignal") {
        const playerId = await getOneSignalPlayerId();
        if (!cancelled) setPushState(playerId ? "subscribed" : permissionState());
        return;
      }
      const sub = await getSubscription();
      if (cancelled) return;
      setPushState(sub ? "subscribed" : permissionState());
    })();
    return () => {
      cancelled = true;
    };
  }, [user, config]);

  async function savePhone() {
    setSavingPhone(true);
    try {
      await api("/api/auth/me/profile/", { method: "PATCH", body: { phone_e164: phone.trim() } });
      await refresh();
      toast.ok("Phone number saved", "WhatsApp test sends will go here.");
    } catch (e) {
      toast.err("Could not save", e instanceof ApiError ? e.friendly : undefined);
    } finally {
      setSavingPhone(false);
    }
  }

  async function setOptIn(field: string, value: boolean) {
    try {
      await api("/api/auth/me/profile/", { method: "PATCH", body: { [field]: value } });
      await refresh();
    } catch (e) {
      toast.err("Could not update", e instanceof ApiError ? e.friendly : undefined);
    }
  }

  async function enablePush() {
    if (!config) return;
    setPushBusy(true);
    try {
      if (pushBackend === "onesignal") {
        const appId = config.push?.onesignal_app_id;
        if (!appId) throw new Error("The backend has no ONESIGNAL_APP_ID set.");
        const { playerId, optedIn } = await subscribeOneSignal(
          appId,
          String(user?.id ?? "anonymous"),
        );
        if (!optedIn) {
          setPushState("denied");
          toast.warn("Permission not granted", "Your browser blocked the request.");
          return;
        }
        await api("/api/push/subscribe/", {
          method: "POST",
          body: {
            provider: "onesignal",
            endpoint: oneSignalEndpoint(playerId),
            onesignal_subscription_id: playerId,
            p256dh: "",
            auth: "",
          },
        });
      } else {
        await registerAndSubscribe(config.vapid_public_key);
      }
      await refresh();
      setPushState("subscribed");
      toast.ok(
        "Browser notifications on",
        pushBackend === "onesignal"
          ? "This device is registered with OneSignal."
          : "This device will now receive Web Push messages.",
      );
    } catch (e) {
      const message = e instanceof Error ? e.message : "Subscription failed";
      setPushState("denied");
      toast.err("Could not enable notifications", message);
    } finally {
      setPushBusy(false);
    }
  }

  async function disablePush() {
    setPushBusy(true);
    try {
      if (isOneSignalLoaded()) {
        const playerId = await getOneSignalPlayerId();
        if (playerId) {
          await api("/api/push/unsubscribe/", {
            method: "POST",
            body: { endpoint: oneSignalEndpoint(playerId) },
          });
        }
        await logoutOneSignal();
      } else {
        await unsubscribe();
      }
      await refresh();
      setPushState("default");
      toast.ok("Browser notifications off");
    } catch (e) {
      toast.err("Could not turn off", e instanceof ApiError ? e.friendly : undefined);
    } finally {
      setPushBusy(false);
    }
  }

  if (!user) {
    return (
      <main className="container">
        <div className="card">
          <div className="row">
            <Spinner /> <span className="dim">Loading your account…</span>
          </div>
        </div>
      </main>
    );
  }

  const subscribed = pushState === "subscribed";
  const profile = user.profile;

  return (
    <main className="container">
      <div className="page-head">
        <div>
          <h1>Hello, {user.first_name || user.username}</h1>
          <p className="sub">
            Signing in and out fires real triggers. Your contact details below decide
            where those messages land.
          </p>
        </div>
        <div className="spacer" />
        {user.is_admin ? (
          <Link href="/admin/notifications" className="btn primary">
            Admin: notification table
          </Link>
        ) : null}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <div className="card-head">
            <h2>Where your messages go</h2>
          </div>

          <div className="field">
            <label htmlFor="phone">WhatsApp number (E.164)</label>
            <div className="row">
              <input
                id="phone"
                className="input mono"
                value={phone}
                placeholder="+919876543210"
                onChange={(e) => setPhone(e.target.value)}
                style={{ maxWidth: 240 }}
              />
              <button className="btn" onClick={savePhone} disabled={savingPhone}>
                {savingPhone ? <Spinner /> : null} Save
              </button>
            </div>
            <div className="help">
              For the Meta sandbox this must also be an approved test recipient.
            </div>
          </div>

          <div className="field">
            <label>Email address</label>
            <input className="input mono" value={user.email} readOnly />
          </div>

          <hr className="hr" />

          <div className="field">
            <label>Channel preferences</label>
            <div className="grid" style={{ gap: 10 }}>
              {(
                [
                  ["whatsapp_opt_in", "WhatsApp", "Login / inactivity messages to my phone"],
                  ["email_opt_in", "Email", "Transactional email to my inbox"],
                  ["webpush_opt_in", "Web Push", "Browser pop-ups on this device"],
                ] as const
              ).map(([field, label, hint]) => (
                <div className="row" key={field} style={{ justifyContent: "space-between" }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{label}</div>
                    <div className="small faint">{hint}</div>
                  </div>
                  <Toggle
                    checked={Boolean(profile[field])}
                    onChange={(v) => setOptIn(field, v)}
                    label={label}
                  />
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>Browser notifications</h2>
            <div className="spacer" />
            <span className={`badge ${subscribed ? "ok" : "warn"}`}>
              {pushState === "checking"
                ? "Checking"
                : subscribed
                  ? "Subscribed"
                  : pushState === "unsupported"
                    ? "Not supported"
                    : pushState === "denied"
                      ? "Blocked"
                      : "Off"}
            </span>
          </div>

          <div className="row tight mb-1">
            <span className="small dim">Delivery via</span>
            {pushBackend === "onesignal" ? (
              <span className="badge info">OneSignal</span>
            ) : pushBackend === "vapid" ? (
              <span className="badge info">Web Push (VAPID)</span>
            ) : (
              <span className="badge warn">not configured</span>
            )}
          </div>

          <p className="small dim">
            Web Push needs a one-time permission from this browser. The endpoint is
            stored on the backend and reused for every notification.
          </p>

          {pushBackend === "none" ? (
            <div className="alert warn mt-1">
              The backend has no Web Push keys yet. Either set{" "}
              <code className="mono">ONESIGNAL_APP_ID</code> +{" "}
              <code className="mono">ONESIGNAL_REST_API_KEY</code>, or run{" "}
              <code className="mono">python manage.py generate_vapid_keys</code> and set{" "}
              <code className="mono">VAPID_PUBLIC_KEY</code> +{" "}
              <code className="mono">VAPID_PRIVATE_KEY</code>.
            </div>
          ) : null}

          {pushState === "unsupported" ? (
            <div className="alert mt-1">
              This browser does not support Web Push. Chrome or Edge on desktop works.
            </div>
          ) : subscribed ? (
            <>
              <div className="alert ok mt-1">
                This device is subscribed. Admin test sends on Web Push should appear even
                if this tab is in the background.
              </div>
              <button className="btn danger mt-1" onClick={disablePush} disabled={pushBusy}>
                {pushBusy ? <Spinner /> : null} Turn off for this device
              </button>
            </>
          ) : (
            <button
              className="btn primary mt-1"
              onClick={enablePush}
              disabled={pushBusy || pushState === "denied" || pushBackend === "none"}
            >
              {pushBusy ? <Spinner /> : null} Enable browser notifications
            </button>
          )}

          {pushBackend === "onesignal" ? (
            <p className="small faint mt-1">
              Uses your OneSignal Website app. Enable Web Push only in the OneSignal
              dashboard and skip the Android / iOS platforms.
            </p>
          ) : null}

          {profile.last_seen_at ? (
            <p className="small faint mt-2">
              Last seen: {new Date(profile.last_seen_at).toLocaleString()}
            </p>
          ) : null}
        </div>
      </div>

      <div className="card mt-2">
        <h2>Try a trigger right now</h2>
        <p className="small dim">
          Signing out fires the <strong>logout</strong> trigger. An admin can also fire
          any trigger on demand from the notification table.
        </p>
        <div className="row">
          <Link href="/admin/logs" className="btn">
            See the activity log
          </Link>
          <Link href="/admin/notifications" className="btn">
            Open the table
          </Link>
        </div>
      </div>
    </main>
  );
}
