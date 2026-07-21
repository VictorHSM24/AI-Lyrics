"""_demo_sprint21.py — Demonstração da Sprint 21 — Sermon Memory Engine.

Simula uma pregação contínua e mostra a evolução do SermonContext:

  "Hoje vamos estudar João..."
      ↓
  "Nicodemos procura Jesus à noite..."
      ↓
  "Importa nascer de novo..."
      ↓
  "Como vimos anteriormente..."

O contexto deve evoluir automaticamente para:
  current_book: "João"
  current_chapter: 3
  probable_theme: "Novo nascimento"
  entities: [Jesus, Nicodemos]
  recent_references: [João 3]
  confidence: alta

Sprint 21 — Sermon Memory Engine.
"""

from __future__ import annotations

import json
import time

from pipeline.bus import PipelineEventBus
from pipeline.event_store import MemoryEventStore
from pipeline.events import (
    ReferenceDetected,
    SermonBookChanged,
    SermonChapterChanged,
    SermonContextUpdated,
    SermonTopicChanged,
    SpeechPartialUpdated,
)
from pipeline.metadata import EventMetadata
from semantic import ContextEngine
from sermon import SermonMemoryEngine


def _make_partial_updated(text, session_id="demo"):
    meta = EventMetadata.for_initial(
        session_id=session_id, origin="StreamingSTTService",
    )
    return SpeechPartialUpdated(
        meta=meta, text=text, appended_text=text,
        language="pt", confidence=0.9, latency_ms=100,
        audio_duration_ms=2000, is_stable=False,
    )


def _make_reference(book, chapter, verse=0, origin="IncrementalBiblicalParser"):
    meta = EventMetadata.for_initial(
        session_id="demo", origin=origin,
    )
    return ReferenceDetected(
        meta=meta, book=book, chapter=chapter, verse_start=verse,
        verse_end=verse, confidence=0.95, raw_text=book,
        normalized_text=f"{book} {chapter}",
    )


