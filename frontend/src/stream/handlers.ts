/**
 * Domain Event Handlers — mapeamento organizado entre eventos do pipeline
 * e atualizações de Stores.
 *
 * Cada handler é uma função pura que recebe o EventDTO e o StoreRegistry,
 * e atualiza APENAS os Stores correspondentes ao seu domínio.
 *
 * NÃO executam lógica de negócio.
 * NÃO conhecem React.
 * NÃO conhecem transporte.
 *
 * O Bridge despacha para estes handlers — ele mesmo não contém lógica
 * de mapeamento, apenas roteamento.
 */

import type { StoreRegistry } from "@/stores";
import type {
  DiagnosticDTO,
  EventDTO,
  MetricsDTO,
  PipelineStatusDTO,
  SessionDTO,
} from "@/types";
import { devLog } from "@/utils";

// ============================================================
// Helpers — extração segura de campos do payload.
// ============================================================

function str(payload: Record<string, unknown>, key: string): string {
  const v = payload[key];
  return typeof v === "string" ? v : "";
}

function bool(payload: Record<string, unknown>, key: string): boolean {
  const v = payload[key];
  return typeof v === "boolean" ? v : false;
}

function num(payload: Record<string, unknown>, key: string): number {
  const v = payload[key];
  return typeof v === "number" ? v : 0;
}

function numOrNull(payload: Record<string, unknown>, key: string): number | null {
  const v = payload[key];
  return typeof v === "number" ? v : null;
}

// ============================================================
// Pipeline — eventos de ciclo de vida.
// ============================================================

/**
 * Atualiza o PipelineStore com base em eventos de ciclo de vida.
 *
 * PipelineStarted → running=true, paused=false
 * PipelineStopped → running=false, paused=false
 * PipelinePaused  → running=true, paused=true
 * PipelineResumed → running=true, paused=false
 */
export function handlePipelineLifecycle(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.pipeline.current?.data;
  const baseStatus: PipelineStatusDTO = prev?.status ?? {
    running: false,
    paused: false,
    is_active: false,
    is_idle: true,
    is_processing: false,
    current_segment: null,
    last_query: "",
    last_candidate_id: "",
    last_event_type: dto.event_type,
    last_event_timestamp: dto.meta.timestamp,
    statistics: prev?.status.statistics ?? {},
  };

  let running = baseStatus.running;
  let paused = baseStatus.paused;

  switch (dto.event_type) {
    case "PipelineStarted":
      running = true;
      paused = false;
      break;
    case "PipelineStopped":
      running = false;
      paused = false;
      break;
    case "PipelinePaused":
      running = true;
      paused = true;
      break;
    case "PipelineResumed":
      running = true;
      paused = false;
      break;
    default:
      return;
  }

  const status: PipelineStatusDTO = {
    ...baseStatus,
    running,
    paused,
    is_active: running && !paused,
    is_idle: !running,
    last_event_type: dto.event_type,
    last_event_timestamp: dto.meta.timestamp,
  };

  stores.pipeline.update((p) => ({
    timestamp: dto.meta.timestamp,
    status,
    session: p?.session ?? null as never,
    metrics: p?.metrics ?? null as never,
    last_event: dto,
  }));

  devLog.bridge(`Pipeline ${dto.event_type} → store atualizado (running=${running}, paused=${paused})`);
}

// ============================================================
// Session — eventos que carregam informações de sessão.
// ============================================================

/**
 * Atualiza o SessionStore quando eventos contêm session_id.
 *
 * A sessão é derivada do EventMetadata.session_id. Quando o pipeline
 * inicia, uma nova sessão começa; quando para, a sessão termina.
 */
export function handleSessionEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  if (dto.event_type !== "PipelineStarted" && dto.event_type !== "PipelineStopped") {
    return;
  }

  const prev = stores.session.current?.data;
  const sessionId = dto.meta.session_id;
  const now = dto.meta.timestamp;

  if (dto.event_type === "PipelineStarted") {
    const session: SessionDTO = prev ?? {
      session_id: sessionId,
      started_at: now,
      ended_at: 0,
      is_active: true,
      is_ended: false,
      duration_s: 0,
      processed_segments: 0,
      processed_queries: 0,
      presentations: 0,
      errors: 0,
      error_rate: 0,
      presentation_rate: 0,
      segments_per_minute: 0,
      queries_per_minute: 0,
      unique_correlations: 0,
      correlation_ids: [],
    };
    session.session_id = sessionId;
    session.started_at = now;
    session.is_active = true;
    session.is_ended = false;
    session.ended_at = 0;
    stores.session.set(session);
    devLog.bridge(`Session iniciada: ${sessionId}`);
  } else {
    // PipelineStopped
    if (prev) {
      prev.is_active = false;
      prev.is_ended = true;
      prev.ended_at = now;
      prev.duration_s = now - prev.started_at;
      stores.session.set(prev);
      devLog.bridge(`Session encerrada: ${prev.session_id}`);
    }
  }
}

