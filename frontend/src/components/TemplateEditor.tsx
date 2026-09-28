"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  api,
  ApiError,
  CHANNEL_META,
  PROVIDER_STATUSES,
  PROVIDER_STATUS_META,
  type Channel,
  type ChannelResult,
  type ProviderStatus,
  type PublicConfig,
  type Template,
  type Trigger,
  type User,
  type VariableInfo,
} from "@/lib/api";
import { useToast } from "./Toast";
import { Spinner, StatusBadge, Toggle } from "./ui";

interface Draft {
  id: number | null;
  triggerKey: string;
  triggerName: string;
  channel: Channel;
  title: string;
  subject: string;
  body: string;
  provider_template_name: string;
  provider_template_id: string;
  provider_language: string;
  provider_status: ProviderStatus;
  provider_status_note: string;
  provider_submitted_at: string | null;
  variable_mapping: Record<string, string>;
  is_enabled: boolean;
}

const PLACEHOLDER_RE = /{{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*(?:\|\s*[a-z_]+\s*)?}}/g;

export function TemplateEditor({
  trigger,
  channel,
  existing,
  variables,
  users,
  config,
  onClose,
  onSaved,
}: {
  trigger: Trigger;
  channel: Channel;
  existing: Template | null;
  variables: VariableInfo[];
  users: User[];
  config: PublicConfig | null;
  onClose: () => void;
  onSaved: (template: Template | null, created: boolean) => void;
}) {
  const toast = useToast();
  const meta = CHANNEL_META[channel];

  const [draft, setDraft] = useState<Draft>(() => ({
    id: existing?.id ?? null,
    triggerKey: trigger.key,
    triggerName: trigger.name,
    channel,
    title: existing?.title ?? "",
    subject: existing?.subject ?? "",
    body: existing?.body ?? "",
    provider_template_name: existing?.provider_template_name ?? "",
    provider_template_id: existing?.provider_template_id ?? "",
    provider_language: existing?.provider_language ?? "",
    provider_status: existing?.provider_status ?? "not_submitted",
    provider_status_note: existing?.provider_status_note ?? "",
    provider_submitted_at: existing?.provider_submitted_at ?? null,
    variable_mapping: existing?.variable_mapping ?? {},
    is_enabled: existing?.is_enabled ?? true,
  }));

  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<ChannelResult[] | null>(null);
  const [testUser, setTestUser] = useState<string>("");
  const [testEmail, setTestEmail] = useState("");
  const [testPhone, setTestPhone] = useState("");
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function update<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDirty(true);
    setDraft((d) => ({ ...d, [key]: value }));
  }

  // ---- placeholder helpers -------------------------------------------------
  const usedVars = useMemo(() => {
    const found = new Set<string>();
    for (const text of [draft.title, draft.subject, draft.body]) {
      for (const m of text.matchAll(PLACEHOLDER_RE)) found.add(m[1]);
    }
    return [...found].sort();
  }, [draft.title, draft.subject, draft.body]);

  const customVars = useMemo(
    () => usedVars.filter((v) => !variables.some((x) => x.name === v)),
    [usedVars, variables],
  );

  const unresolvedVars = useMemo(
    () => customVars.filter((v) => !draft.variable_mapping[v]),
    [customVars, draft.variable_mapping],
  );

  function insertPlaceholder(name: string) {
    const el = bodyRef.current;
    if (!el) {
      update("body", `${draft.body}{{${name}}}`);
      return;
    }
    const token = `{{${name}}}`;
    const start = el.selectionStart ?? draft.body.length;
    const end = el.selectionEnd ?? start;
    const next = `${draft.body.slice(0, start)}${token}${draft.body.slice(end)}`;
    update("body", next);
    requestAnimationFrame(() => {
      el.focus();
      const caret = start + token.length;
      el.setSelectionRange(caret, caret);
    });
  }

  /** Local preview so the admin sees the copy before it round-trips. */
  const preview = useMemo(() => {
    const sample: Record<string, string> = {
      user: "amit",
      username: "amit",
      first_name: "Amit",
      last_name: "Sharma",
      full_name: "Amit Sharma",
      email: "amit@example.com",
      phone: "+919876543210",
      trigger: trigger.name,
      trigger_key: trigger.key,
      days: String(trigger.days ?? 1),
      days_away: String(trigger.days ?? 1),
      last_seen: "2026-09-19T11:40:00Z",
      date: "2026-09-26",
      time: "11:43",
      year: "2026",
      month: "09",
      day: "26",
      site_name: "Notify Demo",
    };
    const render = (text: string) =>
      text.replace(PLACEHOLDER_RE, (_, name: string) => {
        const directKey = name.split(".").pop() ?? name;
        if (sample[directKey] !== undefined) return sample[directKey];
        const mappedSource = draft.variable_mapping[name];
        const mappedKey = mappedSource?.split(".").pop() ?? mappedSource;
        return mappedKey ? (sample[mappedKey] ?? "") : "";
      });
    return { title: render(draft.title), subject: render(draft.subject), body: render(draft.body) };
  }, [draft.title, draft.subject, draft.body, draft.variable_mapping, trigger]);

  // ---- actions ------------------------------------------------------------
  function validate(): string | null {
    if (!draft.body.trim()) return "Message body cannot be empty.";
    if (channel === "email" && !draft.subject.trim()) return "An email subject is required.";
    if (channel === "webpush" && !draft.title.trim()) return "A Web Push title is required.";
    if (channel === "whatsapp" && draft.provider_status !== "not_submitted" && !draft.provider_template_name.trim()) {
      return "Add the Meta template name, or set the status back to “Not submitted”.";
    }
    if (unresolvedVars.length) return `Map or remove unknown variable(s): ${unresolvedVars.join(", ")}.`;
    return null;
  }

  const statusMeta = PROVIDER_STATUS_META[draft.provider_status];
  const consoleUrl =
    config?.whatsapp?.template_console_url ??
    "https://business.facebook.com/wa/manage/message-templates/";
  const defaultLanguage = config?.whatsapp?.language || "en_US";

  async function save() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      let saved: Template;
      let created = false;
      if (draft.id) {
        saved = await api<Template>(`/api/templates/${draft.id}/`, {
          method: "PATCH",
          body: {
            title: draft.title,
            subject: draft.subject,
            body: draft.body,
            provider_template_name: draft.provider_template_name,
            provider_language: draft.provider_language,
            provider_status: draft.provider_status,
            provider_status_note: draft.provider_status_note,
            variable_mapping: draft.variable_mapping,
            is_enabled: draft.is_enabled,
          },
        });
      } else {
        saved = await api<Template>("/api/templates/", {
          method: "POST",
          body: {
            trigger_key: trigger.key,
            channel,
            title: draft.title,
            subject: draft.subject,
            body: draft.body,
            provider_template_name: draft.provider_template_name,
            provider_language: draft.provider_language,
            provider_status: draft.provider_status,
            provider_status_note: draft.provider_status_note,
            variable_mapping: draft.variable_mapping,
            is_enabled: draft.is_enabled,
          },
        });
        created = true;
      }
      toast.ok(created ? "Template created" : "Template saved", `${trigger.name} · ${meta.label}`);
      onSaved(saved, created);
    } catch (e) {
      const message = e instanceof ApiError ? e.friendly : "Save failed";
      setError(message);
      toast.err("Could not save", message);
    } finally {
      setSaving(false);
    }
  }

  async function testSend() {
    const problem = validate();
    if (problem) {
      setError(problem);
      return;
    }
    setTesting(true);
    setError(null);
    setResults(null);
    try {
      const body: Record<string, unknown> = {};
      if (testUser) body.user_id = Number(testUser);
      if (testEmail.trim()) body.email = testEmail.trim();
      if (testPhone.trim()) body.phone = testPhone.trim();

      if (draft.id) {
        const result = await api<ChannelResult>(`/api/templates/${draft.id}/test/`, {
          method: "POST",
          body,
        });
        setResults([result]);
      } else {
        // Unsaved copy: send the draft without persisting it.
        const result = await api<ChannelResult>("/api/templates/draft-test/", {
          method: "POST",
          body: {
            trigger_key: trigger.key,
            channel,
            title: draft.title,
            subject: draft.subject,
            body: draft.body,
            provider_template_name: draft.provider_template_name,
            provider_language: draft.provider_language,
            provider_status: draft.provider_status,
            variable_mapping: draft.variable_mapping,
            ...body,
          },
        });
        setResults([result]);
      }
      toast.ok("Test send finished", "See the result below.");
    } catch (e) {
      const message = e instanceof ApiError ? e.friendly : "Test send failed";
      setError(message);
      toast.err("Test send failed", message);
    } finally {
      setTesting(false);
    }
  }

  async function syncWhatsApp() {
    if (!draft.id) {
      setError("Save the WhatsApp template before syncing with Meta.");
      return;
    }
    if (!draft.provider_template_name.trim()) {
      setError("Add the Meta template name before syncing.");
      return;
    }
    setSyncing(true);
    setError(null);
    try {
      const synced = await api<Template>(`/api/templates/${draft.id}/sync/`, {
        method: "POST",
        body: {},
      });
      setDraft((d) => ({
        ...d,
        provider_template_id: synced.provider_template_id,
        provider_template_name: synced.provider_template_name,
        provider_language: synced.provider_language,
        provider_status: synced.provider_status,
        provider_status_note: synced.provider_status_note,
        provider_submitted_at: synced.provider_submitted_at,
      }));
      onSaved(synced, true);
      toast.ok("Meta status synced", synced.provider_status_label);
    } catch (e) {
      const message = e instanceof ApiError ? e.friendly : "Meta sync failed";
      setError(message);
      toast.err("Meta sync failed", message);
    } finally {
      setSyncing(false);
    }
  }

  async function remove() {
    if (!draft.id) return;
    setSaving(true);
    try {
      await api(`/api/templates/${draft.id}/`, { method: "DELETE" });
      toast.ok("Template deleted", `${trigger.name} · ${meta.label}`);
      onSaved(null, false);
    } catch (e) {
      toast.err("Delete failed", e instanceof ApiError ? e.friendly : undefined);
    } finally {
      setSaving(false);
    }
  }

  const showTitle = channel === "webpush";
  const showSubject = channel === "email";

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="drawer" role="dialog" aria-label={`${meta.label} template editor`}>
        <div className="drawer-head">
          <span style={{ fontSize: 20 }}>{meta.icon}</span>
          <div>
            <h3>
              {meta.label} · {trigger.name}
            </h3>
            <div className="small faint">
              {draft.id ? "Edit template" : "New template"} · {trigger.key}
            </div>
          </div>
          <div className="spacer" />
          <div className="row tight">
            <span className="small dim">Enabled</span>
            <Toggle
              checked={draft.is_enabled}
              onChange={(v) => update("is_enabled", v)}
              label="Channel enabled"
            />
          </div>
          <button className="btn small ghost icon" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="drawer-body">
          {showTitle ? (
            <div className="field">
              <label htmlFor="t-title">Title</label>
              <input
                id="t-title"
                className="input"
                value={draft.title}
                placeholder="Welcome back!"
                onChange={(e) => update("title", e.target.value)}
              />
            </div>
          ) : null}

          {showSubject ? (
            <div className="field">
              <label htmlFor="t-subject">Subject</label>
              <input
                id="t-subject"
                className="input"
                value={draft.subject}
                placeholder="You logged in successfully"
                onChange={(e) => update("subject", e.target.value)}
              />
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="t-body">Message</label>
            <textarea
              id="t-body"
              ref={bodyRef}
              className="textarea mono"
              rows={9}
              value={draft.body}
              placeholder="Hi {{ first_name }}, welcome back to {{ site_name }}!"
              onChange={(e) => update("body", e.target.value)}
            />
            <div className="help">
              Click a variable to insert it. Unknown variables must be mapped to an allowed field or removed before saving.
            </div>
          </div>

          {channel === "whatsapp" ? (
            <>
              <div className="field">
                <label htmlFor="t-tpl">Meta template name</label>
                <input
                  id="t-tpl"
                  className="input mono"
                  value={draft.provider_template_name}
                  placeholder="welcome_back_v1"
                  onChange={(e) => update("provider_template_name", e.target.value)}
                />
                <div className="help">
                  The sandbox sends free-form text, so you can leave this blank. Fill it
                  in only when sending an approved production template.
                </div>
              </div>

              <div className="row" style={{ gap: 10, alignItems: "flex-end" }}>
                <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                  <label htmlFor="t-lang">Template language</label>
                  <input
                    id="t-lang"
                    className="input mono"
                    value={draft.provider_language}
                    placeholder={defaultLanguage}
                    onChange={(e) => update("provider_language", e.target.value)}
                  />
                </div>
              </div>

              <hr className="hr" />

              <div className="card-head">
                <h3>Meta approval</h3>
                <div className="spacer" />
                <span className={`badge ${statusMeta.badge}`}>{statusMeta.label}</span>
                <button
                  type="button"
                  className="btn small"
                  onClick={syncWhatsApp}
                  disabled={!draft.id || syncing || saving}
                >
                  {syncing ? <Spinner /> : null} Sync
                </button>
              </div>

              <div className="alert info">
                Create/submit the provider template in Meta when needed, then use Sync
                here to read its current approval state without manually copying status. {" "}
                <a href={consoleUrl} target="_blank" rel="noreferrer noopener">
                  Open Meta template console ↗
                </a>
              </div>

              <div className="field">
                <label htmlFor="t-status">Status</label>
                <select
                  id="t-status"
                  className="input"
                  value={draft.provider_status}
                  onChange={(e) => update("provider_status", e.target.value as ProviderStatus)}
                >
                  {PROVIDER_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {PROVIDER_STATUS_META[s].label}
                    </option>
                  ))}
                </select>
                <div className="help">{statusMeta.hint}</div>
              </div>

              {draft.provider_status === "rejected" ? (
                <div className="field">
                  <label htmlFor="t-status-note">Why was it rejected?</label>
                  <input
                    id="t-status-note"
                    className="input"
                    value={draft.provider_status_note}
                    placeholder="Meta: category is MARKETING, expected UTILITY"
                    onChange={(e) => update("provider_status_note", e.target.value)}
                  />
                </div>
              ) : null}

              {draft.provider_submitted_at ? (
                <p className="small faint">
                  Submitted {new Date(draft.provider_submitted_at).toLocaleString()}
                </p>
              ) : null}
            </>
          ) : null}

          <div className="field">
            <label>Variables</label>
            <div className="chip-list">
              {variables.map((v) => (
                <button
                  key={v.name}
                  type="button"
                  className="chip"
                  title={`${v.description} — e.g. ${v.example}`}
                  onClick={() => insertPlaceholder(v.name)}
                >
                  {`{{${v.name}}}`}
                </button>
              ))}
            </div>
            {usedVars.length ? (
              <div className="small faint mt-1">
                Used:{" "}
                {usedVars.map((v) => (
                  <span key={v} className="mono">
                    {v} {customVars.includes(v) ? (draft.variable_mapping[v] ? "↦" : "⚠") : ""}
                  </span>
                ))}
                {unresolvedVars.length ? (
                  <span className="faint">
                    {" "}
                    — {unresolvedVars.join(", ")} must be mapped or removed before saving
                  </span>
                ) : null}
              </div>
            ) : null}
            {customVars.length ? (
              <div className="mt-1">
                <div className="small dim" style={{ marginBottom: 8 }}>Custom variable mapping</div>
                {customVars.map((name) => (
                  <div className="row" key={name} style={{ gap: 8, marginBottom: 8, alignItems: "center" }}>
                    <code className="mono" style={{ minWidth: 120 }}>{`{{${name}}}`}</code>
                    <span className="faint">→</span>
                    <select
                      className="input"
                      value={draft.variable_mapping[name] ?? ""}
                      onChange={(e) => {
                        const next = { ...draft.variable_mapping };
                        if (e.target.value) next[name] = e.target.value;
                        else delete next[name];
                        update("variable_mapping", next);
                      }}
                    >
                      <option value="">Choose safe source…</option>
                      {variables.map((v) => (
                        <option key={v.name} value={v.name}>
                          {v.name} — {v.description}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div className="field">
            <label>Preview (sample data)</label>
            <div className="preview-box">
              {showTitle && preview.title ? <div className="preview-heading"><strong>{preview.title}</strong></div> : null}
              {showSubject && preview.subject ? <div className="preview-heading"><strong>{preview.subject}</strong></div> : null}
              <div>{preview.body || <span className="faint">(empty)</span>}</div>
            </div>
          </div>

          <hr className="hr" />

          <div className="card-head">
            <h3>Test send</h3>
            <div className="spacer" />
            <span className="small faint">Ignores the on/off toggles</span>
          </div>

          <div className="grid cols-2">
            <div className="field">
              <label htmlFor="t-user">Send to user</label>
              <select
                id="t-user"
                className="input"
                value={testUser}
                onChange={(e) => {
                  setTestUser(e.target.value);
                  const found = users.find((u) => String(u.id) === e.target.value);
                  if (found) {
                    setTestEmail(found.email);
                    setTestPhone(found.profile.phone_e164);
                  }
                }}
              >
                <option value="">Me ({users.find((u) => u.is_admin)?.username ?? "admin"})</option>
                {users
                  .filter((u) => !u.is_admin)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username} — {u.email}
                    </option>
                  ))}
              </select>
            </div>
            {channel === "email" ? (
              <div className="field">
                <label htmlFor="t-email">Override email</label>
                <input
                  id="t-email"
                  className="input"
                  value={testEmail}
                  placeholder="you@example.com"
                  onChange={(e) => setTestEmail(e.target.value)}
                />
              </div>
            ) : null}
            {channel === "whatsapp" ? (
              <div className="field">
                <label htmlFor="t-phone">Override WhatsApp number</label>
                <input
                  id="t-phone"
                  className="input mono"
                  value={testPhone}
                  placeholder="+919876543210"
                  onChange={(e) => setTestPhone(e.target.value)}
                />
                <div className="help">Must be an approved sandbox test recipient.</div>
              </div>
            ) : null}
          </div>

          {error ? <div className="alert err">{error}</div> : null}

          {results ? (
            <div className="mt-1">
              {results.map((r) => (
                <div key={r.channel} className="alert" style={{ marginBottom: 8 }}>
                  <div className="row tight">
                    <StatusBadge status={r.status} />
                    <strong>{r.channel}</strong>
                    {r.destination ? <span className="small faint mono">{r.destination}</span> : null}
                  </div>
                  <div className="small mt-1">{r.error || r.message}</div>
                </div>
              ))}
            </div>
          ) : null}
        </div>

        <div className="drawer-foot">
          <button className="btn primary" onClick={save} disabled={saving || testing || syncing}>
            {saving ? <Spinner /> : null} {draft.id ? "Save changes" : "Create template"}
          </button>
          <button className="btn" onClick={testSend} disabled={saving || testing || syncing}>
            {testing ? <Spinner /> : null} Test send
          </button>
          {dirty ? <span className="small warn" style={{ color: "var(--warn)" }}>Unsaved</span> : null}
          <div className="spacer" />
          {draft.id ? (
            <button className="btn danger" onClick={remove} disabled={saving || testing || syncing}>
              Delete
            </button>
          ) : null}
          <button className="btn ghost" onClick={onClose} disabled={saving || testing || syncing}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