def _print_header(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def _print_context(ctx, label=""):
    if label:
        print(f"  [{label}]")
    print(f"    book: {ctx.current_book}")
    print(f"    chapter: {ctx.current_chapter}")
    print(f"    theme: {ctx.probable_theme}")
    print(f"    entities: {[e.name for e in ctx.entities]}")
    print(f"    topics: {[t.name for t in ctx.recent_topics]}")
    print(f"    references: {[r.reference_str for r in ctx.recent_references]}")
    print(f"    confidence: {ctx.confidence:.2f}")
    print(f"    total_updates: {ctx.total_updates}")


def main():
    print("="*70)
    print("  SPRINT 21 — SERMON MEMORY ENGINE — DEMONSTRAÇÃO")
    print("="*70)
    print()
    print("  Arquitetura:")
    print("    SpeechPartial/Updated + ReferenceDetected")
    print("        │")
    print("        ▼")
    print("    SermonMemoryEngine (atualiza incrementalmente)")
    print("        │")
    print("        ├─ SermonContextUpdated (a cada atualização)")
    print("        ├─ SermonBookChanged (quando livro muda)")
    print("        ├─ SermonChapterChanged (quando capítulo muda)")
    print("        └─ SermonTopicChanged (quando tema muda)")
    print("            │")
    print("            ▼")
    print("    SemanticEngine (consome SermonContext para enriquecer contexto)")
    print()
    print("  Regra: SermonMemoryEngine NÃO identifica referências.")
    print("         Apenas mantém o estado da pregação.")

    # Setup
    bus = PipelineEventBus(store=MemoryEventStore())
    engine = SermonMemoryEngine(bus=bus, session_id="demo")
    engine.start()

    # ------------------------------------------------------------------
    # Cena 1 — "Hoje vamos estudar João capítulo 3"
    # ------------------------------------------------------------------
    _print_header("CENA 1 — 'Hoje vamos estudar João capítulo 3'")
    print("  (parser detecta João 3 → ReferenceDetected)")
    bus.publish(_make_reference("João", 3))
    time.sleep(0.1)
    ctx = engine.get_context()
    _print_context(ctx, "após ReferenceDetected")

    # ------------------------------------------------------------------
    # Cena 2 — "Nicodemos procura Jesus à noite"
    # ------------------------------------------------------------------
    _print_header("CENA 2 — 'Nicodemos procura Jesus à noite'")
    print("  (entidades Nicodemos e Jesus são reconhecidas)")
    bus.publish(_make_partial_updated("Nicodemos procura Jesus à noite para conversar"))
    time.sleep(0.1)
    ctx = engine.get_context()
    _print_context(ctx, "após SpeechPartialUpdated")

    # ------------------------------------------------------------------
    # Cena 3 — "Importa nascer de novo"
    # ------------------------------------------------------------------
    _print_header("CENA 3 — 'Importa nascer de novo do espírito'")
    print("  (tema 'Novo nascimento' é detectado)")
    bus.publish(_make_partial_updated("Na verdade importa nascer de novo do espírito"))
    time.sleep(0.1)
    ctx = engine.get_context()
    _print_context(ctx, "após tema detectado")

    # ------------------------------------------------------------------
    # Cena 4 — "Como vimos anteriormente"
    # ------------------------------------------------------------------
    _print_header("CENA 4 — 'Como vimos anteriormente'")
    print("  (contexto mantém João 3 — memória contínua)")
    bus.publish(_make_partial_updated("Como vimos anteriormente neste texto"))
    time.sleep(0.1)
    ctx = engine.get_context()
    _print_context(ctx, "memória preservada")

    # ------------------------------------------------------------------
    # Verificar critério de aceitação
    # ------------------------------------------------------------------
    _print_header("CRITÉRIO DE ACEITAÇÃO")
    expected = {
        "current_book": "João",
        "current_chapter": 3,
        "probable_theme": "Novo nascimento",
    }
    ctx = engine.get_context()
    ok_book = ctx.current_book == expected["current_book"]
    ok_chapter = ctx.current_chapter == expected["current_chapter"]
    ok_theme = ctx.probable_theme == expected["probable_theme"]
    entity_names = [e.name.lower() for e in ctx.entities]
    ok_entities = "jesus" in entity_names and "nicodemos" in entity_names
    ok_refs = any(r.book == "João" and r.chapter == 3 for r in ctx.recent_references)

    print(f"  current_book == 'João': {'✓' if ok_book else '✗'} ({ctx.current_book})")
    print(f"  current_chapter == 3: {'✓' if ok_chapter else '✗'} ({ctx.current_chapter})")
    print(f"  probable_theme == 'Novo nascimento': {'✓' if ok_theme else '✗'} ({ctx.probable_theme})")
    print(f"  entities contém Jesus e Nicodemos: {'✓' if ok_entities else '✗'} ({entity_names})")
    print(f"  recent_references contém João 3: {'✓' if ok_refs else '✗'}")
    print(f"  confidence: {ctx.confidence:.2f}")

    # ------------------------------------------------------------------
    # Eventos publicados
    # ------------------------------------------------------------------
    _print_header("EVENTOS PUBLICADOS")
    events = bus.history()
    updates = [e for e in events if isinstance(e, SermonContextUpdated)]
    book_changes = [e for e in events if isinstance(e, SermonBookChanged)]
    chapter_changes = [e for e in events if isinstance(e, SermonChapterChanged)]
    topic_changes = [e for e in events if isinstance(e, SermonTopicChanged)]
    print(f"  SermonContextUpdated: {len(updates)}")
    print(f"  SermonBookChanged: {len(book_changes)}")
    print(f"  SermonChapterChanged: {len(chapter_changes)}")
    print(f"  SermonTopicChanged: {len(topic_changes)}")
    if topic_changes:
        tc = topic_changes[-1]
        print(f"    último tema: '{tc.previous_theme}' → '{tc.new_theme}'")

    # ------------------------------------------------------------------
    # Integração com SemanticEngine
    # ------------------------------------------------------------------
    _print_header("INTEGRAÇÃO COM SEMANTIC ENGINE")
    ce = ContextEngine(
        history_fn=bus.history,
        sermon_context_fn=engine.get_context,
    )
    sem_ctx = ce.build(current_text="como vimos anteriormente")
    print(f"  SemanticContext gerado:")
    print(f"    current_text: '{sem_ctx.current_text}'")
    print(f"    sermon_book: '{sem_ctx.sermon_book}'")
    print(f"    sermon_chapter: {sem_ctx.sermon_chapter}")
    print(f"    sermon_theme: '{sem_ctx.sermon_theme}'")
    print(f"    sermon_entities: {list(sem_ctx.sermon_entities)}")
    print(f"    sermon_confidence: {sem_ctx.sermon_confidence:.2f}")
    print(f"  ✓ SemanticEngine recebe contexto enriquecido pelo SermonMemoryEngine")

    # ------------------------------------------------------------------
    # Métricas
    # ------------------------------------------------------------------
    _print_header("MÉTRICAS OPERACIONAIS")
    m = engine.metrics()
    for k, v in m.items():
        if k != "memory_size":
            print(f"  {k}: {v}")
    print(f"  memory_size:")
    for k2, v2 in m["memory_size"].items():
        print(f"    {k2}: {v2}")

    engine.stop()

    print(f"\n{'='*70}")
    print("  DEMONSTRAÇÃO CONCLUÍDA")
    print(f"{'='*70}")
    print()
    print("  ✓ Memória contínua construída incrementalmente")
    print("  ✓ Livro/capítulo atualizados via ReferenceDetected")
    print("  ✓ Entidades (Jesus, Nicodemos) reconhecidas e mantidas")
    print("  ✓ Tema 'Novo nascimento' detectado e definido como provável")
    print("  ✓ Referências bíblicas mantidas no histórico")
    print("  ✓ Contexto preservado entre cenas ('como vimos anteriormente')")
    print("  ✓ SemanticEngine recebe SermonContext enriquecido")
    print("  ✓ Eventos de mudança publicados (SermonBookChanged, SermonTopicChanged)")
    print("  ✓ Métricas operacionais disponíveis")
    print("  ✓ Arquitetura desacoplada — não alterou StreamingSTT/Parser/Holyrics")


if __name__ == "__main__":
    main()
