import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Header } from "@/components/layout/header";
import { StatusBar } from "@/components/layout/status-bar";
import { SessionProvider } from "next-auth/react"
import { Providers } from "@/components/providers"

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
});

export const metadata: Metadata = {
  title: "C Code Review Dashboard",
  description: "AI-powered code review system for C/C++ pull requests",
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
        <main className="min-h-screen overflow-auto bg-background">
          {children}
        </main>
  )
}