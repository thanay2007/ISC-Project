"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, Binary, Building2, FileScan, Fingerprint, KeyRound, QrCode, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";
import { api, dateText, human } from "@/lib/api";
import type { Analysis, Dashboard, Integrity } from "@/lib/types";
import { AnalysisTable, AuditList, Drop, Empty, ErrorBox, Loading, PageHead, Panel, Pill, RunButton, TextLink } from "@/components/ui";
import { Button } from "@/components/ui/button";
import { IntegrityPanel } from "@/components/analyzer";

const chartTheme = { contentStyle: { background: "#111b2d", border: "1px solid #243751", borderRadius: 8, color: "#f8fafc" }, labelStyle: { color: "#aebcd0" } };

function Stat({ label, value, icon, tone = "cyan", index = 0 }: { label: string; value: ReactNode; icon: ReactNode; tone?: string; index?: number }) {
  return <motion.article className={"stat " + tone} initial={{ opacity: 0, y: 9 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * .04, duration: .22 }}>
    <div><span>{label}</span><strong>{value}</strong></div><i>{icon}</i></motion.article>;
}

export function DashboardPage() {
  const [range, setRange] = useState("7");
  const query = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dashboard>("/dashboard") });
  const items = query.data?.counts || {};
  return <><PageHead tag="WORKSPACE / OVERVIEW" title="Forensic overview" text="Track the documents, integrity checks, and alerts in your workspace."
    action={<Button asChild><Link href="/analyzer"><FileScan size={17} /> New analysis <ArrowRight size={15} /></Link></Button>} />
    {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : <>
      <div className="stats-grid">
        <Stat label="Documents analyzed" value={items.analyzed ?? 0} icon={<FileScan size={20} />} />
        <Stat label="Verified certificates" value={items.verified ?? 0} icon={<ShieldCheck size={20} />} tone="green" index={1} />
        <Stat label="Suspicious / review" value={(items.suspicious || 0) + (items.manual_review || 0)} icon={<TriangleAlert size={20} />} tone="amber" index={2} />
        <Stat label="Signature failures" value={items.signature_failures ?? 0} icon={<KeyRound size={20} />} tone="red" index={3} />
        <Stat label="Unverified documents" value={items.unverified ?? 0} icon={<Fingerprint size={20} />} tone="violet" index={4} />
        <Stat label="Registered institutions" value={items.institutions ?? 0} icon={<Building2 size={20} />} index={5} />
      </div>
      <div className="workspace-grid dashboard-grid space-top">
        <Panel title="Verification activity" hint="Completed document checks by date (UTC)." action={<label><span className="sr-only">Date range</span>
          <select value={range} onChange={event => setRange(event.target.value)}><option value="7">Last 7 days</option><option value="3">Last 3 days</option></select></label>}>
          <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={query.data?.trends.slice(-Number(range))}>
            <defs><linearGradient id="activityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#00d9ff" stopOpacity={.25} /><stop offset="100%" stopColor="#00d9ff" stopOpacity={0} /></linearGradient></defs>
            <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 6" /><XAxis dataKey="day" tickFormatter={value => String(value).slice(5)} stroke="#96a9c3" tickLine={false} fontSize={11} />
            <YAxis allowDecimals={false} stroke="#96a9c3" tickLine={false} fontSize={11} /><Tooltip {...chartTheme} />
            <Area type="monotone" dataKey="analyzed" stroke="#00d9ff" fill="url(#activityFill)" strokeWidth={2} isAnimationActive={false} />
            <Area type="monotone" dataKey="verified" stroke="#10b981" fillOpacity={0} strokeWidth={2} isAnimationActive={false} />
          </AreaChart></ResponsiveContainer></div>
        </Panel>
        <Panel title="Security alerts" hint="Recent activity visible to your account."><AuditList rows={query.data?.alerts || []} /><TextLink href="/security">Open security monitoring</TextLink></Panel>
      </div>
      <Panel title="Recent analyses" className="space-top" action={<TextLink href="/history">View history</TextLink>}><AnalysisTable rows={query.data?.recent || []} /></Panel>
    </>}
  </>;
}

export function HistoryPage() {
  const query = useQuery({ queryKey: ["history"], queryFn: () => api<Analysis[]>("/analyses") });
  const [filter, setFilter] = useState("");
  return <><PageHead tag="WORKSPACE / ACTIVITY" title="Verification history" text="Find and reopen past forensic investigations." />
    <Panel title="Analysis records" action={<label className="search"><Search size={16} /><input aria-label="Search history" placeholder="Search documents" value={filter} onChange={event => setFilter(event.target.value)} /></label>}>
      {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : <AnalysisTable rows={query.data || []} filter={filter} />}
    </Panel></>;
}

