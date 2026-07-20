/**
 * Categorias de eventos do Console — mapeamento de tipos de evento
 * para categorias visuais com cores próprias.
 *
 * Este módulo é puramente declarativo — sem lógica de negócio.
 * Apenas mapeia tipos de evento (strings) para categorias visuais.
 *
 * Novos tipos de evento podem ser adicionados sem refatoração:
 * eventos desconhecidos caem na categoria "Sistema".
 */

import type { VisualStatus } from "@/shared/status";
import type { EventDTO } from "@/types";

// ============================================================
// EventCategory — categoria visual de um evento.
// ============================================================

export type EventCategory =
  | "audio"
  | "stt"
  | "pipeline"
  | "search"
  | "holyrics"
  | "system"
  | "error";

// ============================================================
// EventSeverity — severidade de um evento.
// ============================================================

export type EventSeverity = "info" | "low" | "medium" | "high" | "critical";

// ============================================================
// Mapeamento tipo → categoria.
// ============================================================

const TYPE_TO_CATEGORY: Record<string, EventCategory> = {
  // Áudio
  AudioCaptured: "audio",
  SpeechStarted: "audio",
  SpeechEnded: "audio",
  SpeechSegmentReceived: "audio",

  // STT (Sprint 16 — Continuous Speech Pipeline)
  SpeechRecognized: "stt",
  SpeechSegmentCreated: "stt",
  SpeechTranscribing: "stt",
  SpeechTranscribed: "stt",

  // NLU (Sprint 17 — Biblical Intent & Reference Extraction)
  ReferenceDetected: "search",
  ReferenceInvalid: "error",
  IntentUnknown: "system",

  // Sprint 18 — Automatic Verse Presentation
  VerseResolving: "search",
  VerseResolved: "search",
  VersePresented: "holyrics",
  VersePresentationFailed: "error",

  // Pipeline
  PipelineStarted: "pipeline",
  PipelineStopped: "pipeline",
  PipelinePaused: "pipeline",
  PipelineResumed: "pipeline",
  IntentDetected: "pipeline",

  // Busca
  SearchRequested: "search",
  SearchCompleted: "search",
  CandidateGenerated: "search",
  RecommendationChosen: "search",
  VerseFound: "search",
  RankingCompleted: "search",

  // Holyrics
  HolyricsRequest: "holyrics",
  HolyricsSuccess: "holyrics",
  HolyricsFailure: "holyrics",
  PresentationRequested: "holyrics",
  PresentationCompleted: "holyrics",

  // Sistema
  ConnectionLost: "system",
  ConnectionRestored: "system",
  SessionStarted: "system",
  SessionEnded: "system",

  // Erro
  PipelineError: "error",
  Error: "error",
};

// ============================================================
// Configuração visual por categoria.
// ============================================================

export interface CategoryConfig {
  label: string;
  /** Cor do badge (text-*). */
  colorClass: string;
  /** Cor de fundo do badge (bg-*). */
  bgClass: string;
  /** Cor da borda do badge (border-*). */
  borderClass: string;
  /** Cor do dot. */
  dotClass: string;
  /** Ícone (nome lucide). */
  icon: string;
}

