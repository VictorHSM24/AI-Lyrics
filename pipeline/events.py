"""Eventos tipados do Pipeline (Fase 12).

Todos os eventos são frozen dataclass, imutáveis, hashable, serializáveis.
Cada evento carrega exatamente um EventMetadata (rastreabilidade).

Nenhum evento duplica campos de EventMetadata.

Fluxo principal:
    SpeechSegmentReceived
        ↓
    SpeechRecognized
        ↓
    SearchRequested
        ↓
    SearchCompleted
        ↓
    RankingCompleted
        ↓
    IntelligenceCompleted
        ↓
    PresentationRequested
        ↓
    PresentationCompleted
        ↓
    FeedbackRecorded
        ↓
    EvaluationRecorded

Eventos de ciclo de vida:
    PipelineStarted, PipelineStopped, PipelinePaused, PipelineResumed

Evento de erro:
    PipelineError

Design:
  - Cada evento carrega apenas os dados específicos da sua etapa.
  - EventMetadata é sempre o primeiro campo (chamado `meta`).
  - Nenhum evento chama outro handler diretamente.
  - Novos eventos podem ser adicionados sem quebrar existentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.metadata import EventMetadata


# ---------------------------------------------------------------------------
# Base comum
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineEvent:
    """Base comum para todos os eventos do Pipeline.

    Todo evento tem um campo `meta: EventMetadata` que carrega
    rastreabilidade. Subclasses adicionam apenas dados específicos.

    Sprint 17.2 — Event Stream Optimization:
    A propriedade `category` distingue OperationalEvent de TelemetryEvent.
    O EventBus armazena apenas OperationalEvents no EventStore.
    TelemetryEvents são dispatchados aos handlers mas não persistidos.
    """

    meta: EventMetadata

    @property
    def event_type(self) -> str:
        """Nome do tipo do evento (string identificadora)."""
        return self.__class__.__name__

    @property
    def event_id(self) -> str:
        return self.meta.event_id

    @property
    def correlation_id(self) -> str:
        return self.meta.correlation_id

    @property
    def causation_id(self) -> str | None:
        return self.meta.causation_id

    @property
    def session_id(self) -> str:
        return self.meta.session_id

    @property
    def timestamp(self) -> float:
        return self.meta.timestamp

    @property
    def origin(self) -> str:
        return self.meta.origin

    @property
    def category(self) -> str:
        """Categoria do evento: 'operational' ou 'telemetry'.

        Operational: eventos de negócio que aparecem na Timeline e
        são persistidos no EventStore.

        Telemetry: eventos de alta frequência (audio.level, cpu.usage,
        etc.) que NÃO são persistidos nem exibidos na Timeline.
        """
        if isinstance(self, TelemetryEvent):
            return "telemetry"
        return "operational"

    def to_dict(self) -> dict:
        """Serializa o evento para dict (inclui meta e campos específicos)."""
        result = {
            "event_type": self.event_type,
            "meta": self.meta.to_dict(),
        }
        # Adicionar campos específicos da subclasse (não-meta)
        for f in self.__dataclass_fields__:
            if f == "meta":
                continue
            val = getattr(self, f)
            if hasattr(val, "to_dict"):
                result[f] = val.to_dict()
            elif isinstance(val, (list, tuple)):
                result[f] = [
                    v.to_dict() if hasattr(v, "to_dict") else v for v in val
                ]
            else:
                result[f] = val
        return result


# ---------------------------------------------------------------------------
# Sprint 17.2 — Categorias de evento (Operational vs Telemetry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OperationalEvent(PipelineEvent):
    """Evento operacional — representa um acontecimento de negócio.

    Examples: PipelineStarted, SpeechTranscribed, ReferenceDetected.

    Características:
      - Vai para o EventBus e EventStore.
      - Aparece na Timeline.
      - Pode ser persistido e gerar histórico.
    """

    pass


@dataclass(frozen=True)
class TelemetryEvent(PipelineEvent):
    """Evento de telemetria — atualização contínua de métricas.

    Examples: AudioLevel, CpuUsage, GpuUsage, LatencyUpdate.

    Características:
      - NÃO é persistido no EventStore.
      - NÃO aparece na Timeline.
      - Atualiza apenas componentes visuais específicos (VU Meter, gráficos).
      - É transmitido via WebSocket normalmente.
    """

    pass


# ---------------------------------------------------------------------------
# Eventos do fluxo principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechSegmentReceived(OperationalEvent):
    """Segmento de fala recebido do STT/captura.

    Inicia um novo correlation_id. Este é o ponto de entrada do fluxo.
    """

    audio: bytes = b""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: int = 0
    chunk_count: int = 1


@dataclass(frozen=True)
class SpeechRecognized(OperationalEvent):
    """Texto reconhecido do segmento de fala."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    processing_ms: int = 0


