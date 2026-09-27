// ---------- API base ----------
// The browser calls Django directly (CORS is configured on the backend).
export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

// ---------- Channel ----------
export const CHANNELS = ["whatsapp", "email", "webpush"] as const;
export type Channel = (typeof CHANNELS)[number];

export const CHANNEL_META: Record<
  Channel,
  { label: string; short: string; icon: string; accent: string }
> = {
  whatsapp: { label: "WhatsApp", short: "WA", icon: "💬", accent: "wa" },
  email: { label: "Email", short: "Mail", icon: "✉️", accent: "email" },
  webpush: { label: "Web Push", short: "Push", icon: "🔔", accent: "push" },
};

// ---------- Models ----------
export interface Profile {
  phone_e164: string;
  whatsapp_opt_in: boolean;
  email_opt_in: boolean;
  webpush_opt_in: boolean;
  last_seen_at: string | null;
}

export interface User {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  is_staff: boolean;
  is_superuser: boolean;
  is_admin: boolean;
  date_joined: string;
  last_login: string | null;
  profile: Profile;
  push_subscriptions: Array<{
    id: number;
    provider: string;
    is_active: boolean;
    created_at: string;
  }>;
}

export interface Template {
  id: number;
  trigger: number;
  trigger_key: string;
  channel: Channel;
  channel_label: string;
  title: string;
  subject: string;
  body: string;
  provider_template_name: string;
  provider_template_id: string;
  provider_language: string;
  provider_status: ProviderStatus;
  provider_status_label: string;
  provider_status_note: string;
  provider_submitted_at: string | null;
  is_enabled: boolean;
  variables: string[];
  variable_mapping: Record<string, string>;
  placeholder_count: number;
  created_at: string;
  updated_at: string;
}

export const PROVIDER_STATUSES = [
  "not_submitted",
  "draft",
  "pending",
  "approved",
  "rejected",
] as const;
export type ProviderStatus = (typeof PROVIDER_STATUSES)[number];

export const PROVIDER_STATUS_META: Record<
  ProviderStatus,
  { label: string; badge: string; hint: string }
> = {
  not_submitted: {
    label: "Not submitted",
    badge: "muted",
    hint: "Only needed outside the 24-hour customer-care window.",
  },
  draft: {
    label: "Draft in Meta",
    badge: "info",
    hint: "Created in the Meta template console, not yet sent for review.",
  },
  pending: {
    label: "Pending review",
    badge: "warn",
    hint: "Meta is reviewing it. This can take minutes to hours.",
  },
  approved: {
    label: "Approved",
    badge: "ok",
    hint: "You can now use the template name when sending.",
  },
  rejected: {
    label: "Rejected",
    badge: "err",
    hint: "Fix the reason below and resubmit in Meta.",
  },
};

export interface Trigger {
  id: number;
  key: string;
  name: string;
  description: string;
  kind: "event" | "inactivity";
  config: Record<string, unknown>;
  is_active: boolean;
  order: number;
  days: number | null;
  templates: Template[];
  template_count: number;
  enabled_channels: Channel[];
  updated_at: string;
}

export type SendStatus = "sent" | "simulated" | "failed" | "skipped";

export interface ChannelResult {
  channel: string;
  status: SendStatus;
  message: string;
  error: string;
  destination: string;
  log_id: number | null;
}

export interface DispatchReport {
  trigger: string;
  results: ChannelResult[];
  summary: { sent: number; simulated: number; failed: number; skipped: number };
}

export interface NotificationLog {
  id: number;
  trigger: number | null;
  trigger_key: string | null;
  channel: Channel;
  channel_label: string;
  status: SendStatus;
  username: string | null;
  destination: string;
  rendered_title: string;
  rendered_subject: string;
  rendered_body: string;
  provider: string;
  provider_message_id: string;
  error: string;
  is_test: boolean;
  created_at: string;
}

export interface ProviderInfo {
  channel: Channel;
  label: string;
  provider: string;
  configured: boolean;
  message: string;
}

export interface VariableInfo {
  name: string;
  example: string;
  description: string;
}

export interface PublicConfig {
  sandbox: boolean;
  frontend_url: string;
  channels: Array<{ key: Channel; label: string }>;
  providers: ProviderInfo[];
  vapid_public_key: string;
  variables: VariableInfo[];
  /** Which Web Push transport the browser should subscribe through. */
  push?: {
    backend: "onesignal" | "vapid" | "none";
    onesignal_app_id: string;
    onesignal_configured: boolean;
    vapid_configured: boolean;
  };
  whatsapp?: {
    api_version: string;
    language: string;
    template_console_url: string;
    sync_configured?: boolean;
  };
}

export interface Stats {
  triggers: number;
  templates: number;
  templates_enabled: number;
  users: number;
  push_subscriptions: number;
  logs_last_7_days: {
    total: number;
    by_status: Partial<Record<SendStatus, number>>;
    by_channel: Partial<Record<Channel, number>>;
  };
  sandbox: boolean;
}

export interface PushSubscriptionInput {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

// ---------- Token storage ----------
const TOKEN_KEY = "notif.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

// ---------- HTTP ----------
export class ApiError extends Error {
  status: number;
  detail: Record<string, string[]> | string;

  constructor(status: number, message: string, detail?: Record<string, string[]> | string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail ?? message;
  }

  /** Flatten DRF error bodies into one readable line. */
  get friendly(): string {
    if (typeof this.detail === "string") return this.detail;
    const parts: string[] = [];
    for (const [field, errors] of Object.entries(this.detail)) {
      parts.push(field === "detail" ? errors.join(" ") : `${field}: ${errors.join(" ")}`);
    }
    return parts.join(" | ");
  }
}

type Options = Omit<RequestInit, "body"> & { body?: unknown; auth?: boolean };

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const { body, auth = true, headers, ...rest } = options;
  const finalHeaders = new Headers(headers);

  if (body !== undefined && !(body instanceof FormData)) {
    finalHeaders.set("Content-Type", "application/json");
  }
  if (auth) {
    const token = getToken();
    if (token) finalHeaders.set("Authorization", `Token ${token}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? safeJson(text) : null;

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `Request failed (${response.status})`,
      typeof payload === "string" || (payload && typeof payload === "object")
        ? (payload as string | Record<string, string[]>)
        : undefined,
    );
  }
  return payload as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
