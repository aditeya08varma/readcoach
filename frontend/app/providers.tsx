"use client";

import { SessionProvider } from "next-auth/react";
import PageTransition from "@/components/PageTransition";
import { Toaster } from "@/components/ui/sonner";

export default function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <PageTransition>{children}</PageTransition>
      <Toaster position="top-center" richColors />
    </SessionProvider>
  );
}
