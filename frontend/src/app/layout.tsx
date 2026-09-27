import type { Metadata, Viewport } from "next";

import { TopBar } from "@/components/TopBar";
import { ToastProvider } from "@/components/Toast";
import { AuthProvider } from "@/lib/auth";

import "./globals.css";

export const metadata: Metadata = {
  title: "Notify — Notification System",
  description:
    "Admin-managed notifications over WhatsApp, Email and Web Push. Django + Next.js.",
};

export const viewport: Viewport = {
  themeColor: "#0b0f17",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <ToastProvider>
            <TopBar />
            {children}
          </ToastProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
