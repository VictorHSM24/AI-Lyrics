/**
 * Domain Stores — um store por domínio do sistema.
 *
 * Cada Store encapsula um SnapshotStore tipado e expõe
 * métodos específicos do domínio para atualização.
 *
 * Stores NÃO conhecem React.
 * Stores NÃO conhecem transporte.
 * Stores NÃO executam lógica de negócio — apenas armazenam estado.
 */

import type {
  AudioDeviceDTO,
  AudioLevelsDTO,
  ConfigurationDTO,
  DiagnosticDTO,
  EventDTO,
  HealthSnapshot,
  InfoDTO,
  LogDTO,
  MetricsDTO,
  PipelineSnapshot,
  PipelineStatusDTO,
  SessionDTO,
  SystemInfoDTO,
} from "@/types";
import {
  createSnapshotStore,
  type Snapshot,
  type SnapshotStore,
  type StoreSubscription,
  type StoreListener,
} from "./SnapshotStore";

// ============================================================
// Base helper — expõe uma interface comum.
// ============================================================

export interface DomainStore<T> {
  readonly current: Snapshot<T> | null;
  readonly version: number;
  readonly hasSnapshot: boolean;
  subscribe(listener: StoreListener<T>): StoreSubscription;
  set(data: T): void;
  update(updater: (prev: T | null) => T): void;
  clear(): void;
}

/**
 * Cria um DomainStore a partir de um SnapshotStore.
 * Usa herança prototipal para preservar todas as propriedades
 * (incluindo getters como `hasSnapshot`).
 */
function wrap<T>(store: SnapshotStore<T>): DomainStore<T> {
  // O SnapshotStore já implementa todos os métodos de DomainStore.
  // Apenas retornamos com o tipo correto.
  return store as unknown as DomainStore<T>;
}

// ============================================================
// PipelineStore
// ============================================================

export interface PipelineStore extends DomainStore<PipelineSnapshot> {
  setStatus(status: PipelineStatusDTO): void;
}

export function createPipelineStore(): PipelineStore {
  const store = createSnapshotStore<PipelineSnapshot>();
  const base = wrap(store);
  const pipelineStore: PipelineStore = {
    get current() { return base.current; },
    get version() { return base.version; },
    get hasSnapshot() { return base.hasSnapshot; },
    subscribe: (l) => base.subscribe(l),
    set: (d) => base.set(d),
    update: (u) => base.update(u),
    clear: () => base.clear(),
    setStatus(status: PipelineStatusDTO) {
      store.update((prev) => ({
        timestamp: Date.now() / 1000,
        status,
        session: prev?.session ?? null as never,
        metrics: prev?.metrics ?? null as never,
        last_event: prev?.last_event ?? null,
      }));
    },
  };
  return pipelineStore;
}

// ============================================================
// HealthStore
// ============================================================

export type HealthStore = DomainStore<HealthSnapshot>;
export function createHealthStore(): HealthStore {
  return wrap(createSnapshotStore<HealthSnapshot>());
}

// ============================================================
// MetricsStore
// ============================================================

export type MetricsStore = DomainStore<MetricsDTO>;
export function createMetricsStore(): MetricsStore {
  return wrap(createSnapshotStore<MetricsDTO>());
}

// ============================================================
// SessionStore
// ============================================================

export type SessionStore = DomainStore<SessionDTO>;
export function createSessionStore(): SessionStore {
  return wrap(createSnapshotStore<SessionDTO>());
}

// ============================================================
// ConfigurationStore
// ============================================================

export type ConfigurationStore = DomainStore<ConfigurationDTO>;
export function createConfigurationStore(): ConfigurationStore {
  return wrap(createSnapshotStore<ConfigurationDTO>());
}

// ============================================================
// DiagnosticsStore
// ============================================================

export type DiagnosticsStore = DomainStore<DiagnosticDTO[]>;
export function createDiagnosticsStore(): DiagnosticsStore {
  return wrap(createSnapshotStore<DiagnosticDTO[]>());
}

// ============================================================
// LogStore
// ============================================================

export type LogStore = DomainStore<LogDTO[]>;
export function createLogStore(): LogStore {
  return wrap(createSnapshotStore<LogDTO[]>());
}

// ============================================================
// ReplayStore
// ============================================================

export interface ReplayState {
  events: EventDTO[];
  sessionIds: string[];
  correlations: string[];
}

