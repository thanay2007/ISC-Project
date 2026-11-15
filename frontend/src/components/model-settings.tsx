"use client";
import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CircleAlert } from "lucide-react";
import { useState } from "react";
import { api, dateText, human, percent } from "@/lib/api";
import type { Metrics, ModelPerformance } from "@/lib/types";
import { Empty, ErrorBox, Loading, PageHead, Panel, Pill, TextLink } from "@/components/ui";

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
  const groups = split === "test" ? evaluation?.groups : evaluation?.validation_groups;
  return <><PageHead tag="LAB / MODEL CARD" title="Model performance" text="Explore held-out results by dataset and representative model errors."
    action={<label><span className="sr-only">Evaluation split</span><select value={split} onChange={event => setSplit(event.target.value as "validation" | "test")}><option value="test">Held-out test</option><option value="validation">Validation</option></select></label>} />
    {query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> : !config ? <Empty>No trained model is loaded on this server.</Empty> : <>
      <Panel title={config.name} hint={config.version} action={<Pill value="complete" />}>
        <dl className="field-list"><div><dt>Training date</dt><dd>{dateText(config.trained_at)}</dd></div>
          <div><dt>Selected epoch / completed</dt><dd>{config.epoch} / {evaluation?.history?.length || "—"}</dd></div>
          <div><dt>Training device and input</dt><dd>{config.device.toUpperCase()} · {config.size} × {config.size}</dd></div>
          <div><dt>Training pool</dt><dd>{((config.dataset.counts.train_0 || 0) + (config.dataset.counts.train_1 || 0)).toLocaleString()} full-page images</dd></div></dl>
        <div className="notice warn"><CircleAlert size={18} /><span>{config.limitations}</span></div>
      </Panel>
      {metrics ? <div className="space-top"><MetricsPanel metrics={metrics} /></div> : <Panel className="space-top"><Empty>No evaluation was recorded for this checkpoint.</Empty></Panel>}
      <div className="workspace-grid dashboard-grid space-top">
        <Panel title="Training loss and validation quality" hint="Recorded over the completed training run.">
          <div className="chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={evaluation?.history || []}>
            <CartesianGrid vertical={false} stroke="#243149" strokeDasharray="3 6" /><XAxis dataKey="epoch" stroke="#96a9c3" /><YAxis yAxisId="loss" stroke="#96a9c3" width={36} />
            <YAxis yAxisId="quality" orientation="right" domain={[0, 1]} stroke="#96a9c3" width={36} />
            <Tooltip {...tooltip} /><Area yAxisId="loss" dataKey="training_loss" stroke="#00d9ff" fill="#00d9ff15" strokeWidth={2} isAnimationActive={false} />
            <Area yAxisId="quality" dataKey="validation_quality" stroke="#a678fc" fill="#a678fc16" strokeWidth={2} isAnimationActive={false} />
          </AreaChart></ResponsiveContainer></div>
        </Panel>
        <Panel title="Confusion matrix" hint={metrics ? String(metrics.count) + " images in this split" : "No recorded matrix"}>
          {metrics && <div className="matrix"><span /><small>Pred. genuine</small><small>Pred. altered</small>
            <small>Actual genuine</small><b>{metrics.confusion_matrix[0][0]}</b><b>{metrics.confusion_matrix[0][1]}</b>
            <small>Actual altered</small><b>{metrics.confusion_matrix[1][0]}</b><b>{metrics.confusion_matrix[1][1]}</b></div>}
        </Panel>
      </div>
      {groups && <Panel title="Results by dataset" hint="DocTamper contains altered pages only." className="space-top"><div className="table-wrap"><table><thead><tr><th>Dataset</th><th>Images</th><th>ROC-AUC</th><th>Recall</th><th>False positives</th><th>Pixel Dice</th></tr></thead><tbody>
        {Object.entries(groups).map(([name, row]) => <tr key={name}><td>{human(name)}</td><td>{row.count}</td><td>{percent(row.roc_auc)}</td><td>{percent(row.recall)}</td><td>{percent(row.false_positive_rate)}</td><td>{percent(row.dice)}</td></tr>)}
      </tbody></table></div></Panel>}
      {!!evaluation?.samples?.length && <Panel title="Sample predictions and failure cases" className="space-top" action={<TextLink href="/demo">Open demo lab</TextLink>}>
        <div className="table-wrap"><table><thead><tr><th>Sample</th><th>Condition</th><th>Actual</th><th>Prediction</th><th>Score</th></tr></thead><tbody>
          {evaluation.samples.map((row, index) => <tr key={row.id + index}><td>{row.id} · {row.template}</td><td>{human(row.condition)}</td><td>{row.label ? "Altered" : "Genuine"}</td>
            <td><Pill value={row.prediction === row.label ? "pass" : "failed"} /> {row.prediction ? "Altered" : "Genuine"}</td><td>{percent(row.score)}</td></tr>)}
        </tbody></table></div>
      </Panel>}
    </>}
  </>;
}