// ============================================================
// Metrics — eventos de processamento que incrementam contadores.
// ============================================================

/**
 * Atualiza o MetricsStore incrementalmente com base em eventos de processamento.
 *
 * Cada evento incrementa contadores específicos:
 * - SpeechSegmentReceived → segments_received
 * - SpeechRecognized → segments_processed
 * - SearchCompleted → queries_processed
 * - PresentationCompleted → presentations_executed (ou failed)
 * - PipelineError → errors_total
 */
export function handleMetricsEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.metrics.current?.data;
  const base: MetricsDTO = prev ?? EMPTY_METRICS;

  let updated: MetricsDTO = base;

  switch (dto.event_type) {
    case "SpeechSegmentReceived":
      updated = { ...base, segments_received: base.segments_received + 1 };
      break;
    case "SpeechRecognized":
      updated = { ...base, segments_processed: base.segments_processed + 1 };
      break;
    case "SearchCompleted":
      updated = { ...base, queries_processed: base.queries_processed + 1 };
      break;
    case "PresentationCompleted": {
      const presented = bool(dto.payload, "presented");
      updated = presented
        ? { ...base, presentations_executed: base.presentations_executed + 1 }
        : { ...base, presentations_failed: base.presentations_failed + 1 };
      break;
    }
    case "PipelineError": {
      const recoverable = bool(dto.payload, "recoverable");
      updated = recoverable
        ? {
            ...base,
            errors_total: base.errors_total + 1,
            errors_recoverable: base.errors_recoverable + 1,
          }
        : {
            ...base,
            errors_total: base.errors_total + 1,
            errors_fatal: base.errors_fatal + 1,
          };
      break;
    }
    default:
      return;
  }

  stores.metrics.set(updated);
  devLog.bridge(`Metrics ${dto.event_type} → store atualizado`);
}

const EMPTY_METRICS: MetricsDTO = {
  segments_received: 0,
  segments_processed: 0,
  segments_dropped: 0,
  queries_processed: 0,
  presentations_executed: 0,
  presentations_failed: 0,
  errors_total: 0,
  errors_recoverable: 0,
  errors_fatal: 0,
  total_latency_ms: 0,
  avg_latency_ms: 0,
  avg_recognition_latency_ms: 0,
  avg_search_latency_ms: 0,
  avg_ranking_latency_ms: 0,
  avg_intelligence_latency_ms: 0,
  avg_presentation_latency_ms: 0,
  throughput_segments_per_min: 0,
  throughput_queries_per_min: 0,
  error_rate: 0,
  drop_rate: 0,
  presentation_success_rate: 0,
  processing_success_rate: 0,
  duration_s: 0,
  correlation_count: 0,
};

// ============================================================
// Diagnostics — eventos de erro.
// ============================================================

/**
 * Atualiza o DiagnosticsStore quando PipelineError ocorre.
 *
 * Cria um DiagnosticDTO sintético a partir do evento de erro,
 * permitindo que a UI mostre diagnósticos em tempo real.
 */
export function handleDiagnosticEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  if (dto.event_type !== "PipelineError") return;

  const errorType = str(dto.payload, "error_type");
  const errorMessage = str(dto.payload, "error_message");
  const handlerName = str(dto.payload, "handler_name");
  const recoverable = bool(dto.payload, "recoverable");

  const diagnostic: DiagnosticDTO = {
    component: handlerName || "pipeline",
    category: errorType || "PipelineError",
    available: true,
    info: {
      error_message: errorMessage,
      recoverable,
      timestamp: dto.meta.timestamp,
      correlation_id: dto.meta.correlation_id,
    },
    warnings: recoverable ? [errorMessage] : [],
    errors: recoverable ? [] : [errorMessage],
    has_warnings: recoverable,
    has_errors: !recoverable,
  };

  const prev = stores.diagnostics.current?.data ?? [];
  // Mantém os últimos 50 diagnósticos.
  const next = [...prev, diagnostic].slice(-50);
  stores.diagnostics.set(next);

  devLog.bridge(`Diagnostic ${errorType} → store atualizado (${next.length} itens)`);
}

// ============================================================
// Despachante — seleciona handlers por tipo de evento.
// ============================================================

