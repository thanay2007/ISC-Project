"use client";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, RenderTask } from "pdfjs-dist";
import { Loading } from "@/components/ui";
import { Button } from "@/components/ui/button";

export default function PdfPreview({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let task: PDFDocumentLoadingTask | undefined;
    let rendering: RenderTask | undefined;
    setLoading(true); setError("");
    async function render() {
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
      const bytes = await file.arrayBuffer();
      if (!active) return;
      task = pdfjs.getDocument({ data: bytes, disableFontFace: true });
      const pdf = await task.promise;
      if (!active) return;
      setTotal(pdf.numPages);
      const current = await pdf.getPage(Math.min(page, pdf.numPages));
      if (!active || !canvas.current) return;
      const unscaled = current.getViewport({ scale: 1 });
      const viewport = current.getViewport({ scale: 900 / unscaled.width });
      canvas.current.width = viewport.width; canvas.current.height = viewport.height;
      rendering = current.render({ canvas: canvas.current, viewport });
      await rendering.promise;
      if (active) setLoading(false);
    }
    void render().catch(() => { if (active) { setError("Local PDF preview is unavailable. Submit to render it on the server."); setLoading(false); } });
    return () => { active = false; rendering?.cancel(); void task?.destroy().catch(() => {}); };
  }, [file, page]);
  return <div className="local-preview">
    {error && <p className="muted">{error}</p>}{loading && <Loading />}
    <canvas ref={canvas} aria-label="Local PDF preview" style={{ display: loading || error ? "none" : "block" }} />
    {total > 1 && <div className="row"><Button type="button" variant="outline" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button><span>{page} / {total}</span><Button type="button" variant="outline" size="sm" disabled={page >= total} onClick={() => setPage(page + 1)}>Next</Button></div>}
  </div>;
}
