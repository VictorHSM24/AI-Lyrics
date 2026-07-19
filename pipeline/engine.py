"""StreamingPipelineEngine — orquestra o Pipeline.

Responsabilidade única:
  - start(): inicia pipeline (publica PipelineStarted)
  - stop(): para pipeline (publica PipelineStopped)
  - pause(): pausa pipeline (publica PipelinePaused)
  - resume(): retoma pipeline (publica PipelineResumed)
  - process(segment): processa um segmento (publica SpeechSegmentReceived)

Nenhuma regra de negócio. Nenhuma decisão. Apenas orquestra.

O Engine não conhece Handlers diretamente — apenas publica eventos.
Os Handlers (registrados via Coordinator) reagem aos eventos.

Tudo síncrono. Sem threads, asyncio, multiprocessing.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    PipelinePaused,
    PipelineResumed,
    PipelineStarted,
    PipelineStopped,
    SpeechSegmentReceived,
)
from pipeline.metadata import (
    EventMetadata,
    _default_correlation_id_generator,
    _default_event_id_generator,
    _default_session_id_generator,
)
from pipeline.metrics import PipelineMetrics
from pipeline.policy import PipelinePolicy
from pipeline.session import PipelineSession
from pipeline.state import PipelineState


class StreamingPipelineEngine:
    """Engine do Pipeline de streaming.

    Orquestra o ciclo de vida e o processamento de segmentos.
    Não implementa regra de negócio.
    """

    def __init__(
        self,
        bus: PipelineEventBus,
        policy: PipelinePolicy | None = None,
        session: PipelineSession | None = None,
        state: PipelineState | None = None,
        metrics: PipelineMetrics | None = None,
        session_id: str | None = None,
        event_id_generator: Callable[[], str] | None = None,
        correlation_id_generator: Callable[[], str] | None = None,
    ) -> None:
        self._bus = bus
        self._policy = policy or PipelinePolicy()
        self._session_id = session_id or (
            session.session_id if session else _default_session_id_generator()
        )
        self._session = session or PipelineSession.create(
            session_id=self._session_id)
        self._state = state or PipelineState()
        self._metrics = metrics or PipelineMetrics()
        self._event_id_gen = event_id_generator or _default_event_id_generator
        self._corr_id_gen = correlation_id_generator or _default_correlation_id_generator

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def bus(self) -> PipelineEventBus:
        return self._bus

    @property
    def policy(self) -> PipelinePolicy:
        return self._policy

    @property
    def session(self) -> PipelineSession:
        return self._session

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def metrics(self) -> PipelineMetrics:
        return self._metrics

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def is_running(self) -> bool:
        return self._state.running

    @property
    def is_paused(self) -> bool:
        return self._state.paused

    @property
    def is_active(self) -> bool:
        return self._state.is_active

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inicia o pipeline."""
        if self._state.running:
            return  # Já rodando — idempotente
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="StreamingPipelineEngine",
            event_id_generator=self._event_id_gen,
            correlation_id_generator=self._corr_id_gen,
        )
        self._bus.publish(PipelineStarted(meta=meta))
        self._state = self._state.with_running(True).with_last_event(
            "PipelineStarted", meta.timestamp)
        self._metrics.started_at = time.time()

    def stop(self, reason: str = "") -> None:
        """Para o pipeline."""
        if not self._state.running:
            return  # Já parado — idempotente
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="StreamingPipelineEngine",
            event_id_generator=self._event_id_gen,
            correlation_id_generator=self._corr_id_gen,
        )
        self._bus.publish(PipelineStopped(meta=meta, reason=reason))
        self._session = self._session.with_ended(meta.timestamp)
        self._state = self._state.with_running(False).with_last_event(
            "PipelineStopped", meta.timestamp)

    def pause(self, reason: str = "") -> None:
        """Pausa o pipeline."""
        if not self._state.running or self._state.paused:
            return
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="StreamingPipelineEngine",
            event_id_generator=self._event_id_gen,
            correlation_id_generator=self._corr_id_gen,
        )
        self._bus.publish(PipelinePaused(meta=meta, reason=reason))
        self._state = self._state.with_paused(True).with_last_event(
            "PipelinePaused", meta.timestamp)

    def resume(self, reason: str = "") -> None:
        """Retoma o pipeline pausado."""
        if not self._state.paused:
            return
        meta = EventMetadata.for_session_event(
            session_id=self._session_id,
            origin="StreamingPipelineEngine",
            event_id_generator=self._event_id_gen,
            correlation_id_generator=self._corr_id_gen,
        )
        self._bus.publish(PipelineResumed(meta=meta, reason=reason))
        self._state = self._state.with_paused(False).with_last_event(
            "PipelineResumed", meta.timestamp)

    # ------------------------------------------------------------------
    # Processamento
    # ------------------------------------------------------------------

    def process(
        self,
        audio: bytes = b"",
        start_time: float = 0.0,
        end_time: float = 0.0,
        duration_ms: int = 0,
        chunk_count: int = 1,
        text: str = "",  # Para teste (sem STT)
        confidence: float = 0.0,
    ) -> str:
        """Processa um segmento de fala.

        Publica SpeechSegmentReceived (que dispara o fluxo via EventBus).
        Retorna o correlation_id do fluxo iniciado.

        Se o pipeline não está ativo, descarta o segmento e registra
        métrica de descarte.

        Args:
            audio: bytes do áudio (opcional para teste).
            start_time: timestamp de início do segmento.
            end_time: timestamp de fim do segmento.
            duration_ms: duração em milissegundos.
            chunk_count: número de chunks.
            text: texto direto (para teste sem STT).
            confidence: confiança direta (para teste sem STT).

        Returns:
            correlation_id do fluxo, ou "" se descartado.
        """
        # Validar estado
        if not self._state.is_active:
            self._metrics.record_segment_dropped()
            return ""

        # Validar duração
        if duration_ms > 0 and not self._policy.is_segment_valid(duration_ms):
            self._metrics.record_segment_dropped()
            return ""

        # Criar EventMetadata inicial (novo correlation_id)
        extra_metadata = ()
        if text:
            extra_metadata = (("text", text), ("confidence", str(confidence)))

        meta = EventMetadata.for_initial(
            session_id=self._session_id,
            origin="StreamingPipelineEngine",
            event_id_generator=self._event_id_gen,
            correlation_id_generator=self._corr_id_gen,
            metadata=extra_metadata,
        )

        # Atualizar estado
        self._state = self._state.with_current_segment(meta.event_id).with_last_event(
            "SpeechSegmentReceived", meta.timestamp)

        # Registrar métricas
        self._metrics.record_segment_received()
        self._metrics.record_correlation()

        # Atualizar sessão
        self._session = self._session.with_segment_processed(meta.correlation_id)

        # Publicar SpeechSegmentReceived (dispara o fluxo)
        self._bus.publish(SpeechSegmentReceived(
            meta=meta,
            audio=audio,
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            chunk_count=chunk_count,
        ))

        return meta.correlation_id

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reseta o engine para estado inicial (não publica eventos)."""
        self._state = PipelineState()
        self._metrics.reset()
        self._session = PipelineSession.create(session_id=self._session_id)


__all__ = [
    "StreamingPipelineEngine",
]
