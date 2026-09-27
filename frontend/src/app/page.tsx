"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, CHANNEL_META, type PublicConfig } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function HomePage() {
  const { user, isAdmin } = useAuth();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<PublicConfig>("/api/config/", { auth: false })
      .then(setConfig)
      .catch((e) => setError(e.message ?? "Could not reach the API"));
  }, []);

  return (
    <main className="container">
      <div className="page-head">
        <div>
          <h1>One screen for every notification</h1>
          <p className="sub">
            Triggers, templates and on/off switches live in a single admin table. No
            more opening the WhatsApp or Postmark dashboards.
          </p>
        </div>
        <div className="spacer" />
        {isAdmin ? (
          <Link href="/admin/notifications" className="btn primary">
            Open the notification table
          </Link>
        ) : (
          <Link href="/login" className="btn primary">
            Sign in
          </Link>
        )}
      </div>

      {error ? (
        <div className="alert err">
          <strong>Backend unreachable.</strong> {error}
          <div className="small mt-1">
            Set <code>NEXT_PUBLIC_API_URL</code> in <code>frontend/.env.local</code>, then
            start Django with <code>python manage.py runserver</code>.
          </div>
        </div>
      ) : null}

      <div className="grid cols-3">
        {(["whatsapp", "email", "webpush"] as const).map((channel) => {
          const meta = CHANNEL_META[channel];
          const provider = config?.providers.find((p) => p.channel === channel);
          return (
            <div className="card" key={channel}>
              <div className="row">
                <span style={{ fontSize: 22 }}>{meta.icon}</span>
                <h3>{meta.label}</h3>
                <div className="spacer" />
                {provider ? (
                  <span className={`badge ${provider.configured ? "ok" : "warn"}`}>
                    {provider.configured ? "Ready" : "No keys"}
                  </span>
                ) : null}
              </div>
              <p className="small dim mt-1">
                {channel === "whatsapp" && "WhatsApp Cloud API sandbox message to the user's phone."}
                {channel === "email" && "Transactional email via Postmark (or another free provider)."}
                {channel === "webpush" && "Browser pop-up delivered with VAPID or OneSignal."}
              </p>
              {provider && !provider.configured ? (
                <p className="small faint mt-1">{provider.message}</p>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="card mt-2">
        <h2>How it works</h2>
        <div className="grid cols-3 mt-1">
          <div>
            <h3>1 · Trigger</h3>
            <p className="small dim">
              Anything that should send a message — login, logout, inactive for a day,
              inactive for a week. Each trigger is one row.
            </p>
          </div>
          <div>
            <h3>2 · Template</h3>
            <p className="small dim">
              Each trigger has its own copy per channel. Write it with{" "}
              <code className="mono">{"{{ first_name }}"}</code> placeholders and see a
              live preview before saving.
            </p>
          </div>
          <div>
            <h3>3 · Toggle &amp; test</h3>
            <p className="small dim">
              Switch any channel on or off per trigger, and send a real test to yourself
              before switching it on for everyone.
            </p>
          </div>
        </div>
      </div>

      {config?.sandbox ? (
        <div className="alert warn mt-2">
          <strong>Sandbox mode is ON.</strong> Messages are rendered and stored in the
          activity log, but nothing leaves the machine. Fill the provider keys in{" "}
          <code>backend/.env</code> and set <code>NOTIFICATION_SANDBOX=False</code> to send
          for real.
        </div>
      ) : null}

      {user ? (
        <p className="small faint mt-2">
          Signed in as <strong>{user.username}</strong>
          {user.profile.phone_e164 ? ` · WhatsApp ${user.profile.phone_e164}` : " · no WhatsApp number set"}
        </p>
      ) : null}
    </main>
  );
}