export type ReplayStore = DomainStore<ReplayState>;
export function createReplayStore(): ReplayStore {
  return wrap(createSnapshotStore<ReplayState>());
}

// ============================================================
// EventStore (frontend) — histórico de eventos recebidos.
// ============================================================

export type EventStore = DomainStore<EventDTO[]>;
export function createEventStore(): EventStore {
  return wrap(createSnapshotStore<EventDTO[]>());
}

// ============================================================
// AudioStore (Sprint 14/15.1) — dispositivos, níveis e captura.
// ============================================================

export interface AudioState {
  devices: AudioDeviceDTO[];
  current: AudioDeviceDTO | null;
  levels: AudioLevelsDTO | null;
  // Sprint 15.1 — estado de captura em tempo real.
  capturing: boolean;
  selectedDeviceIndex: number | null;
  sampleRate: number;
  channels: number;
  rms: number;
  peak: number;
  lastUpdate: number;
  connected: boolean;
}

export type AudioStore = DomainStore<AudioState>;
export function createAudioStore(): AudioStore {
  return wrap(createSnapshotStore<AudioState>());
}

// ============================================================
// SystemStore (Sprint 14) — informações de sistema.
// ============================================================

export type SystemStore = DomainStore<SystemInfoDTO>;
export function createSystemStore(): SystemStore {
  return wrap(createSnapshotStore<SystemInfoDTO>());
}

// ============================================================
// InfoStore (Sprint 14) — metadados da API.
// ============================================================

export type InfoStore = DomainStore<InfoDTO>;
export function createInfoStore(): InfoStore {
  return wrap(createSnapshotStore<InfoDTO>());
}

// ============================================================
// TranscriptStore (Sprint 16) — transcrições em tempo real.
// ============================================================

export interface TranscriptEntry {
  /** ID único (correlation_id do evento SpeechTranscribed). */
  id: string;
  /** Texto transcrito. */
  text: string;
  /** Idioma detectado. */
  language: string;
  /** Confiança [0.0, 1.0]. */
  confidence: number;
  /** Latência em ms (fim da fala → texto). */
  latencyMs: number;
  /** Duração do segmento de áudio em ms. */
  durationMs: number;
  /** Timestamp do evento. */
  timestamp: number;
}

export interface TranscriptState {
  /** Histórico de transcrições (mais recente primeiro). */
  entries: TranscriptEntry[];
  /** True se o VAD está detectando fala agora. */
  listening: boolean;
  /** True se o Whisper está transcrevendo um segmento. */
  transcribing: boolean;
  /** Texto parcial (vazio até completar). */
  partialText: string;
}

export type TranscriptStore = DomainStore<TranscriptState>;
export function createTranscriptStore(): TranscriptStore {
  return wrap(createSnapshotStore<TranscriptState>());
}

// ============================================================
// ReferenceStore (Sprint 17) — referências bíblicas detectadas.
// ============================================================

export interface ReferenceEntry {
  /** ID único (correlation_id do evento). */
  id: string;
  /** Intenção detectada (ex.: "OPEN_REFERENCE"). */
  intent: string;
  /** Nome canônico do livro (ex.: "João", "1 Coríntios"). */
  book: string;
  /** ID do livro (1..66). */
  bookId: number;
  /** Capítulo. */
  chapter: number;
  /** Versículo inicial. */
  verseStart: number;
  /** Versículo final (igual a verseStart se for versículo único). */
  verseEnd: number;
  /** Confiança da detecção [0.0, 1.0]. */
  confidence: number;
  /** Texto original transcrito. */
  rawText: string;
  /** Texto normalizado (ex.: "joao 3:16"). */
  normalizedText: string;
  /** Timestamp do evento. */
  timestamp: number;
}

export interface ReferenceState {
  /** Última referência detectada (ou null se nenhuma). */
  current: ReferenceEntry | null;
  /** Histórico de referências (mais recente primeiro). */
  entries: ReferenceEntry[];
  /** Última referência inválida (ou null). */
  invalid: { book: string; reason: string; rawText: string; timestamp: number } | null;
}

export type ReferenceStore = DomainStore<ReferenceState>;
export function createReferenceStore(): ReferenceStore {
  return wrap(createSnapshotStore<ReferenceState>());
}

