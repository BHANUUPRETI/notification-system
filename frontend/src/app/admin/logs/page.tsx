"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError, CHANNELS, CHANNEL_META, type Channel, type NotificationLog, type SendStatus } from "@/lib/api";
import { EmptyState, Spinner, StatusBadge } from "@/components/ui";

const STATUSES: SendStatus[] = ["sent", "simulated", "failed", "skipped"];

export default function LogsPage() {
  const [logs, setLogs] = useState<NotificationLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<Channel | "">("");
  const [status, setStatus] = useState<SendStatus | "">("");
  const [expanded, setExpanded] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ limit: "200" });
      if (channel) params.set("channel", channel);
      if (status) params.set("status", status);
      setLogs(await api<NotificationLog[]>(`/api/logs/?${params.toString()}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.friendly : "Could not load logs.");
    } finally {
      setLoading(false);
    }
  }, [channel, status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="container wide">
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <p className="sub">
            Every send attempt is recorded — including skipped ones, so you can see why a
            message did not arrive.
          </p>
        </div>
        <div className="spacer" />
        <button className="btn" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>

      <div className="card mb-2">
        <div className="row">
          <div>
            <label className="small dim" htmlFor="f-channel">Channel</label>
            <select
              id="f-channel"
              className="input"
              style={{ width: "auto" }}
              value={channel}
              onChange={(e) => setChannel(e.target.value as Channel | "")}
            >
              <option value="">All</option>
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {CHANNEL_META[c].label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="small dim" htmlFor="f-status">Status</label>
            <select
              id="f-status"
              className="input"
              style={{ width: "auto" }}
              value={status}
              onChange={(e) => setStatus(e.target.value as SendStatus | "")}
            >
              <option value="">All</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
          <div className="spacer" />
          <span className="small faint">{logs.length} entries</span>
        </div>
      </div>

      {error ? <div className="alert err mb-2">{error}</div> : null}

      <div className="table-wrap">
        <table className="grid-table" style={{ minWidth: 1000 }}>
          <thead>
            <tr>
              <th style={{ width: 150 }}>When</th>
              <th style={{ width: 90 }}>Channel</th>
              <th style={{ width: 100 }}>Status</th>
              <th style={{ width: 130 }}>Trigger</th>
              <th style={{ width: 110 }}>User</th>
              <th>Destination / message</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => {
              const isOpen = expanded === log.id;
              return (
                <tr
                  key={log.id}
                  onClick={() => setExpanded(isOpen ? null : log.id)}
                  style={{ cursor: "pointer" }}
                >
                  <td className="nowrap small dim">
                    {new Date(log.created_at).toLocaleString()}
                    {log.is_test ? (
                      <div>
                        <span className="badge info">test</span>
                      </div>
                    ) : null}
                  </td>
                  <td>
                    <span className={`badge ${CHANNEL_META[log.channel]?.accent ?? "muted"}`}>
                      {CHANNEL_META[log.channel]?.icon} {log.channel}
                    </span>
                  </td>
                  <td>
                    <StatusBadge status={log.status} />
                  </td>
                  <td className="small mono">{log.trigger_key ?? "—"}</td>
                  <td className="small">{log.username ?? "—"}</td>
                  <td className="small">
                    <div className="mono faint">{log.destination || "—"}</div>
                    {isOpen ? (
                      <div className="mt-1">
                        {log.rendered_title ? (
                          <div style={{ fontWeight: 650 }}>{log.rendered_title}</div>
                        ) : null}
                        {log.rendered_subject ? (
                          <div style={{ fontWeight: 650 }}>{log.rendered_subject}</div>
                        ) : null}
                        <div style={{ whiteSpace: "pre-wrap" }} className="dim">
                          {log.rendered_body}
                        </div>
                        {log.error ? <div className="alert err mt-1">{log.error}</div> : null}
                        {log.provider ? (
                          <div className="small faint mono mt-1">
                            provider={log.provider}
                            {log.provider_message_id ? ` id=${log.provider_message_id}` : ""}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="dim" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 520 }}>
                        {log.error || log.rendered_subject || log.rendered_body}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {!loading && logs.length === 0 ? (
        <div className="card mt-2">
          <EmptyState icon="📭" title="No activity yet">
            Fire a trigger from the notification table to see entries here.
          </EmptyState>
        </div>
      ) : null}

      {loading ? (
        <div className="card mt-2 row">
          <Spinner /> <span className="dim">Loading…</span>
        </div>
      ) : null}
    </main>
  );
}
