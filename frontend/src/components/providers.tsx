"use client";
import { ClerkProvider, useAuth, useClerk } from "@clerk/react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { createContext, useContext, useState, type ReactNode } from "react";
import { Toaster } from "sonner";
import { api } from "@/lib/api";

type ClerkState = {
  configured: boolean;
  ready: boolean;
  configUnavailable?: boolean;
  retryConfig?: () => void;
  sessionId?: string | null;
  signOut?: () => Promise<void>;
};
const ClerkStateContext = createContext<ClerkState>({ configured: false, ready: false });
export const useClerkState = () => useContext(ClerkStateContext);

function WorkspaceQueries({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000 } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function ClerkSession({ children }: { children: ReactNode }) {
  const { isLoaded, sessionId } = useAuth();
  const clerk = useClerk();
  return <ClerkStateContext.Provider value={{ configured: true, ready: isLoaded, sessionId,
    signOut: sessionId ? () => clerk.signOut() : undefined }}>
    <WorkspaceQueries key={sessionId || "guest"}>{children}</WorkspaceQueries>
  </ClerkStateContext.Provider>;
}

function WorkspaceAuth({ children }: { children: ReactNode }) {
  const config = useQuery({ queryKey: ["clerk-config"], queryFn: () => api<{ clerk_publishable_key: string | null }>("/health"), staleTime: Infinity });
  const key = config.data?.clerk_publishable_key;
  if (!key) return <ClerkStateContext.Provider value={{
    configured: false, ready: !config.isFetching,
    configUnavailable: config.isError, retryConfig: () => { void config.refetch(); },
  }}>
    <WorkspaceQueries>{children}</WorkspaceQueries>
  </ClerkStateContext.Provider>;
  return <ClerkProvider publishableKey={key} signInUrl="/login" afterSignOutUrl="/">
    <ClerkSession>{children}</ClerkSession>
  </ClerkProvider>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  return <QueryClientProvider client={client}><MotionConfig reducedMotion="user">
    <WorkspaceAuth>{children}</WorkspaceAuth><Toaster theme="dark" richColors position="bottom-right" />
  </MotionConfig></QueryClientProvider>;
}