// ============================================================
// VersePresentationStore (Sprint 18) — apresentação automática
// de versículos no Holyrics.
// ============================================================

/**
 * Status possível da última apresentação.
 * - "presenting"  : VerseResolving publicado, busca em andamento.
 * - "presented"   : VersePresented publicado, Holyrics confirmou.
 * - "failed"      : VersePresentationFailed publicado.
 * - "idle"        : nenhuma apresentação iniciada ainda.
 */
export type VersePresentationStatus = "idle" | "presenting" | "presented" | "failed";

export interface VersePresentationEntry {
  /** ID único (correlation_id do fluxo). */
  id: string;
  /** Livro (ex.: "João"). */
  book: string;
  /** ID do livro (1..66). */
  bookId: number;
  /** Capítulo. */
  chapter: number;
  /** Versículo. */
  verse: number;
  /** Referência formatada (ex.: "João 3:16"). */
  reference: string;
  /** Versão bíblica usada. */
  version: string;
  /** Texto do versículo (vazio até VerseResolved). */
  verseText: string;
  /** Status da apresentação. */
  status: VersePresentationStatus;
  /** True se quick_presentation foi usado. */
  quickPresentation: boolean;
  /** Latência total (ReferenceDetected → VersePresented) em ms. */
  totalLatencyMs: number;
  /** Latência específica do Holyrics em ms. */
  holyricsLatencyMs: number;
  /** Status retornado pelo Holyrics (ex.: "ok"). */
  holyricsStatus: string;
  /** Stage da falha (se status="failed"): "search" | "holyrics" | "internal". */
  failureStage: string;
  /** Tipo do erro (se status="failed"): "book_not_found", "timeout", etc. */
  errorType: string;
  /** Mensagem de erro (se status="failed"). */
  errorMessage: string;
  /** Timestamp do evento mais recente deste fluxo. */
  timestamp: number;
}

export interface VersePresentationState {
  /** Última apresentação (ou null). */
  current: VersePresentationEntry | null;
  /** Histórico de apresentações (mais recente primeiro, máx 50). */
  entries: VersePresentationEntry[];
}

export type VersePresentationStore = DomainStore<VersePresentationState>;
export function createVersePresentationStore(): VersePresentationStore {
  return wrap(createSnapshotStore<VersePresentationState>());
}

// ============================================================
// SemanticStore (Sprint 20) — camada de compreensão semântica.
// Mostra inferências do SemanticEngine e resoluções do
// ReferenceResolver para depuração.
// ============================================================

/** Candidato semântico individual gerado pelo LLM. */
export interface SemanticCandidateEntry {
  book: string;
  chapter: number;
  verse: number;
  confidence: number;
  reason: string;
}

/** Resultado de uma inferência semântica. */
export interface SemanticInferenceEntry {
  /** ID único (correlation_id do fluxo). */
  id: string;
  /** Texto analisado. */
  contextText: string;
  /** Intenção detectada ("show_reference" | "none" | ""). */
  intent: string;
  /** Candidatos gerados pelo LLM. */
  candidates: SemanticCandidateEntry[];
  /** Tempo de inferência em ms. */
  inferenceMs: number;
  /** Provider usado ("local-llm", "stub", etc.). */
  provider: string;
  /** Modelo usado. */
  model: string;
  /** True se veio do cache. */
  cached: boolean;
  /** Erro (vazio se sucesso). */
  error: string;
  /** Hash do contexto. */
  contextHash: string;
  /** Timestamp. */
  timestamp: number;
}

/** Resultado da resolução (ReferenceResolver). */
export interface SemanticResolutionEntry {
  /** ID único (correlation_id do fluxo). */
  id: string;
  /** True se ReferenceDetected foi publicado. */
  resolved: boolean;
  /** Livro escolhido. */
  chosenBook: string;
  /** Capítulo escolhido. */
  chosenChapter: number;
  /** Versículo escolhido. */
  chosenVerse: number;
  /** Confiança do escolhido. */
  chosenConfidence: number;
  /** Motivo da decisão. */
  reason: string;
  /** Candidatos recebidos. */
  numCandidatesIn: number;
  /** Candidatos válidos após Searcher. */
  numCandidatesValid: number;
  /** True se parser já havia resolvido. */
  skippedDueToParser: boolean;
  /** Timestamp. */
  timestamp: number;
}

