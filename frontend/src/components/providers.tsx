"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { useState } from "react";
import { Toaster } from "sonner";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000 } } }));
  return <QueryClientProvider client={client}><MotionConfig reducedMotion="user">
    {children}<Toaster theme="dark" richColors position="bottom-right" />
  </MotionConfig></QueryClientProvider>;
}
