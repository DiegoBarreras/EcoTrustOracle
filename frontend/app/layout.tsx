import "./globals.css";
import "@solana/wallet-adapter-react-ui/styles.css";
import type { ReactNode } from "react";
import { Providers } from "./providers";

export const metadata = { title: "EcoTrust Oracle", description: "Physical ESG oracle on Solana Devnet" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body className="min-h-screen bg-slate-950 text-slate-100">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