@dataclass(frozen=True)
class SearchRequested(OperationalEvent):
    """Pedido de busca emitido (texto reconhecido → query)."""

    query: str = ""
    intent_action: str = ""
    intent_book: str | None = None
    intent_chapter: int | None = None
    intent_verse: int | None = None


@dataclass(frozen=True)
class SearchCompleted(OperationalEvent):
    """Busca completada com resultados."""

    query: str = ""
    results: tuple = field(default_factory=tuple)  # tuple de SearchResult
    result_count: int = 0
    search_ms: int = 0


@dataclass(frozen=True)
class RankingCompleted(OperationalEvent):
    """Ranking dos resultados completado."""

    query: str = ""
    ranked_candidates: tuple = field(default_factory=tuple)  # tuple de CandidateInfo
    candidate_count: int = 0


@dataclass(frozen=True)
class IntelligenceCompleted(OperationalEvent):
    """Sermon Intelligence produziu recomendação."""

    query: str = ""
    recommendation: Any = None  # IntelligenceRecommendation
    best_candidate_id: str = ""
    confidence_level: str = ""


@dataclass(frozen=True)
class PresentationRequested(OperationalEvent):
    """Pedido de apresentação enviado ao Holyrics."""

    candidate_id: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int | None = None
    version: str = "ACF"


@dataclass(frozen=True)
class PresentationCompleted(OperationalEvent):
    """Apresentação executada no Holyrics."""

    candidate_id: str = ""
    status: str = ""
    verse_id: str = ""
    presented: bool = False


@dataclass(frozen=True)
class FeedbackRecorded(OperationalEvent):
    """Feedback registrado no Feedback Learning."""

    candidate_id: str = ""
    feedback_type: str = ""  # "accepted" | "rejected"
    scope: str = "GLOBAL"
    query: str = ""


@dataclass(frozen=True)
class EvaluationRecorded(OperationalEvent):
    """Métrica registrada no Continuous Evaluation."""

    query: str = ""
    classification: str = ""
    candidate_id: str = ""
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Eventos de ciclo de vida do Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineStarted(OperationalEvent):
    """Pipeline iniciado."""

    pass


@dataclass(frozen=True)
class PipelineStopped(OperationalEvent):
    """Pipeline parado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelinePaused(OperationalEvent):
    """Pipeline pausado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineResumed(OperationalEvent):
    """Pipeline retomado."""

    reason: str = ""


@dataclass(frozen=True)
class PipelineError(OperationalEvent):
    """Erro durante processamento do Pipeline.

    Não interrompe o Pipeline (erro é tratado pelo handler/engine).
    Carrega informações para diagnóstico.
    """

    error_type: str = ""
    error_message: str = ""
    handler_name: str = ""
    recoverable: bool = True


# ---------------------------------------------------------------------------
# Sprint 16 — Eventos do Continuous Speech Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechStarted(OperationalEvent):
    """VAD detectou início de fala.

    Emitido quando o VAD transiciona de silêncio para fala.
    Inicia um novo correlation_id para o segmento.
    """

    timestamp_start: float = 0.0


@dataclass(frozen=True)
class SpeechEnded(OperationalEvent):
    """VAD detectou fim da fala.

    Emitido quando o silêncio após fala excede max_silence_ms.
    """

    timestamp_end: float = 0.0
    duration_ms: int = 0


@dataclass(frozen=True)
class SpeechSegmentCreated(OperationalEvent):
    """SpeechSegment criado e enfileirado para transcrição.

    Contém metadados do segmento (sem o áudio raw — apenas duração e timestamps).
    """

    duration_ms: int = 0
    chunk_count: int = 0
    sample_rate: int = 16000
    channels: int = 1


@dataclass(frozen=True)
class SpeechTranscribing(OperationalEvent):
    """SpeechWorker começou a transcrever o segmento."""

    duration_ms: int = 0


