"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowRight, BrainCircuit, FileCheck2, FileDiff, FileScan, FlaskConical, KeyRound, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, human } from "@/lib/api";
import type { Analysis, Audit, Engine, User } from "@/lib/types";
import { AuditList, Consent, ErrorBox, Loading, PageHead, Panel, Pill, RunButton, TextLink } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { useUser } from "@/components/shell";

export function SecurityPage() {
  const user = useUser();
  const [consent, setConsent] = useState(false);
  const query = useQuery({ queryKey: ["security"], queryFn: () => api<{ events: Audit[]; counts: Record<string, number>; signals: Record<string, number> }>("/security") });
  const summary = useMutation({ mutationFn: () => api<{ answer: string; source: string; engine: Engine }>("/security/summary", { external_ai: consent }) });
  return <><PageHead tag="OPERATIONS / SECURITY" title="Security monitoring" text="Review access denials, account activity, and forensic alerts recorded by the API." />
    {query.isPending ? <Loading /> : query.error || !query.data ? <ErrorBox error={query.error} /> : <>
      <div className="stats-grid">{Object.entries({ "Access denials": query.data.counts.access_denied || 0, "Failed sign-ins": query.data.counts.login_failed || 0,
        "Suspicious uploads": query.data.counts.suspicious_upload || 0, "Verification attempts": query.data.counts.public_verification || 0 }).map(([label, count]) =>
        <article className="stat amber" key={label}><div><span>{label}</span><strong>{count}</strong></div><i><ShieldAlert size={19} /></i></article>)}</div>
      <div className="workspace-grid dashboard-grid space-top">
        <Panel title="Audit events" hint="Up to 150 recent events visible to your account."><AuditList rows={query.data.events} /></Panel>
        <Panel title="Activity patterns" hint="Patterns from the same audit window.">
          <dl className="field-list">{Object.entries(query.data.signals).map(([label, count]) => <div key={label}><dt>{human(label)}</dt><dd>{count}</dd></div>)}</dl>
          {user.data?.role === "admin" && <form className="form-stack space-top" onSubmit={event => { event.preventDefault(); summary.mutate(); }}>
            <Consent value={consent} setValue={setConsent} text="Allow Groq to summarize aggregate event counts." /><ErrorBox error={summary.error} />
            <div><RunButton busy={summary.isPending} disabled={!consent}>Summarize activity</RunButton></div>
            {summary.data && <div className="answer"><small>{summary.data.source}</small><p>{summary.data.answer}</p>{summary.data.engine.detail && <p className="muted">{summary.data.engine.detail}</p>}</div>}
          </form>}
        </Panel>
      </div>
    </>}
  </>;
}

export function InstitutionsPage({ admin = false }: { admin?: boolean }) {
  const cache = useQueryClient();
  const query = useQuery({ queryKey: ["institutions"], queryFn: () => api<User[]>("/admin/users") });
  const update = useMutation({ mutationFn: (user: User) => api<User>("/admin/users/" + user.id + "/role", { role: user.role === "institution" ? "verifier" : "institution" }),
    onSuccess: () => { void cache.invalidateQueries({ queryKey: ["institutions"] }); void cache.invalidateQueries({ queryKey: ["dashboard"] }); toast.success("Institution access updated."); } });
  return <><PageHead tag="OPERATIONS / ADMIN" title={admin ? "Administration" : "Institution management"}
    text={admin ? "Review user roles and open platform administration tools." : "Grant and revoke institution issuance privileges."}
    action={admin && <Button variant="outline" asChild><Link href="/security">View security events <ArrowRight size={15} /></Link></Button>} />
    {query.isPending ? <Loading /> : query.error || !query.data ? <ErrorBox error={query.error} /> : <>
      {admin && <div className="stats-grid"><article className="stat"><div><span>Accounts in this view</span><strong>{query.data.length}</strong></div><i><Activity size={20} /></i></article>
        <article className="stat violet"><div><span>Institutions in this view</span><strong>{query.data.filter(item => item.role === "institution").length}</strong></div></article></div>}
      <Panel title={admin ? "Account directory" : "Issuer authorization"} className={admin ? "space-top" : ""} action={admin && <TextLink href="/institutions">Manage institutions</TextLink>}>
        <ErrorBox error={update.error} /><div className="table-wrap"><table><thead><tr><th>Account</th><th>Email</th><th>Role</th>{!admin && <th>Action</th>}</tr></thead><tbody>
          {query.data.map(item => <tr key={item.id}><td>{item.name}</td><td>{item.email}</td><td><Pill value={item.role} /></td>{!admin && <td>{item.role !== "admin" &&
            <Button size="sm" variant="outline" disabled={update.isPending} onClick={() => update.mutate(item)}>{item.role === "institution" ? "Remove issuer access" : "Verify as institution"}</Button>}</td>}</tr>)}
        </tbody></table></div>
      </Panel>
    </>}
  </>;
}

