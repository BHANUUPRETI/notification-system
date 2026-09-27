"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { useAuth } from "@/lib/auth";
import { useToast } from "./Toast";

const NAV = [
  { href: "/", label: "Home" },
  { href: "/dashboard", label: "My account" },
  { href: "/admin", label: "Overview", admin: true },
  { href: "/admin/notifications", label: "Notifications", admin: true },
  { href: "/admin/logs", label: "Activity", admin: true },
  { href: "/admin/users", label: "Users", admin: true },
];

export function TopBar() {
  const { user, isAdmin, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();

  useEffect(() => {
    if (user && !isAdmin && pathname.startsWith("/admin")) router.replace("/dashboard");
  }, [user, isAdmin, pathname, router]);

  async function handleLogout() {
    try {
      await logout();
      toast.ok("Signed out", "The logout trigger was fired.");
      router.push("/login");
    } catch {
      toast.err("Sign out failed");
    }
  }

  return (
    <header className="topbar">
      <Link href="/" className="brand" style={{ color: "inherit", textDecoration: "none" }}>
        <span className="brand-mark">🔔</span>
        <span>
          Notify
          <small>notification system</small>
        </span>
      </Link>

      <nav className="nav">
        {NAV.filter((item) => !item.admin || isAdmin).map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={pathname === item.href ? "active" : ""}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      <div className="spacer" />

      {user ? (
        <div className="row tight">
          <span className="badge muted nowrap">
            {user.first_name || user.username}
            {isAdmin ? " · admin" : ""}
          </span>
          <button className="btn small ghost" onClick={handleLogout}>
            Sign out
          </button>
        </div>
      ) : (
        <Link href="/login" className="btn small primary">
          Sign in
        </Link>
      )}
    </header>
  );
}
