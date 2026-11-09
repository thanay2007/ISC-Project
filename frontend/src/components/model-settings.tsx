"use client";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowRight, CircleAlert } from "lucide-react";
import { useState } from "react";
import { api, dateText, human, percent } from "@/lib/api";
import type { Metrics, ModelPerformance } from "@/lib/types";
import { Empty, ErrorBox, Loading, PageHead, Panel, Pill, TextLink } from "@/components/ui";
import { useUser } from "@/components/shell";

const tooltip = { contentStyle: { background: "#111b2d", border: "1px solid #243751", borderRadius: 8, color: "#f8fafc" } };
function MetricsPanel({ metrics }: { metrics: Metrics }) {
  return <div className="stats-grid model-stats">{[
    ["Accuracy", metrics.accuracy], ["Precision", metrics.precision], ["Recall", metrics.recall], ["F1 score", metrics.f1],
    ["False-positive rate", metrics.false_positive_rate], ["ROC AUC", metrics.roc_auc], ["Pixel IoU", metrics.iou], ["Pixel Dice", metrics.dice],
  ].filter(([, value]) => value != null).map(([label, value]) => <article className="stat" key={String(label)}>
    <div><span>{label}</span><strong>{percent(value as number)}</strong></div><i><Activity size={18} /></i></article>)}</div>;
}

