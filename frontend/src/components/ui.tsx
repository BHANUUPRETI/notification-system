"use client";

export function Toggle({
  checked,
  onChange,
  disabled,
  label,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  label: string;
}) {
  return (
    <label className="switch" title={label}>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        aria-label={label}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="track" />
    </label>
  );
}

export function Spinner() {
  return <span className="spinner" aria-label="loading" />;
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; label: string }> = {
    sent: { cls: "ok", label: "Sent" },
    simulated: { cls: "info", label: "Simulated" },
    failed: { cls: "err", label: "Failed" },
    skipped: { cls: "muted", label: "Skipped" },
  };
  const entry = map[status] ?? { cls: "muted", label: status };
  return <span className={`badge ${entry.cls}`}>{entry.label}</span>;
}

export function EmptyState({
  icon = "📭",
  title,
  children,
}: {
  icon?: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <div className="big">{icon}</div>
      <div style={{ fontWeight: 600, color: "var(--text-dim)" }}>{title}</div>
      {children ? <div className="small mt-1">{children}</div> : null}
    </div>
  );
}
