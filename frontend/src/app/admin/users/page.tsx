"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError, type User } from "@/lib/api";
import { EmptyState, Spinner } from "@/components/ui";

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("search", search.trim());
      setUsers(await api<User[]>(`/api/users/?${params.toString()}`));
    } catch (e) {
      setError(e instanceof ApiError ? e.friendly : "Could not load users.");
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="container wide">
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p className="sub">
            Who can receive notifications, and where each channel will reach them.
          </p>
        </div>
      </div>

      <div className="card mb-2">
        <div className="row">
          <input
            className="input"
            style={{ maxWidth: 280 }}
            placeholder="Search username, email or name"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className="btn" onClick={load} disabled={loading}>
            Search
          </button>
          <div className="spacer" />
          <span className="small faint">{users.length} users</span>
        </div>
      </div>

      {error ? <div className="alert err mb-2">{error}</div> : null}

      <div className="table-wrap">
        <table className="grid-table" style={{ minWidth: 900 }}>
          <thead>
            <tr>
              <th>User</th>
              <th>Email</th>
              <th>WhatsApp</th>
              <th>Last seen</th>
              <th>Push</th>
              <th>Opt-ins</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id}>
                <td>
                  <div style={{ fontWeight: 600 }}>
                    {user.first_name} {user.last_name}
                  </div>
                  <div className="small faint mono">{user.username}</div>
                  {user.is_admin ? <span className="badge info">admin</span> : null}
                </td>
                <td className="small mono">{user.email || "—"}</td>
                <td className="small mono">
                  {user.profile.phone_e164 || <span className="faint">not set</span>}
                </td>
                <td className="small dim">
                  {user.profile.last_seen_at
                    ? new Date(user.profile.last_seen_at).toLocaleDateString()
                    : "never"}
                </td>
                <td>
                  {user.push_subscriptions.filter((s) => s.is_active).length > 0 ? (
                    <span className="badge ok">{user.push_subscriptions.filter((s) => s.is_active).length} active</span>
                  ) : (
                    <span className="badge muted">none</span>
                  )}
                </td>
                <td>
                  <div className="chip-list">
                    {user.profile.whatsapp_opt_in ? <span className="badge wa">WA</span> : null}
                    {user.profile.email_opt_in ? <span className="badge email">Mail</span> : null}
                    {user.profile.webpush_opt_in ? <span className="badge push">Push</span> : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!loading && users.length === 0 ? (
        <div className="card mt-2">
          <EmptyState icon="👥" title="No users found" />
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
