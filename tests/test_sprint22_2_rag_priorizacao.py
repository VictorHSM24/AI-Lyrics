"""Sprint 22.2 — Testes de integração dos 4 casos de aceite.

Valida o fluxo completo: SemanticEngine + ContextPolicy + BibleRetriever
(mockado) + StubProvider, garantindo que o princípio RAG
(BibleRetriever > Texto Atual > Contexto do Sermão) é respeitado.

Os 4 casos de aceite do enunciado:
1. "O Senhor te abençoe" → Números 6:24, mesmo com contexto "Salmos".
2. "Portanto, vão e façam discípulos" → Mateus 28:19, mesmo com contexto
   "Romanos".
3. Candidatos empatados → contexto participa da decisão.
4. Após várias inferências apontando para outro livro → SermonMemory
   migra naturalmente (validado parcialmente: confiança cai → contexto
   omitido → nova inferência não é ancorada).

Para isolamento do BibleRetriever real (que depende de bases SQLite
locais e pode não estar disponível em CI), usamos um MockRetriever
que retorna candidatos pré-definidos.
"""
from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from pipeline.bus import PipelineEventBus
from pipeline.events import (
    IntentCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
)
from pipeline.metadata import EventMetadata
from semantic.engine import SemanticEngine
from semantic.local_provider import StubProvider
from semantic.context_engine import ContextEngine
from semantic.cache import SemanticCache
from semantic.context_policy import (
    CONTEXT_FULL,
    CONTEXT_OMIT,
    CONTEXT_SUMMARY,
    ContextPolicy,
)
from knowledge.types import BibleCandidate, BibleVersionMatch
from sermon.engine import SermonMemoryEngine
from sermon.types import SermonContext


# ---------------------------------------------------------------------------
# Mock BibleRetriever — retorna candidatos pré-definidos
# ---------------------------------------------------------------------------


class MockRetriever:
    """Mock do BibleRetriever que retorna candidatos pré-definidos.

    Imita a interface pública do BibleRetriever real:
    - is_ready: True após warmup.
    - retrieve(text, top_k): retorna lista de BibleCandidate.
    - close(): no-op.
    """

    def __init__(self, candidates_by_query: dict[str, list[BibleCandidate]]):
        self._candidates_by_query = candidates_by_query
        self._warmed_up = True
        self.is_ready = True

    def retrieve(self, text: str, top_k: int = 20) -> list[BibleCandidate]:
        text_lower = text.lower().strip()
        for query_key, candidates in self._candidates_by_query.items():
            if query_key in text_lower:
                return candidates[:top_k]
        return []

    def close(self) -> None:
        pass


