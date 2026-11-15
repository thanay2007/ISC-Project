"use client";

import { SignIn } from "@clerk/react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { useClerkState } from "@/components/providers";
import { Brand, Loading, Panel } from "@/components/ui";
import { Button } from "@/components/ui/button";

const workspacePath = /^\/(?:dashboard|analyzer|assistant|history|reports|issue|security|institutions|admin|demo|model-performance|verify)(?:[?#]|$)/;

function ClerkForm() {
  const { configured, ready, configUnavailable, retryConfig, sessionId } = useClerkState();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "";
  const target = workspacePath.test(next) && !/[\\\x00-\x20\x7f]/.test(next) ? next : "/dashboard";

  useEffect(() => {
    if (sessionId) router.replace(target);
  }, [router, sessionId, target]);

  if (!ready || sessionId) return <Loading />;
  if (configUnavailable) return <div>
    <p role="alert">The VERIFEX API is unavailable. Check the server terminal, then retry.</p>
    <Button onClick={retryConfig}>Retry</Button>
  </div>;
  if (!configured) return <p role="status" className="muted">Clerk is unavailable until the server has Clerk API keys.</p>;

  return <div className="clerk-form">
    <SignIn
      routing="hash"
      withSignUp
      forceRedirectUrl={target}
      signUpForceRedirectUrl={target}
      appearance={{ elements: { footerAction__signUp: { display: "none" } } }}
    />
  </div>;
}

export function AuthPage() {
  return <main className="landing">
    <header className="landing-nav"><Brand /><Link href="/">Home</Link></header>
    <Panel className="login-panel" title="Sign in to VERIFEX">
      <Suspense fallback={<Loading />}><ClerkForm /></Suspense>
      <div className="admin-login-action">
        <Button asChild variant="outline"><Link href="/admin-login">Admin sign in</Link></Button>
      </div>
    </Panel>
  </main>;
}
