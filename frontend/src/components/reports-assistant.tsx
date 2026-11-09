"use client";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, MessageSquareText, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { api, dateText } from "@/lib/api";
import type { Analysis, Engine } from "@/lib/types";
import { Consent, Empty, ErrorBox, Loading, PageHead, Panel, Pill, RunButton, TextLink } from "@/components/ui";
import { Button } from "@/components/ui/button";

const useHistory = () => useQuery({ queryKey: ["history"], queryFn: () => api<Analysis[]>("/analyses") });

export function ReportsPage() {
  const query = useHistory();
  const [file, setFile] = useState<File | null>(null);
  const [signature, setSignature] = useState("");
  const check = useMutation({ mutationFn: () => { const form = new FormData(); if (file) form.append("file", file); form.append("signature", signature.trim());
    return api<{ signature_valid: boolean; public_key: string; sha256: string }>("/reports/verify", form); } });
  const rows = (query.data || []).filter(row => row.stage === "complete");
  return <><PageHead tag="WORKSPACE / REPORTS" title="Forensic reports" text="Download an evidence report and verify its detached Ed25519 signature." />
    <div className="workspace-grid">
      <Panel title="Signed exports" hint="Download the PDF and its matching signature file.">
        {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : !rows.length ? <Empty>No completed analyses yet.</Empty> :
          <div className="engines">{rows.map(item => <article key={item.id}><div><b>{item.filename}</b><p>{dateText(item.created_at)}</p></div><div className="row wrap">
            <a className="text-link" href={"/api/analyses/" + item.id + "/report.pdf"}>PDF</a><a className="text-link" href={"/api/analyses/" + item.id + "/report.pdf?signature=true"}>SIG</a></div></article>)}</div>}
      </Panel>
      <Panel title="Validate a report" hint="Check the PDF against this instance’s signing key.">
        <form className="form-stack" onSubmit={event => { event.preventDefault(); check.mutate(); }}>
          <label>Report PDF<input type="file" accept="application/pdf,.pdf" required onChange={event => { setFile(event.target.files?.[0] || null); check.reset(); }} /></label>
          <label>Detached signature<input type="file" accept=".sig,text/plain" onChange={async event => {
            const selected = event.target.files?.[0]; if (selected && selected.size <= 256) { setSignature((await selected.text()).trim()); check.reset(); }
          }} /></label>
          <label>Ed25519 signature (hex)<textarea rows={3} maxLength={128} value={signature} onChange={event => { setSignature(event.target.value); check.reset(); }} required /></label>
          <ErrorBox error={check.error} /><div><RunButton busy={check.isPending} disabled={!file || !/^[a-f0-9]{128}$/i.test(signature)}><ShieldCheck size={17} /> Verify signature</RunButton></div>
          {check.data && <div className="hash"><Pill value={check.data.signature_valid ? "valid" : "invalid"} /><small>Report SHA-256</small><code>{check.data.sha256}</code><small>Report public key</small><code>{check.data.public_key}</code></div>}
        </form>
      </Panel>
    </div></>;
}

export function AssistantPage() {
  const params = useSearchParams();
  const [selected, setSelected] = useState(params.get("job") || "");
  const [question, setQuestion] = useState("");
  const [consent, setConsent] = useState(false);
  const [messages, setMessages] = useState<{ job: string; question: string; answer: string; source: string; engine: Engine }[]>([]);
  const query = useHistory();
  const request = useMutation({
    mutationFn: (value: { job: string; question: string }) => api<{ answer: string; source: string; engine: Engine }>("/analyses/" + value.job + "/assistant", { question: value.question, external_ai: consent }),
    onSuccess: (result, value) => { setMessages(previous => [...previous, { ...value, ...result }]); setQuestion(""); },
  });
  const completed = (query.data || []).filter(row => row.stage === "complete");
  return <><PageHead tag="AI / FORENSIC ASSISTANT" title="VERIFEX Intelligence" text="Ask about the findings in a completed analysis you own." />
    <Panel title="Evidence conversation" className="assistant-panel" action={<Sparkles size={20} className="accent" />}>
      <form className="form-stack" onSubmit={event => { event.preventDefault(); request.mutate({ job: selected, question }); }}>
        <label>Analysis context<select required value={selected} onChange={event => setSelected(event.target.value)}>
          <option value="">Choose a completed analysis</option>{completed.map(item => <option key={item.id} value={item.id}>{item.filename} · {dateText(item.created_at)}</option>)}
        </select></label>
        <ErrorBox error={query.error} />{!query.isPending && !completed.length && <TextLink href="/analyzer">Run an analysis</TextLink>}
        <div className="conversation" aria-live="polite">{!messages.some(item => item.job === selected) ?
          <Empty icon={<MessageSquareText size={23} />}>Choose a document and ask about its evidence.</Empty> : messages.filter(item => item.job === selected).map((item, index) =>
          <article key={index}><p className="question">{item.question}</p><div className="answer"><small>{item.source === "Groq" ? "GROQ" : "LOCAL EVIDENCE"}</small><p>{item.answer}</p>
            {item.engine.detail && <p className="muted">{item.engine.detail}</p>}</div></article>)}</div>
        <div className="row wrap">{["Why was this flagged?", "Which fields changed?", "How does SHA-256 work?"].map(prompt =>
          <Button type="button" size="sm" variant="outline" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</Button>)}</div>
        <label>Question<textarea rows={2} value={question} maxLength={750} minLength={2} onChange={event => setQuestion(event.target.value)} placeholder="Ask about a finding…" required /></label>
        <Consent value={consent} setValue={setConsent} text="Allow Groq to receive this question and selected evidence. The analysis must also have external processing enabled." />
        <ErrorBox error={request.error} /><div><RunButton busy={request.isPending} disabled={!selected || !question.trim()}>Send question <ArrowRight size={16} /></RunButton></div>
      </form>
    </Panel></>;
}
