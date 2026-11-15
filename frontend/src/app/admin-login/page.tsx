"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Suspense, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { Brand, ErrorBox, Loading, Panel, RunButton } from "@/components/ui";

function AdminForm() {
  const params = useSearchParams();
  const target = params.get("next") === "/institutions" ? "/institutions" : "/admin";
  const status = useQuery({ queryKey: ["admin-login-config"], queryFn: () => api<{ local_admin_login: boolean }>("/health") });
  const login = useMutation({
    mutationFn: (data: FormData) => api<User>("/auth/admin/login", {
      username: data.get("username"), password: data.get("password"),
    }),
    onSuccess: () => window.location.assign(target),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login.mutate(new FormData(event.currentTarget));
  }

  if (status.isPending) return <Loading />;
  if (status.error) return <ErrorBox error={status.error} />;
  if (!status.data?.local_admin_login) return <p role="status">Admin password sign-in is available on localhost.</p>;

  return <form className="form-stack" onSubmit={submit}>
    <label>Username<input name="username" autoComplete="username" maxLength={80} required /></label>
    <label>Password<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>
    <ErrorBox error={login.error} />
    <div><RunButton busy={login.isPending} disabled={login.isPending}>Sign in as admin</RunButton></div>
  </form>;
}

export default function AdminLoginPage() {
  return <main className="landing">
    <header className="landing-nav"><Brand /><Link href="/login">User sign in</Link></header>
    <Panel className="login-panel" title="Admin sign in">
      <Suspense fallback={<Loading />}><AdminForm /></Suspense>
    </Panel>
  </main>;
}
