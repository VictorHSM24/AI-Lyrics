"""Motor de decisão determinístico.

Responsabilidade: orquestrar parser, busca, estado e Holyrics — sem
executar lógica de nenhum deles. Apenas decide e encaminha.

Pipeline de decisão (doc. técnica §8 e §10):
  1. Receber Intent (do parser ou LLM) + c_stt.
  2. Se action == "none" → ignore.
  3. Se c_stt < stt_min → ignore (STT ruim).
  4. Se action == "uncertain" → forward_to_llm.
  4b. Se action == "show" + c_intent >= parser_high + book/chapter/verse
      presentes → execute (bypass de referências explícitas, ignora c_stt).
  5. Se action == "search":
     a. Se SearchResult ambíguo → confirm.
     b. c_final = c_stt * c_intent * c_search.
     c. Aplicar limiares (min_execute, min_confirm).
  6. Se action in ("show", "next", "previous", "jump"):
     a. c_final = c_stt * c_intent (c_search = 1.0).
     b. Aplicar limiares.
  7. Modo "confirm" → sempre confirmar (override).
  8. Produzir Decision.

Princípios (doc. técnica §10.1):
  - "Nunca executar comandos duvidosos."
  - Multiplicação de confianças é conservadora.
  - Busca ambígua → sempre confirmar, independentemente do score.
  - LLM não fala com Holyrics — passa pelo motor de decisão.

Determinismo:
  - Sem IA, sem aleatoriedade, sem rede na avaliação.
  - Mesmas entradas → mesma Decision. Testável.
  - execute() (side effects) é separado de evaluate() (pure logic).

Limites explícitos (o que este módulo NÃO faz):
  - Não executa lógica de parser (recebe Intent pronto).
  - Não executa lógica de busca (recebe SearchResult pronto).
  - Não executa lógica de STT (recebe c_stt pronto).
  - Não executa lógica de LLM (apenas sinaliza forward_to_llm).
  - Não implementa cache (futuro módulo cache/).
  - Não implementa telemetria.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from config.models import ConfidenceConfig
from core.exceptions import DecisionError, StateError
from core.types import Confidence, Decision, Intent, VerseRef
from estado.state import BibleStateManager

if TYPE_CHECKING:
    from busca.searcher import SearchResult
    from integracao_holyrics import HolyricsClient, HolyricsError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


@dataclass
class DecisionMetrics:
    """Métricas acumuladas do motor de decisão."""

    total_evaluations: int = 0
    execute: int = 0
    confirm: int = 0
    ignore: int = 0
    forward_to_llm: int = 0
    errors: int = 0
    total_time_ms: float = 0.0

    @property
    def avg_time_ms(self) -> float:
        if self.total_evaluations == 0:
            return 0.0
        return self.total_time_ms / self.total_evaluations

    def reset(self) -> None:
        self.total_evaluations = 0
        self.execute = 0
        self.confirm = 0
        self.ignore = 0
        self.forward_to_llm = 0
        self.errors = 0
        self.total_time_ms = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Limita value ao intervalo [low, high]."""
    return max(low, min(high, value))


def _extract_search_confidence(results: list[SearchResult]) -> tuple[float, bool]:
    """Extrai c_search e flag ambiguous de uma lista de SearchResult.

    Returns:
        (c_search, ambiguous). c_search = 1.0 se lista vazia.
    """
    if not results:
        return 1.0, False
    top = results[0]
    c_search = top.c_search
    ambiguous = top.ambiguous
    return _clamp(c_search), ambiguous


# ---------------------------------------------------------------------------
# DecisionEngine
# ---------------------------------------------------------------------------