export function VerifyPage({ reference }: { reference?: string }) {
  const router = useRouter();
  const [ref, setRef] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const record = useQuery({ queryKey: ["certificate", reference], enabled: Boolean(reference), queryFn: () => api<Integrity>("/verify/" + reference) });
  const check = useMutation({ mutationFn: () => { const form = new FormData(); if (file) form.append("file", file); return api<Integrity>("/verify/" + reference, form); } });
  function lookup(event: FormEvent) {
    event.preventDefault();
    const normalized = ref.trim().match(/(?:^|\/verify\/)([a-f0-9]{32})\/?$/i)?.[1]?.toLowerCase();
    if (!normalized) return toast.error("Enter a 32-character certificate reference or verification link.");
    router.push("/verify/" + normalized);
  }
  return <><PageHead tag="PUBLIC / ISSUANCE RECORD" title="Certificate verification" text="Check the issuer signature, revocation status, and optional file fingerprint." />
    {!reference ? <Panel title="Find a certificate record" className="narrow"><form className="form-stack" onSubmit={lookup}>
      <label>Verification reference or link<input value={ref} onChange={event => setRef(event.target.value)} placeholder="Paste a reference or QR link" required /></label>
      <div><RunButton busy={false}><QrCode size={17} /> Open verification record</RunButton></div></form></Panel> :
      record.isPending ? <Loading /> : record.error ? <ErrorBox error={record.error} /> :
      <div className="workspace-grid">
        <Panel title="Registered issuance" hint={reference}><IntegrityPanel info={check.data || record.data!} /></Panel>
        <Panel title="Check a copy" hint="The file is used to calculate its fingerprint. Its contents are discarded.">
          <form className="form-stack" onSubmit={event => { event.preventDefault(); check.mutate(); }}>
            <Drop file={file} onFile={next => { setFile(next); check.reset(); }} compact /><ErrorBox error={check.error} />
            <div><RunButton busy={check.isPending} disabled={!file}><Binary size={17} /> Check file integrity</RunButton></div>
          </form>
          {check.data && <div className="notice info"><Fingerprint size={17} />{check.data.record_status === "revoked" ? "This certificate has been revoked." :
            check.data.sha256_match && check.data.signature_valid ? "The copy matches and the signature verifies." :
            check.data.sha256_match ? "The copy matches but the signature could not be verified." : "The copy differs from the registered original."}</div>}
        </Panel>
      </div>}
  </>;
}

export function IssuePage() {
  const cache = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [active, setActive] = useState<Integrity | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const query = useQuery({ queryKey: ["issued"], queryFn: () => api<Integrity[]>("/certificates") });
  const submit = useMutation({ mutationFn: (body: FormData) => { if (file) body.append("file", file); return api<Integrity>("/certificates", body); },
    onSuccess: result => { setFile(null); setActive(result); void cache.invalidateQueries({ queryKey: ["issued"] }); toast.success("Certificate signed."); } });
  const revoke = useMutation({ mutationFn: (ref: string) => api<Integrity>("/certificates/" + ref + "/revoke", {}),
    onSuccess: result => { setActive(result); void cache.invalidateQueries({ queryKey: ["issued"] }); toast.success("Certificate revoked."); } });
  return <><PageHead tag="TRUST / ISSUANCE" title="Certificate issuance" text="Register a credential and sign its exact bytes with your issuer key." />
    {query.error ? <ErrorBox error={query.error} /> : <>
      <div className="workspace-grid">
        <Panel title="Register an original" hint="The original is encrypted at rest with AES-256-GCM.">
          <form className="form-stack" onSubmit={event => { event.preventDefault(); submit.mutate(new FormData(event.currentTarget)); }}><Drop file={file} onFile={setFile} />
            <details><summary>Private certificate metadata</summary><div className="form-stack space-top">
              <label>Student name<input name="student_name" maxLength={120} /></label><label>Certificate ID<input name="certificate_id" maxLength={100} /></label>
              <label>Course<input name="course" maxLength={150} /></label></div></details><ErrorBox error={submit.error} />
            <div><RunButton busy={submit.isPending} disabled={!file}><KeyRound size={16} /> Register and sign</RunButton></div></form>
        </Panel>
        <Panel title="Verification QR" hint="Share the reference to open the public issuance record.">
          {active?.certificate_ref ? <div className="qr-panel">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={"/api/verify/" + active.certificate_ref + "/qr.png"} alt="Certificate verification QR code" />
            <div><code>{active.certificate_ref}</code><Pill value={active.record_status} /><TextLink href={"/verify/" + active.certificate_ref}>Open public record</TextLink>
              {Object.entries(active.private_metadata || {}).map(([key, value]) => <small key={key}>{human(key)} · {value}</small>)}
              {active.record_status !== "revoked" && <Button variant={confirmRevoke ? "danger" : "ghost"} size="sm" disabled={revoke.isPending} onClick={() => {
                if (confirmRevoke) { revoke.mutate(active.certificate_ref!); setConfirmRevoke(false); } else setConfirmRevoke(true);
              }}>{confirmRevoke ? "Confirm revocation" : "Revoke certificate"}</Button>}</div><ErrorBox error={revoke.error} />
          </div> : <Empty icon={<QrCode size={23} />}>Select or issue a certificate to display its QR code.</Empty>}
        </Panel>
      </div>
      <Panel title="Issuance history" className="space-top">{query.isPending ? <Loading /> : !query.data?.length ? <Empty>No certificates have been issued.</Empty> :
        <div className="table-wrap"><table><thead><tr><th>Reference</th><th>Issuer</th><th>Status</th><th>Issued</th></tr></thead><tbody>
          {query.data.map(item => <tr key={item.certificate_ref}><td><button className="link-button mono" onClick={() => { setActive(item); setConfirmRevoke(false); }}>{item.certificate_ref}</button></td>
            <td>{item.issuer}</td><td><Pill value={item.record_status} /></td><td>{item.issued_at && dateText(item.issued_at)}</td></tr>)}
        </tbody></table></div>}</Panel>
    </>}
  </>;
}
