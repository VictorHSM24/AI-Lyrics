"""semantic/resolver.py — ReferenceResolver (Sprint 20, Etapa 5).

Responsabilidade:
  - Assinar IntentCandidate (do SemanticEngine).
  - Validar cada candidato via Searcher (elimina inexistentes).
  - Verificar se o parser já resolveu esta correlation_id (dedup).
  - Escolher o candidato de maior confiança entre os válidos.
  - Publicar ReferenceDetected (ÚNICO componente além do parser que pode fazer isso).
  - Publicar SemanticResolutionCompleted (telemetria para o frontend).

Regras:
  - Se o parser já publicou ReferenceDetected para a mesma correlation_id,
    NÃO publica (parser vence — é determinístico e mais confiável).
  - Se nenhum candidato é válido (Searcher retorna None), não publica.
  - Se todos os candidatos têm confidence < threshold (default 0.50), não publica.
  - NUNCA consulta Holyrics, NUNCA acessa frontend.

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pipeline.events import (
    IntentCandidate,
    ReferenceDetected,
    SemanticResolutionCompleted,
)
from pipeline.metadata import EventMetadata
from semantic.types import SemanticCandidate

logger = logging.getLogger(__name__)

__all__ = ["ReferenceResolver"]


# Confiança mínima para considerar um candidato válido.
_DEFAULT_MIN_CONFIDENCE = 0.50


class ReferenceResolver:
    """Resolve candidatos semânticos em ReferenceDetected.

    Args:
        bus: EventBus para assinar/publicar eventos.
        searcher: Searcher para validar referências (busca/searcher.py).
        session_id: ID da sessão atual.
        min_confidence: confiança mínima para aceitar um candidato.
        enabled: se False, não processa nada (kill switch).
    """

    def __init__(
        self,
        bus: Any,
        searcher: Any,
        session_id: str,
        min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
        enabled: bool = True,
    ) -> None:
        self._bus = bus
        self._searcher = searcher
        self._session_id = session_id
        self._min_confidence = min_confidence
        self._enabled = enabled

        # Estatísticas.
        self._total_resolved = 0
        self._total_skipped_parser = 0
        self._total_skipped_invalid = 0
        self._total_skipped_low_conf = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Inscreve-se em IntentCandidate."""
        if not self._enabled:
            logger.info("ReferenceResolver: disabled, not subscribing")
            return
        self._bus.subscribe(IntentCandidate, self._on_intent_candidate)
        logger.info(
            "ReferenceResolver: started (min_confidence=%.2f)",
            self._min_confidence,
        )

    def stop(self) -> None:
        """Para o resolver."""
        try:
            self._bus.unsubscribe(IntentCandidate, self._on_intent_candidate)
        except Exception:
            pass
        logger.info("ReferenceResolver: stopped")

    # ------------------------------------------------------------------
    # Handler
    # ------------------------------------------------------------------

    def _on_intent_candidate(self, event: IntentCandidate) -> None:
        """Processa IntentCandidate: valida, escolhe, publica."""
        if not self._enabled:
            return

        # 1. Desserializar candidatos.
        candidates = self._deserialize_candidates(event.candidates_json)
        if not candidates:
            self._publish_resolution(
                event, resolved=False, reason="no_candidates",
                num_in=0, num_valid=0,
            )
            return

        # 2. Verificar se o parser já resolveu esta correlation_id.
        if self._parser_already_resolved(event.meta.correlation_id):
            self._total_skipped_parser += 1
            logger.debug(
                "ReferenceResolver: parser already resolved correlation_id=%s, skipping",
                event.meta.correlation_id,
            )
            self._publish_resolution(
                event, resolved=False, reason="parser_already_resolved",
                num_in=len(candidates), num_valid=0,
                skipped_parser=True,
            )
            return

        # 3. Validar cada candidato via Searcher.
        valid_candidates = self._validate_candidates(candidates)

        # 4. Filtrar por confiança mínima.
        confident_candidates = [
            c for c in valid_candidates if c.confidence >= self._min_confidence
        ]

        if not confident_candidates:
            if not valid_candidates:
                self._total_skipped_invalid += 1
                reason = "all_invalid"
            else:
                self._total_skipped_low_conf += 1
                reason = "low_confidence"
            self._publish_resolution(
                event, resolved=False, reason=reason,
                num_in=len(candidates), num_valid=len(valid_candidates),
            )
            return

        # 5. Escolher candidato de maior confiança.
        chosen = max(confident_candidates, key=lambda c: c.confidence)

        # 6. Publicar ReferenceDetected.
        self._publish_reference_detected(event, chosen)
        self._total_resolved += 1

        # 7. Publicar telemetria de resolução.
        self._publish_resolution(
            event, resolved=True, reason="highest_confidence",
            num_in=len(candidates), num_valid=len(valid_candidates),
            chosen=chosen,
        )

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def _deserialize_candidates(self, candidates_json: str) -> list[SemanticCandidate]:
        """Desserializa JSON de candidatos para SemanticCandidate[]."""
        try:
            data = json.loads(candidates_json)
        except json.JSONDecodeError:
            logger.warning("ReferenceResolver: invalid candidates JSON")
            return []

        if not isinstance(data, list):
            return []

        candidates: list[SemanticCandidate] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(SemanticCandidate(
                    book=item.get("book", ""),
                    chapter=int(item.get("chapter", 0)),
                    verse=int(item.get("verse", 0)),
                    confidence=float(item.get("confidence", 0.0)),
                    reason=item.get("reason", ""),
                ))
            except (TypeError, ValueError):
                continue
        return candidates

    def _parser_already_resolved(self, correlation_id: str) -> bool:
        """Verifica no histórico se o parser já publicou ReferenceDetected
        para esta correlation_id."""
        try:
            events = self._bus.history()
        except Exception as e:
            logger.warning("ReferenceResolver: failed to read history: %s", e)
            return False

        for event in events:
            # ReferenceDetected do parser (origin="IncrementalBiblicalParser").
            if isinstance(event, ReferenceDetected):
                if event.meta.correlation_id == correlation_id:
                    if event.meta.origin == "IncrementalBiblicalParser":
                        return True
        return False

    def _validate_candidates(
        self, candidates: list[SemanticCandidate]
    ) -> list[SemanticCandidate]:
        """Valida cada candidato via Searcher. Retorna apenas os válidos."""
        valid: list[SemanticCandidate] = []
        for cand in candidates:
            if self._validate_single(cand):
                valid.append(cand)
        return valid

    def _validate_single(self, cand: SemanticCandidate) -> bool:
        """Valida um candidato via Searcher.search_by_reference().

        Retorna True se a referência existe na base bíblica.
        """
        if not cand.book.strip():
            return False
        if cand.chapter <= 0:
            return False

        try:
            # Se versículo > 0, buscar versículo exato.
            # Se versículo == 0, buscar capítulo (primeiro versículo).
            result = self._searcher.search_by_reference(
                book_name=cand.book,
                chapter=cand.chapter,
                verse=cand.verse if cand.verse > 0 else None,
            )
            if result is not None:
                return True
            # Se versículo específico não existe, tentar capítulo inteiro.
            if cand.verse > 0:
                chapter_result = self._searcher.search_by_reference(
                    book_name=cand.book,
                    chapter=cand.chapter,
                    verse=None,
                )
                if chapter_result is not None:
                    # Capítulo existe mas versículo não — marcar como válido
                    # mas com confiança reduzida? Por ora, considerar inválido
                    # para não mostrar versículo errado.
                    return False
            return False
        except Exception as e:
            # SearchError (livro desconhecido) ou outro erro — inválido.
            logger.debug(
                "ReferenceResolver: candidate '%s %d:%d' invalid: %s",
                cand.book, cand.chapter, cand.verse, e,
            )
            return False

    # ------------------------------------------------------------------
    # Publicação
    # ------------------------------------------------------------------

    def _publish_reference_detected(
        self,
        source_event: IntentCandidate,
        chosen: SemanticCandidate,
    ) -> None:
        """Publica ReferenceDetected para o candidato escolhido."""
        # Resolver book_id via Searcher (já validado, então existe).
        book_id = 0
        try:
            match = self._searcher._book_table.resolve(chosen.book)
            if match is not None:
                book_id = match.book.id
        except Exception:
            pass

        # Texto normalizado.
        if chosen.verse > 0:
            normalized = f"{chosen.book} {chosen.chapter}:{chosen.verse}"
        else:
            normalized = f"{chosen.book} {chosen.chapter}"

        meta = EventMetadata.for_next(
            previous=source_event.meta,
            origin="ReferenceResolver",
        )

        event = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book=chosen.book,
            book_id=book_id,
            chapter=chosen.chapter,
            verse_start=chosen.verse,
            verse_end=chosen.verse,
            confidence=round(chosen.confidence, 4),
            raw_text=source_event.meta.origin,  # marker de origem semântica
            normalized_text=normalized,
        )
        self._bus.publish(event)
        logger.info(
            "ReferenceResolver: published ReferenceDetected %s (confidence=%.2f, provider=%s)",
            normalized, chosen.confidence, source_event.provider,
        )

    def _publish_resolution(
        self,
        source_event: IntentCandidate,
        resolved: bool,
        reason: str,
        num_in: int,
        num_valid: int,
        chosen: SemanticCandidate | None = None,
        skipped_parser: bool = False,
    ) -> None:
        """Publica SemanticResolutionCompleted (telemetria)."""
        meta = EventMetadata.for_next(
            previous=source_event.meta,
            origin="ReferenceResolver",
        )
        event = SemanticResolutionCompleted(
            meta=meta,
            resolved=resolved,
            chosen_book=chosen.book if chosen else "",
            chosen_chapter=chosen.chapter if chosen else 0,
            chosen_verse=chosen.verse if chosen else 0,
            chosen_confidence=chosen.confidence if chosen else 0.0,
            reason=reason,
            num_candidates_in=num_in,
            num_candidates_valid=num_valid,
            skipped_due_to_parser=skipped_parser,
        )
        self._bus.publish(event)

    # ------------------------------------------------------------------
    # Estatísticas
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "total_resolved": self._total_resolved,
            "total_skipped_parser": self._total_skipped_parser,
            "total_skipped_invalid": self._total_skipped_invalid,
            "total_skipped_low_conf": self._total_skipped_low_conf,
            "min_confidence": self._min_confidence,
            "enabled": self._enabled,
        }
