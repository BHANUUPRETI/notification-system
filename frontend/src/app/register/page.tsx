"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { api, ApiError, setToken, type User } from "@/lib/api";
import { Spinner } from "@/components/ui";

export default function RegisterPage() {
  const router = useRouter();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    username: "",
    email: "",
    password: "",
    first_name: "",
    last_name: "",
    phone_number: "",
  });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const data = await api<{ token: string; access: string; refresh: string; user: User }>(
        "/api/auth/register/",
        { method: "POST", auth: false, body: form },
      );
      setToken(data.token);
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.friendly : "Registration failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="auth-wrap">
      <form className="auth-card" onSubmit={submit}>
        <h1>Create account</h1>
        <p className="dim">Register a user to test login/logout notification triggers.</p>
        <div className="grid cols-2">
          <div className="field">
            <label>First name</label>
            <input className="input" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          </div>
          <div className="field">
            <label>Last name</label>
            <input className="input" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          </div>
        </div>
        <div className="field">
          <label>Username</label>
          <input className="input" required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </div>
        <div className="field">
          <label>Email</label>
          <input className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="field">
          <label>WhatsApp number (optional)</label>
          <input className="input mono" placeholder="+919876543210" value={form.phone_number} onChange={(e) => setForm({ ...form, phone_number: e.target.value })} />
        </div>
        <div className="field">
          <label>Password</label>
          <input className="input" type="password" minLength={8} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        {error ? <div className="alert err">{error}</div> : null}
        <button className="btn primary" disabled={saving} type="submit">
          {saving ? <Spinner /> : null} Register
        </button>
        <p className="small faint">Already registered? <Link href="/login">Sign in</Link></p>
      </form>
    </main>
  );
}
