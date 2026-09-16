/** Tipos espelhando os schemas da API. */

export type Severity = "HEALTHY" | "WARNING" | "FAILURE";
export type FaultType = "normal" | "bearing" | "misalignment" | "unbalance";
export type Criticality = "A" | "B" | "C";
export type AlertStatus = "OPEN" | "ACKNOWLEDGED" | "RESOLVED" | "DISMISSED";

export interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
}

export interface LoginResponse {
  access_token: string;
  expires_in: number;
  csrf_token: string;
  user: User;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Plant {
  id: string;
  code: string;
  name: string;
  location: string | null;
}

export interface Area {
  id: string;
  code: string;
  name: string;
  plant_id: string;
}

export interface Line {
  id: string;
  code: string;
  name: string;
  area_id: string;
}

export interface TreeMotor {
  id: string;
  tag: string;
  name: string;
  criticality: Criticality;
  last_severity: Severity | null;
  open_alerts: number;
  max_priority: number;
}

export interface TreeLine {
  id: string;
  code: string;
  name: string;
  motors: TreeMotor[];
  open_alerts: number;
}

export interface TreeArea {
  id: string;
  code: string;
  name: string;
  lines: TreeLine[];
  open_alerts: number;
}

export interface TreePlant {
  id: string;
  code: string;
  name: string;
  location: string | null;
  areas: TreeArea[];
  open_alerts: number;
  motor_count: number;
}

export interface Motor {
  id: string;
  tag: string;
  name: string;
  line_id: string | null;
  criticality: Criticality;
  manufacturer: string | null;
  model: string | null;
  power_kw: number | null;
  rated_rpm: number | null;
  poles: number | null;
  iso_machine_class: string;
  foundation_type: "RIGID" | "FLEXIBLE" | null;
  baseline_measurement_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface MotorDetail extends Motor {
  line_name: string | null;
  area_name: string | null;
  plant_name: string | null;
  measurement_count: number;
  last_measurement_at: string | null;
  last_severity: Severity | null;
  last_fault_type: FaultType | null;
  last_is_baseline: boolean;
  open_alerts: number;
  max_priority: number;
  has_baseline: boolean;
}

export interface TopFactor {
  feature: string;
  contribution: number;
  value: number;
}

export interface Prediction {
  id: string;
  /** Severidade por critério físico (ISO 10816) — saída primária. */
  severity: Severity;
  severity_criterion: string | null;
  severity_explanation: string | null;
  ratio_to_baseline: number | null;
  /** Severidade prevista pelo modelo — experimento preliminar, informativa. */
  ml_severity: Severity | null;
  severity_probabilities: Record<string, number>;
  fault_type: FaultType;
  fault_type_probabilities: Record<string, number>;
  physical_type: FaultType | null;
  evidence_agreement: boolean;
  confidence: number;
  recommendation: string;
  top_factors: TopFactor[];
  baseline_comparison: Record<string, number> | null;
  inference_ms: number | null;
  created_at: string;
}

export interface Measurement {
  id: string;
  motor_id: string;
  collected_at: string;
  load_nm: number | null;
  rpm: number | null;
  temperature_c: number | null;
  is_baseline: boolean;
  source_filename: string | null;
  sample_rate_hz: number;
  n_samples: number;
  n_channels: number;
  duration_s: number;
  iso_v_rms_mms: number | null;
  iso_v_1x_mms: number | null;
  iso_v_2x_mms: number | null;
  iso_a_hf_g: number | null;
  iso_zone: string | null;
  notes: string | null;
  created_at: string;
}

export interface MeasurementListItem extends Measurement {
  prediction_id: string | null;
  fault_type: FaultType | null;
  severity: Severity | null;
  inspected: boolean;
}

export interface MeasurementWithPrediction extends Measurement {
  prediction: Prediction | null;
  model_version: string | null;
  profile: string | null;
  profile_note: string | null;
  alert_id: string | null;
}

export interface Alert {
  id: string;
  motor_id: string;
  prediction_id: string | null;
  ml_model_id: string | null;
  severity: "WARNING" | "FAILURE";
  status: AlertStatus;
  message: string;
  rule: string;
  reasons: string[];
  priority_score: number;
  fault_type: FaultType | null;
  physical_type: FaultType | null;
  confidence: number | null;
  evidence_agreement: boolean | null;
  trend_pct: number | null;
  indicators: Record<string, unknown> | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  action_taken: string | null;
  created_at: string;
  motor_tag?: string | null;
  motor_name?: string | null;
  criticality?: Criticality | null;
  line_name?: string | null;
  area_name?: string | null;
  plant_name?: string | null;
}

export interface CriticalMotor {
  motor_id: string;
  tag: string;
  name: string;
  criticality: Criticality;
  line_name: string | null;
  area_name: string | null;
  priority_score: number;
  severity: Severity | null;
  fault_type: FaultType | null;
  physical_type: FaultType | null;
  evidence_agreement: boolean | null;
  confidence: number | null;
  trend_pct: number | null;
  open_alerts: number;
  top_rule: string | null;
  reasons: string[];
  last_measurement_at: string | null;
}

export interface Dashboard {
  total_motors: number;
  monitored_motors: number;
  severity_counts: {
    healthy: number;
    warning: number;
    failure: number;
    unmeasured: number;
  };
  open_alerts: number;
  failure_alerts: number;
  divergence_alerts: number;
  critical_motors: CriticalMotor[];
  recent_alerts: Alert[];
  measurements_last_7d: number;
}

// --- rotulos em portugues -------------------------------------------------
export const ROTULO_SEVERIDADE: Record<Severity, string> = {
  HEALTHY: "Saudável",
  WARNING: "Atenção",
  FAILURE: "Falha",
};

export const ROTULO_FALHA: Record<FaultType, string> = {
  normal: "Sem falha detectada",
  bearing: "Rolamento",
  misalignment: "Desalinhamento de eixo",
  unbalance: "Desbalanceamento de rotor",
};

export const ROTULO_CRITICIDADE: Record<Criticality, string> = {
  A: "Crítico — para a linha",
  B: "Impacto parcial",
  C: "Redundante",
};

export const ROTULO_REGRA: Record<string, string> = {
  FALHA_CONFIRMADA: "Falha confirmada",
  NORMA_CRITICA: "Nível inaceitável (ISO zona D)",
  FALHA_INCERTA: "Falha provável, evidências incertas",
  DIVERGENCIA_EM_SAUDAVEL: "Divergência: modelo diz saudável",
  SALTO_SOBRE_BASELINE: "Salto sobre a referência",
  NORMA_ATENCAO: "Nível insatisfatório (ISO zona C)",
  DEGRADACAO: "Degradação incipiente",
  DEGRADACAO_INCERTA: "Degradação com evidências incertas",
};

/* --- inspecoes de campo -------------------------------------------------- */

export interface Inspection {
  id: string;
  motor_id: string;
  prediction_id: string | null;
  alert_id: string | null;
  performed_at: string;
  findings: string | null;
  notes: string | null;
  confirmed_fault_type: FaultType | null;
  created_at: string;
  predicted_fault_type: FaultType | null;
  predicted_severity: Severity | null;
  model_version: string | null;
  agreement: boolean | null;
}



/* --- auditoria ----------------------------------------------------------- */

export interface AuditEntry {
  id: string;
  action: string;
  entity: string | null;
  entity_id: string | null;
  detail: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
  user_name: string | null;
  sensitive: boolean;
}

export interface AuditSummary {
  days: number;
  total: number;
  by_action: Record<string, number>;
  sensitive: Record<string, number>;
  first_event: string | null;
  last_event: string | null;
}

/* --- forma de onda ------------------------------------------------------- */

export interface WaveformPoint {
  t: number;
  min: number;
  max: number;
}

export interface Waveform {
  measurement_id: string;
  channel: number;
  channel_name: string;
  unit: string;
  sample_rate_hz: number;
  n_samples: number;
  duration_s: number;
  decimation: number;
  points: WaveformPoint[];
  peak_to_peak_g: number;
  peak_g: number;
  rms_g: number;
  crest_factor: number;
}
