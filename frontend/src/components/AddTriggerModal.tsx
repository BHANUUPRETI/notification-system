"use client";

import { useEffect, useState } from "react";

import { ApiError, api, type Trigger } from "@/lib/api";
import { useToast } from "./Toast";
import { Spinner } from "./ui";

interface FormState {
  name: string;
  key: string;
  kind: "event" | "inactivity";
  days: string;
  description: string;
  is_active: boolean;
}

const EMPTY: FormState = {
  name: "",
  key: "",
  kind: "event",
  days: "7",
  description: "",
  is_active: true,
};

/** Mirrors the backend's slugify so the preview matches what will be stored. */
function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

export function AddTriggerModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (trigger: Trigger) => void;
}) {
  const toast = useToast();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((f) => ({ ...f, [key]: value }));
    setErrors((e) => ({ ...e, [key]: "", config: "" }));
  }

  const derivedKey = slugify(form.name);
  const finalKey = form.key.trim() || derivedKey;

  async function submit() {
    setBusy(true);
    setErrors({});
    try {
      const body: Record<string, unknown> = {
        name: form.name.trim(),
        kind: form.kind,
        description: form.description.trim(),
        is_active: form.is_active,
      };
      if (form.key.trim()) body.key = form.key.trim();
      if (form.kind === "inactivity") {
        body.config = { days: Number(form.days) || 0 };
      }

      const created = await api<Trigger>("/api/triggers/", { method: "POST", body });
      toast.ok("Trigger added", `${created.name} — now fill its three channels.`);
      onCreated(created);
    } catch (e) {
      if (e instanceof ApiError) {
        if (typeof e.detail === "string") {
          setErrors({ name: e.friendly });
        } else {
          const flat: Record<string, string> = {};
          for (const [field, messages] of Object.entries(e.detail)) {
            flat[field] = messages.join(" ");
          }
          setErrors(flat);
        }
        toast.err("Could not add trigger", e.friendly);
      } else {
        toast.err("Could not add trigger");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="overlay modal-wrap"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div className="modal" role="dialog" aria-label="Add trigger">
        <div className="drawer-head">
          <h3>Add trigger</h3>
          <div className="spacer" />
          <button className="btn small ghost icon" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="drawer-body">
          <p className="small dim">
            A trigger is anything that should send a message — a user action or a
            condition. It becomes a new row in the table; then you fill its
            WhatsApp, Email and Web Push cells.
          </p>

          <div className="field">
            <label htmlFor="t-name">Name</label>
            <input
              id="t-name"
              className="input"
              value={form.name}
              placeholder="Cart Abandoned"
              onChange={(e) => update("name", e.target.value)}
            />
            {errors.name ? <div className="error">{errors.name}</div> : null}
          </div>

          <div className="field">
            <label htmlFor="t-key">Key</label>
            <input
              id="t-key"
              className="input mono"
              value={form.key}
              placeholder={derivedKey || "cart-abandoned"}
              onChange={(e) => update("key", e.target.value)}
            />
            <div className="help">
              Leave blank to use <code className="mono">{finalKey || "…"}</code>. This
              is the name your code passes when firing the trigger.
            </div>
          </div>

          <div className="field">
            <label htmlFor="t-kind">Type</label>
            <select
              id="t-kind"
              className="input"
              value={form.kind}
              onChange={(e) => update("kind", e.target.value as FormState["kind"])}
            >
              <option value="event">Event — fired by the code (e.g. a button)</option>
              <option value="inactivity">
                Inactivity window — fired by the daily scan
              </option>
            </select>
          </div>

          {form.kind === "inactivity" ? (
            <div className="field">
              <label htmlFor="t-days">Inactive for how many days?</label>
              <input
                id="t-days"
                className="input mono"
                type="number"
                min={1}
                max={365}
                value={form.days}
                onChange={(e) => update("days", e.target.value)}
              />
              {errors.config ? <div className="error">{errors.config}</div> : null}
              <div className="help">
                Run <code className="mono">manage.py scan_inactive</code> (or the
                scheduler endpoint) once a day to notify these users.
              </div>
            </div>
          ) : null}

          <div className="field">
            <label htmlFor="t-desc">Description</label>
            <input
              id="t-desc"
              className="input"
              value={form.description}
              placeholder="User leaves items in the cart for 2 hours."
              onChange={(e) => update("description", e.target.value)}
            />
          </div>

          <div className="row">
            <input
              id="t-active"
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => update("is_active", e.target.checked)}
            />
            <label htmlFor="t-active" className="small">
              Enabled
            </label>
          </div>
        </div>

        <div className="drawer-foot">
          <button
            className="btn primary"
            onClick={submit}
            disabled={busy || !form.name.trim()}
          >
            {busy ? <Spinner /> : null} Add trigger
          </button>
          <div className="spacer" />
          <button className="btn ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