const PIPELINE_LIFECYCLE_EVENTS = new Set([
  "PipelineStarted",
  "PipelineStopped",
  "PipelinePaused",
  "PipelineResumed",
]);

const METRICS_EVENTS = new Set([
  "SpeechSegmentReceived",
  "SpeechRecognized",
  "SearchCompleted",
  "PresentationCompleted",
  "PipelineError",
]);

const AUDIO_EVENTS = new Set([
  "audio.started",
  "audio.stopped",
  "audio.device.changed",
  "audio.level",
]);

const SPEECH_EVENTS = new Set([
  "SpeechStarted",
  "SpeechEnded",
  "SpeechSegmentCreated",
  "SpeechTranscribing",
  "SpeechTranscribed",
]);

const REFERENCE_EVENTS = new Set([
  "ReferenceDetected",
  "ReferenceInvalid",
  "IntentUnknown",
]);

// Sprint 18 — Automatic Verse Presentation
const VERSE_PRESENTATION_EVENTS = new Set([
  "VerseResolving",
  "VerseResolved",
  "VersePresented",
  "VersePresentationFailed",
]);

/**
 * Despacha um EventDTO para os handlers de domínio apropriados.
 *
 * Um evento pode atualizar múltiplos stores (ex: PipelineStarted
 * atualiza pipeline e session).
 */
export function dispatchDomainHandlers(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  if (PIPELINE_LIFECYCLE_EVENTS.has(dto.event_type)) {
    handlePipelineLifecycle(dto, stores);
    handleSessionEvent(dto, stores);
  }
  if (METRICS_EVENTS.has(dto.event_type)) {
    handleMetricsEvent(dto, stores);
  }
  if (dto.event_type === "PipelineError") {
    handleDiagnosticEvent(dto, stores);
  }
  if (AUDIO_EVENTS.has(dto.event_type)) {
    handleAudioEvent(dto, stores);
  }
  if (SPEECH_EVENTS.has(dto.event_type)) {
    handleSpeechEvent(dto, stores);
  }
  if (REFERENCE_EVENTS.has(dto.event_type)) {
    handleReferenceEvent(dto, stores);
  }
  if (VERSE_PRESENTATION_EVENTS.has(dto.event_type)) {
    handleVersePresentationEvent(dto, stores);
  }
}

// ============================================================
// Reference — eventos do Biblical Intent & Reference Extraction (Sprint 17).
// ============================================================

/**
 * Atualiza o ReferenceStore com base em eventos de referência bíblica.
 *
 * ReferenceDetected → adiciona entrada ao histórico, define current
 * ReferenceInvalid  → define invalid
 * IntentUnknown     → (apenas log, sem mudança de estado)
 */
export function handleReferenceEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.reference.current?.data;
  const baseState = prev ?? {
    current: null,
    entries: [],
    invalid: null,
  };

  switch (dto.event_type) {
    case "ReferenceDetected": {
      const entry = {
        id: dto.meta.correlation_id,
        intent: str(dto.payload, "intent"),
        book: str(dto.payload, "book"),
        bookId: num(dto.payload, "book_id"),
        chapter: num(dto.payload, "chapter"),
        verseStart: num(dto.payload, "verse_start"),
        verseEnd: num(dto.payload, "verse_end"),
        confidence: num(dto.payload, "confidence"),
        rawText: str(dto.payload, "raw_text"),
        normalizedText: str(dto.payload, "normalized_text"),
        timestamp: dto.meta.timestamp,
      };

      stores.reference.set({
        current: entry,
        entries: [entry, ...baseState.entries].slice(0, 50),
        invalid: null,
      });
      devLog.bridge(`ReferenceDetected → ${entry.normalizedText} (conf=${entry.confidence})`);
      break;
    }

    case "ReferenceInvalid": {
      const invalid = {
        book: str(dto.payload, "book"),
        reason: str(dto.payload, "reason"),
        rawText: str(dto.payload, "raw_text"),
        timestamp: dto.meta.timestamp,
      };
      stores.reference.set({
        ...baseState,
        invalid,
      });
      devLog.bridge(`ReferenceInvalid → ${invalid.book}: ${invalid.reason}`);
      break;
    }

    case "IntentUnknown":
      devLog.bridge(`IntentUnknown → reason=${dto.payload.reason}`);
      break;

    default:
      break;
  }
}

// ============================================================
// Speech — eventos do Continuous Speech Pipeline (Sprint 16).
// ============================================================