export function ModelPage() {
  const [split, setSplit] = useState<"validation" | "test">("test");
  const query = useQuery({ queryKey: ["model-performance"], queryFn: () => api<ModelPerformance>("/ai/model-performance") });
  const config = query.data?.deployed;
  const evaluation = query.data?.evaluation;
  const metrics = evaluation?.[split];
  return <><PageHead tag="LAB / MODEL CARD" title="Model performance" text="Explore measured results, held-out templates, and representative model errors."
    action={<label><span className="sr-only">Evaluation split</span><select value={split} onChange={event => setSplit(event.target.value as "validation" | "test")}><option value="test">Held-out test</option><option value="validation">Validation</option></select></label>} />
    {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : !config ? <Empty>No trained model is loaded on this server.</Empty> : <>
      <Panel title={config.name} hint={config.version} action={<Pill value="complete" />}>
        <dl className="field-list"><div><dt>Training date</dt><dd>{dateText(config.trained_at)}</dd></div>
          <div><dt>Selected epoch / completed</dt><dd>{config.epoch} / {evaluation?.history?.length || "—"}</dd></div>
          <div><dt>Training device and input</dt><dd>{config.device.toUpperCase()} · {config.size} × {config.size}</dd></div>
          <div><dt>Dataset</dt><dd>{Object.entries(config.dataset.counts).filter(([key]) => /_[01]$/.test(key)).reduce((sum, [, n]) => sum + n, 0)} synthetic images</dd></div></dl>
        <div className="notice warn"><CircleAlert size={18} /><span>{config.limitations}</span></div>
      </Panel>
      {metrics ? <div className="space-top"><MetricsPanel metrics={metrics} /></div> : <Panel className="space-top"><Empty>No evaluation was recorded for this checkpoint.</Empty></Panel>}
      <div className="workspace-grid dashboard-grid space-top">
        <Panel title="Training and validation loss" hint="Recorded over the completed training run.">
          <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={evaluation?.history || []}>
            <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 6" /><XAxis dataKey="epoch" stroke="#96a9c3" /><YAxis stroke="#96a9c3" width={36} />
            <Tooltip {...tooltip} /><Area dataKey="training_loss" stroke="#00d9ff" fill="#00d9ff15" strokeWidth={2} isAnimationActive={false} />
            <Area dataKey="validation_loss" stroke="#a678fc" fill="#a678fc16" strokeWidth={2} isAnimationActive={false} />
          </AreaChart></ResponsiveContainer></div>
        </Panel>
        <Panel title="Confusion matrix" hint={metrics ? String(metrics.count) + " images in this split" : "No recorded matrix"}>
          {metrics && <div className="matrix"><span /><small>Pred. genuine</small><small>Pred. altered</small>
            <small>Actual genuine</small><b>{metrics.confusion_matrix[0][0]}</b><b>{metrics.confusion_matrix[0][1]}</b>
            <small>Actual altered</small><b>{metrics.confusion_matrix[1][0]}</b><b>{metrics.confusion_matrix[1][1]}</b></div>}
        </Panel>
      </div>
      {evaluation?.comparisons && <Panel title="Model comparison" hint="Held-out synthetic test F1 and precision." className="space-top"><div className="chart"><ResponsiveContainer width="100%" height="100%">
        <BarChart data={Object.entries(evaluation.comparisons).map(([name, row]) => ({ name, F1: row.f1, Precision: row.precision }))}><CartesianGrid vertical={false} stroke="#243149" />
          <XAxis dataKey="name" stroke="#96a9c3" fontSize={11} /><YAxis domain={[0, 1]} stroke="#96a9c3" /><Tooltip {...tooltip} />
          <Bar dataKey="F1" fill="#00b8d4" isAnimationActive={false} /><Bar dataKey="Precision" fill="#8b5cf6" isAnimationActive={false} />
        </BarChart></ResponsiveContainer></div></Panel>}
      {evaluation?.groups && <Panel title="Held-out conditions" className="space-top"><div className="table-wrap"><table><thead><tr><th>Condition</th><th>Images</th><th>F1</th><th>False positives</th><th>Pixel Dice</th></tr></thead><tbody>
        {Object.entries(evaluation.groups).map(([name, row]) => <tr key={name}><td>{human(name)}</td><td>{row.count}</td><td>{percent(row.f1)}</td><td>{percent(row.false_positive_rate)}</td><td>{percent(row.dice)}</td></tr>)}
      </tbody></table></div></Panel>}
      <Panel title="External benchmark" hint={evaluation?.public_benchmark ? "Kriyam TamperFlow · C0 · " + evaluation.public_benchmark.count + " images" : "Separate evaluation on public documents."} className="space-top">
        {evaluation?.public_benchmark ? <><MetricsPanel metrics={evaluation.public_benchmark} />
          <p className="muted space-top">Class-balanced exploratory sample. It does not represent the full dataset.</p></> : <p className="muted">No external benchmark run is recorded for this checkpoint.</p>}</Panel>
      {!!evaluation?.samples?.length && <Panel title="Sample predictions and failure cases" className="space-top" action={<TextLink href="/demo">Open demo lab</TextLink>}>
        <div className="table-wrap"><table><thead><tr><th>Sample</th><th>Condition</th><th>Actual</th><th>Prediction</th><th>Score</th></tr></thead><tbody>
          {evaluation.samples.map((row, index) => <tr key={row.id + index}><td>{row.id} · {row.template}</td><td>{human(row.condition)}</td><td>{row.label ? "Altered" : "Genuine"}</td>
            <td><Pill value={row.prediction === row.label ? "pass" : "failed"} /> {row.prediction ? "Altered" : "Genuine"}</td><td>{percent(row.score)}</td></tr>)}
        </tbody></table></div>
      </Panel>}
    </>}
  </>;
}

export function SettingsPage() {
  const user = useUser();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<{ status: string; demo_enabled: boolean; model_loaded: boolean; paddle_status: string }>("/health") });
  return <><PageHead tag="WORKSPACE / SETTINGS" title="Workspace settings" text="Review your account and the available analysis services." />
    <div className="workspace-grid">
      <Panel title="Account"><dl className="field-list"><div><dt>Display name</dt><dd>{user.data?.name}</dd></div><div><dt>Email</dt><dd>{user.data?.email}</dd></div>
        <div><dt>Role</dt><dd><Pill value={user.data?.role} /></dd></div></dl></Panel>
      <Panel title="Processing preferences"><p className="muted">New runs use local analysis by default. Authorize external processing from the upload form.</p>
        <dl className="field-list space-top"><div><dt>Custom model</dt><dd><Pill value={health.data?.model_loaded ? "complete" : "unavailable"} /></dd></div>
          <div><dt>PaddleOCR</dt><dd><Pill value={health.data?.paddle_status} /></dd></div>
          <div><dt>Demo lab</dt><dd>{health.data?.demo_enabled ? "Enabled" : "Disabled"}</dd></div></dl><a href="/api/docs" className="text-link">Open API documentation <ArrowRight size={15} /></a></Panel>
    </div></>;
}
