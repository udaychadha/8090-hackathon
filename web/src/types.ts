export type Json =
  null | boolean | number | string | Json[] | { [key: string]: Json };
export type ObjectData = Record<string, Json>;
export interface Event {
  seq: number;
  ts: string;
  run_id: string;
  stage: string;
  variant: string | null;
  status: string;
  message: string;
  data: ObjectData;
}
export interface Step {
  id: string;
  kind: string;
  label: string;
  state: string;
  number: number | null;
  attempts: number;
  max_attempts: number | null;
  details: string[];
  logs: Event[];
}
export interface StrategySpec {
  paper_id: string;
  title: string;
  category: string;
  hypothesis: string;
  universe: string[];
  frequency: string;
  signal_rules: string[];
  claimed_metrics: ObjectData;
  ambiguities: string[];
  test_type: string;
}
export interface Source {
  source_id: string;
  title: string;
  source_kind: string;
  spec: StrategySpec;
  provenance: ObjectData;
}
export interface DataNeed {
  id: string;
  kind: string;
  name: string;
  symbols: string[];
  frequency: string | null;
  start: string | null;
  end: string | null;
  status: string;
  provider: string | null;
  candidates: ObjectData[];
}
export interface LeaderboardRow {
  variant_id: string;
  run_id: string;
  source_id: string;
  source_title: string;
  source_kind: string;
  variant: string;
  test_type: string;
  frequency: string;
  claimed_sharpe: number | null;
  verified_sharpe: number | null;
  break_even_bps: number | null;
  evals_passed: number;
  status: string;
  profile: string;
  default_status: string;
  default_evals_passed: number;
  summary: string;
  days_traded: number | null;
  notes: string[];
  voided: boolean;
  void_reason: string | null;
  created_at: string | null;
}
export interface VariantRun extends LeaderboardRow {
  steps: Step[];
}
export interface RunSummary {
  run_id: string;
  status: string;
  source: Source | null;
  variants: LeaderboardRow[];
  data_needs: DataNeed[];
  created_at: string | null;
  started_at: string | null;
  wall_seconds: number | null;
  estimated_model_cost_usd: number | null;
  cost_complete: boolean | null;
  voided: boolean;
  void_reason: string | null;
  error_type: string | null;
  error: string | null;
  submission: { upload_name: string; accepted_at: string } | null;
}
export interface RunDetail extends RunSummary {
  variants: VariantRun[];
  steps: Step[];
  usage: ObjectData[];
  extraction_diagnostics: ObjectData[];
  artifacts: Artifact[];
}
export interface EvalResult {
  n: number;
  name: string;
  passed: boolean;
  metrics: ObjectData;
}
export interface Equity {
  dates: string[];
  gross: number[];
  net: number[];
  is_end: string;
  oos_end: string;
}
export interface VariantDetail extends LeaderboardRow {
  code: string | null;
  params: ObjectData | null;
  evals: EvalResult[];
  equity: Equity | null;
  heal_attempts: {
    attempt: number;
    error: string;
    fixed: boolean;
    result_error?: string | null;
  }[];
  critique: string | null;
  steps: Step[];
  activity: ObjectData | null;
  equity_boundaries: { is_end: string; oos_end: string } | null;
  source: Source | null;
  artifacts: Artifact[];
  original_result: ObjectData | null;
}
export interface GraveyardEntry {
  variant_id: string;
  run_id: string;
  source_title: string;
  variant: string;
  status: string;
  test_type: string;
  frequency: string;
  evals_passed: number;
  summary: string;
  cause: string;
  critique: string | null;
  notes: string[];
  voided: boolean;
  void_reason: string | null;
  original_result: ObjectData | null;
}
export interface Artifact {
  id: string;
  name: string;
  kind: string;
  media_type: string;
  size_bytes: number;
  run_ids: string[];
  source_id: string | null;
  dataset_id: string | null;
  historical: boolean;
  audit_only: boolean;
  downloadable: boolean;
  notes: string[];
}
export interface ArtifactView {
  artifact: Artifact;
  content: string | null;
  offset: number;
  next_offset: number | null;
}
export interface Dataset {
  id: string;
  name: string;
  kind: string;
  symbols: string[];
  frequency: string | null;
  start: string;
  end: string;
  rows: number;
  source: string;
  verified: boolean;
  scope: "main" | "smoke";
  schema_version: string;
  feed: string;
  adjustment: string;
  fill_rate: number;
  expected_rows: number | null;
  missing_rows: number | null;
  notes: string[];
}
export interface DatasetDetail {
  dataset: Dataset;
  manifest: ObjectData;
  metadata: ObjectData;
  splits: ObjectData;
  fields: ObjectData;
  artifacts: Artifact[];
}
export interface DatasetPreview {
  dataset_id: string;
  rows: ObjectData[];
  splits: ObjectData;
  coverage: ObjectData;
  gaps: { start: string; end: string; rows: number }[];
  total_gaps: number;
  holdout_sealed: true;
  downsampled: boolean;
}
export interface Knob {
  key: string;
  label: string;
  default: number;
  min: number;
  max: number;
  locked: boolean;
  tooltip: { what_it_is: string; if_raised: string; if_lowered: string };
}
export interface Check extends Knob {
  metric: string;
  op: string;
  relative_to: string | null;
}
export interface EvalDefinition {
  n: number;
  name: string;
  question: string;
  settings: Knob[];
  checks: Check[];
  data_scope: string;
  notes: string[];
  source_file: string;
  source_code: string;
}
export interface EvalSchema {
  evals: EvalDefinition[];
  readonly: boolean;
  constants: Record<string, number | number[]>;
  notes: string[];
}
export interface EvalProfile {
  name: string;
  editable: boolean;
  values: Record<string, number>;
  stale: boolean;
}
export interface Provider {
  name: string;
  connected: boolean;
  covers: string[];
}
