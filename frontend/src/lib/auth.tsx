/**
 * Authentication context.
 *
 * The Django API issues a DRF token; we keep it in localStorage and expose it
 * through a React context so every page can read the current user.
 */

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, getToken, setToken, type User } from "./api";

interface AuthState {
  user: User | null;
  loading: boolean;
  error: string | null;
  isAdmin: boolean;
  login: (identifier: string, password: string) => Promise<{ user: User; notification: unknown }>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<User>("/api/auth/me/");
      setUser(me);
      setError(null);
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!user || !getToken()) return;
    const markActivity = () => {
      void api<{ last_seen_at: string }>("/api/users/activity/", { method: "POST", body: {} }).catch(() => {
        // A heartbeat must never interrupt normal browsing. Auth failures are
        // handled by the regular /me refresh path.
      });
    };
    markActivity();
    const interval = window.setInterval(markActivity, 5 * 60 * 1000);
    const onVisible = () => {
      if (document.visibilityState === "visible") markActivity();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [user]);

  const login = useCallback(
    async (identifier: string, password: string) => {
      setError(null);
      const data = await api<{
        token: string;
        user: User;
        notification: unknown;
      }>("/api/auth/login/", {
        method: "POST",
        auth: false,
        body: { identifier, password },
      });
      setToken(data.token);
      setUser(data.user);
      return data;
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      await api("/api/auth/logout/", { method: "POST", body: {} });
    } finally {
      setToken(null);
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      error,
      isAdmin: Boolean(user?.is_admin),
      login,
      logout,
      refresh,
    }),
    [user, loading, error, login, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