export interface SemanticState {
  /** Última inferência (ou null). */
  currentInference: SemanticInferenceEntry | null;
  /** Última resolução (ou null). */
  currentResolution: SemanticResolutionEntry | null;
  /** Histórico de inferências (mais recente primeiro, máx 30). */
  inferenceHistory: SemanticInferenceEntry[];
  /** Histórico de resoluções (mais recente primeiro, máx 30). */
  resolutionHistory: SemanticResolutionEntry[];
}

export type SemanticStore = DomainStore<SemanticState>;
export function createSemanticStore(): SemanticStore {
  return wrap(createSnapshotStore<SemanticState>());
}

// ============================================================
// SermonStore (Sprint 21) — memória contínua da pregação.
// Mostra o SermonContext vivo (livro, capítulo, tema, entidades,
// referências recentes) e eventos de mudança.
// ============================================================

/** Entidade reconhecida no sermão. */
export interface SermonEntityEntry {
  name: string;
  weight: number;
  mentionCount: number;
  firstSeen: string;
  lastSeen: string;
}

/** Tema provável do sermão. */
export interface SermonTopicEntry {
  name: string;
  weight: number;
  mentionCount: number;
  firstSeen: string;
  lastSeen: string;
}

/** Referência bíblica histórica. */
export interface SermonReferenceEntry {
  book: string;
  chapter: number;
  verse: number;
  referenceStr: string;
  detectedAt: string;
  source: string;
}

/** Snapshot do SermonContext. */
export interface SermonContextEntry {
  currentBook: string | null;
  currentChapter: number | null;
  probableTheme: string | null;
  entities: SermonEntityEntry[];
  recentTopics: SermonTopicEntry[];
  recentReferences: SermonReferenceEntry[];
  confidence: number;
  updatedAt: string;
  sermonStartedAt: string;
  totalUpdates: number;
  isEmpty: boolean;
}

/** Evento de mudança (livro/capítulo/tema). */
export interface SermonChangeEvent {
  type: "book" | "chapter" | "topic";
  previous: string;
  next: string;
  timestamp: number;
}

export interface SermonState {
  /** Contexto atual (ou null). */
  current: SermonContextEntry | null;
  /** Histórico de mudanças (mais recente primeiro, máx 30). */
  changes: SermonChangeEvent[];
  /** Métricas operacionais. */
  metrics: {
    totalUpdates: number;
    updatesPerMinute: number;
    bookChanges: number;
    chapterChanges: number;
    topicChanges: number;
    entityExpirations: number;
    topicExpirations: number;
    referenceExpirations: number;
    uptimeSeconds: number;
    contextAgeSeconds: number;
    sermonDurationSeconds: number;
    confidence: number;
  } | null;
}

export type SermonStore = DomainStore<SermonState>;
export function createSermonStore(): SermonStore {
  return wrap(createSnapshotStore<SermonState>());
}

// ============================================================
// Registry — agregador de todos os stores.
// ============================================================

export interface StoreRegistry {
  readonly pipeline: PipelineStore;
  readonly health: HealthStore;
  readonly metrics: MetricsStore;
  readonly session: SessionStore;
  readonly configuration: ConfigurationStore;
  readonly diagnostics: DiagnosticsStore;
  readonly logs: LogStore;
  readonly replay: ReplayStore;
  readonly events: EventStore;
  readonly audio: AudioStore;
  readonly system: SystemStore;
  readonly info: InfoStore;
  readonly transcript: TranscriptStore;
  readonly reference: ReferenceStore;
  readonly versePresentation: VersePresentationStore;
  readonly semantic: SemanticStore;
  readonly sermon: SermonStore;
}

export function createStoreRegistry(): StoreRegistry {
  return {
    pipeline: createPipelineStore(),
    health: createHealthStore(),
    metrics: createMetricsStore(),
    session: createSessionStore(),
    configuration: createConfigurationStore(),
    diagnostics: createDiagnosticsStore(),
    logs: createLogStore(),
    replay: createReplayStore(),
    events: createEventStore(),
    audio: createAudioStore(),
    system: createSystemStore(),
    info: createInfoStore(),
    transcript: createTranscriptStore(),
    reference: createReferenceStore(),
    versePresentation: createVersePresentationStore(),
    semantic: createSemanticStore(),
    sermon: createSermonStore(),
  };
}
