"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Building2, Fingerprint, History, LayoutDashboard, LogIn, Menu, MessageSquareText, ScanLine, Settings, X, type LucideIcon } from "lucide-react";
import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ApiError, api } from "@/lib/api";
import type { User } from "@/lib/types";
import { Brand, ErrorBox, Loading, Panel } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { useClerkState } from "@/components/providers";

const groups: { name: string; hideForAdmin?: boolean; links: { path: string; title: string; icon: LucideIcon; roles?: User["role"][] }[] }[] = [
  { name: "WORKSPACE", hideForAdmin: true, links: [
    { path: "/dashboard", title: "Overview", icon: LayoutDashboard },
    { path: "/analyzer", title: "Document analyzer", icon: ScanLine },
    { path: "/assistant", title: "Intelligence", icon: MessageSquareText },
    { path: "/history", title: "Verification history", icon: History },
    { path: "/reports", title: "Forensic reports", icon: BookOpenCheck },
  ] },
  { name: "TRUST & OPERATIONS", links: [
    { path: "/issue", title: "Certificate issuance", icon: Fingerprint, roles: ["institution", "admin"] },
    { path: "/institutions", title: "Institution management", icon: Building2, roles: ["admin"] },
    { path: "/admin", title: "Administration", icon: Settings, roles: ["admin"] },
  ] },
];
const titles: Record<string, string> = {
  ...Object.fromEntries(groups.flatMap(group => group.links.map(item => [item.path, item.title]))),
  "/security": "Security monitoring",
  "/demo": "Live demo",
  "/model-performance": "Model performance",
};

export function useUser(enabled = true) {
  const { ready, sessionId } = useClerkState();
  return useQuery({ queryKey: ["me", sessionId], queryFn: () => api<User>("/auth/guest", {}), enabled: enabled && ready });
}

function AccountActions({ user, route }: { user?: User; route: string }) {
  const router = useRouter();
  const cache = useQueryClient();
  const params = useSearchParams();
  const clerk = useClerkState();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const query = params.toString();
  const signIn = "/login?next=" + encodeURIComponent(route + (query ? "?" + query : ""));
  async function signOut() {
    setBusy(true);
    try {
      await api("/auth/logout", {});
      cache.clear();
      if (clerk.signOut) await clerk.signOut();
      else router.push("/");
    } catch (failure) {
      setError(failure);
      setBusy(false);
    }
  }
  return <div className="sidebar-account">{user && user.role !== "guest" ? <>
    <b>{user.name}</b><Button variant="ghost" size="sm" disabled={busy} onClick={signOut}>Sign out</Button><ErrorBox error={error} />
  </> : <Button size="sm" asChild><Link href={signIn}><LogIn size={15} /> Sign in</Link></Button>}</div>;
}

export function Shell({ children, publicPage = false, adminOnly = false }: { children: ReactNode; publicPage?: boolean; adminOnly?: boolean }) {
  const user = useUser(!publicPage && !adminOnly);
  const { ready, sessionId } = useClerkState();
  const session = useQuery({ queryKey: ["current-session", sessionId], queryFn: () => api<User>("/auth/me"), enabled: (adminOnly || publicPage) && ready });
  const account = adminOnly || publicPage ? session : user;
  const role = account.data?.role;
  const route = usePathname();
  const [menu, setMenu] = useState(false);
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ status: string }>("/health"), refetchInterval: 30_000 });
  return <div className="shell">
    {menu && <button className="mobile-shade" onClick={() => setMenu(false)} aria-label="Close menu" />}
    <aside className={"sidebar " + (menu ? "opened" : "")}>
      <Brand />
      <nav aria-label="Main navigation">{!account.isPending && groups.map(group => {
        if (role === "admin" && group.hideForAdmin) return null;
        const links = group.links.filter(link => !link.roles || (role && link.roles.includes(role)));
        return links.length > 0 && <div className="nav-group" key={group.name}>
        {role !== "admin" && <p>{group.name}</p>}{links.map(link => {
          const Icon = link.icon;
          const active = route === link.path || route.startsWith(link.path + "/");
          return <Link key={link.path} href={link.path} onClick={() => setMenu(false)} aria-current={active ? "page" : undefined}>
            <Icon size={17} />{link.title}{active && <i />}
          </Link>;
        })}</div>;
      })}</nav>
      <AccountActions user={account.data} route={route} />
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><Button variant="ghost" size="icon" className="menu-button" aria-label="Toggle menu" onClick={() => setMenu(!menu)}>
        {menu ? <X size={19} /> : <Menu size={19} />}</Button><span>Workspace</span><i>/</i><strong>{titles[route] || (route.startsWith("/verify") ? "QR verification" : "VERIFEX")}</strong></div>
        <span className="health"><i className={health.data ? "online" : ""} />{health.data ? "API operational" : health.isPending ? "Connecting" : "API unavailable"}</span></header>
      <main className="main-content">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={route} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: .17 }}>
            {adminOnly ? session.isPending ? <Loading /> : session.data?.role === "admin" ? children :
              session.error && !(session.error instanceof ApiError && session.error.status === 401) ? <ErrorBox error={session.error} /> :
              <Panel title="Administrator access required">{session.data && session.data.role !== "guest" ?
                <p>Your account does not have administrator access.</p> :
                <p>Sign in to manage this workspace.</p>}
                <Button asChild><Link href={"/admin-login?next=" + encodeURIComponent(route)}>Admin sign in</Link></Button>
              </Panel>
              : publicPage || user.data ? children : user.isPending ? <Loading /> : <ErrorBox error={user.error} />}
          </motion.div>
        </AnimatePresence>
        <footer className="workspace-footer"><span>VERIFEX / FORENSIC WORKSPACE</span><span>Local-first document intelligence</span></footer>
      </main>
    </div>
  </div>;
}
