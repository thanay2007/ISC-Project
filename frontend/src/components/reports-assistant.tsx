"use client";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, MessageSquareText, Sparkles } from "lucide-react";
import { useState } from "react";
import { api, dateText } from "@/lib/api";
import type { Analysis, Engine } from "@/lib/types";
import { Empty, ErrorBox, Loading, PageHead, Panel, RunButton, TextLink } from "@/components/ui";
import { Button } from "@/components/ui/button";

const useHistory = () => useQuery({ queryKey: ["history"], queryFn: () => api<Analysis[]>("/analyses") });

export function ReportsPage() {
  const query = useHistory();
  const rows = (query.data || []).filter(row => row.stage === "complete");
  return <><PageHead tag="WORKSPACE / REPORTS" title="Forensic reports" text="Download PDF reports for your completed analyses." />
      <Panel title="Available reports">
        {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : !rows.length ? <Empty>No completed analyses yet.</Empty> :
          <div className="engines">{rows.map(item => <article key={item.id}><div><b>{item.filename}</b><p>{dateText(item.created_at)}</p></div><div className="row wrap">
            <a className="text-link" href={"/api/analyses/" + item.id + "/report.pdf"}>Download PDF</a></div></article>)}</div>}
      </Panel>
    </>;
}

export function AssistantPage() {
  const params = useSearchParams();
  const [selected, setSelected] = useState(params.get("job") || "");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<{ job: string; question: string; answer: string; source: string; engine: Engine }[]>([]);
  const query = useHistory();
  const request = useMutation({
    mutationFn: (value: { job: string; question: string }) => api<{ answer: string; source: string; engine: Engine }>("/analyses/" + value.job + "/assistant", { question: value.question }),
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
        <div className="row wrap">{["How was the verdict reached?", "Which fields were extracted?", "How does SHA-256 work?"].map(prompt =>
          <Button type="button" size="sm" variant="outline" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</Button>)}</div>
        <label>Question<textarea rows={2} value={question} maxLength={750} minLength={2} onChange={event => setQuestion(event.target.value)} placeholder="Ask about a finding…" required /></label>
        <small>Groq uses your question and the selected report’s evidence to answer.</small>
        <ErrorBox error={request.error} /><div><RunButton busy={request.isPending} disabled={!selected || !question.trim()}>Send question <ArrowRight size={16} /></RunButton></div>
      </form>
    </Panel></>;
}