@dataclass(frozen=True)
class SpeechTranscribed(OperationalEvent):
    """Transcrição completada com texto reconhecido."""

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    latency_ms: int = 0
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Sprint 17 — Biblical Intent & Reference Extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceDetected(OperationalEvent):
    """Referência bíblica detectada e validada pelo parser determinístico.

    Emitido quando o BiblicalNLUService processa um SpeechTranscribed e
    o Parser identifica uma referência válida (action="show").
    """

    intent: str = "OPEN_REFERENCE"
    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    confidence: float = 0.0
    raw_text: str = ""
    normalized_text: str = ""


@dataclass(frozen=True)
class ReferenceInvalid(OperationalEvent):
    """Referência bíblica inválida detectada pelo parser.

    Emitido quando o Parser encontra um livro mas capítulo/versículo
    são inválidos (ex.: "João capítulo 300", "Mateus capítulo zero").
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    reason: str = ""  # "invalid_chapter", "invalid_verse", "zero_chapter"
    raw_text: str = ""


@dataclass(frozen=True)
class IntentUnknown(OperationalEvent):
    """Intenção não reconhecida pelo parser.

    Emitido quando o Parser não identifica nem referência nem navegação
    nem gatilhos bíblicos (action="none"). O texto transcrito não é
    um comando bíblico.
    """

    raw_text: str = ""
    reason: str = ""  # "no_book", "no_pattern", "empty_text"


# ---------------------------------------------------------------------------
# Sprint 18 — Automatic Verse Presentation
#
# Fluxo:
#   ReferenceDetected
#       ↓
#   VerseResolving        (VersePresentationService iniciou busca no Searcher)
#       ↓
#   VerseResolved         (Searcher retornou SearchResult com texto)
#       ↓
#   VersePresented        (HolyricsClient.show_verse() executou com sucesso)
#
# Em caso de erro em qualquer etapa após ReferenceDetected:
#   VersePresentationFailed (motivo detalhado, sem alterar Health)
#
# Todos derivados de OperationalEvent — aparecem na Timeline e são
# persistidos no EventStore. NÃO são telemetria.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerseResolving(OperationalEvent):
    """VersePresentationService iniciou resolução da referência no Searcher.

    Emitido quando o serviço recebe ReferenceDetected e começa a buscar
    o versículo na base bíblica.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    normalized_text: str = ""


@dataclass(frozen=True)
class VerseResolved(OperationalEvent):
    """Searcher retornou o versículo resolvido.

    Emitido quando Searcher.search_by_reference() encontra o versículo
    com texto e versão. Próxima etapa: chamar HolyricsClient.show_verse().
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    version: str = ""
    verse_text: str = ""
    reference: str = ""
    search_ms: int = 0


@dataclass(frozen=True)
class VersePresented(OperationalEvent):
    """HolyricsClient.show_verse() executou com sucesso.

    Emitido após o Holyrics confirmar a apresentação do versículo.
    Carrega a latência total (ReferenceDetected → ShowVerse) e a
    latência específica da chamada ao Holyrics.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    version: str = ""
    reference: str = ""
    quick_presentation: bool = False
    holyrics_status: str = ""
    holyrics_latency_ms: int = 0
    total_latency_ms: int = 0


