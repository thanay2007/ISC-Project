"use client";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent, type PointerEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, ArrowRight, BrainCircuit, Check, ChevronLeft, ChevronRight, Download, FileDiff, FileScan, Fingerprint, ScanLine, SlidersHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { motion } from "motion/react";
import { api, dateText, human, percent } from "@/lib/api";
import type { Analysis, Box, Difference, Finding, Integrity, Preview, Result, Stage } from "@/lib/types";
import { Consent, Drop, Empty, ErrorBox, Loading, PageHead, Panel, Pill, RunButton, TextLink } from "@/components/ui";
import { Button } from "@/components/ui/button";

const Overlay = dynamic(() => import("./overlay"), { ssr: false });
const PdfPreview = dynamic(() => import("./pdf-preview"), { ssr: false, loading: () => <Loading /> });

function useAnalysis(id: string | null) {
  const cache = useQueryClient();
  const [live, setLive] = useState<{ id: string; items: Stage[] } | null>(null);
  const [preview, setPreview] = useState<{ id: string; value: Preview } | null>(null);
  const query = useQuery({ queryKey: ["analysis", id], enabled: Boolean(id), queryFn: () => api<Analysis>("/analyses/" + id),
    refetchInterval: query => query.state.data && !["complete", "failed"].includes(query.state.data.stage) ? 4500 : false });
  const terminal = ["complete", "failed"].includes(query.data?.stage || "");
  useEffect(() => {
    if (!id || terminal || query.isError) return;
    const stream = new EventSource("/api/analyses/" + id + "/events");
    stream.addEventListener("preview", (event: MessageEvent<string>) => setPreview({ id, value: JSON.parse(event.data) }));
    stream.onmessage = event => {
      const stage = JSON.parse(event.data) as Stage;
      setLive(previous => {
        const items = previous?.id === id ? previous.items : [];
        const sequence = Number(event.lastEventId);
        return { id, items: sequence > 0 ? [...items.slice(0, sequence - 1), stage] : [...items, stage] };
      });
      if (["complete", "failed"].includes(stage.stage)) {
        stream.close();
        void cache.invalidateQueries({ queryKey: ["analysis", id] });
        void cache.invalidateQueries({ queryKey: ["dashboard"] });
        void cache.invalidateQueries({ queryKey: ["history"] });
      }
    };
    stream.onerror = () => { if (stream.readyState === EventSource.CLOSED) void cache.invalidateQueries({ queryKey: ["analysis", id] }); };
    return () => stream.close();
  }, [id, terminal, query.isError, cache]);
  const history = query.data?.progress || [];
  const items = live?.id === id && live.items.length >= history.length ? live.items : history;
  return { ...query, progress: items, preview: preview?.id === id ? preview.value : query.data?.preview };
}

function LocalPreview({ file }: { file: File }) {
  const [url, setUrl] = useState("");
  useEffect(() => {
    if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) return;
    const objectUrl = URL.createObjectURL(file);
    setUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [file]);
  if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) return <PdfPreview key={file.name + file.size} file={file} />;
  // Uploaded content is displayed directly from an in-browser object URL.
  // eslint-disable-next-line @next/next/no-img-element
  return url && <div className="local-preview"><img src={url} alt="Local document preview" /></div>;
}