export function DemoPage() {
  const router = useRouter();
  const cache = useQueryClient();
  const info = useQuery({ queryKey: ["demo"], queryFn: () => api<{ restricted_ref: string; actor_role: string; failure_case: boolean }>("/demo") });
  const [consent, setConsent] = useState(false);
  const [status, setStatus] = useState<{ code: number; message: string } | null>(null);
  const run = useMutation({ mutationFn: async (scenario: string) => {
    if (scenario === "restricted") {
      const res = await fetch("/api/certificates/" + info.data?.restricted_ref + "/original", { cache: "no-store" });
      const detail = !res.ok ? (await res.json()).detail : "The signed-in role has access to the original.";
      setStatus({ code: res.status, message: detail });
      void cache.invalidateQueries({ queryKey: ["security"] });
      return;
    }
    const value = await api<Analysis>("/demo/" + scenario, { external_ai: consent });
    void cache.invalidateQueries({ queryKey: ["history"] });
    void cache.invalidateQueries({ queryKey: ["dashboard"] });
    if (scenario === "reset") { setStatus(null); toast.success("Demo runs reset."); return; }
    router.push("/analyzer?job=" + value.id);
  } });
  const scenarios = [
    { key: "genuine", title: "Genuine certificate", description: "Inspect the evidence and verify a signed issuance record.", icon: FileCheck2, tone: "green" },
    { key: "modified", title: "Modified grade", description: "Compare the changed grade with the registered original and verify its fingerprint.", icon: FileDiff, tone: "red" },
    { key: "unknown", title: "Unknown certificate", description: "Inspect a fictional credential without a trusted issuance record.", icon: FileScan, tone: "cyan" },
    { key: "failure", title: "Model failure analysis", description: "Rerun a held-out synthetic error case and examine the model’s limitations.", icon: BrainCircuit, tone: "violet" },
    { key: "restricted", title: "Unauthorized access", description: "Request a private original and inspect the recorded HTTP response.", icon: KeyRound, tone: "amber" },
  ];
  return <><PageHead tag="LAB / LIVE SCENARIOS" title="Live demo lab" text="Run real analyses on fictional credentials and inspect the evidence as it arrives."
    action={<Button variant="outline" disabled={run.isPending || !info.data} onClick={() => run.mutate("reset")}>Reset demo</Button>} />
    <ErrorBox error={info.error || run.error} />
    {info.isPending ? <Loading /> : info.data && <>
      <Panel className="demo-banner"><div className="row"><FlaskConical size={22} className="accent" /><div><h2>Presentation mode</h2>
        <p className="muted">The restricted access scenario uses the current account’s role. Sign in as a verifier to show the denial.</p></div></div>
        <Consent value={consent} setValue={setConsent} text="Enable Gemini and Groq for these fictional examples when configured." /></Panel>
      <div className="demo-grid space-top">{scenarios.map((item, index) =>
        <Panel key={item.key} className={"scenario " + item.tone}><div className="scenario-top"><i><item.icon size={22} /></i><small>SCENARIO 0{index + 1}</small></div>
          <h2>{item.title}</h2><p>{item.description}</p><Button variant="outline" disabled={run.isPending || (item.key === "failure" && !info.data.failure_case)}
            onClick={() => run.mutate(item.key)}>{run.isPending && run.variables === item.key ? "Starting…" : "Run scenario"} <ArrowRight size={15} /></Button>
        </Panel>)}</div>
      {status && <div role="status" className={"notice space-top " + (status.code === 403 ? "error" : "info")}><ShieldAlert size={18} />
        <div><strong>HTTP {status.code}</strong><p>{status.message}</p>{status.code === 403 && <TextLink href="/security">Open recorded security alert</TextLink>}</div></div>}
    </>}
  </>;
}