/**
 * Atualiza o TranscriptStore com base em eventos de speech.
 *
 * SpeechStarted       → listening=true
 * SpeechEnded         → listening=false
 * SpeechSegmentCreated → (apenas log, sem mudança de estado)
 * SpeechTranscribing  → transcribing=true
 * SpeechTranscribed   → transcribing=false, adiciona entrada ao histórico
 */
export function handleSpeechEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.transcript.current?.data;
  const baseState = prev ?? {
    entries: [],
    listening: false,
    transcribing: false,
    partialText: "",
  };

  switch (dto.event_type) {
    case "SpeechStarted":
      stores.transcript.set({
        ...baseState,
        listening: true,
      });
      devLog.bridge(`SpeechStarted → listening=true`);
      break;

    case "SpeechEnded":
      stores.transcript.set({
        ...baseState,
        listening: false,
      });
      devLog.bridge(`SpeechEnded → listening=false`);
      break;

    case "SpeechSegmentCreated":
      // Segmento criado — aguardando transcrição.
      devLog.bridge(`SpeechSegmentCreated → duration=${dto.payload.duration_ms}ms`);
      break;

    case "SpeechTranscribing":
      stores.transcript.set({
        ...baseState,
        transcribing: true,
      });
      devLog.bridge(`SpeechTranscribing → transcribing=true`);
      break;

    case "SpeechTranscribed": {
      const text = str(dto.payload, "text");
      const language = str(dto.payload, "language");
      const confidence = num(dto.payload, "confidence");
      const latencyMs = num(dto.payload, "latency_ms");
      const durationMs = num(dto.payload, "duration_ms");

      const entry = {
        id: dto.meta.correlation_id,
        text,
        language,
        confidence,
        latencyMs,
        durationMs,
        timestamp: dto.meta.timestamp,
      };

      stores.transcript.set({
        entries: [entry, ...baseState.entries].slice(0, 100), // max 100 entries
        listening: false,
        transcribing: false,
        partialText: "",
      });
      devLog.bridge(`SpeechTranscribed → text="${text.slice(0, 50)}..." latency=${latencyMs}ms`);
      break;
    }

    default:
      break;
  }
}

// ============================================================
// VersePresentation — eventos da apresentação automática (Sprint 18).
// ============================================================

/**
 * Atualiza o VersePresentationStore com base em eventos do fluxo
 * ReferenceDetected → VerseResolving → VerseResolved → VersePresented
 * (ou VersePresentationFailed).
 *
 * A chave de correlação é dto.meta.correlation_id — todos os eventos
 * de um mesmo fluxo compartilham o mesmo correlation_id, então
 * atualizamos a mesma entrada.
 */
