import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Nebo — The sky has more to tell",
  description: "Explore the sky and compare SPHEREx infrared images over time.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
