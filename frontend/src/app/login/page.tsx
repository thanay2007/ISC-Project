"use client";
import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Fingerprint } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { Brand, ErrorBox, Loading, RunButton } from "@/components/ui";

function LoginForm() {
  const [register, setRegister] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>();
  const router = useRouter();
  const params = useSearchParams();
  const cache = useQueryClient();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true); setError(null);
    const form = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const user = await api<User>(register ? "/auth/register" : "/auth/login", form);
      cache.clear(); cache.setQueryData(["me"], user);
      const next = params.get("next");
      router.push(next && /^\/[a-z][a-z0-9/-]*$/i.test(next) ? next : "/dashboard");
    } catch (failure) { setError(failure); } finally { setPending(false); }
  }
  return <main className="login-page"><header><Brand /><Link className="text-link" href="/"><ArrowLeft size={15} /> Home</Link></header>
    <div className="login-panel panel"><div className="login-icon"><Fingerprint size={27} /></div><p className="eyebrow"><span /> SECURE WORKSPACE</p>
      <h1>{register ? "Create your workspace" : "Sign in to VERIFEX"}</h1><p className="muted">{register ? "New accounts start with verifier access." : "Open your private document investigations."}</p>
      <form className="form-stack" onSubmit={submit}>
        {register && <label>Display name<input name="name" autoComplete="name" minLength={2} maxLength={120} required /></label>}
        <label>Email address<input name="email" type="email" autoComplete="email" maxLength={254} required /></label>
        <label>Password<input name="password" type="password" autoComplete={register ? "new-password" : "current-password"} minLength={register ? 12 : 1} maxLength={128} required /></label>
        {register && <small>Use at least 12 characters.</small>}<ErrorBox error={error} /><RunButton busy={pending}>{register ? "Create account" : "Sign in"}</RunButton>
      </form>
      <button className="link-button" type="button" onClick={() => { setRegister(!register); setError(null); }}>{register ? "Already registered? Sign in" : "New to VERIFEX? Create an account"}</button>
    </div></main>;
}
export default function LoginPage() { return <Suspense fallback={<Loading />}><LoginForm /></Suspense>; }
