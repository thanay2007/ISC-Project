export type Box = [number, number, number, number];
export type User = { id: string; name: string; email: string; role: "admin" | "institution" | "verifier" | "guest" };
export type Stage = { stage: string; label: string; at: string };
export type Preview = { page_count: number; boxes: { page: number; box: Box }[] };
export type Assessment = { label: "Fake" | "Original"; confidence: number } | { label: null; confidence: null };
export type Analysis = { id: string; filename: string; mime: string; stage: string; verdict: Assessment["label"] | null; created_at: string; demo: boolean; progress: Stage[]; result: Result | null; preview?: Preview | null };
export type Finding = { page: number; box?: Box; kind?: string; finding: string; severity?: string; region?: string };
export type Line = { page: number; box: Box; text: string; confidence: number | null };
export type Field = { page: number; box: Box; value: string };
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
  assessment: Assessment; crypto: Integrity; fields: Record<string, Field>; field_agreement?: Record<string, boolean>; ocr: Line[];
  page_count: number; opencv: Finding[]; anomaly: (number | null)[]; custom_model: CustomModel;
  gemini: { document_type: string; extracted_fields: Record<string, string | null>; observations: Finding[];
    visual_assessment?: "likely_edited" | "no_clear_edit" | "inconclusive"; additional_fields?: { label: string; value: string }[] } | null;
  limitations: string[]; warnings: string[]; engines: Record<string, Engine>;
  explanation: { summary: string; detailed: string; presentation: string; recommendation: string; source: string };
  demo_case?: { id: string; label: number; prediction: number; score: number };
};
export type Audit = { id: string; actor: string | null; kind: string; detail: string; subject: string | null; created_at: string };
export type Dashboard = { counts: Record<string, number>; trends: { day: string; analyzed: number; original: number }[]; recent: Analysis[]; alerts: Audit[] };
export type Metrics = { accuracy: number; precision: number; recall: number; f1: number; roc_auc: number | null; false_positive_rate: number | null; confusion_matrix: number[][]; iou?: number; dice?: number; pixel_precision?: number; pixel_recall?: number; count: number };
export type ModelPerformance = {
  deployed: { name: string; version: string; trained_at: string; epoch: number; device: string; size: number; limitations: string; dataset: { counts: Record<string, number> } } | null;
  evaluation: { validation?: Metrics; test?: Metrics; groups?: Record<string, Metrics>; validation_groups?: Record<string, Metrics>; history?: { epoch: number; training_loss: number; validation_quality: number }[]; samples?: { id: string; label: number; prediction: number; score: number; template: string; condition: string }[] };
};