function NewAnalysis({ comparison = false }: { comparison?: boolean }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [ref, setRef] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.append("file", file); body.append("certificate_ref", ref.trim()); body.append("external_ai", String(consent));
    setBusy(true); setError(null);
    try {
      const job = await api<Analysis>("/analyses", body);
      router.push((comparison ? "/compare" : "/analyzer") + "?job=" + job.id);
    } catch (failure) { setError(failure); } finally { setBusy(false); }
  }
  return <div className="workspace-grid">
    <Panel title={comparison ? "Upload candidate" : "Upload document"} hint="Start with an academic certificate, marksheet, or credential." className="upload-panel">
      <form className="form-stack" onSubmit={submit}><Drop file={file} onFile={setFile} />{file && <LocalPreview file={file} />}
        <label>Certificate reference {comparison ? "" : "(optional)"}<input value={ref} onChange={event => setRef(event.target.value)} maxLength={32}
          placeholder="Reference from a VERIFEX verification link" required={comparison} /></label>
        <small>Original files and extracted comparisons are restricted to the issuing institution and administrators.</small>
        <Consent value={consent} setValue={setConsent} /><ErrorBox error={error} />
        <div className="row"><RunButton busy={busy} disabled={!file}><ScanLine size={17} /> Run {comparison ? "comparison" : "analysis"} <ArrowRight size={15} /></RunButton></div>
      </form>
    </Panel>
    <Panel title="Evidence pipeline" hint="The report keeps findings separate by engine.">
      <div className="pipeline">{[
        [FileScan, "OCR extraction", "Locate text and extract labeled academic fields."],
        [SlidersHorizontal, "OpenCV forensics", "Measure texture, compression, and render differences."],
        [BrainCircuit, "Custom AI & Gemini", "Review model regions and optional multimodal observations."],
        [Fingerprint, "Cryptographic verification", "Check exact bytes and the issuer’s signature."],
        [Activity, "Forensic report", "Read the evidence and export a signed PDF."],
      ].map(([Icon, label, detail], index) => {
        const Step = Icon as typeof FileScan;
        return <article key={String(label)}><span><Step size={18} /></span><div><b>{String(label)}</b><p>{String(detail)}</p></div><small>0{index + 1}</small></article>;
      })}</div>
    </Panel>
  </div>;
}

type Layer = "uploaded" | "processed" | "heatmap" | "mask" | "difference";
type Annotation = { box: Box; color: string; active?: boolean };

