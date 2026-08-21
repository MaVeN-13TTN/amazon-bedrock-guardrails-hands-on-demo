import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kilimo Desk — Bedrock Guardrails demo",
  description:
    "Amazon Bedrock Guardrails as a screen / answer / verify pipeline, demonstrated on a fictional Kenyan farming co-operative.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