@dataclass(frozen=True)
class VersePresentationFailed(OperationalEvent):
    """Falha em qualquer etapa da apresentação do versículo.

    Emitido quando:
    - Searcher não encontra o versículo (book_not_found, verse_not_found).
    - HolyricsClient levanta exceção (connection, timeout, auth, api).
    - Qualquer erro inesperado no VersePresentationService.

    NÃO altera o Health do componente Holyrics — falhas pontuais de
    apresentação não significam que o Holyrics está indisponível.
    Health só muda via health_check periódico do HealthService.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse: int = 0
    reference: str = ""
    failure_stage: str = ""  # "search" | "holyrics" | "internal"
    error_type: str = ""     # "book_not_found", "verse_not_found",
                             # "connection", "timeout", "auth", "api",
                             # "internal_error"
    error_message: str = ""
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Sprint 19 — Streaming Speech Pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpeechPartial(OperationalEvent):
    """Transcrição parcial de streaming (Sprint 19).

    Emitido pelo StreamingSTTService quando uma janela de áudio é
    transcrita pela primeira vez (sem texto anterior para comparar).
    Contém o texto parcial reconhecido até o momento.

    Diferente de SpeechTranscribed, este evento:
      - É produzido continuamente (a cada ~400ms).
      - Pode ser atualizado por SpeechPartialUpdated.
      - Representa transcrição em andamento, não final.
      - correlation_id é compartilhado entre todos os SpeechPartial /
        SpeechPartialUpdated do mesmo fluxo contínuo de fala.
    """

    text: str = ""
    language: str = ""
    confidence: float = 0.0
    latency_ms: int = 0          # latência captura → partial
    audio_duration_ms: int = 0   # duração da janela transcrita
    is_stable: bool = False      # True se o texto não deve mudar mais


@dataclass(frozen=True)
class SpeechPartialUpdated(OperationalEvent):
    """Atualização de transcrição parcial de streaming (Sprint 19).

    Emitido pelo StreamingSTTService quando uma nova janela é
    transcrita e o resultado difere do SpeechPartial anterior.
    Contém apenas o texto novo (diff por alinhamento de prefixo).

    O campo ``text`` contém o texto completo atualizado (não apenas
    o diff) para simplificar o consumo no frontend. O campo
    ``appended_text`` contém apenas o trecho novo adicionado desde
    o último SpeechPartial / SpeechPartialUpdated.

    correlation_id é o mesmo do SpeechPartial inicial do fluxo.
    """

    text: str = ""               # texto completo atualizado
    appended_text: str = ""      # apenas o trecho novo (diff)
    language: str = ""
    confidence: float = 0.0
    latency_ms: int = 0
    audio_duration_ms: int = 0
    is_stable: bool = False


@dataclass(frozen=True)
class ReferenceCandidate(OperationalEvent):
    """Candidato a referência bíblica detectada incrementalmente (Sprint 19).

    Emitido pelo IncrementalBiblicalParser quando consome SpeechPartial
    ou SpeechPartialUpdated e identifica parcialmente uma referência
    (ex.: apenas o livro, ou livro + capítulo, mas não o versículo).

    A confiança cresce conforme mais componentes são identificados:
      - Apenas livro: confidence ~ 0.40
      - Livro + capítulo: confidence ~ 0.75
      - Livro + capítulo + versículo: confidence ~ 0.98

    Quando confidence atinge o threshold (default 0.90), o
    IncrementalBiblicalParser publica ReferenceDetected (evento
    definitivo) em vez de ReferenceCandidate.

    correlation_id é o mesmo do SpeechPartial que originou a detecção.
    """

    book: str = ""
    book_id: int = 0
    chapter: int = 0
    verse_start: int = 0
    verse_end: int = 0
    confidence: float = 0.0
    completeness: str = ""  # "book" | "chapter" | "verse"
    normalized_text: str = ""


# ---------------------------------------------------------------------------
# Sprint 20 — Semantic Understanding Engine
#
# Fluxo paralelo ao parser determinístico:
#   SpeechPartial / SpeechPartialUpdated
#       ↓
#   SemanticEngine (consome SpeechPartial/Updated)
#       ↓
#   IntentCandidate (hipóteses do LLM, NUNCA definitivo)
#       ↓
#   ReferenceResolver (valida via Searcher, elimina inexistentes)
#       ↓
#   ReferenceDetected (publicado apenas pelo Resolver — LLM nunca publica)
#
# O parser determinístico (IncrementalBiblicalParser) continua sendo o
# caminho principal. A camada semântica atua em paralelo quando o parser
# não consegue resolver referências implícitas.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IntentCandidate(OperationalEvent):
    """Candidatos semânticos gerados pelo SemanticEngine (Sprint 20).

    Emitido pelo SemanticEngine quando consome SpeechPartial/Updated e
    o SemanticProvider (LLM) identifica possíveis referências implícitas.

    NÃO é definitivo — é uma hipótese. O ReferenceResolver valida cada
    candidato via Searcher antes de publicar ReferenceDetected.

    O LLM NUNCA publica ReferenceDetected diretamente. Apenas o
    ReferenceResolver pode fazer isso.

    correlation_id é o mesmo do SpeechPartial que originou a análise.
    """

    intent: str = "show_reference"  # "show_reference" | "none"
    candidates_json: str = ""       # JSON serializado de SemanticCandidate[]
    inference_ms: int = 0           # tempo de inferência do LLM
    provider: str = ""              # "local-llm", "stub", "openai", etc.
    model: str = ""                 # "llama3.2:3b", etc.
    context_hash: str = ""          # hash do contexto (para dedup de cache)
    cached: bool = False            # True se veio do cache


@dataclass(frozen=True)
class SemanticInferenceCompleted(OperationalEvent):
    """Telemetria da inferência semântica (Sprint 20).

    Emitido após o SemanticEngine completar uma inferência (sucesso ou falha).
    Útil para o painel de depuração do frontend.
    """

    intent: str = ""
    num_candidates: int = 0
    inference_ms: int = 0
    provider: str = ""
    model: str = ""
    cached: bool = False
    error: str = ""                 # "" se sucesso, mensagem se falha
    context_text: str = ""          # texto analisado (para depuração)
    context_hash: str = ""


@dataclass(frozen=True)
class SemanticResolutionCompleted(OperationalEvent):
    """Resultado da resolução semântica (Sprint 20).

    Emitido pelo ReferenceResolver após validar candidatos e decidir
    se publica ou não ReferenceDetected.

    Útil para o painel de depuração: mostra qual candidato foi escolhido
    e por quê, ou por que nenhum foi escolhido.
    """

    resolved: bool = False          # True se ReferenceDetected foi publicado
    chosen_book: str = ""
    chosen_chapter: int = 0
    chosen_verse: int = 0
    chosen_confidence: float = 0.0
    reason: str = ""                # "highest_confidence", "all_invalid", "parser_already_resolved"
    num_candidates_in: int = 0      # candidatos recebidos
    num_candidates_valid: int = 0   # candidatos válidos após Searcher
    skipped_due_to_parser: bool = False  # True se parser já resolveu


# ---------------------------------------------------------------------------
# Sprint 21 — Sermon Memory Engine
#
# Fluxo paralelo ao parser e ao semantic engine:
#   SpeechPartial / SpeechPartialUpdated / ReferenceDetected
#       ↓
#   SermonMemoryEngine (atualiza estado incrementalmente)
#       ↓
#   SermonContextUpdated (publica o contexto vivo)
#       ↓
#   SemanticEngine (consome SermonContextUpdated para enriquecer contexto)
#
# Eventos de mudança (publicados quando campos mudam):
#   SermonBookChanged     — current_book mudou
#   SermonChapterChanged  — current_chapter mudou
#   SermonTopicChanged    — probable_theme mudou
#
# O SermonMemoryEngine NÃO identifica referências bíblicas.
# Sua única responsabilidade é manter o estado da pregação.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SermonContextUpdated(OperationalEvent):
    """Contexto do sermão atualizado (Sprint 21).

    Emitido pelo SermonMemoryEngine após cada atualização incremental
    do SermonContext. Contém um snapshot serializado do contexto vivo.

    O SemanticEngine consome este evento para enriquecer o contexto
    enviado ao SemanticProvider.
    """

    context_json: str = ""          # JSON serializado de SermonContext.to_dict()
    current_book: str = ""          # livro atual (vazio se None)
    current_chapter: int = 0        # capítulo atual (0 se None)
    probable_theme: str = ""        # tema provável (vazio se None)
    num_entities: int = 0           # número de entidades
    num_topics: int = 0             # número de temas
    num_references: int = 0         # número de referências recentes
    confidence: float = 0.0         # confiança geral
    total_updates: int = 0          # total de atualizações desde o início
    is_empty: bool = True           # True se contexto vazio


@dataclass(frozen=True)
class SermonBookChanged(OperationalEvent):
    """Livro atual do sermão mudou (Sprint 21).

    Emitido quando current_book muda (ex.: de "João" para "Romanos").
    """

    previous_book: str = ""
    new_book: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class SermonChapterChanged(OperationalEvent):
    """Capítulo atual do sermão mudou (Sprint 21).

    Emitido quando current_chapter muda dentro do mesmo livro.
    """

    book: str = ""
    previous_chapter: int = 0
    new_chapter: int = 0


@dataclass(frozen=True)
class SermonTopicChanged(OperationalEvent):
    """Tema provável do sermão mudou (Sprint 21).

    Emitido quando probable_theme muda significativamente.
    """

    previous_theme: str = ""
    new_theme: str = ""
    confidence: float = 0.0


@dataclass(frozen=True)
class SemanticProviderUnavailable(OperationalEvent):
    """Provider semântico indisponível (Sprint 21.1).

    Emitido quando o SemanticEngine não consegue validar o provider LLM
    (Ollama offline, modelo não instalado, etc.). O sistema continua
    operacional — apenas a camada semântica fica desativada.

    O IncrementalParser e o restante do pipeline NÃO são afetados.
    """

    provider: str = ""        # "ollama", "stub", etc.
    model: str = ""           # modelo esperado
    reason: str = ""          # "server_offline", "model_not_found", etc.
    base_url: str = ""        # URL consultada


# ---------------------------------------------------------------------------
# Registry de tipos de evento
# ---------------------------------------------------------------------------


_ALL_EVENT_TYPES = (
    SpeechSegmentReceived,
    SpeechRecognized,
    SearchRequested,
    SearchCompleted,
    RankingCompleted,
    IntelligenceCompleted,
    PresentationRequested,
    PresentationCompleted,
    FeedbackRecorded,
    EvaluationRecorded,
    PipelineStarted,
    PipelineStopped,
    PipelinePaused,
    PipelineResumed,
    PipelineError,
    # Sprint 16 — Continuous Speech Pipeline
    SpeechStarted,
    SpeechEnded,
    SpeechSegmentCreated,
    SpeechTranscribing,
    SpeechTranscribed,
    # Sprint 17 — Biblical Intent & Reference Extraction
    ReferenceDetected,
    ReferenceInvalid,
    IntentUnknown,
    # Sprint 18 — Automatic Verse Presentation
    VerseResolving,
    VerseResolved,
    VersePresented,
    VersePresentationFailed,
    # Sprint 19 — Streaming Speech Pipeline
    SpeechPartial,
    SpeechPartialUpdated,
    ReferenceCandidate,
    # Sprint 20 — Semantic Understanding Engine
    IntentCandidate,
    SemanticInferenceCompleted,
    SemanticResolutionCompleted,
    # Sprint 21 — Sermon Memory Engine
    SermonContextUpdated,
    SermonBookChanged,
    SermonChapterChanged,
    SermonTopicChanged,
    # Sprint 21.1 — Semantic provider health
    SemanticProviderUnavailable,
)

_ALL_EVENT_TYPE_NAMES = tuple(c.__name__ for c in _ALL_EVENT_TYPES)


def all_event_types() -> tuple:
    """Retorna todas as classes de evento do Pipeline."""
    return _ALL_EVENT_TYPES


def all_event_type_names() -> tuple:
    """Retorna os nomes de todos os tipos de evento."""
    return _ALL_EVENT_TYPE_NAMES


def is_pipeline_event(obj: Any) -> bool:
    """True se obj é uma instância de PipelineEvent."""
    return isinstance(obj, PipelineEvent)


def is_operational_event(obj: Any) -> bool:
    """True se obj é uma instância de OperationalEvent."""
    return isinstance(obj, OperationalEvent)


def is_telemetry_event(obj: Any) -> bool:
    """True se obj é uma instância de TelemetryEvent."""
    return isinstance(obj, TelemetryEvent)


__all__ = [
    "PipelineEvent",
    "OperationalEvent",
    "TelemetryEvent",
    "SpeechSegmentReceived",
    "SpeechRecognized",
    "SearchRequested",
    "SearchCompleted",
    "RankingCompleted",
    "IntelligenceCompleted",
    "PresentationRequested",
    "PresentationCompleted",
    "FeedbackRecorded",
    "EvaluationRecorded",
    "PipelineStarted",
    "PipelineStopped",
    "PipelinePaused",
    "PipelineResumed",
    "PipelineError",
    # Sprint 16 — Continuous Speech Pipeline
    "SpeechStarted",
    "SpeechEnded",
    "SpeechSegmentCreated",
    "SpeechTranscribing",
    "SpeechTranscribed",
    # Sprint 17 — Biblical Intent & Reference Extraction
    "ReferenceDetected",
    "ReferenceInvalid",
    "IntentUnknown",
    # Sprint 18 — Automatic Verse Presentation
    "VerseResolving",
    "VerseResolved",
    "VersePresented",
    "VersePresentationFailed",
    # Sprint 19 — Streaming Speech Pipeline
    "SpeechPartial",
    "SpeechPartialUpdated",
    "ReferenceCandidate",
    # Sprint 20 — Semantic Understanding Engine
    "IntentCandidate",
    "SemanticInferenceCompleted",
    "SemanticResolutionCompleted",
    # Sprint 21 — Sermon Memory Engine
    "SermonContextUpdated",
    "SermonBookChanged",
    "SermonChapterChanged",
    "SermonTopicChanged",
    "SemanticProviderUnavailable",
    "all_event_types",
    "all_event_type_names",
    "is_pipeline_event",
    "is_operational_event",
    "is_telemetry_event",
]
