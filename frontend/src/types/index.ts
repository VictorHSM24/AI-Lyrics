/**
 * Tipos TypeScript da Presentation Layer.
 *
 * Estes tipos refletem EXCLUSIVAMENTE os DTOs da Presentation Layer
 * do backend (Python). NUNCA refletem objetos internos do Core.
 *
 * A interface web nunca acessa o Core diretamente — apenas consome
 * DTOs via Services.
 */

// ============================================================
// Event Metadata
// ============================================================

export interface EventMetadataDTO {
  event_id: string;
  correlation_id: string;
  causation_id: string | null;
  session_id: string;
  timestamp: number;
  origin: string;
  metadata: Array<[string, string]>;
}

// ============================================================
// Event
// ============================================================

export interface EventDTO {
  event_type: string;
  meta: EventMetadataDTO;
  payload: Record<string, unknown>;
}

// ============================================================
// Pipeline Status
// ============================================================

export interface PipelineStatusDTO {
  running: boolean;
  paused: boolean;
  is_active: boolean;
  is_idle: boolean;
  is_processing: boolean;
  current_segment: Record<string, unknown> | null;
  last_query: string;
  last_candidate_id: string;
  last_event_type: string;
  last_event_timestamp: number;
  statistics: Record<string, number>;
}

// ============================================================
// Session
// ============================================================

export interface SessionDTO {
  session_id: string;
  started_at: number;
  ended_at: number;
  is_active: boolean;
  is_ended: boolean;
  duration_s: number;
  processed_segments: number;
  processed_queries: number;
  presentations: number;
  errors: number;
  error_rate: number;
  presentation_rate: number;
  segments_per_minute: number;
  queries_per_minute: number;
  unique_correlations: number;
  correlation_ids: string[];
}

// ============================================================
// Metrics
// ============================================================

export interface MetricsDTO {
  segments_received: number;
  segments_processed: number;
  segments_dropped: number;
  queries_processed: number;
  presentations_executed: number;
  presentations_failed: number;
  errors_total: number;
  errors_recoverable: number;
  errors_fatal: number;
  total_latency_ms: number;
  avg_latency_ms: number;
  avg_recognition_latency_ms: number;
  avg_search_latency_ms: number;
  avg_ranking_latency_ms: number;
  avg_intelligence_latency_ms: number;
  avg_presentation_latency_ms: number;
  throughput_segments_per_min: number;
  throughput_queries_per_min: number;
  error_rate: number;
  drop_rate: number;
  presentation_success_rate: number;
  processing_success_rate: number;
  duration_s: number;
  correlation_count: number;
}

// ============================================================
// Configuration
// ============================================================

export interface ConfigurationDTO {
  mode: string;
  holyrics: Record<string, unknown>;
  stt: Record<string, unknown>;
  llm: Record<string, unknown>;
  search: Record<string, unknown>;
  state: Record<string, unknown>;
  cache: Record<string, unknown>;
  confidence: Record<string, unknown>;
  log: Record<string, unknown>;
  audio: Record<string, unknown> | null;
  pipeline_policy: Record<string, unknown> | null;
}

// ============================================================
// Health
// ============================================================

export type HealthStatus = "healthy" | "degraded" | "unhealthy" | "unknown";

export interface HealthDTO {
  component: string;
  status: HealthStatus;
  message: string;
  details: Record<string, unknown>;
  is_healthy: boolean;
}

export interface HealthSnapshot {
  timestamp: number;
  components: HealthDTO[];
  component_count: number;
  healthy_count: number;
  unhealthy_count: number;
  all_healthy: boolean;
}

// ============================================================
// Diagnostic
// ============================================================

export interface DiagnosticDTO {
  component: string;
  category: string;
  available: boolean;
  info: Record<string, unknown>;
  warnings: string[];
  errors: string[];
  has_warnings: boolean;
  has_errors: boolean;
}

// ============================================================
// Log
// ============================================================

export interface LogDTO {
  timestamp: number;
  level: string;
  component: string;
  message: string;
  correlation_id: string;
  session_id: string;
}

// ============================================================
// Domain DTOs
// ============================================================

export interface CandidateDTO {
  candidate_id: string;
  base_score: number;
  book: string;
  chapter: number | null;
  verse: number | null;
  display: string;
}

export interface EvidenceDTO {
  id: string;
  type: string;
  description: string;
  value: number;
  weight: number;
  confidence: number;
  contribution: number;
  metadata: Array<[string, string]>;
  timestamp: number;
}

export interface SignalDTO {
  signal_type: string;
  value: number;
  weight: number;
  contribution: number;
  explanation: string;
  evidences: EvidenceDTO[];
  evidence_count: number;
}

export interface ScoreDTO {
  candidate_id: string;
  base_score: number;
  final_score: number;
  context_contribution: number;
  feedback_contribution: number;
  continuity_contribution: number;
  reference_contribution: number;
  theme_contribution: number;
  book_contribution: number;
  confidence_contribution: number;
  evaluation_contribution: number;
  total_contribution: number;
  confidence_level: string;
  signals: SignalDTO[];
  signal_count: number;
  explanation: string;
}

export interface RecommendationDTO {
  query: string;
  best_candidate_id: string;
  confidence_level: string;
  explanation: string;
  has_candidates: boolean;
  scores: ScoreDTO[];
  ranking: string[];
  candidate_count: number;
}

export interface PresentationDTO {
  candidate_id: string;
  book_id: number;
  chapter: number;
  verse: number | null;
  version: string;
  status: string;
  verse_id: string;
  presented: boolean;
}

// ============================================================
// Snapshots
// ============================================================

export interface PipelineSnapshot {
  timestamp: number;
  status: PipelineStatusDTO;
  session: SessionDTO;
  metrics: MetricsDTO;
  last_event: EventDTO | null;
}

export interface SessionSnapshot {
  timestamp: number;
  session: SessionDTO;
}

export interface MetricsSnapshot {
  timestamp: number;
  metrics: MetricsDTO;
}

export interface ConfigurationSnapshot {
  timestamp: number;
  configuration: ConfigurationDTO;
}

export interface EventSnapshot {
  timestamp: number;
  events: EventDTO[];
  event_count: number;
  event_types: string[];
  correlation_id: string;
}

// ============================================================
// Sprint 14 — System, Audio, Info
// ============================================================

export interface AudioDeviceDTO {
  index: number;
  name: string;
  channels: number;
  sample_rate: number;
  is_default: boolean;
  available: boolean;
}

export interface AudioDevicesResponse {
  devices: AudioDeviceDTO[];
  count: number;
}

export interface AudioLevelsDTO {
  rms: number;
  peak: number;
  timestamp: number;
}

export interface SystemInfoDTO {
  python_version: string;
  os_name: string;
  os_version: string;
  architecture: string;
  cpu_count: number;
  cpu_percent: number;
  memory_total_bytes: number;
  memory_available_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
  log_dir: string;
  cache_dir: string;
  data_dir: string;
  gpu_name: string;
  gpu_memory_total_bytes: number;
  gpu_memory_used_bytes: number;
  torch_version: string;
  faster_whisper_version: string;
  sentence_transformers_version: string;
  sounddevice_version: string;
}

export interface InfoDTO {
  name: string;
  version: string;
  api_version: {
    major: number;
    minor: number;
    patch: number;
    pre: string | null;
  };
  server_time: number;
  build_id: string;
  commit: string;
  build_date: string;
  frontend_version: string;
  sdk_compatibility: string;
}
