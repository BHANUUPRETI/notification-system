"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api, CHANNEL_META, type PublicConfig, type Stats } from "@/lib/api";
import { Spinner } from "@/components/ui";

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([api<Stats>("/api/stats/"), api<PublicConfig>("/api/config/", { auth: false })])
      .then(([s, c]) => {
        setStats(s);
        setConfig(c);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <main className="container">
        <div className="card row">
          <Spinner /> <span className="dim">Loading…</span>
        </div>
      </main>
    );
  }

  const byStatus = stats?.logs_last_7_days.by_status ?? {};

  return (
    <main className="container">
      <div className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="sub">Health of the notification system and its provider keys.</p>
        </div>
      </div>

      <div className="grid cols-4">
        <div className="stat">
          <div className="label">Triggers</div>
          <div className="value">{stats?.triggers ?? 0}</div>
          <div className="hint">rows in the table</div>
        </div>
        <div className="stat">
          <div className="label">Templates</div>
          <div className="value">{stats?.templates ?? 0}</div>
          <div className="hint">{stats?.templates_enabled ?? 0} switched on</div>
        </div>
        <div className="stat">
          <div className="label">Users</div>
          <div className="value">{stats?.users ?? 0}</div>
          <div className="hint">{stats?.push_subscriptions ?? 0} push subscriptions</div>
        </div>
        <div className="stat">
          <div className="label">Sends (7d)</div>
          <div className="value">{stats?.logs_last_7_days.total ?? 0}</div>
          <div className="hint">{byStatus.failed ?? 0} failed</div>
        </div>
      </div>

      <div className="card mt-2">
        <div className="card-head">
          <h2>Provider readiness</h2>
          <div className="spacer" />
          {config?.sandbox ? <span className="badge warn">sandbox mode</span> : <span className="badge ok">live</span>}
        </div>
        <div className="grid cols-3">
          {(config?.providers ?? []).map((p) => (
            <div className="alert" key={p.channel}>
              <div className="row tight">
                <span>{CHANNEL_META[p.channel].icon}</span>
                <strong>{p.label}</strong>
                <div className="spacer" />
                <span className={`badge ${p.configured ? "ok" : "warn"}`}>
                  {p.configured ? "configured" : "missing keys"}
                </span>
              </div>
              <div className="small faint mt-1 mono">{p.provider}</div>
              {p.message ? <div className="small mt-1">{p.message}</div> : null}
            </div>
          ))}
        </div>
      </div>

      <div className="card mt-2">
        <h2>Next steps</h2>
        <div className="grid cols-3 mt-1">
          <div>
            <h3>Task A</h3>
            <p className="small dim">
              Pick one trigger, create all three templates, and test each one.
            </p>
            <Link href="/admin/notifications" className="btn small">
              Notification table
            </Link>
          </div>
          <div>
            <h3>Task B</h3>
            <p className="small dim">Repeat for a second trigger with different copy.</p>
            <Link href="/admin/notifications" className="btn small">
              Notification table
            </Link>
          </div>
          <div>
            <h3>Task C</h3>
            <p className="small dim">Edit a template and flip a channel toggle off/on.</p>
            <Link href="/admin/logs" className="btn small">
              Activity log
            </Link>
          </div>
        </div>
      </div>
    </main>
  );
}
