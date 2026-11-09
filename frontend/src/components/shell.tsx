"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenCheck, BrainCircuit, Building2, FileDiff, FileScan, Fingerprint, FlaskConical, History, LayoutDashboard, LogOut, Menu, MessageSquareText, ScanLine, Settings, ShieldAlert, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { toast } from "sonner";
import { api, human } from "@/lib/api";
import type { User } from "@/lib/types";
import { Brand, ErrorBox, Loading } from "@/components/ui";
import { Button } from "@/components/ui/button";

const groups = [
  { name: "WORKSPACE", links: [
    { path: "/dashboard", title: "Overview", icon: LayoutDashboard },
    { path: "/analyzer", title: "Document analyzer", icon: ScanLine },
    { path: "/compare", title: "Comparison", icon: FileDiff },
    { path: "/assistant", title: "Intelligence", icon: MessageSquareText },
    { path: "/history", title: "Verification history", icon: History },
    { path: "/reports", title: "Forensic reports", icon: BookOpenCheck },
  ] },
  { name: "TRUST & OPERATIONS", links: [
    { path: "/issue", title: "Certificate issuance", icon: Fingerprint, roles: ["institution", "admin"] },
    { path: "/verify", title: "QR verification", icon: FileScan },
    { path: "/security", title: "Security monitoring", icon: ShieldAlert },
    { path: "/institutions", title: "Institution management", icon: Building2, roles: ["admin"] },
    { path: "/admin", title: "Administration", icon: Settings, roles: ["admin"] },
  ] },
  { name: "LAB", links: [
    { path: "/demo", title: "Live demo", icon: FlaskConical },
    { path: "/model-performance", title: "Model performance", icon: BrainCircuit },
    { path: "/settings", title: "Settings", icon: Settings },
  ] },
];
const titles = Object.fromEntries(groups.flatMap(group => group.links.map(item => [item.path, item.title])));

export function useUser() { return useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me") }); }

export function Shell({ children, publicPage = false }: { children: ReactNode; publicPage?: boolean }) {
  const user = useUser();
  const route = usePathname();
  const router = useRouter();
  const cache = useQueryClient();
  const [menu, setMenu] = useState(false);
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ status: string; demo_enabled: boolean }>("/health"), refetchInterval: 30_000 });
  async function logout() {
    try { await api("/auth/logout", {}); cache.clear(); router.push("/"); } catch (error) { toast.error((error as Error).message); }
  }
  return <div className="shell">
    {menu && <button className="mobile-shade" onClick={() => setMenu(false)} aria-label="Close menu" />}
    <aside className={"sidebar " + (menu ? "opened" : "")}>
      <Brand /><div className="workspace-label"><span><Activity size={16} /></span><div><b>Forensic Workspace</b><small>Document trust platform</small></div></div>
      <nav aria-label="Main navigation">{groups.map(group => <div className="nav-group" key={group.name}>
        <p>{group.name}</p>{group.links.filter(link => (!link.roles || link.roles.includes(user.data?.role || "")) &&
          (link.path !== "/demo" || health.data?.demo_enabled !== false)).map(link => {
          const Icon = link.icon;
          const active = route === link.path || route.startsWith(link.path + "/");
          return <Link key={link.path} href={link.path} onClick={() => setMenu(false)} aria-current={active ? "page" : undefined}>
            <Icon size={17} />{link.title}{active && <i />}
          </Link>;
        })}</div>)}</nav>
      <div className="sidebar-footer">{user.data ? <><span className="avatar">{user.data.name.slice(0, 1).toUpperCase()}</span><div><b>{user.data.name}</b><small>{human(user.data.role)}</small></div>
        <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out"><LogOut size={17} /></Button></> :
        <Link href="/login">Sign in to your workspace</Link>}</div>
    </aside>
    <div className="main-shell">
      <header className="topbar"><div className="breadcrumb"><Button variant="ghost" size="icon" className="menu-button" aria-label="Toggle menu" onClick={() => setMenu(!menu)}>
        {menu ? <X size={19} /> : <Menu size={19} />}</Button><span>Workspace</span><i>/</i><strong>{titles[route] || (route.startsWith("/verify") ? "QR verification" : "VERIFEX")}</strong></div>
        <span className="health"><i className={health.data ? "online" : ""} />{health.data ? "API operational" : health.isPending ? "Connecting" : "API unavailable"}</span></header>
      <main className="main-content">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={route} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: .17 }}>
            {publicPage || user.data ? children : user.isPending ? <Loading /> :
              <div className="auth-gate"><BarChart3 size={30} /><h1>Sign in to continue</h1><p>Your documents and reports belong to your workspace.</p>
                {user.error && !("status" in user.error && user.error.status === 401) && <ErrorBox error={user.error} />}
                <Button asChild><Link href={"/login?next=" + encodeURIComponent(route)}>Sign in</Link></Button></div>}
          </motion.div>
        </AnimatePresence>
        <footer className="workspace-footer"><span>VERIFEX / FORENSIC WORKSPACE</span><span>Local-first document intelligence</span></footer>
      </main>
    </div>
  </div>;
}
