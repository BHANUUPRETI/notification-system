"use client";

import { useCallback, useEffect, useState } from "react";

import {
  api,
  ApiError,
  CHANNEL_META,
  CHANNELS,
  PROVIDER_STATUS_META,
  type Channel,
  type DispatchReport,
  type PublicConfig,
  type Template,
  type Trigger,
  type User,
  type VariableInfo,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { AddTriggerModal } from "@/components/AddTriggerModal";
import { TemplateEditor } from "@/components/TemplateEditor";
import { Spinner, StatusBadge, Toggle } from "@/components/ui";

interface EditorState {
  trigger: Trigger;
  channel: Channel;
  existing: Template | null;
}

/**
 * Toggle one template and keep the derived `enabled_channels` in step, so the
 * "N/3 channels on" counter can never drift from the switches above it.
 */
function withTemplateToggle(trigger: Trigger, templateId: number, enabled: boolean): Trigger {
  const templates = trigger.templates.map((t) =>
    t.id === templateId ? { ...t, is_enabled: enabled } : t,
  );
  return {
    ...trigger,
    templates,
    enabled_channels: templates.filter((t) => t.is_enabled).map((t) => t.channel),
  };
}

export default function NotificationTablePage() {
  const toast = useToast();

  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [variables, setVariables] = useState<VariableInfo[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [sandbox, setSandbox] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [addingTrigger, setAddingTrigger] = useState(false);
  const [firing, setFiring] = useState<string | null>(null);
  const [fireUser, setFireUser] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [triggerData, config, userData] = await Promise.all([
        api<Trigger[]>("/api/triggers/"),
        api<PublicConfig>("/api/config/", { auth: false }),
        api<User[]>("/api/users/"),
      ]);
      setTriggers(triggerData);
      setVariables(config.variables);
      setSandbox(config.sandbox);
      setUsers(userData);
      setConfig(config);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.status === 401
            ? "Your session expired. Sign in again."
            : e.friendly
          : "Could not load the notification table.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /** Apply a saved/deleted template back into local state without a refetch. */
  function applyTemplate(saved: Template | null, created: boolean, target: EditorState) {
    setTriggers((prev) =>
      prev.map((trigger) => {
        if (trigger.id !== target.trigger.id) return trigger;
        const rest = trigger.templates.filter((t) => t.channel !== target.channel);
        const templates = saved ? [...rest, saved] : rest;
        templates.sort((a, b) => CHANNELS.indexOf(a.channel) - CHANNELS.indexOf(b.channel));
        return {
          ...trigger,
          templates,
          template_count: templates.length,
          enabled_channels: templates.filter((t) => t.is_enabled).map((t) => t.channel),
        };
      }),
    );
    if (!created) setEditor(null);
    else {
      // Stay open so the admin can keep iterating; the row now has a template.
      setEditor((prev) => (prev ? { ...prev, existing: saved } : prev));
    }
  }

  async function toggleTemplate(trigger: Trigger, template: Template, next: boolean) {
    setTriggers((prev) =>
      prev.map((t) => (t.id === trigger.id ? withTemplateToggle(t, template.id, next) : t)),
    );
    try {
      await api(`/api/templates/${template.id}/toggle/`, { method: "POST", body: {} });
      toast.ok(
        next
          ? `${CHANNEL_META[template.channel].label} switched on`
          : `${CHANNEL_META[template.channel].label} switched off`,
        `${trigger.name}`,
      );
    } catch (e) {
      // Roll the row back. enabled_channels has to move too, otherwise the
      // "N/3 channels on" counter keeps the optimistic (wrong) value.
      setTriggers((prev) =>
        prev.map((t) => (t.id === trigger.id ? withTemplateToggle(t, template.id, !next) : t)),
      );
      toast.err("Toggle failed", e instanceof ApiError ? e.friendly : undefined);
    }
  }

  async function toggleTrigger(trigger: Trigger, next: boolean) {
    setTriggers((prev) =>
      prev.map((t) => (t.id === trigger.id ? { ...t, is_active: next } : t)),
    );
    try {
      await api(`/api/triggers/${trigger.key}/toggle/`, {
        method: "POST",
        body: { is_active: next },
      });
      toast.ok(next ? "Trigger enabled" : "Trigger disabled", trigger.name);
    } catch (e) {
      setTriggers((prev) =>
        prev.map((t) => (t.id === trigger.id ? { ...t, is_active: !next } : t)),
      );
      toast.err("Toggle failed", e instanceof ApiError ? e.friendly : undefined);
    }
  }

  const [lastReport, setLastReport] = useState<DispatchReport | null>(null);

  /** Insert a freshly created trigger without refetching the whole table. */
  function addTriggerRow(trigger: Trigger) {
    setTriggers((prev) => [...prev, trigger]);
    setAddingTrigger(false);
  }

  async function fireNow(trigger: Trigger) {
    setFiring(trigger.key);
    try {
      const body: Record<string, unknown> = {};
      if (fireUser) body.user_id = Number(fireUser);
      const report = await api<DispatchReport>(`/api/triggers/${trigger.key}/fire/`, {
        method: "POST",
        body,
      });
      setLastReport(report);
      const s = report.summary;
      toast.ok(
        `Fired ${trigger.name}`,
        `${s.sent + s.simulated} delivered · ${s.skipped} skipped · ${s.failed} failed`,
      );
    } catch (e) {
      toast.err("Could not fire trigger", e instanceof ApiError ? e.friendly : undefined);
    } finally {
      setFiring(null);
    }
  }

  if (loading) {
    return (
      <main className="container wide">
        <div className="card">
          <div className="row">
            <Spinner /> <span className="dim">Loading triggers…</span>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="container wide">
      <div className="page-head">
        <div>
          <h1>Notifications</h1>
          <p className="sub">
            One row per trigger, one column per channel. Every cell creates, edits,
            toggles and tests its own template.
          </p>
        </div>
        <div className="spacer" />
        <button className="btn" onClick={load} disabled={loading}>
          Refresh
        </button>
        <button className="btn primary" onClick={() => setAddingTrigger(true)}>
          + Add trigger
        </button>
      </div>

      {error ? <div className="alert err mb-2">{error}</div> : null}

      {sandbox ? (
        <div className="alert warn mb-2">
          <strong>Sandbox mode.</strong> Test sends are rendered and written to the
          activity log, but not delivered. Add provider keys in{" "}
          <code>backend/.env</code> and set <code>NOTIFICATION_SANDBOX=False</code> to send
          for real.
        </div>
      ) : null}

      <div className="card mb-2">
        <div className="row">
          <label htmlFor="fire-user" className="small dim">
            Fire triggers for
          </label>
          <select
            id="fire-user"
            className="input"
            style={{ width: "auto", minWidth: 220 }}
            value={fireUser}
            onChange={(e) => setFireUser(e.target.value)}
          >
            <option value="">Myself (admin)</option>
            {users
              .filter((u) => !u.is_admin)
              .map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} — {u.email}
                </option>
              ))}
          </select>
          <div className="spacer" />
          <span className="small faint">
            {triggers.length} triggers ·{" "}
            {triggers.reduce((n, t) => n + t.templates.length, 0)} templates
          </span>
        </div>
      </div>

      {lastReport ? (
        <div className="card mb-2">
          <div className="card-head">
            <h3>Last fire · {lastReport.trigger}</h3>
            <div className="spacer" />
            <button className="btn small ghost" onClick={() => setLastReport(null)}>
              Dismiss
            </button>
          </div>
          <div className="grid cols-3">
            {lastReport.results.map((r) => (
              <div key={r.channel} className="alert">
                <div className="row tight">
                  <StatusBadge status={r.status} />
                  <strong>{r.channel}</strong>
                </div>
                <div className="small mt-1">
                  {r.destination ? <div className="mono faint">{r.destination}</div> : null}
                  {r.error || r.message}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="grid-table">
          <thead>
            <tr>
              <th style={{ minWidth: 250 }}>Trigger</th>
              {CHANNELS.map((channel) => (
                <th key={channel}>
                  <span className={`badge ${CHANNEL_META[channel].accent}`}>
                    {CHANNEL_META[channel].icon} {CHANNEL_META[channel].label}
                  </span>
                </th>
              ))}
              <th style={{ width: 120 }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {triggers.map((trigger) => {
              const byChannel = new Map(trigger.templates.map((t) => [t.channel, t]));
              const busy = firing === trigger.key;
              return (
                <tr key={trigger.id} className={trigger.is_active ? "" : "off"}>
                  <td className="trigger-cell">
                    <div className="trigger-name">
                      {trigger.name}
                      {trigger.kind === "inactivity" ? (
                        <span className="badge muted">inactivity</span>
                      ) : null}
                    </div>
                    <div className="trigger-key">{trigger.key}</div>
                    {trigger.description ? (
                      <div className="trigger-desc">{trigger.description}</div>
                    ) : null}
                    <div className="row tight mt-1">
                      <span className="small faint">Trigger</span>
                      <Toggle
                        checked={trigger.is_active}
                        onChange={(v) => toggleTrigger(trigger, v)}
                        label={`${trigger.name} enabled`}
                      />
                      <span className={`small ${trigger.is_active ? "faint" : ""}`}
                        style={{ color: trigger.is_active ? undefined : "var(--warn)" }}
                      >
                        {trigger.is_active ? "on" : "off"}
                      </span>
                    </div>
                  </td>

                  {CHANNELS.map((channel) => {
                    const template = byChannel.get(channel);
                    return (
                      <td key={channel}>
                        <div className="cell">
                          {template ? (
                            <>
                              <div className="cell-preview">
                                {template.subject ? (
                                  <span className="t">{template.subject}</span>
                                ) : null}
                                {template.title && channel === "webpush" ? (
                                  <span className="t">{template.title}</span>
                                ) : null}
                                {template.body}
                              </div>
                              <div className="cell-actions">
                                <Toggle
                                  checked={template.is_enabled}
                                  onChange={(v) => toggleTemplate(trigger, template, v)}
                                  label={`${CHANNEL_META[channel].label} for ${trigger.name}`}
                                />
                                <button
                                  className="btn small"
                                  onClick={() => setEditor({ trigger, channel, existing: template })}
                                >
                                  Edit
                                </button>
                                <div className="spacer" />
                                {template.variables.length ? (
                                  <span
                                    className="badge muted"
                                    title={`Uses: ${template.variables.join(", ")}`}
                                  >
                                    {template.variables.length} var
                                  </span>
                                ) : null}
                                {channel === "whatsapp" &&
                                template.provider_status !== "not_submitted" ? (
                                  <span
                                    className={`badge ${PROVIDER_STATUS_META[template.provider_status].badge}`}
                                    title="WhatsApp template approval status in Meta"
                                  >
                                    {PROVIDER_STATUS_META[template.provider_status].label}
                                  </span>
                                ) : null}
                              </div>
                            </>
                          ) : (
                            <>
                              <div className="cell-empty">No template</div>
                              <div className="cell-actions">
                                <button
                                  className="btn small primary"
                                  onClick={() => setEditor({ trigger, channel, existing: null })}
                                >
                                  Create template
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      </td>
                    );
                  })}

                  <td>
                    <div className="cell" style={{ minHeight: "auto" }}>
                      <button
                        className="btn small"
                        disabled={busy}
                        onClick={() => void fireNow(trigger)}
                      >
                        {busy ? <Spinner /> : null} Fire now
                      </button>
                      <span className="small faint">
                        {trigger.enabled_channels.length}/3 channels on
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
            {triggers.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty">
                  <div className="big">🗂️</div>
                  No triggers yet. Run{" "}
                  <code className="mono">python manage.py seed_triggers --with-templates</code>{" "}
                  on the backend.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {addingTrigger ? (
        <AddTriggerModal
          onClose={() => setAddingTrigger(false)}
          onCreated={addTriggerRow}
        />
      ) : null}

      {editor ? (
        <TemplateEditor
          trigger={editor.trigger}
          channel={editor.channel}
          existing={editor.existing}
          variables={variables}
          users={users}
          config={config}
          onClose={() => setEditor(null)}
          onSaved={(saved, created) => applyTemplate(saved, created, editor)}
        />
      ) : null}
    </main>
  );
}
