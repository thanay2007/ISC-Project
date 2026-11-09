export type Box = [number, number, number, number];
export type User = { id: string; name: string; email: string; role: "admin" | "institution" | "verifier" };
export type Stage = { stage: string; label: string; at: string };
export type Preview = { page_count: number; boxes: { page: number; box: Box }[] };
export type Analysis = { id: string; filename: string; mime: string; stage: string; outcome: string | null; created_at: string; demo: boolean; progress: Stage[]; result: Result | null; preview?: Preview | null };
export type Finding = { page: number; box?: Box; kind?: string; finding: string; severity?: string; region?: string };
export type Line = { page: number; box: Box; text: string; confidence: number | null };
export type Field = { page: number; box: Box; value: string };
export type Difference = { field: string; label: string; original: string | null; uploaded: string | null; kind: string; page: number | null; box: Box | null };
export type Integrity = {
  record_status: string; signature_valid: boolean | null; record_signature_valid: boolean | null;
  sha256_match: boolean | null; certificate_ref: string | null; issuer?: string; issued_at?: string;
  revoked_at?: string | null; issuer_public_key?: string; record_signature?: string; uploaded_sha256: string | null; registered_sha256?: string;
  private_metadata?: Record<string, string>;
};
export type Engine = { status: string; detail?: string; model?: string; input_tokens?: number; output_tokens?: number };
export type CustomModel = {
  status: string; detail?: string; name?: string; version?: string; predicted_class?: string;
  risk_score?: number; threshold?: number; regions?: Finding[]; page_scores?: number[]; inference_ms?: number; limitations?: string;
};
export type Result = {
  outcome: string; crypto: Integrity; fields: Record<string, Field>; ocr: Line[]; original_ocr: Line[];
  differences: Difference[]; comparison: { page: number; regions: Finding[]; changed_fraction: number }[];
  page_count: number; original_pages: number; opencv: Finding[]; anomaly: (number | null)[]; custom_model: CustomModel;
  gemini: { document_type: string; extracted_fields: Record<string, string | null>; observations: Finding[]; comparison_summary: string | null; manual_review_recommended: boolean } | null;
  gemini_discrepancies: Difference[]; limitations: string[]; warnings: string[]; engines: Record<string, Engine>;
  explanation: { summary: string; detailed: string; presentation: string; recommendation: string; source: string };
  demo_case?: { id: string; label: number; prediction: number; score: number };
};
export type Audit = { id: string; actor: string | null; kind: string; detail: string; subject: string | null; created_at: string };
export type Dashboard = { counts: Record<string, number>; trends: { day: string; analyzed: number; verified: number }[]; recent: Analysis[]; alerts: Audit[] };
export type Metrics = { accuracy: number; precision: number; recall: number; f1: number; roc_auc: number | null; false_positive_rate: number; confusion_matrix: number[][]; iou?: number; dice?: number; pixel_precision?: number; pixel_recall?: number; count: number; median_ms?: number };
export type ModelPerformance = {
  deployed: { name: string; version: string; trained_at: string; epoch: number; device: string; size: number; classification_threshold: number; mask_threshold: number; limitations: string; dataset: { counts: Record<string, number>; template_split: Record<string, number[]> } } | null;
  evaluation: { validation?: Metrics; test?: Metrics; groups?: Record<string, Metrics>; history?: { epoch: number; training_loss: number; validation_loss: number; validation_f1: number }[]; comparisons?: Record<string, Metrics>; samples?: { id: string; label: number; prediction: number; score: number; template: string; condition: string }[]; public_benchmark?: Metrics };
};
