import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AskWarehouse",
  description:
    "Text-to-SQL analytics agent: asks for clarification, writes SQL, runs it read-only, repairs its own errors, and returns a chart plus the SQL it used.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
