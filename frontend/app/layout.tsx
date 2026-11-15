import type { Metadata } from "next";
import "./globals.css";
import WarpOverlay from "@/components/WarpOverlay";
export const metadata: Metadata = {
  title: "Nebo — The sky has more to tell",
  description: "Explore the sky and compare SPHEREx infrared images over time.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        {/* Persistent across navigation: the loading tunnel of "Begin exploring". */}
        <WarpOverlay />
      </body>
    </html>
  );
}
