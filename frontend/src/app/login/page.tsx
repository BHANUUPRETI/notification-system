"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/components/Toast";
import { Spinner } from "@/components/ui";

const DEMO = [
  { id: "admin", password: "admin12345", role: "Admin (all channels)" },
  { id: "amit", password: "demo12345", role: "User, has a phone number" },
  { id: "priya", password: "demo12345", role: "User" },
  { id: "demo", password: "demo12345", role: "User, no phone number" },
];

export default function LoginPage() {
  const { login, user, isAdmin } = useAuth();
  const router = useRouter();
  const toast = useToast();

  const [identifier, setIdentifier] = useState("admin");
  const [password, setPassword] = useState("admin12345");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Redirect once the auth context has settled, not during render.
  useEffect(() => {
    if (user) router.replace(isAdmin ? "/admin/notifications" : "/dashboard");
  }, [user, isAdmin, router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(identifier.trim(), password);
      toast.ok("Welcome back", "The login trigger was fired.");
      router.push("/dashboard");
    } catch (e) {
      const message =
        e instanceof ApiError ? e.friendly : "Could not reach the backend. Is Django running?";
      setError(message);
      toast.err("Sign in failed", message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-wrap">
      <div className="auth-card">
        <div className="card">
          <div className="brand" style={{ marginBottom: 2 }}>
            <span className="brand-mark">🔔</span>
            <span>Notify</span>
          </div>
          <p className="center small dim" style={{ marginBottom: 18 }}>
            Sign in with your username or email.
          </p>

          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="identifier">Username or email</label>
              <input
                id="identifier"
                className="input"
                value={identifier}
                autoComplete="username"
                onChange={(e) => setIdentifier(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                className="input"
                value={password}
                autoComplete="current-password"
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error ? <div className="alert err mb-1">{error}</div> : null}

            <button className="btn primary block" type="submit" disabled={busy}>
              {busy ? <Spinner /> : null} Sign in
            </button>
          </form>

          <hr className="hr" />
          <p className="small dim" style={{ marginBottom: 8 }}>
            Seeded demo accounts
          </p>
          <div className="chip-list">
            {DEMO.map((d) => (
              <button
                key={d.id}
                type="button"
                className="chip"
                title={`${d.role} · password ${d.password}`}
                onClick={() => {
                  setIdentifier(d.id);
                  setPassword(d.password);
                }}
              >
                {d.id} / {d.password}
              </button>
            ))}
          </div>
          <p className="small faint mt-1">
            Click an account to fill the form. Admin sees the notification table.
          </p>
          <p className="small faint mt-1">
            Need a test user? <Link href="/register">Create an account</Link>
          </p>
        </div>

        <p className="center small faint mt-2">
          <Link href="/">← Back to home</Link>
        </p>
      </div>
    </main>
  );
}
