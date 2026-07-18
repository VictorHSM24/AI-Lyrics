"""Exemplo de uso do módulo core/decision.py.

Executa: python examples/use_decision.py

Demonstra os 5 fluxos obrigatórios:
  1. Parser "João 3:16" → show → Holyrics
  2. Parser "next" + State → próximo versículo → Holyrics
  3. Parser "uncertain" + query → forward_to_llm
  4. SearchResult ambiguous → request_confirmation
  5. confidence abaixo do limite → ignore

Usa mocks para Holyrics (não requer Holyrics real rodando).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from busca.searcher import SearchResult
from config.models import ConfidenceConfig
from core.decision import DecisionEngine
from core.types import Intent, VerseRef
from estado.state import BibleStructure, BibleStateManager


def _conf_config() -> ConfidenceConfig:
    return ConfidenceConfig(
        min_execute=0.85,
        min_confirm=0.60,
        stt_min=0.50,
        parser_high=0.90,
        parser_compact=0.85,
    )


def _structure() -> BibleStructure:
    return BibleStructure(
        chapter_counts={43: 21, 1: 50, 45: 16},
        verse_counts={(43, 3): 36, (1, 1): 31, (45, 8): 39},
    )


def _book_names() -> dict[int, str]:
    return {43: "João", 1: "Gênesis", 45: "Romanos"}


def _state_manager() -> BibleStateManager:
    return BibleStateManager(
        structure=_structure(),
        book_names=_book_names(),
        default_version="ACF",
    )


def _search_result(
    book_id: int = 43, chapter: int = 3, verse: int = 16,
    c_search: float = 0.95, ambiguous: bool = False,
) -> SearchResult:
    return SearchResult(
        reference=f"João {chapter}:{verse}",
        book="João", book_id=book_id, chapter=chapter, verse=verse,
        text="Porque Deus amou o mundo...",
        version="ACF", score=0.95, c_search=c_search,
        ambiguous=ambiguous, match_type="hybrid",
    )


def _print_decision(decision, label: str = "") -> None:
    """Imprime um Decision de forma legível."""
    print(f"\n--- {label} ---" if label else "")
    print(f"  Decision(")
    print(f"    action={decision.action!r}")
    print(f"    outcome={decision.outcome!r}")
    print(f"    confidence={decision.confidence:.3f}")
    print(f"    requires_confirmation={decision.requires_confirmation}")
    print(f"    forward_to_llm={decision.forward_to_llm}")
    print(f"    ignore={decision.ignore}")
    print(f"    reason={decision.reason!r}")
    if decision.confidence_breakdown:
        cb = decision.confidence_breakdown
        print(f"    c_stt={cb.c_stt:.2f} c_intent={cb.c_intent:.2f} c_search={cb.c_search:.2f}")
    if decision.ref:
        print(f"    ref={decision.ref.reference}")
    print(f"  )")


def main() -> None:
    print("=== Motor de Decisão — DecisionEngine ===\n")

    # Setup
    state_mgr = _state_manager()
    holyrics = MagicMock()
    holyrics.show_verse.return_value = MagicMock(status="ok")

    engine = DecisionEngine(
        confidence_config=_conf_config(),
        state_manager=state_mgr,
        holyrics_client=holyrics,
        mode="auto",
    )

    # Fluxo 1: Parser "João 3:16" → show → Holyrics
    print("=" * 60)
    print("Fluxo 1: Parser 'João 3:16' → show → Holyrics")
    print("=" * 60)

    intent = Intent(
        action="show", book="João", book_id=43, chapter=3, verse=16,
        confidence=0.98, source="parser", raw="joão três dezesseis",
    )
    decision = engine.evaluate(intent, c_stt=0.95)
    _print_decision(decision, "Avaliação")

    if decision.outcome == "execute":
        ref = engine.execute(decision)
        print(f"\n  → Holyrics ShowVerse: {ref.reference if ref else 'N/A'}")
        print(f"  → State atualizado: {state_mgr.current_ref()}" if state_mgr.current_ref() else "")

    # Fluxo 2: Parser "next" + State → próximo versículo
    print("\n" + "=" * 60)
    print("Fluxo 2: Parser 'next' + State (João 3:16) → João 3:17")
    print("=" * 60)

    # State já está em João 3:16 do fluxo anterior
    intent = Intent(
        action="next", confidence=0.98, source="parser", raw="próximo",
    )
    decision = engine.evaluate(intent, c_stt=0.95)
    _print_decision(decision, "Avaliação")

    if decision.outcome == "execute":
        ref = engine.execute(decision)
        print(f"\n  → Holyrics ShowVerse: {ref.reference if ref else 'N/A'}")
        print(f"  → State atualizado: {state_mgr.current_ref()}" if state_mgr.current_ref() else "")

    # Fluxo 3: Parser "uncertain" + query → forward_to_llm
    print("\n" + "=" * 60)
    print("Fluxo 3: Parser 'uncertain' + query → forward_to_llm")
    print("=" * 60)

    intent = Intent(
        action="uncertain", confidence=0.0, source="parser",
        query="aquele texto que fala que Deus amou o mundo",
        raw="abre aquele texto que fala que deus amou o mundo",
    )
    decision = engine.evaluate(intent, c_stt=0.9)
    _print_decision(decision, "Avaliação")
    print(f"\n  → forward_to_llm={decision.forward_to_llm}")
    print(f"  → query={decision.intent.query!r}")

    # Fluxo 4: SearchResult ambiguous → request_confirmation
    print("\n" + "=" * 60)
    print("Fluxo 4: SearchResult ambiguous → request_confirmation")
    print("=" * 60)

    intent = Intent(
        action="search", confidence=0.98, source="parser",
        query="fé", raw="abre aquele texto da fé",
    )
    results = [_search_result(c_search=0.95, ambiguous=True)]
    decision = engine.evaluate(intent, c_stt=0.95, search_results=results)
    _print_decision(decision, "Avaliação")
    print(f"\n  → requires_confirmation={decision.requires_confirmation}")

    # Fluxo 5: confidence abaixo do limite → ignore
    print("\n" + "=" * 60)
    print("Fluxo 5: confidence abaixo do limite → ignore")
    print("=" * 60)

    intent = Intent(
        action="show", book="João", book_id=43, chapter=3, verse=16,
        confidence=0.3, source="parser", raw="joão... algo...",
    )
    decision = engine.evaluate(intent, c_stt=0.9)
    _print_decision(decision, "Avaliação")
    print(f"\n  → ignore={decision.ignore}")

    # Métricas finais
    print("\n" + "=" * 60)
    print("Métricas")
    print("=" * 60)

    m = engine.metrics
    print(f"  total_evaluations: {m.total_evaluations}")
    print(f"  execute:           {m.execute}")
    print(f"  confirm:           {m.confirm}")
    print(f"  ignore:            {m.ignore}")
    print(f"  forward_to_llm:    {m.forward_to_llm}")
    print(f"  errors:            {m.errors}")
    print(f"  avg_time_ms:       {m.avg_time_ms:.3f}")

    print("\n=== Concluído ===")


if __name__ == "__main__":
    main()