export const CATEGORY_CONFIG: Record<EventCategory, CategoryConfig> = {
  audio: {
    label: "Áudio",
    colorClass: "text-blue-400",
    bgClass: "bg-blue-500/10",
    borderClass: "border-blue-500/30",
    dotClass: "bg-blue-500",
    icon: "Mic",
  },
  stt: {
    label: "STT",
    colorClass: "text-cyan-400",
    bgClass: "bg-cyan-500/10",
    borderClass: "border-cyan-500/30",
    dotClass: "bg-cyan-500",
    icon: "AudioLines",
  },
  pipeline: {
    label: "Pipeline",
    colorClass: "text-purple-400",
    bgClass: "bg-purple-500/10",
    borderClass: "border-purple-500/30",
    dotClass: "bg-purple-500",
    icon: "Workflow",
  },
  search: {
    label: "Busca",
    colorClass: "text-amber-400",
    bgClass: "bg-amber-500/10",
    borderClass: "border-amber-500/30",
    dotClass: "bg-amber-500",
    icon: "Search",
  },
  holyrics: {
    label: "Holyrics",
    colorClass: "text-emerald-400",
    bgClass: "bg-emerald-500/10",
    borderClass: "border-emerald-500/30",
    dotClass: "bg-emerald-500",
    icon: "Send",
  },
  system: {
    label: "Sistema",
    colorClass: "text-slate-400",
    bgClass: "bg-slate-500/10",
    borderClass: "border-slate-500/30",
    dotClass: "bg-slate-500",
    icon: "Server",
  },
  error: {
    label: "Erro",
    colorClass: "text-status-error",
    bgClass: "bg-status-error/10",
    borderClass: "border-status-error/30",
    dotClass: "bg-status-error",
    icon: "AlertCircle",
  },
};

// ============================================================
// Mapeamento severidade → VisualStatus.
// ============================================================

const SEVERITY_TO_VISUAL: Record<EventSeverity, VisualStatus> = {
  info: "info",
  low: "healthy",
  medium: "warning",
  high: "error",
  critical: "error",
};

// ============================================================
// Funções utilitárias.
// ============================================================

export function eventToCategory(eventType: string): EventCategory {
  return TYPE_TO_CATEGORY[eventType] ?? "system";
}

export function categoryToConfig(category: EventCategory): CategoryConfig {
  return CATEGORY_CONFIG[category];
}

export function severityToVisualStatus(severity: EventSeverity): VisualStatus {
  return SEVERITY_TO_VISUAL[severity];
}

/**
 * Infere severidade a partir do tipo de evento.
 */
export function eventToSeverity(eventType: string): EventSeverity {
  if (eventType.includes("Error") || eventType === "Error") return "high";
  if (eventType.includes("Failure") || eventType.includes("Failed")) return "high";
  if (eventType === "ConnectionLost") return "critical";
  if (eventType === "ConnectionRestored") return "medium";
  if (eventType === "PipelineStopped") return "low";
  if (eventType === "PipelineStarted") return "info";
  if (eventType.includes("Warning") || eventType === "Warning") return "medium";
  return "info";
}

/**
 * Lista todas as categorias (para filtros).
 */
export const ALL_CATEGORIES: EventCategory[] = [
  "audio",
  "stt",
  "pipeline",
  "search",
  "holyrics",
  "system",
  "error",
];

/**
 * Lista todas as severidades (para filtros).
 */
export const ALL_SEVERITIES: EventSeverity[] = [
  "info",
  "low",
  "medium",
  "high",
  "critical",
];

// ============================================================
// Sprint 17.2 — Event Stream Optimization
// ============================================================

/**
 * True se o evento é de telemetria (alta frequência, não operacional).
 * Eventos de telemetria NÃO devem aparecer na Timeline nem no EventStore.
 */
export function isTelemetryEvent(dto: EventDTO): boolean {
  return dto.category === "telemetry";
}

/**
 * True se o evento é operacional (negócio, aparece na Timeline).
 */
export function isOperationalEvent(dto: EventDTO): boolean {
  return dto.category !== "telemetry";
}

/**
 * Lista de event_types conhecidos como telemetria.
 * Usado como fallback quando o campo `category` não está presente
 * (compatibilidade com eventos legacy sem category).
 */
export const TELEMETRY_EVENT_TYPES: ReadonlySet<string> = new Set([
  "audio.level",
  "audio.rms",
  "audio.peak",
  "waveform",
  "cpu.usage",
  "gpu.usage",
  "ram.usage",
  "latency",
  "fps",
  "queue.size",
  "pipeline.metrics",
]);

/**
 * Verifica se um event_type é telemetria — considerando tanto
 * o campo `category` quanto a lista de tipos conhecidos.
 */
export function isTelemetryType(eventType: string, category?: string): boolean {
  if (category === "telemetry") return true;
  return TELEMETRY_EVENT_TYPES.has(eventType);
}
