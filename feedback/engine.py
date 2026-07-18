"""Engine de Feedback Learning.

Responsabilidade única:
  - Receber um FeedbackEvent e atualizar FeedbackStatistics.
  - Aplicar LearningPolicy (pesos e decaimento).
  - Persistir via FeedbackRepository.

Nunca conversa diretamente com:
  - Searcher
  - Ranking
  - Holyrics
  - Parser
  - LLM
  - Embeddings
  - KnowledgeBase
  - Context Engine

O Engine apenas atualiza estatísticas. O ponto de integração com o
restante do sistema é o RankingFeedbackAdapter.

Design:
  - process(event) → atualiza repository.
  - get_statistics(key) → FeedbackStatistics | None.
  - get_summary(key) → FeedbackSummary (para explicabilidade).
  - increment_decay(key) → incrementa contador de decaimento.
  - apply_all_decay() → aplica decaimento a todas as chaves.
  - reset() → limpa todas as estatísticas.

Imutabilidade:
  - FeedbackStatistics é imutável. Atualizações criam nova instância.
  - O Engine mantém estado (repository), mas as estatísticas são imutáveis.
"""

from __future__ import annotations

import time
from dataclasses import replace

from feedback.dtos import (
    FeedbackKey,
    FeedbackStatistics,
    FeedbackSummary,
)
from feedback.events import (
    CandidateAccepted,
    CandidateRejected,
    FeedbackEvent,
    ManualReferenceSelected,
    ManualSearch,
    SuggestionIgnored,
)
from feedback.policy import LearningPolicy
from feedback.repository import FeedbackRepository


class FeedbackEngine:
    """Engine que processa eventos de feedback e atualiza estatísticas.

    Uso:
        engine = FeedbackEngine(repository)
        engine.process(CandidateAccepted(key=..., timestamp=...))
        stats = engine.get_statistics(key)
        summary = engine.get_summary(key)

    Desacoplamento:
        - Não conhece Searcher, Ranking, Holyrics, Parser, LLM,
          Embeddings, KnowledgeBase, Context Engine.
        - Apenas atualiza estatísticas via repository.
    """

    def __init__(
        self,
        repository: FeedbackRepository,
        policy: LearningPolicy | None = None,
        clock: callable = time.time,
    ) -> None:
        """Inicializa engine.

        Args:
            repository: repository de persistência.
            policy: política de pesos (se None, usa default).
            clock: função que retorna timestamp (para testes).
        """
        self._repo = repository
        self._policy = policy or LearningPolicy()
        self._clock = clock

    @property
    def policy(self) -> LearningPolicy:
        """Política de pesos."""
        return self._policy

    @property
    def repository(self) -> FeedbackRepository:
        """Repository de persistência."""
        return self._repo

    # ------------------------------------------------------------------
    # Processamento de eventos
    # ------------------------------------------------------------------

    def process(self, event: FeedbackEvent) -> FeedbackStatistics:
        """Processa um evento e atualiza estatísticas.

        Args:
            event: evento tipado (CandidateAccepted, etc.).

        Returns:
            FeedbackStatistics atualizada para a chave do evento.
        """
        key = event.key
        weight = self._policy.weight_for(event)
        event_type = self._policy.event_type_name(event)
        timestamp = event.timestamp if event.timestamp > 0 else self._clock()

        # Recuperar estatísticas atuais (ou criar vazias)
        current = self._repo.get(key)
        if current is None:
            current = FeedbackStatistics(
                key=key,
                first_used=timestamp,
                last_used=timestamp,
            )

        # Atualizar contadores por tipo
        counter_changes = {}
        if isinstance(event, CandidateAccepted):
            counter_changes["acceptances"] = current.acceptances + 1
        elif isinstance(event, CandidateRejected):
            counter_changes["rejections"] = current.rejections + 1
        elif isinstance(event, ManualReferenceSelected):
            counter_changes["manual_selections"] = current.manual_selections + 1
        elif isinstance(event, SuggestionIgnored):
            counter_changes["ignored"] = current.ignored + 1
        elif isinstance(event, ManualSearch):
            # ManualSearch não incrementa contador específico
            # (apenas registra o evento)
            pass

        # Calcular novo peso acumulado (com decaimento aplicado ao peso atual)
        decayed_current_weight = self._policy.apply_decay(
            current.total_weight, current.decay_count
        )
        new_total_weight = decayed_current_weight + weight

        # Criar nova estatística (imutável)
        new_stats = replace(
            current,
            last_used=timestamp,
            total_weight=new_total_weight,
            **counter_changes,
        )

        # Persistir
        self._repo.save(new_stats)
        return new_stats

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def get_statistics(self, key: FeedbackKey) -> FeedbackStatistics | None:
        """Recupera estatísticas para uma chave."""
        return self._repo.get(key)

    def get_summary(self, key: FeedbackKey) -> FeedbackSummary:
        """Recupera resumo para explicabilidade.

        Retorna FeedbackSummary com has_feedback=False se não há
        estatísticas para a chave.

        Args:
            key: FeedbackKey.

        Returns:
            FeedbackSummary.
        """
        stats = self._repo.get(key)
        if stats is None:
            return FeedbackSummary(
                key=key,
                total_events=0,
                total_weight=0.0,
                acceptances=0,
                rejections=0,
                manual_selections=0,
                ignored=0,
                decay_count=0,
                last_used=0.0,
                has_feedback=False,
            )
        return FeedbackSummary(
            key=key,
            total_events=stats.total_events,
            total_weight=stats.total_weight,
            acceptances=stats.acceptances,
            rejections=stats.rejections,
            manual_selections=stats.manual_selections,
            ignored=stats.ignored,
            decay_count=stats.decay_count,
            last_used=stats.last_used,
            has_feedback=True,
        )

    # ------------------------------------------------------------------
    # Decaimento
    # ------------------------------------------------------------------

    def increment_decay(self, key: FeedbackKey) -> FeedbackStatistics | None:
        """Incrementa contador de decaimento para uma chave.

        Chamado quando uma busca é feita sem que o candidato seja
        reutilizado (indicando que a preferência está envelhecendo).

        Args:
            key: FeedbackKey.

        Returns:
            FeedbackStatistics atualizada, ou None se não existe.
        """
        stats = self._repo.get(key)
        if stats is None:
            return None
        new_stats = replace(stats, decay_count=stats.decay_count + 1)
        self._repo.save(new_stats)
        return new_stats

    def apply_all_decay(self) -> int:
        """Aplica decaimento a todas as estatísticas.

        Recalcula total_weight com base no decay_count atual.

        Returns:
            Número de estatísticas atualizadas.
        """
        count = 0
        for stats in self._repo.list_all():
            decayed_weight = self._policy.apply_decay(
                stats.total_weight, stats.decay_count
            )
            if decayed_weight != stats.total_weight:
                new_stats = replace(stats, total_weight=decayed_weight)
                self._repo.save(new_stats)
                count += 1
        return count

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Limpa todas as estatísticas."""
        self._repo.clear()

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Persiste em disco (delegado ao repository)."""
        self._repo.flush()


__all__ = ["FeedbackEngine"]
