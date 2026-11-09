"use client";
import { AlertCircle, ArrowUpRight, Check, ChevronRight, FileScan, Loader2, ShieldCheck, UploadCloud } from "lucide-react";
import Link from "next/link";
import { type ReactNode } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { human, dateText } from "@/lib/api";
import type { Analysis, Audit } from "@/lib/types";
import { Button } from "@/components/ui/button";

export function Brand() {
  return <Link href="/" className="brand" aria-label="VERIFEX home"><span className="brand-icon"><ShieldCheck size={21} /></span><span>VERIFEX<span className="brand-dot">.</span></span></Link>;
}

export function PageHead({ tag, title, text, action }: { tag: string; title: string; text: string; action?: ReactNode }) {
  return <header className="page-head"><div><p className="eyebrow"><span /> {tag}</p><h1>{title}</h1><p>{text}</p></div>{action}</header>;
}

export function Panel({ title, hint, action, children, className = "" }: { title?: string; hint?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={"panel " + className}>{title && <header className="panel-header"><div><h2>{title}</h2>{hint && <p>{hint}</p>}</div>{action}</header>}{children}</section>;
}

export function Pill({ value }: { value?: string | null }) {
  const tone = value && ["verified", "registered", "contributed", "complete", "valid", "pass", "ready"].includes(value) ? "good" :
    value && ["failed", "modified", "revoked", "invalid_record", "access_denied", "invalid"].includes(value) ? "bad" :
    value && ["manual_review", "suspicious", "unverified", "unknown", "rate_limited", "unavailable"].includes(value) ? "warn" : "neutral";
  const label = value === "modified" ? "Integrity mismatch" : value === "unverified" ? "Unverified" : human(value);
  return <span className={"pill " + tone}><i />{label}</span>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return error ? <div className="notice error" role="alert"><AlertCircle size={17} />{error instanceof Error ? error.message : String(error)}</div> : null;
}

export function Empty({ children, icon = <FileScan size={23} /> }: { children: ReactNode; icon?: ReactNode }) {
  return <div className="empty"><span>{icon}</span><p>{children}</p></div>;
}

export function Loading() {
  return <div className="loading" role="status" aria-label="Loading"><div /><div /><div /></div>;
}

export function Drop({ file, onFile, compact = false }: { file: File | null; onFile: (file: File) => void; compact?: boolean }) {
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    maxFiles: 1, maxSize: 10 * 1024 * 1024,
    accept: { "application/pdf": [".pdf"], "image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"] },
    onDropAccepted: ([selected]) => onFile(selected),
    onDropRejected: () => toast.error("Choose one PDF, PNG, or JPEG up to 10 MiB."),
  });
  return <div {...getRootProps({ className: "dropzone " + (isDragActive ? "dragging " : "") + (compact ? "compact" : ""), "aria-label": "Choose a certificate file" })}>
    <input {...getInputProps()} /><span className="drop-icon">{file ? <Check size={22} /> : <UploadCloud size={24} />}</span>
    <div><strong>{file?.name || "Drop your document here"}</strong><p>{file ? (file.size / 1024).toFixed(1) + " KiB • Click to replace" : "Browse files  ·  PDF, PNG or JPEG up to 10 MiB"}</p></div>
  </div>;
}

export function Consent({ value, setValue, text = "Allow Gemini to see document pages and Groq to process extracted evidence for this run." }:
  { value: boolean; setValue: (next: boolean) => void; text?: string }) {
  return <label className="consent"><input type="checkbox" checked={value} onChange={event => setValue(event.target.checked)} /><span>{text}</span></label>;
}

export function RunButton({ busy, children, disabled = false }: { busy: boolean; children: ReactNode; disabled?: boolean }) {
  return <Button type="submit" disabled={busy || disabled}>{busy && <Loader2 size={17} className="spin" />}{children}</Button>;
}

export function AnalysisTable({ rows, filter }: { rows: Analysis[]; filter?: string }) {
  const visible = rows.filter(row => !filter || [row.filename, row.outcome, row.id].some(value => value?.toLowerCase().includes(filter.toLowerCase())));
  if (!visible.length) return <Empty>{filter ? "No matching analyses." : "Your analyses will appear here."}</Empty>;
  return <div className="table-wrap"><table><thead><tr><th>Document</th><th>Assessment</th><th>Created</th><th><span className="sr-only">Open</span></th></tr></thead>
    <tbody>{visible.map(row => <tr key={row.id}><td><Link href={"/analyzer?job=" + row.id} className="file-link"><FileScan size={16} />{row.filename}</Link></td>
      <td><Pill value={row.outcome || row.stage} /></td><td>{dateText(row.created_at)}</td><td><Link href={"/analyzer?job=" + row.id} aria-label={"Open " + row.filename}><ArrowUpRight size={16} /></Link></td></tr>)}</tbody>
  </table></div>;
}

export function AuditList({ rows }: { rows: Audit[] }) {
  if (!rows.length) return <Empty icon={<ShieldCheck size={23} />}>No events have been recorded for this view.</Empty>;
  return <div className="audit-list">{rows.map(row => <article key={row.id}><span className="audit-icon"><ShieldCheck size={16} /></span><div><strong>{human(row.kind)}</strong><p>{row.detail}</p></div><time>{dateText(row.created_at)}</time></article>)}</div>;
}

export function TextLink({ href, children }: { href: string; children: ReactNode }) {
  return <Link href={href} className="text-link">{children}<ChevronRight size={15} /></Link>;
}