function DocumentImage({ src, overlay, alt, boxes = [], zoom, busy, split, original }: {
  src: string; overlay?: string; alt: string; boxes?: Annotation[]; zoom: number; busy?: boolean;
  split?: number; original?: string;
}) {
  const viewport = useRef<HTMLDivElement>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!stage.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(stage.current);
    return () => observer.disconnect();
  }, []);
  function down(event: PointerEvent<HTMLDivElement>) {
    if (zoom <= 1 || !viewport.current || event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, left: viewport.current.scrollLeft, top: viewport.current.scrollTop };
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    if (!drag.current || !viewport.current) return;
    viewport.current.scrollLeft = drag.current.left + drag.current.x - event.clientX;
    viewport.current.scrollTop = drag.current.top + drag.current.y - event.clientY;
  }
  return <div ref={viewport} className={"document-viewport" + (zoom > 1 ? " pannable" : "")} onPointerDown={down}
    onPointerMove={move} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
    {error && <div className="notice error">The document preview could not be loaded.</div>}
    <div className="document-image" ref={stage} style={{ width: zoom * 100 + "%" }}>
      {/* All URLs come from authenticated raster endpoints. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt={alt} draggable={false} onLoad={() => setError(false)} onError={() => setError(true)} />
      {original && typeof split === "number" &&
        // eslint-disable-next-line @next/next/no-img-element
        <img className="image-layer" src={original} alt="" style={{ clipPath: "inset(0 " + (100 - split) + "% 0 0)" }} />}
      {overlay &&
        // eslint-disable-next-line @next/next/no-img-element
        <img className="image-layer" src={overlay} alt="" />}
      {boxes.length > 0 && size.width > 0 && <Overlay width={size.width} height={size.height} boxes={boxes} />}
      {busy && <span className="scan-beam" />}
    </div>
  </div>;
}

function Viewer({ id, result, progress, failure, stage, comparison, active, preview }: {
  id: string; result?: Result | null; progress: Stage[]; failure: boolean; stage?: string; comparison: boolean; active: Finding | null; preview?: Preview | null;
}) {
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [mode, setMode] = useState<Layer>("uploaded");
  const [showOcr, setShowOcr] = useState(false);
  const [showRegions, setShowRegions] = useState(true);
  const [split, setSplit] = useState(50);
  const [view, setView] = useState<"side" | "slider">("side");
  useEffect(() => { if (active) setPage(active.page); }, [active]);
  const effectivePage = page;
  const source = "/api/analyses/" + id + "/pages/" + effectivePage;
  const ready = Boolean(result);
  const analyzing = !ready && !failure;
  const hasOriginal = !!result && effectivePage <= result.original_pages;
  const hasUploaded = !result || effectivePage <= result.page_count;
  const total = result ? Math.max(result.page_count, comparison ? result.original_pages : 0) : preview?.page_count ?? 1;
  const regions = result ? [...result.opencv, ...(result.gemini?.observations || []),
    ...(result.custom_model.regions || []), ...result.comparison.flatMap(item => item.regions),
    ...result.differences.flatMap(item => item.page && item.box ? [{ page: item.page, box: item.box, finding: item.label, kind: "field_difference" }] : []),
  ] : [];
  const annotations: Annotation[] = [
    ...((analyzing ? preview?.boxes : showOcr ? result?.ocr : []) || []).filter(line => line.page === effectivePage).map(line => ({ box: line.box, color: "#19c9df" })),
    ...(showRegions ? regions.filter(item => item.page === effectivePage && item.box)
      .map(item => ({ box: item.box!, color: item.kind === "custom_model" ? "#b58af4" : "#ff9a61" })) : []),
    ...(active?.box && active.page === effectivePage ? [{ box: active.box, color: "#ffad5e", active: true }] : []),
  ];
  const overlay = ["heatmap", "mask", "difference"].includes(mode) && (mode !== "difference" || hasOriginal) ? source + "?layer=" + mode : undefined;
  const photo = <DocumentImage src={source + (mode === "processed" ? "?layer=processed" : "")} overlay={overlay}
    alt={"Uploaded document page " + effectivePage} boxes={annotations} zoom={zoom} busy={analyzing} />;
  return <Panel title={comparison ? "Document comparison" : "Document viewer"} hint="Use overlays to inspect where each engine found evidence." className="viewer-panel">
    <div className="viewer-toolbar">
      <div className="row"><Button size="icon" variant="outline" disabled={effectivePage <= 1} onClick={() => setPage(effectivePage - 1)} aria-label="Previous page"><ChevronLeft size={17} /></Button>
        <span className="mono">Page {effectivePage} / {total}</span>
        <Button size="icon" variant="outline" disabled={effectivePage >= total} onClick={() => setPage(effectivePage + 1)} aria-label="Next page"><ChevronRight size={17} /></Button></div>
      <div className="row"><Button variant="ghost" size="icon" onClick={() => setZoom(Math.max(1, zoom - .25))} disabled={zoom <= 1} aria-label="Zoom out"><ZoomOut size={17} /></Button>
        <span className="mono">{Math.round(zoom * 100)}%</span>
        <Button variant="ghost" size="icon" onClick={() => setZoom(Math.min(2.5, zoom + .25))} disabled={zoom >= 2.5} aria-label="Zoom in"><ZoomIn size={17} /></Button></div>
    </div>
    {comparison && hasOriginal && hasUploaded && <div className="segmented"><button onClick={() => setView("side")} aria-pressed={view === "side"}>Side by side</button>
      <button onClick={() => setView("slider")} aria-pressed={view === "slider"}>Before / after</button></div>}
    {comparison && view === "slider" && hasOriginal && hasUploaded ? <>
      <DocumentImage src={source} alt={"Before and after page " + effectivePage} original={source + "?layer=original"} split={split} zoom={zoom} boxes={annotations} overlay={overlay} />
      <label className="slider">Original<input type="range" min="0" max="100" value={split} onChange={event => setSplit(Number(event.target.value))} aria-label="Original reveal percentage" /> Uploaded</label>
    </> : comparison && (hasOriginal || !hasUploaded) ? <div className="compare-images">
      <div><p className="eyebrow">AUTHORIZED ORIGINAL</p>{hasOriginal ? <DocumentImage src={source + "?layer=original"} alt={"Authorized original page " + effectivePage} zoom={zoom} /> : <Empty>No original page.</Empty>}</div>
      <div><p className="eyebrow">UPLOADED FILE</p>{hasUploaded ? photo : <Empty>No corresponding uploaded page.</Empty>}</div>
    </div> : photo}
    {ready && <div className="viewer-toolbar viewer-options"><label><span className="sr-only">Image layer</span><select value={mode} onChange={event => setMode(event.target.value as Layer)}>
      <option value="uploaded">Original document</option><option value="processed">Processed grayscale</option>
      {result?.custom_model.status === "complete" && <><option value="heatmap">AI heatmap</option><option value="mask">Forgery mask</option></>}
      {hasOriginal && hasUploaded && <option value="difference">Image difference</option>}
    </select></label><label className="inline-check"><input type="checkbox" checked={showOcr} onChange={event => setShowOcr(event.target.checked)} /> OCR boxes</label>
      <label className="inline-check"><input type="checkbox" checked={showRegions} onChange={event => setShowRegions(event.target.checked)} /> Review regions</label></div>}
    {analyzing && <div className="live-stages" aria-live="polite"><div className="live-title"><Activity size={16} /><strong>{progress.at(-1)?.label || human(stage || "queued")}</strong></div>
      <ol>{progress.map((item, index) => <li key={item.stage + index}><Check size={13} />{item.label}</li>)}</ol></div>}
    {failure && <ErrorBox error="The analysis failed. Start another run or check the API log for details." />}
  </Panel>;
}

export function IntegrityPanel({ info }: { info: Integrity }) {
  return <div className="integrity">
    <div className="integrity-grid">
      <div><small>Issuance record</small><Pill value={info.record_status} /></div>
      <div><small>Registered signature</small><Pill value={info.record_signature_valid == null ? "unavailable" : info.record_signature_valid ? "valid" : "invalid"} /></div>
      {info.uploaded_sha256 && <><div><small>SHA-256 match</small><Pill value={info.sha256_match == null ? "unavailable" : info.sha256_match ? "valid" : "invalid"} /></div>
        <div><small>Signature for upload</small><Pill value={info.signature_valid == null ? "unavailable" : info.signature_valid ? "valid" : "invalid"} /></div></>}
    </div>
    {info.issuer && <p><b>{info.issuer}</b>{info.issued_at ? " · Issued " + dateText(info.issued_at) : ""}</p>}
    {info.revoked_at && <p>Revoked {dateText(info.revoked_at)}</p>}
    {info.uploaded_sha256 && <div className="hash"><small>Uploaded SHA-256</small><code>{info.uploaded_sha256}</code></div>}
    {info.registered_sha256 && <div className="hash"><small>Registered SHA-256</small><code>{info.registered_sha256}</code></div>}
    {info.certificate_ref && <TextLink href={"/verify/" + info.certificate_ref}>Open verification record</TextLink>}
  </div>;
}

function Differences({ rows, onFinding, provider = false }: { rows: Difference[]; onFinding: (finding: Finding) => void; provider?: boolean }) {
  if (!rows.length) return <p className="muted">No differences were recorded between available extracted fields.</p>;
  return <div className="table-wrap"><table><thead><tr><th>Field</th><th>{provider ? "Gemini" : "Original"}</th><th>Uploaded OCR</th></tr></thead>
    <tbody>{rows.map(item => <tr key={item.field}><td>{item.page && item.box ?
      <button className="link-button" onClick={() => onFinding({ page: item.page!, box: item.box!, finding: item.label })}>{item.label}</button> : item.label}</td>
      <td>{item.original || "Unreadable"}</td><td className="difference-value">{item.uploaded || "Unreadable"}</td></tr>)}</tbody></table></div>;
}

function Evidence({ result, onFinding }: { result: Result; onFinding: (finding: Finding) => void }) {
  const [tab, setTab] = useState("overview");
  const custom = result.custom_model;
  return <Panel title="Forensic findings" action={<Pill value={result.outcome} />} className="evidence-panel">
    <div className="segmented evidence-tabs">{["overview", "text", "visual", "engines"].map(item =>
      <button key={item} onClick={() => setTab(item)} aria-pressed={tab === item}>{item}</button>)}</div>
    {tab === "overview" && <>
      {result.demo_case && <div className="notice warn"><BrainCircuit size={18} /><div><strong>Held-out model error · {result.demo_case.id}</strong>
        <p>The dataset labels this sample {result.demo_case.label ? "altered" : "genuine"}. The visual score and the issuance check are independent.</p></div></div>}
      <div className="notice info"><Fingerprint size={18} /><div><strong>{result.explanation.summary}</strong><p>Explanation source · {result.explanation.source}</p></div></div>
      <div className="evidence-section"><h3>Cryptographic integrity</h3><IntegrityPanel info={result.crypto} /></div>
      <div className="evidence-section"><h3>Forensic explanation</h3><p>{result.explanation.detailed}</p>
        <p className="muted">{result.explanation.recommendation}</p>
        <details><summary>Presentation summary</summary><p>{result.explanation.presentation}</p></details></div>
      <div className="evidence-section"><h3>Evidence limitations</h3><ul>{[...result.limitations, ...result.warnings].map(item => <li key={item}>{item}</li>)}</ul></div>
    </>}
    {tab === "text" && <>
      <div className="evidence-section"><h3>Extracted fields</h3>{Object.keys(result.fields).length ? <dl className="field-list">
        {Object.entries(result.fields).map(([key, item]) => <div key={key}><dt>{human(key)}</dt><dd>
          <button className="link-button" onClick={() => onFinding({ ...item, finding: key })}>{item.value}</button></dd></div>)}</dl> : <Empty>No labeled fields were extracted.</Empty>}</div>
      {result.original_pages > 0 && <div className="evidence-section"><h3>Authorized original vs. uploaded OCR</h3><Differences rows={result.differences} onFinding={onFinding} /></div>}
      {result.gemini && <div className="evidence-section"><h3>Gemini extraction cross-check</h3><Differences rows={result.gemini_discrepancies} onFinding={onFinding} provider /></div>}
      <div className="evidence-section"><details><summary>Raw uploaded OCR · {result.ocr.length} lines</summary>
        <div className="ocr-list">{result.ocr.map((line, index) => <button className="ocr-line" key={index} onClick={() => onFinding({ ...line, finding: line.text })}>
          <span>{line.text}</span><small>p{line.page} · {percent(line.confidence, 0)}</small></button>)}</div></details>
        {result.original_pages > 0 && <details><summary>Raw original OCR · {result.original_ocr.length} lines</summary>
          <pre className="ocr-text">{result.original_ocr.map(line => line.text).join("\n")}</pre></details>}</div>
    </>}
    {tab === "visual" && <>
      <div className="evidence-section"><h3>Custom AI Forgery Detection Engine</h3>
        {custom.status === "complete" ? <><div className="model-signal"><BrainCircuit size={22} /><div><strong>{custom.name}</strong><code>{custom.version}</code></div><b>{percent(custom.risk_score)}</b></div>
          <p>{human(custom.predicted_class)} · {custom.inference_ms} ms · {custom.regions?.length || 0} marked regions</p><p className="muted">{custom.limitations}</p></> : <p className="muted">{custom.detail}</p>}
        <FindingList items={custom.regions || []} onFinding={onFinding} /></div>
      <div className="evidence-section"><h3>OpenCV and anomaly detection</h3>
        <p className="muted">Peak patch anomaly scores by page · {result.anomaly.map(score => score?.toFixed(3) ?? "—").join(" / ")}</p>
        <FindingList items={result.opencv} onFinding={onFinding} /></div>
      <div className="evidence-section"><h3>Gemini visual observations</h3>{result.gemini ? <><FindingList items={result.gemini.observations} onFinding={onFinding} />
        {result.gemini.comparison_summary && <p>{result.gemini.comparison_summary}</p>}</> : <p className="muted">{result.engines.Gemini?.detail || human(result.engines.Gemini?.status)}</p>}</div>
    </>}
    {tab === "engines" && <div className="engines">{Object.entries(result.engines).map(([name, engine]) =>
      <article key={name}><div><b>{name}</b><p>{engine.model || engine.detail}</p>{engine.model && engine.detail && <p>{engine.detail}</p>}
        {typeof engine.input_tokens === "number" && <small>{engine.input_tokens} input · {engine.output_tokens ?? 0} output tokens</small>}</div>
        <Pill value={engine.status} /></article>)}</div>}
  </Panel>;
}

function FindingList({ items, onFinding }: { items: Finding[]; onFinding: (finding: Finding) => void }) {
  return items.length ? <ul className="finding-list">{items.map((item, index) =>
    <li key={index}>{item.box ? <button className="link-button" onClick={() => onFinding(item)}>Page {item.page} <ChevronRight size={12} /></button> : <span>Page {item.page}</span>}
      <p>{item.finding}</p>{item.severity && <small>{item.severity} severity</small>}</li>)}</ul> : <p className="muted">No review regions reported.</p>;
}

export function AnalyzerPage({ comparison = false }: { comparison?: boolean }) {
  const id = useSearchParams().get("job");
  const query = useAnalysis(id);
  const [selected, setSelected] = useState<{ id: string | null; finding: Finding } | null>(null);
  const result = query.data?.result;
  const route = comparison ? "/compare" : "/analyzer";
  const recent = useQuery({ queryKey: ["history"], enabled: comparison && !id, queryFn: () => api<Analysis[]>("/analyses") });
  const selectFinding = (finding: Finding) => setSelected({ id, finding });
  return <>
    <PageHead tag={comparison ? "EVIDENCE / COMPARISON" : "EVIDENCE / ANALYSIS"} title={comparison ? "Document comparison" : "Document analyzer"}
      text={id ? query.data?.filename || "Inspect the document and its forensic report." : comparison ? "Compare a candidate against a registered issuance record." : "Inspect a credential with independent forensic and cryptographic checks."}
      action={id && <Button variant="outline" asChild><Link href={route}><ArrowLeft size={16} /> New {comparison ? "comparison" : "analysis"}</Link></Button>} />
    {!id ? <><NewAnalysis comparison={comparison} />
      {comparison && <Panel title="Open a previous analysis" className="space-top"><div className="row wrap">
        {(recent.data || []).filter(item => item.stage === "complete").slice(0, 6).map(item => <Button asChild key={item.id} variant="outline" size="sm">
          <Link href={"/compare?job=" + item.id}><FileDiff size={16} />{item.filename}</Link></Button>)}
        {!recent.data?.length && <p className="muted">Completed analyses will appear here.</p>}</div></Panel>}</> :
      query.isPending ? <Loading /> : query.error ? <ErrorBox error={query.error} /> :
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className={comparison ? "comparison-workspace" : "workspace-grid analysis-grid"}>
        <div>
          <Viewer key={id} id={id} result={result} progress={query.progress} failure={query.data?.stage === "failed"}
            stage={query.data?.stage} comparison={comparison} active={selected?.id === id ? selected.finding : null} preview={query.preview} />
          {result && <div className="row wrap action-strip">
            <Button variant="outline" asChild><Link href={(comparison ? "/analyzer" : "/compare") + "?job=" + id}><FileDiff size={16} />{comparison ? "Open analysis" : "Compare"}</Link></Button>
            <Button variant="outline" asChild><a href={"/api/analyses/" + id + "/report.pdf"}><Download size={16} /> Signed report</a></Button>
            <Button variant="ghost" asChild><a href={"/api/analyses/" + id + "/report.pdf?signature=true"}>Signature file</a></Button>
            <TextLink href={"/assistant?job=" + id}>Ask Intelligence</TextLink>
          </div>}
          {comparison && result && <Panel title="Field and image differences" className="space-top">
            {result.original_pages ? <><Differences rows={result.differences} onFinding={selectFinding} />
              {result.comparison.map(item => <p className="muted" key={item.page}>Page {item.page} · {percent(item.changed_fraction, 2)} changed rendered pixels</p>)}</> :
              <Empty>An authorized original is required to compare document contents.</Empty>}
          </Panel>}
        </div>
        {result ? <Evidence result={result} onFinding={selectFinding} /> : <Panel title="Forensic findings" hint="The report will appear once all enabled stages finish.">
          {query.data?.stage === "failed" ? <Empty>No report was produced.</Empty> : <Loading />}</Panel>}
      </motion.div>}
  </>;
}
