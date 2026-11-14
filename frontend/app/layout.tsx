import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Nebo — El cielo tiene más que contar",
  description:
    "Explora el cielo y compara imágenes infrarrojas de SPHEREx a través del tiempo.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