def _cand(
    book: str, ref: str, score: float, book_ref_id: int, num_versions: int = 3,
    chapter: int = 1, verse: int = 1,
) -> BibleCandidate:
    versions = tuple(
        BibleVersionMatch(version=f"V{i}", text=f"texto {i}", score=score)
        for i in range(num_versions)
    )
    return BibleCandidate(
        book=book, book_reference_id=book_ref_id,
        chapter=chapter, verse=verse,
        canonical_reference=ref, aggregated_score=score,
        versions=versions, best_score=score, mean_score=score,
        num_versions=num_versions, search_rank=1,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(correlation_id: str | None = None) -> EventMetadata:
    return EventMetadata.for_initial(
        session_id="test-session", origin="test",
        correlation_id=correlation_id,
    )


def _make_committed(
    text: str, correlation_id: str | None = None,
) -> SpeechCommittedWords:
    """Cria SpeechCommittedWords (Sprint 28 — substitui _make_partial_updated)."""
    return SpeechCommittedWords(
        meta=_make_meta(correlation_id=correlation_id),
        committed_text=text, full_committed_text=text,
        words=tuple(), language="pt",
        confidence=0.9, latency_ms=100, audio_duration_ms=2000,
    )


def _make_ref_detected(
    book: str, chapter: int, correlation_id: str | None = None,
) -> ReferenceDetected:
    return ReferenceDetected(
        meta=_make_meta(correlation_id=correlation_id),
        book=book, chapter=chapter, verse_start=0, verse_end=0,
        confidence=0.9, raw_text="",
    )


def _make_bus() -> PipelineEventBus:
    return PipelineEventBus(store=MagicMock())


class _EventCollector:
    def __init__(self, bus: PipelineEventBus, event_types: list) -> None:
        self.events: list = []
        for et in event_types:
            bus.subscribe(et, self.events.append)

    def of_type(self, et) -> list:
        return [e for e in self.events if isinstance(e, et)]


def _parse_candidates(intent: IntentCandidate) -> list[dict]:
    """Extrai os candidatos de um IntentCandidate (candidates_json)."""
    return json.loads(intent.candidates_json) if intent.candidates_json else []


def _make_engine(
    bus: PipelineEventBus,
    *,
    bible_retriever: Any = None,
    context_policy: Any = None,
    sermon_context_fn: Any = None,
) -> SemanticEngine:
    return SemanticEngine(
        bus=bus,
        provider=StubProvider(),
        context_engine=ContextEngine(
            history_fn=bus.history,
            sermon_context_fn=sermon_context_fn,
        ),
        cache=SemanticCache(),
        session_id="test-session",
        debounce_ms=0,
        timeout_ms=5000,
        enabled=True,
        min_growth_chars=5,
        min_append_words=1,
        min_interval_ms=0,
        bible_retriever=bible_retriever,
        rag_top_k=10,
        rag_fallback_on_empty=True,
        context_policy=context_policy,
    )


def _make_sermon_context_fn(
    book: str | None, chapter: int | None, book_confidence: float,
) -> Any:
    """Cria um callable que retorna um SermonContext fixo."""
    ctx = SermonContext(
        current_book=book,
        current_chapter=chapter,
        current_book_confidence=book_confidence,
        confidence=book_confidence,
    )
    return lambda: ctx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def context_policy():
    return ContextPolicy()


@pytest.fixture
def mock_retriever_numeros():
    """Retriever que retorna Números 6:24 como top1 dominante."""
    return MockRetriever({
        "abençoe": [
            _cand("Números", "Números 6:24", 1.00, 4, chapter=6, verse=24),
            _cand("Salmos", "Salmos 67:1", 0.91, 19, chapter=67, verse=1),
        ],
    })


@pytest.fixture
def mock_retriever_mateus():
    """Retriever que retorna Mateus 28:19 como top1 dominante."""
    return MockRetriever({
        "discípulos": [
            _cand("Mateus", "Mateus 28:19", 1.00, 40, chapter=28, verse=19),
            _cand("Romanos", "Romanos 1:5", 0.91, 45, chapter=1, verse=5),
        ],
    })


@pytest.fixture
def mock_retriever_empatados():
    """Retriever que retorna dois candidatos empatados."""
    return MockRetriever({
        "amor": [
            _cand("João", "João 3:16", 0.91, 43, chapter=3, verse=16),
            _cand("Romanos", "Romanos 5:8", 0.90, 45, chapter=5, verse=8),
        ],
    })


# ---------------------------------------------------------------------------
# Caso 1: Números 6:24 com contexto Salmos
# ---------------------------------------------------------------------------


class TestCasoAceitacao1:
    def test_numeros_24_prevalece_sobre_contexto_salmos(
        self, mock_retriever_numeros, context_policy,
    ):
        """Top1=Números 6:24 (dominante) deve prevalecer mesmo com
        sermon_book=Salmos. Contexto omitido pelo policy."""
        bus = _make_bus()
        sermon_fn = _make_sermon_context_fn("Salmos", 23, 0.85)
        engine = _make_engine(
            bus, bible_retriever=mock_retriever_numeros,
            context_policy=context_policy,
            sermon_context_fn=sermon_fn,
        )
        engine.start()
        collector = _EventCollector(bus, [IntentCandidate])

        bus.publish(_make_committed(
            "O Senhor te abençoe e te guarde",
            correlation_id="caso1",
        ))
        time.sleep(0.3)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1
        cands = _parse_candidates(intents[0])
        assert len(cands) == 1
        # StubProvider escolhe top1 = Números 6:24
        assert cands[0]["book"] == "Números"
        assert cands[0]["chapter"] == 6
        assert cands[0]["verse"] == 24

    def test_context_policy_omite_contexto_salmos(
        self, mock_retriever_numeros, context_policy,
    ):
        """Valida que a ContextPolicy classifica como alta_confiança
        e decide omitir o contexto Salmos."""
        bus = _make_bus()
        # Capturar o contexto enviado ao provider via spy no StubProvider.
        contexts_seen: list = []
        original_infer = StubProvider.infer

        class SpyProvider(StubProvider):
            def infer(self, context, timeout_ms=5000):
                contexts_seen.append(context)
                return super().infer(context, timeout_ms)

        sermon_fn = _make_sermon_context_fn("Salmos", 23, 0.85)
        engine = SemanticEngine(
            bus=bus,
            provider=SpyProvider(),
            context_engine=ContextEngine(
                history_fn=bus.history, sermon_context_fn=sermon_fn,
            ),
            cache=SemanticCache(),
            session_id="test",
            debounce_ms=0, timeout_ms=5000, enabled=True,
            min_growth_chars=5, min_append_words=1, min_interval_ms=0,
            bible_retriever=mock_retriever_numeros,
            rag_top_k=10, rag_fallback_on_empty=True,
            context_policy=context_policy,
        )
        engine.start()
        bus.publish(_make_committed(
            "O Senhor te abençoe e te guarde", correlation_id="spy1",
        ))
        time.sleep(0.3)
        engine.stop()

        assert len(contexts_seen) >= 1
        ctx = contexts_seen[0]
        # ContextPolicy deve ter setado a decisão
        assert ctx.context_decision is not None
        assert ctx.context_decision.include_context == CONTEXT_OMIT
        assert ctx.context_decision.level == "alta_confianca"


# ---------------------------------------------------------------------------
# Caso 2: Mateus 28:19 com contexto Romanos
# ---------------------------------------------------------------------------


class TestCasoAceitacao2:
    def test_mateus_28_19_prevalece_sobre_contexto_romanos(
        self, mock_retriever_mateus, context_policy,
    ):
        """Top1=Mateus 28:19 (dominante) deve prevalecer mesmo com
        sermon_book=Romanos."""
        bus = _make_bus()
        sermon_fn = _make_sermon_context_fn("Romanos", 8, 0.85)
        engine = _make_engine(
            bus, bible_retriever=mock_retriever_mateus,
            context_policy=context_policy,
            sermon_context_fn=sermon_fn,
        )
        engine.start()
        collector = _EventCollector(bus, [IntentCandidate])

        bus.publish(_make_committed(
            "Portanto, vão e façam discípulos de todas as nações",
            correlation_id="caso2",
        ))
        time.sleep(0.3)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1
        cands = _parse_candidates(intents[0])
        assert cands[0]["book"] == "Mateus"
        assert cands[0]["chapter"] == 28
        assert cands[0]["verse"] == 19

    def test_context_policy_omite_contexto_romanos(
        self, mock_retriever_mateus, context_policy,
    ):
        """Valida que a ContextPolicy omite o contexto Romanos."""
        contexts_seen: list = []

        class SpyProvider(StubProvider):
            def infer(self, context, timeout_ms=5000):
                contexts_seen.append(context)
                return super().infer(context, timeout_ms)

        bus = _make_bus()
        sermon_fn = _make_sermon_context_fn("Romanos", 8, 0.85)
        engine = SemanticEngine(
            bus=bus, provider=SpyProvider(),
            context_engine=ContextEngine(
                history_fn=bus.history, sermon_context_fn=sermon_fn,
            ),
            cache=SemanticCache(), session_id="test",
            debounce_ms=0, timeout_ms=5000, enabled=True,
            min_growth_chars=5, min_append_words=1, min_interval_ms=0,
            bible_retriever=mock_retriever_mateus,
            rag_top_k=10, rag_fallback_on_empty=True,
            context_policy=context_policy,
        )
        engine.start()
        bus.publish(_make_committed(
            "Portanto, vão e façam discípulos", correlation_id="spy2",
        ))
        time.sleep(0.3)
        engine.stop()

        assert len(contexts_seen) >= 1
        ctx = contexts_seen[0]
        assert ctx.context_decision is not None
        assert ctx.context_decision.include_context == CONTEXT_OMIT


# ---------------------------------------------------------------------------
# Caso 3: Candidatos empatados → contexto participa
# ---------------------------------------------------------------------------


class TestCasoAceitacao3:
    def test_candidatos_empatados_contexto_completo(
        self, mock_retriever_empatados, context_policy,
    ):
        """Candidatos empatados (gap < ambiguity_gap) → contexto completo."""
        contexts_seen: list = []

        class SpyProvider(StubProvider):
            def infer(self, context, timeout_ms=5000):
                contexts_seen.append(context)
                return super().infer(context, timeout_ms)

        bus = _make_bus()
        sermon_fn = _make_sermon_context_fn("João", 3, 0.75)
        engine = SemanticEngine(
            bus=bus, provider=SpyProvider(),
            context_engine=ContextEngine(
                history_fn=bus.history, sermon_context_fn=sermon_fn,
            ),
            cache=SemanticCache(), session_id="test",
            debounce_ms=0, timeout_ms=5000, enabled=True,
            min_growth_chars=5, min_append_words=1, min_interval_ms=0,
            bible_retriever=mock_retriever_empatados,
            rag_top_k=10, rag_fallback_on_empty=True,
            context_policy=context_policy,
        )
        engine.start()
        bus.publish(_make_committed(
            "Porque Deus mostra o seu amor", correlation_id="caso3",
        ))
        time.sleep(0.3)
        engine.stop()

        assert len(contexts_seen) >= 1
        ctx = contexts_seen[0]
        assert ctx.context_decision is not None
        # gap = 0.91 - 0.90 = 0.01 < 0.03 → alta ambiguidade → full
        assert ctx.context_decision.include_context == CONTEXT_FULL
        assert ctx.context_decision.level == "alta_ambiguidade"

    def test_stub_escolhe_top1_mesmo_empatado(
        self, mock_retriever_empatados, context_policy,
    ):
        """StubProvider escolhe top1 (João 3:16) mesmo empatado."""
        bus = _make_bus()
        sermon_fn = _make_sermon_context_fn("João", 3, 0.75)
        engine = _make_engine(
            bus, bible_retriever=mock_retriever_empatados,
            context_policy=context_policy,
            sermon_context_fn=sermon_fn,
        )
        engine.start()
        collector = _EventCollector(bus, [IntentCandidate])
        bus.publish(_make_committed(
            "Porque Deus mostra o seu amor", correlation_id="caso3b",
        ))
        time.sleep(0.3)
        engine.stop()

        intents = collector.of_type(IntentCandidate)
        assert len(intents) >= 1
        cands = _parse_candidates(intents[0])
        assert cands[0]["book"] == "João"


# ---------------------------------------------------------------------------
# Caso 4: Migração natural do SermonMemory
# ---------------------------------------------------------------------------


class TestCasoAceitacao4:
    def test_sermon_memory_confidence_cai_apos_livro_mudar(self):
        """Quando uma nova ReferenceDetected chega com livro diferente,
        a current_book_confidence reseta para o valor inicial (0.50)
        em vez de manter a confiança alta do livro anterior."""
        bus = _make_bus()
        engine = SermonMemoryEngine(bus=bus, session_id="test-sermon")
        engine.start()

        # 1. Pregador começa em João 3 — confiança inicial 0.50.
        bus.publish(_make_ref_detected("João", 3, correlation_id="r1"))
        time.sleep(0.1)
        ctx1 = engine.get_context()
        assert ctx1.current_book == "João"
        assert abs(ctx1.current_book_confidence - 0.50) < 1e-6

        # 2. Mais referências a João — confiança reforça.
        bus.publish(_make_ref_detected("João", 4, correlation_id="r2"))
        time.sleep(0.1)
        bus.publish(_make_ref_detected("João", 5, correlation_id="r3"))
        time.sleep(0.1)
        ctx2 = engine.get_context()
        assert ctx2.current_book == "João"
        # 0.50 + 0.15 + 0.15 = 0.80
        assert abs(ctx2.current_book_confidence - 0.80) < 1e-6

        # 3. Pregador migra para Romanos — confiança reseta para 0.50.
        bus.publish(_make_ref_detected("Romanos", 8, correlation_id="r4"))
        time.sleep(0.1)
        ctx3 = engine.get_context()
        assert ctx3.current_book == "Romanos"
        assert abs(ctx3.current_book_confidence - 0.50) < 1e-6

        engine.stop()

    def test_context_policy_omite_contexto_apos_confianca_cair(
        self, mock_retriever_numeros, context_policy,
    ):
        """Após migração, se a confiança do novo livro ainda for baixa
        (< min_confidence), a ContextPolicy omite o contexto, evitando
        ancoragem prematura no novo livro."""
        contexts_seen: list = []

        class SpyProvider(StubProvider):
            def infer(self, context, timeout_ms=5000):
                contexts_seen.append(context)
                return super().infer(context, timeout_ms)

        bus = _make_bus()
        # Simula SermonMemory logo após trocar de livro: confiança 0.20
        # (abaixo do min_confidence=0.40).
        sermon_fn = _make_sermon_context_fn("NovoLivro", 1, 0.20)
        engine = SemanticEngine(
            bus=bus, provider=SpyProvider(),
            context_engine=ContextEngine(
                history_fn=bus.history, sermon_context_fn=sermon_fn,
            ),
            cache=SemanticCache(), session_id="test",
            debounce_ms=0, timeout_ms=5000, enabled=True,
            min_growth_chars=5, min_append_words=1, min_interval_ms=0,
            bible_retriever=mock_retriever_numeros,
            rag_top_k=10, rag_fallback_on_empty=True,
            context_policy=context_policy,
        )
        engine.start()
        bus.publish(_make_committed(
            "O Senhor te abençoe", correlation_id="caso4",
        ))
        time.sleep(0.3)
        engine.stop()

        assert len(contexts_seen) >= 1
        ctx = contexts_seen[0]
        assert ctx.context_decision is not None
        # Confiança 0.20 < min 0.40 → omitido (não ancorar em NovoLivro)
        assert ctx.context_decision.include_context == CONTEXT_OMIT
        assert "sermon_confidence_below_min" in ctx.context_decision.reason


# ---------------------------------------------------------------------------
# Validação das 3 variantes do prompt no LocalLLMProvider
# ---------------------------------------------------------------------------


class TestVariantesPrompt:
    """Valida que o LocalLLMProvider gera as 3 variantes corretas."""

    def _build_context(
        self, include: str, sermon_book: str = "Salmos",
    ):
        from semantic.types import SemanticContext
        from semantic.context_policy import ContextDecision

        cand = _cand("Números", "Números 6:24", 1.00, 4, chapter=6, verse=24)
        decision = ContextDecision(
            level="alta_confianca", include_context=include,
            reason="test", top1_score=1.0, top2_score=0.91, gap=0.09,
            sermon_confidence=0.8, sermon_book=sermon_book,
            num_candidates=2,
        )
        return SemanticContext(
            current_text="O Senhor te abençoe",
            sermon_book=sermon_book,
            sermon_chapter=23,
            sermon_theme="Proteção",
            sermon_entities=("Deus",),
            sermon_confidence=0.8,
            rag_candidates=(cand,),
            context_decision=decision,
        )

    def test_variante_omit_nao_tem_contexto_sermão(self):
        from semantic.local_provider import LocalLLMProvider
        provider = LocalLLMProvider.__new__(LocalLLMProvider)
        ctx = self._build_context(CONTEXT_OMIT)
        prompt = provider._build_user_prompt(ctx)
        # Variante alta confiança: sem "Contexto do sermão"
        assert "Contexto do sermão" not in prompt
        assert "Texto ouvido" in prompt
        assert "Escolha o melhor" in prompt

    def test_variante_summary_so_tem_livro(self):
        from semantic.local_provider import LocalLLMProvider
        provider = LocalLLMProvider.__new__(LocalLLMProvider)
        ctx = self._build_context(CONTEXT_SUMMARY)
        prompt = provider._build_user_prompt(ctx)
        # Variante moderada: tem "Contexto do sermão (auxiliar): pregando em Salmos"
        # mas NÃO tem tema nem entidades.
        assert "Contexto do sermão (auxiliar)" in prompt
        assert "Salmos" in prompt
        assert "Tema atual" not in prompt
        assert "Entidades mencionadas" not in prompt

    def test_variante_full_tem_contexto_completo(self):
        from semantic.local_provider import LocalLLMProvider
        provider = LocalLLMProvider.__new__(LocalLLMProvider)
        ctx = self._build_context(CONTEXT_FULL)
        prompt = provider._build_user_prompt(ctx)
        # Variante alta ambiguidade: contexto completo.
        assert "Contexto do sermão (auxiliar para desambiguação)" in prompt
        assert "Tema atual" in prompt
        assert "Entidades mencionadas" in prompt
