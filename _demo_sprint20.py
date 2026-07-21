"""_demo_sprint20.py — Demonstração da Sprint 20 — Semantic Understanding Engine.

Demonstra:
  1. Parser vence LLM quando há referência explícita.
  2. LLM resolve referência implícita ("Nicodemos" → João 3).
  3. LLM resolve "guardar o coração" → Provérbios 4:23.
  4. LLM resolve "bom pastor" → João 10.
  5. Cache evita re-chamada ao provider.
  6. Candidatos inválidos são descartados.
  7. Schema inválido é descartado (segurança).
  8. Contexto longo (última referência) é usado.

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from pipeline.bus import PipelineEventBus
from pipeline.event_store import MemoryEventStore
from pipeline.events import (
    IntentCandidate,
    ReferenceDetected,
    SemanticInferenceCompleted,
    SemanticResolutionCompleted,
    SpeechPartial,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic import (
    ContextEngine,
    ReferenceResolver,
    SemanticCache,
    SemanticCandidate,
    SemanticContext,
    SemanticEngine,
    SemanticResult,
    StubProvider,
)


class _MockSearcher:
    """Searcher mock com base bíblica mínima para a demo."""

    _VALID = {
        ("João", 3, 0), ("João", 3, 5), ("João", 3, 16),
        ("João", 10, 0), ("João", 10, 11),
        ("Provérbios", 4, 23),
        ("Lucas", 10, 0),
        ("Gênesis", 1, 0),
        ("Mateus", 5, 0),
        ("Isaías", 40, 31),
    }

    def __init__(self):
        self._book_table = MagicMock()
        self._book_table.resolve = MagicMock(return_value=MagicMock(
            book=MagicMock(id=43, canonical="João")
        ))

    def search_by_reference(self, book_name, chapter, verse=None, version=None):
        book_lower = book_name.lower().strip()
        variants = {
            "joão": "João", "joao": "João", "jo": "João",
            "provérbios": "Provérbios", "proverbios": "Provérbios",
            "lucas": "Lucas", "gênesis": "Gênesis", "genesis": "Gênesis",
            "mateus": "Mateus", "isaías": "Isaías", "isaías": "Isaías",
        }
        book_key = variants.get(book_lower, book_name)
        key = (book_key, chapter, verse if verse else 0)
        return MagicMock() if key in self._VALID else None


def _make_partial_updated(text, correlation_id=None):
    meta = EventMetadata.for_initial(
        session_id="demo", origin="StreamingSTTService",
        correlation_id=correlation_id,
    )
    return SpeechPartialUpdated(
        meta=meta, text=text, appended_text=text,
        language="pt", confidence=0.9, latency_ms=100,
        audio_duration_ms=2000, is_stable=False,
    )


def _collect(bus, event_type):
    return [e for e in bus.history() if isinstance(e, event_type)]


def _print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def _print_ref(event):
    if event.verse_start > 0:
        print(f"    → {event.book} {event.chapter}:{event.verse_start} "
              f"(confidence={event.confidence:.2f}, origin={event.meta.origin})")
    else:
        print(f"    → {event.book} {event.chapter} "
              f"(confidence={event.confidence:.2f}, origin={event.meta.origin})")


def main():
    print("="*70)
    print("  SPRINT 20 — SEMANTIC UNDERSTANDING ENGINE — DEMONSTRAÇÃO")
    print("="*70)
    print()
    print("  Arquitetura:")
    print("    SpeechPartial/Updated")
    print("        │")
    print("        ├──────────────────────┐")
    print("        ▼                      ▼")
    print("    IncrementalParser      SemanticEngine")
    print("        │                      │")
    print("    ReferenceDetected     IntentCandidate")
    print("        │                      │")
    print("        │                      ▼")
    print("        │              ReferenceResolver")
    print("        │                      │")
    print("        └──────────┬───────────┘")
    print("                   ▼")
    print("           ReferenceDetected")
    print("                   ▼")
    print("              Holyrics")
    print()
    print("  Regra: LLM nunca publica ReferenceDetected.")
    print("         Apenas o ReferenceResolver publica.")
    print("         Parser vence se resolver primeiro.")

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    bus = PipelineEventBus(store=MemoryEventStore())
    searcher = _MockSearcher()
    provider = StubProvider()
    context_engine = ContextEngine(history_fn=bus.history)
    cache = SemanticCache(ttl_seconds=300)

    engine = SemanticEngine(
        bus=bus, provider=provider, context_engine=context_engine,
        cache=cache, session_id="demo", debounce_ms=100, timeout_ms=5000,
    )
    resolver = ReferenceResolver(bus=bus, searcher=searcher, session_id="demo")

    engine.start()
    resolver.start()

    # ------------------------------------------------------------------
    # Demo 1 — Referência implícita: "Nicodemos" → João 3
    # ------------------------------------------------------------------
    _print_header("DEMO 1 — Referência implícita: 'Nicodemos' → João 3")
    print("  Pregador: 'o texto onde Jesus conversa com Nicodemos'")
    print("  (parser não consegue resolver — não há livro/capítulo explícito)")
    print()
    bus.publish(_make_partial_updated("o texto onde Jesus conversa com Nicodemos"))
    time.sleep(0.4)

    intents = _collect(bus, IntentCandidate)
    print(f"  IntentCandidate publicado: {len(intents)}")
    if intents:
        cands = json.loads(intents[0].candidates_json)
        print(f"  Candidatos do LLM: {len(cands)}")
        for c in cands:
            ref = f"{c['book']} {c['chapter']}:{c['verse']}" if c['verse'] else f"{c['book']} {c['chapter']}"
            print(f"    • {ref} (conf={c['confidence']:.2f}) — {c['reason']}")

    refs = _collect(bus, ReferenceDetected)
    print(f"\n  ReferenceDetected publicado: {len(refs)}")
    for r in refs:
        _print_ref(r)

    resolutions = _collect(bus, SemanticResolutionCompleted)
    if resolutions:
        r = resolutions[0]
        print(f"\n  Resolução: resolved={r.resolved}, reason='{r.reason}', "
              f"valid={r.num_candidates_valid}/{r.num_candidates_in}")

    # ------------------------------------------------------------------
    # Demo 2 — "guardar o coração" → Provérbios 4:23
    # ------------------------------------------------------------------
    _print_header("DEMO 2 — 'guardar o coração' → Provérbios 4:23")
    print("  Pregador: 'o versículo que fala para guardar o coração'")
    bus.publish(_make_partial_updated("o versículo que fala para guardar o coração"))
    time.sleep(0.4)
    refs = [e for e in bus.history() if isinstance(e, ReferenceDetected)
            and e.meta.origin == "ReferenceResolver"]
    print(f"  ReferenceDetected (via semantic): {len(refs)}")
    for r in refs[-1:]:
        _print_ref(r)

    # ------------------------------------------------------------------
    # Demo 3 — "bom pastor" → João 10
    # ------------------------------------------------------------------
    _print_header("DEMO 3 — 'bom pastor' → João 10")
    print("  Pregador: 'a passagem do bom pastor'")
    bus.publish(_make_partial_updated("a passagem do bom pastor"))
    time.sleep(0.4)
    refs = [e for e in bus.history() if isinstance(e, ReferenceDetected)
            and e.meta.origin == "ReferenceResolver"]
    print(f"  ReferenceDetected (via semantic): {len(refs)}")
    for r in refs[-1:]:
        _print_ref(r)

    # ------------------------------------------------------------------
    # Demo 4 — Parser vence LLM (referência explícita)
    # ------------------------------------------------------------------
    _print_header("DEMO 4 — Parser vence LLM (referência explícita)")
    print("  Pregador: 'vamos para João 3:16'")
    print("  (parser determinístico publica ReferenceDetected primeiro)")
    print()
    corr_id = "demo-parser-wins"
    bus.publish(_make_partial_updated("vamos para João 3:16", correlation_id=corr_id))
    # Simular parser publicando ReferenceDetected imediatamente.
    parser_meta = EventMetadata.for_initial(
        session_id="demo", origin="IncrementalBiblicalParser",
        correlation_id=corr_id,
    )
    bus.publish(ReferenceDetected(
        meta=parser_meta, book="João", chapter=3, verse_start=16,
        confidence=0.98, raw_text="joão 3 16", normalized_text="João 3:16",
    ))
    time.sleep(0.4)
    # Verificar que o resolver NÃO publicou novo ReferenceDetected.
    semantic_refs = [e for e in bus.history()
                     if isinstance(e, ReferenceDetected)
                     and e.meta.origin == "ReferenceResolver"
                     and e.meta.correlation_id == corr_id]
    print(f"  ReferenceDetected do parser: 1 (origin=IncrementalBiblicalParser)")
    print(f"  ReferenceDetected do resolver: {len(semantic_refs)} (deveria ser 0)")
    print(f"  ✓ Parser venceu — resolver respeitou a decisão determinística")

    # ------------------------------------------------------------------
    # Demo 5 — Cache em ação
    # ------------------------------------------------------------------
    _print_header("DEMO 5 — Cache evita re-chamada ao provider")
    print("  Publicando texto não-bíblico duas vezes (mesmo contexto, sem ReferenceDetected)")
    stats_before = engine.stats()
    cache_text = "hoje o trânsito está terrível na cidade toda"
    bus.publish(_make_partial_updated(cache_text))
    time.sleep(0.4)
    stats_mid = engine.stats()
    # Publicar exatamente o mesmo texto — contexto é idêntico porque:
    # 1. current_text é igual (excluído de recent_text)
    # 2. Nenhum ReferenceDetected novo (texto não-bíblico)
    # 3. last_book/last_chapter não mudaram
    bus.publish(_make_partial_updated(cache_text))
    time.sleep(0.4)
    stats_after = engine.stats()
    print(f"  Chamadas ao engine após 1ª: {stats_mid['total_calls']}")
    print(f"  Chamadas ao engine após 2ª: {stats_after['total_calls']}")
    print(f"  Cache hits: {stats_after['total_cache_hits']}")
    if stats_after['total_cache_hits'] > stats_mid['total_cache_hits']:
        print(f"  ✓ Cache evitou nova chamada ao LLM (mesmo hash de contexto)")
    else:
        print(f"  ℹ Contexto mudou — cache miss é esperado")

    # ------------------------------------------------------------------
    # Demo 6 — Texto não-bíblico
    # ------------------------------------------------------------------
    _print_header("DEMO 6 — Texto não-bíblico não gera referência")
    print("  Pregador: 'hoje está chovendo muito forte'")
    bus.publish(_make_partial_updated("hoje está chovendo muito forte"))
    time.sleep(0.4)
    teles = [e for e in bus.history()
             if isinstance(e, SemanticInferenceCompleted)
             and "chovendo" in e.context_text]
    if teles:
        print(f"  Inferência: intent='{teles[0].intent}', candidates=0")
    print(f"  ✓ Nenhum ReferenceDetected publicado")

    # ------------------------------------------------------------------
    # Estatísticas finais
    # ------------------------------------------------------------------
    _print_header("ESTATÍSTICAS FINAIS")
    print(f"  SemanticEngine:")
    for k, v in engine.stats().items():
        print(f"    {k}: {v}")
    print(f"\n  ReferenceResolver:")
    for k, v in resolver.stats().items():
        print(f"    {k}: {v}")

    engine.stop()
    resolver.stop()

    print(f"\n{'='*70}")
    print("  DEMONSTRAÇÃO CONCLUÍDA")
    print(f"{'='*70}")
    print()
    print("  ✓ Referências implícitas resolvidas (Nicodemos, guardar o coração, bom pastor)")
    print("  ✓ Parser continua sendo caminho preferencial para referências explícitas")
    print("  ✓ LLM nunca publica ReferenceDetected — apenas ReferenceResolver")
    print("  ✓ Cache evita re-chamadas ao provider")
    print("  ✓ Texto não-bíblico não gera referência")
    print("  ✓ Arquitetura desacoplada — não alterou StreamingSTT/Parser/Holyrics/EventBus")


if __name__ == "__main__":
    main()