export function handleVersePresentationEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.versePresentation.current?.data;
  const prevEntries = prev?.entries ?? [];
  const correlationId = dto.meta.correlation_id;

  // Encontrar entrada existente para este fluxo (mesmo correlation_id).
  const existingIdx = prevEntries.findIndex((e) => e.id === correlationId);
  const existing = existingIdx >= 0 ? prevEntries[existingIdx] : null;

  // Construir entrada base (preserva campos de etapas anteriores).
  const baseEntry = existing ?? {
    id: correlationId,
    book: "",
    bookId: 0,
    chapter: 0,
    verse: 0,
    reference: "",
    version: "",
    verseText: "",
    status: "idle" as const,
    quickPresentation: false,
    totalLatencyMs: 0,
    holyricsLatencyMs: 0,
    holyricsStatus: "",
    failureStage: "",
    errorType: "",
    errorMessage: "",
    timestamp: dto.meta.timestamp,
  };

  let updated: typeof baseEntry | null = null;

  switch (dto.event_type) {
    case "VerseResolving": {
      updated = {
        ...baseEntry,
        book: str(dto.payload, "book"),
        bookId: num(dto.payload, "book_id"),
        chapter: num(dto.payload, "chapter"),
        verse: num(dto.payload, "verse_start"),
        reference: str(dto.payload, "normalized_text"),
        status: "presenting",
        timestamp: dto.meta.timestamp,
      };
      devLog.bridge(
        `VerseResolving → ${updated.reference} (status=presenting)`,
      );
      break;
    }

    case "VerseResolved": {
      updated = {
        ...baseEntry,
        book: str(dto.payload, "book") || baseEntry.book,
        bookId: num(dto.payload, "book_id") || baseEntry.bookId,
        chapter: num(dto.payload, "chapter") || baseEntry.chapter,
        verse: num(dto.payload, "verse") || baseEntry.verse,
        reference: str(dto.payload, "reference") || baseEntry.reference,
        version: str(dto.payload, "version"),
        verseText: str(dto.payload, "verse_text"),
        status: "presenting", // ainda apresentando — aguarda VersePresented
        timestamp: dto.meta.timestamp,
      };
      devLog.bridge(
        `VerseResolved → ${updated.reference} = "${updated.verseText.slice(0, 50)}..."`,
      );
      break;
    }

    case "VersePresented": {
      updated = {
        ...baseEntry,
        reference: str(dto.payload, "reference") || baseEntry.reference,
        version: str(dto.payload, "version") || baseEntry.version,
        quickPresentation: bool(dto.payload, "quick_presentation"),
        holyricsStatus: str(dto.payload, "holyrics_status"),
        holyricsLatencyMs: num(dto.payload, "holyrics_latency_ms"),
        totalLatencyMs: num(dto.payload, "total_latency_ms"),
        status: "presented",
        timestamp: dto.meta.timestamp,
      };
      devLog.bridge(
        `VersePresented → ${updated.reference} (status=${updated.holyricsStatus}, total=${updated.totalLatencyMs}ms)`,
      );
      break;
    }

    case "VersePresentationFailed": {
      updated = {
        ...baseEntry,
        reference: str(dto.payload, "reference") || baseEntry.reference,
        failureStage: str(dto.payload, "failure_stage"),
        errorType: str(dto.payload, "error_type"),
        errorMessage: str(dto.payload, "error_message"),
        totalLatencyMs: num(dto.payload, "latency_ms"),
        status: "failed",
        timestamp: dto.meta.timestamp,
      };
      devLog.bridge(
        `VersePresentationFailed → ${updated.reference} stage=${updated.failureStage} error=${updated.errorType}`,
      );
      break;
    }

    default:
      break;
  }

  if (updated === null) return;

  // Substituir entrada existente ou adicionar nova no topo.
  let newEntries: typeof prevEntries;
  if (existingIdx >= 0) {
    newEntries = [...prevEntries];
    newEntries[existingIdx] = updated;
  } else {
    newEntries = [updated, ...prevEntries].slice(0, 50);
  }

  stores.versePresentation.set({
    current: updated,
    entries: newEntries,
  });
}

// ============================================================
// Audio — eventos de captura de áudio (Sprint 15.1).
// ============================================================

/**
 * Atualiza o AudioStore com base em eventos de áudio.
 *
 * audio.started      → capturing=true, sample_rate, channels
 * audio.stopped      → capturing=false, rms=0, peak=0
 * audio.device.changed → selectedDeviceIndex, restarted
 * audio.level        → rms, peak, lastUpdate (tempo real)
 */
export function handleAudioEvent(
  dto: EventDTO,
  stores: StoreRegistry,
): void {
  const prev = stores.audio.current?.data;
  const base = prev ?? {
    devices: [],
    current: null,
    levels: null,
    capturing: false,
    selectedDeviceIndex: null as number | null,
    sampleRate: 16000,
    channels: 1,
    rms: 0,
    peak: 0,
    lastUpdate: 0,
    connected: false,
  };

  switch (dto.event_type) {
    case "audio.started": {
      const deviceIndex = numOrNull(dto.payload, "device_index");
      const sampleRate = num(dto.payload, "sample_rate") || base.sampleRate;
      const channels = num(dto.payload, "channels") || base.channels;
      stores.audio.set({
        ...base,
        capturing: true,
        selectedDeviceIndex: deviceIndex,
        sampleRate,
        channels,
        connected: true,
      });
      devLog.bridge(`audio.started → capturing=true device=${deviceIndex}`);
      break;
    }
    case "audio.stopped": {
      stores.audio.set({
        ...base,
        capturing: false,
        rms: 0,
        peak: 0,
        connected: false,
      });
      devLog.bridge("audio.stopped → capturing=false");
      break;
    }
    case "audio.device.changed": {
      const deviceIndex = num(dto.payload, "device_index");
      const restarted = bool(dto.payload, "restarted");
      stores.audio.set({
        ...base,
        selectedDeviceIndex: deviceIndex,
        capturing: restarted,
        connected: restarted,
      });
      devLog.bridge(`audio.device.changed → device=${deviceIndex} restarted=${restarted}`);
      break;
    }
    case "audio.level": {
      const rms = num(dto.payload, "rms");
      const peak = num(dto.payload, "peak");
      const timestamp = num(dto.payload, "timestamp");
      stores.audio.set({
        ...base,
        rms,
        peak,
        lastUpdate: timestamp,
        connected: true,
      });
      break;
    }
    default:
      return;
  }
}