class DecisionEngine:
    """Motor de decisão determinístico.

    Avalia Intent + c_stt + (opcional) SearchResult e produz Decision.
    Se outcome == "execute", pode executar a ação via Holyrics e State.

    Args:
        confidence_config: limiares (min_execute, min_confirm, stt_min).
        mode: "auto" (executa se >= min_execute), "confirm" (sempre
            confirma), "quick" (quick_presentation para ambíguos).
        state_manager: BibleStateManager para next/previous/jump/show.
        holyrics_client: HolyricsClient para ShowVerse (pode ser None
            em modo dry-run para testes).

    Example:
        >>> engine = DecisionEngine(conf_config, state_mgr, holyrics)
        >>> decision = engine.evaluate(intent, c_stt=0.95)
        >>> if decision.outcome == "execute":
        ...     engine.execute(decision)
    """

    def __init__(
        self,
        confidence_config: ConfidenceConfig,
        state_manager: BibleStateManager,
        holyrics_client: HolyricsClient | None = None,
        mode: str = "auto",
    ) -> None:
        self._config = confidence_config
        self._state = state_manager
        self._holyrics = holyrics_client
        self._mode = mode
        self._metrics = DecisionMetrics()

        logger.info(
            "DecisionEngine initialized: mode=%s min_execute=%.2f min_confirm=%.2f stt_min=%.2f",
            mode,
            confidence_config.min_execute,
            confidence_config.min_confirm,
            confidence_config.stt_min,
        )

    # ------------------------------------------------------------------
    # Avaliação (pure logic — sem side effects)
    # ------------------------------------------------------------------

    def evaluate(
        self,
        intent: Intent,
        c_stt: float = 1.0,
        search_results: list[SearchResult] | None = None,
    ) -> Decision:
        """Avalia Intent e produz Decision (determinístico, sem side effects).

        Aplica a tabela de decisão (doc. técnica §8.5):
        1. action == "none" → ignore.
        2. c_stt < stt_min → ignore.
        3. action == "uncertain" → forward_to_llm.
        3b. action == "show" + c_intent >= parser_high + book/chapter/verse
            presentes → execute (bypass de referências explícitas).
        4. action == "search" + ambiguous → confirm.
        5. c_final >= min_execute → execute.
        6. c_final >= min_confirm → confirm.
        7. else → ignore.
        8. mode == "confirm" → sempre confirmar (override de execute).

        Args:
            intent: Intent do parser ou LLM.
            c_stt: confiança da transcrição [0.0, 1.0].
            search_results: resultados de busca (se action == "search").

        Returns:
            Decision com outcome, confidence, flags e reason.
        """
        t0 = time.monotonic()
        self._metrics.total_evaluations += 1

        c_stt = _clamp(c_stt)
        c_intent = _clamp(intent.confidence)

        # 1. action == "none" → ignore direto
        if intent.action == "none":
            decision = self._build_decision(
                intent, "ignore", 0.0, "action is none",
                Confidence(c_stt=c_stt, c_intent=c_intent, c_search=1.0),
            )
            self._record_metric("ignore", t0)
            return decision

        # 2. c_stt < stt_min → ignore (STT ruim)
        if c_stt < self._config.stt_min:
            decision = self._build_decision(
                intent, "ignore", c_stt,
                f"c_stt={c_stt:.2f} < stt_min={self._config.stt_min:.2f}",
                Confidence(c_stt=c_stt, c_intent=c_intent, c_search=1.0),
            )
            self._record_metric("ignore", t0)
            return decision

        # 3. action == "uncertain" → forward_to_llm
        if intent.action == "uncertain":
            decision = self._build_decision(
                intent, "forward_to_llm", c_stt * c_intent,
                "parser uncertain — forward to LLM",
                Confidence(c_stt=c_stt, c_intent=c_intent, c_search=1.0),
            )
            decision.forward_to_llm = True
            self._record_metric("forward_to_llm", t0)
            return decision

        # 3b. Bypass para referências explícitas de alta confiança
        #
        # O Whisper tem confiança naturalmente baixa para frases curtas
        # como "João 3:16" (c_stt ~0.30). Se o parser reconheceu a
        # referência com alta confiança (>= parser_high) e todos os
        # campos estão presentes (book, chapter, verse), executar
        # diretamente sem penalizar pelo c_stt — desde que c_stt >=
        # stt_min (já garantido pelo step 2).
        #
        # c_search = 1.0 para action="show" (default, ainda não
        # modificado pelo step 4). c_final continua sendo calculado
        # normalmente (c_stt * c_intent * c_search) para transparência,
        # mas o outcome é "execute" independentemente dos limiares.
        if (
            intent.action == "show"
            and c_intent >= self._config.parser_high
            and intent.book is not None
            and intent.chapter is not None
            and intent.verse is not None
        ):
            conf = Confidence(c_stt=c_stt, c_intent=c_intent, c_search=1.0)
            outcome = "execute"
            reason = "explicit_reference_high_confidence"
            # mode == "confirm" → override execute para confirm
            if self._mode == "confirm":
                outcome = "confirm"
                reason = f"mode=confirm forces confirmation ({reason})"
            decision = self._build_decision(
                intent, outcome, conf.c_final, reason, conf,
            )
            if outcome == "confirm":
                decision.requires_confirmation = True
            logger.info(
                "Decision: action=show outcome=%s reason=%s "
                "c_stt=%.2f c_intent=%.2f c_final=%.3f",
                outcome, reason, c_stt, c_intent, conf.c_final,
            )
            self._record_metric(outcome, t0)
            return decision

        # 4. action == "search" — processar search_results
        c_search = 1.0
        ambiguous = False
        if intent.action == "search" and search_results is not None:
            c_search, ambiguous = _extract_search_confidence(search_results)
        elif intent.action == "search" and search_results is None:
            # action=search mas sem resultados — não deveria acontecer
            # no pipeline real, mas tratamos como ambiguous → confirm
            ambiguous = True

        # 5. ambiguous → confirm (independentemente do score)
        if ambiguous:
            conf = Confidence(c_stt=c_stt, c_intent=c_intent, c_search=c_search)
            decision = self._build_decision(
                intent, "confirm", conf.c_final,
                "search ambiguous — gap top1/top2 < search_gap",
                conf,
            )
            decision.requires_confirmation = True
            self._record_metric("confirm", t0)
            return decision

        # 6. Calcular c_final
        conf = Confidence(c_stt=c_stt, c_intent=c_intent, c_search=c_search)
        c_final = conf.c_final

        # 7. Aplicar limiares
        if c_final >= self._config.min_execute:
            outcome = "execute"
            reason = f"c_final={c_final:.3f} >= min_execute={self._config.min_execute:.2f}"
        elif c_final >= self._config.min_confirm:
            outcome = "confirm"
            reason = f"c_final={c_final:.3f} in [min_confirm, min_execute)"
        else:
            outcome = "ignore"
            reason = f"c_final={c_final:.3f} < min_confirm={self._config.min_confirm:.2f}"

        # 8. mode == "confirm" → override execute para confirm
        if self._mode == "confirm" and outcome == "execute":
            outcome = "confirm"
            reason = f"mode=confirm forces confirmation ({reason})"

        decision = self._build_decision(intent, outcome, c_final, reason, conf)
        self._record_metric(outcome, t0)
        return decision

    # ------------------------------------------------------------------
    # Execução (side effects — Holyrics + State)
    # ------------------------------------------------------------------

    def execute(
        self,
        decision: Decision,
        search_results: list[SearchResult] | None = None,
    ) -> VerseRef | None:
        """Executa a decisão: chama Holyrics e atualiza State.

        Só deve ser chamado se decision.outcome == "execute".
        Para outcome == "confirm", a execução acontece após confirmação
        do usuário (fora deste módulo).
        Para outcome == "forward_to_llm" ou "ignore", não há execução.

        Args:
            decision: Decision com outcome == "execute".
            search_results: resultados de busca (se action == "search"
                e o versículo alvo vem da busca).

        Returns:
            VerseRef resolvido e enviado ao Holyrics, ou None.

        Raises:
            DecisionError: se outcome != "execute" ou execução falha.
        """
        if decision.outcome != "execute":
            raise DecisionError(
                f"cannot execute decision with outcome={decision.outcome!r} "
                f"(expected 'execute')"
            )

        intent = decision.intent

        try:
            # Resolver VerseRef baseado na action
            ref = self._resolve_ref(intent, search_results)
            if ref is None:
                logger.warning(
                    "execute: could not resolve ref for action=%s", intent.action
                )
                return None

            # Atualizar estado
            self._state.set(ref)
            self._state.set_intent(intent)
            if intent.action == "search":
                self._state.set_search(intent.query or "")

            # Enviar ao Holyrics
            if self._holyrics is not None:
                quick = self._mode == "quick" and decision.requires_confirmation
                self._holyrics.show_verse(
                    book_id=ref.book_id,
                    chapter=ref.chapter,
                    verse=ref.verse,
                    version=ref.version,
                    quick=quick,
                )
                logger.info(
                    "execute: ShowVerse sent ref=%s version=%s quick=%s",
                    ref.reference,
                    ref.version,
                    quick,
                )
            else:
                logger.info(
                    "execute: dry-run (no Holyrics) ref=%s", ref.reference
                )

            # Atualizar decision com ref resolvido
            decision.ref = ref
            return ref

        except StateError as e:
            self._metrics.errors += 1
            raise DecisionError(f"state error during execute: {e}") from e
        except Exception as e:
            # Capturar HolyricsError sem importá-lo no top-level (evita circular)
            from integracao_holyrics import HolyricsError as _HolyricsError
            if isinstance(e, _HolyricsError):
                self._metrics.errors += 1
                raise DecisionError(f"holyrics error during execute: {e}") from e
            self._metrics.errors += 1
            raise DecisionError(f"unexpected error during execute: {e}") from e

    # ------------------------------------------------------------------
    # Resolução de VerseRef
    # ------------------------------------------------------------------

    def _resolve_ref(
        self,
        intent: Intent,
        search_results: list[SearchResult] | None,
    ) -> VerseRef | None:
        """Resolve VerseRef baseado na action do Intent.

        - show/jump: usa state.apply(intent).
        - next/previous: usa state.apply(intent).
        - search: usa top-1 SearchResult se disponível.

        Returns:
            VerseRef ou None se não resolvível.
        """
        if intent.action == "search":
            if search_results and len(search_results) > 0:
                top = search_results[0]
                return VerseRef(
                    book_id=top.book_id,
                    book=top.book,
                    chapter=top.chapter,
                    verse=top.verse,
                    version=top.version,
                )
            return None

        # show, next, previous, jump — delegar ao state manager
        return self._state.apply(intent)

    # ------------------------------------------------------------------
    # Construção de Decision
    # ------------------------------------------------------------------

    @staticmethod
    def _build_decision(
        intent: Intent,
        outcome: str,
        confidence: float,
        reason: str,
        conf: Confidence,
    ) -> Decision:
        """Constrói um Decision com flags derivadas do outcome."""
        return Decision(
            action=intent.action,
            outcome=outcome,  # type: ignore[arg-type]
            confidence=_clamp(confidence),
            requires_confirmation=(outcome == "confirm"),
            forward_to_llm=(outcome == "forward_to_llm"),
            ignore=(outcome == "ignore"),
            reason=reason,
            intent=intent,
            ref=None,
            confidence_breakdown=conf,
        )

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------

    def _record_metric(self, outcome: str, t0: float) -> None:
        """Registra métrica de outcome."""
        elapsed = (time.monotonic() - t0) * 1000
        self._metrics.total_time_ms += elapsed

        if outcome == "execute":
            self._metrics.execute += 1
        elif outcome == "confirm":
            self._metrics.confirm += 1
        elif outcome == "ignore":
            self._metrics.ignore += 1
        elif outcome == "forward_to_llm":
            self._metrics.forward_to_llm += 1

        logger.debug(
            "evaluate: action=%s outcome=%s confidence=%.3f time=%.2fms reason=%s",
            "n/a",
            outcome,
            0.0,
            elapsed,
            "",
        )

    @property
    def metrics(self) -> DecisionMetrics:
        """Métricas acumuladas do motor de decisão."""
        return self._metrics

    @property
    def mode(self) -> str:
        """Modo de operação atual."""
        return self._mode
