import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NOVA",
  description: "Ahmed's personal AI operating assistant",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
