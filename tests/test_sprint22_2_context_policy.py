"""Sprint 22.2 — Testes unitários da ContextPolicy.

Cobre os três níveis de confiança da recuperação (alta_confianca,
ambiguidade_moderada, alta_ambiguidade), os três modos de inclusão
do contexto (omit, summary, full), e os critérios auxiliares
(sem sermon_book, confiança do SermonMemory abaixo do mínimo).

Princípio sob teste: BibleRetriever > Texto Atual > Contexto do Sermão.
Quando há candidato dominante, o contexto é omitido mesmo se o
SermonMemory apontar para outro livro.
"""
from __future__ import annotations

from config.models import RagPolicyConfig, SermonContextPolicyConfig
from knowledge.types import (
    BibleCandidate,
    BibleVersionMatch,
    RetrievalMeta,
    compute_retrieval_meta,
)
from semantic.context_policy import (
    CONTEXT_FULL,
    CONTEXT_OMIT,
    CONTEXT_SUMMARY,
    LEVEL_ALTA_AMBIGUIDADE,
    LEVEL_ALTA_CONFIANCA,
    LEVEL_AMBIGUIDADE_MODERADA,
    ContextPolicy,
)


def _cand(
    book: str,
    ref: str,
    score: float,
    book_ref_id: int = 1,
    num_versions: int = 3,
) -> BibleCandidate:
    """Constrói um BibleCandidate de teste."""
    versions = tuple(
        BibleVersionMatch(version=f"V{i}", text=f"texto {i}", score=score)
        for i in range(num_versions)
    )
    return BibleCandidate(
        book=book,
        book_reference_id=book_ref_id,
        chapter=1,
        verse=1,
        canonical_reference=ref,
        aggregated_score=score,
        versions=versions,
        best_score=score,
        mean_score=score,
        num_versions=num_versions,
        search_rank=1,
    )


def _meta(top1: float, top2: float, n: int = 2) -> RetrievalMeta:
    """Constrói RetrievalMeta diretamente (sem depender de candidatos)."""
    return RetrievalMeta(
        top1_score=top1,
        top2_score=top2,
        gap=top1 - top2 if n >= 2 else top1,
        num_candidates=n,
        top1_book="Numeros",
        top1_reference="Numeros 6:24",
        top1_num_versions=7,
    )


# ---------------------------------------------------------------------
# Nível: alta confiança (candidato dominante)
# ---------------------------------------------------------------------


def test_alta_confianca_top1_dominante_omite_contexto():
    """Top1 score alto + gap grande → contexto omitido, mesmo com sermon_book."""
    cp = ContextPolicy()
    meta = _meta(top1=1.0, top2=0.91, n=2)  # gap=0.09 >= 0.08
    d = cp.decide(meta, sermon_book="Salmos", sermon_confidence=0.8)
    assert d.level == LEVEL_ALTA_CONFIANCA
    assert d.include_context == CONTEXT_OMIT
    assert "dominant_candidate" in d.reason
    assert d.sermon_book == "Salmos"


def test_alta_confianca_top1_exatamente_no_limiar():
    """Top1 = 0.98 (limiar) e gap = 0.08 (limiar) → alta confiança."""
    cp = ContextPolicy()
    meta = _meta(top1=0.98, top2=0.90, n=2)  # gap=0.08
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_ALTA_CONFIANCA
    assert d.include_context == CONTEXT_OMIT


def test_alta_confianca_top1_abaixo_do_limiar_nao_e_dominante():
    """Top1 < 0.98 → não é alta confiança mesmo com gap grande."""
    cp = ContextPolicy()
    meta = _meta(top1=0.95, top2=0.50, n=2)  # gap=0.45 mas top1 < 0.98
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    # gap >= dominant_gap mas top1 < dominant_score → moderada
    assert d.level == LEVEL_AMBIGUIDADE_MODERADA
    assert d.include_context == CONTEXT_SUMMARY


# ---------------------------------------------------------------------
# Nível: ambiguidade moderada
# ---------------------------------------------------------------------


def test_ambiguidade_moderada_gap_intermediario():
    """Gap entre ambiguity_gap e dominant_gap → contexto resumido."""
    cp = ContextPolicy()
    # gap=0.05 está em [0.03, 0.08)
    meta = _meta(top1=0.92, top2=0.87, n=2)
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_AMBIGUIDADE_MODERADA
    assert d.include_context == CONTEXT_SUMMARY
    assert "moderate_ambiguity" in d.reason


def test_ambiguidade_moderada_top1_abaixo_dominant_score_gap_grande():
    """Top1 < dominant_score e gap >= dominant_gap → moderada (não alta)."""
    cp = ContextPolicy()
    # top1=0.90 < 0.98, gap=0.10 >= 0.08 → moderada (top1 fraco)
    meta = _meta(top1=0.90, top2=0.80, n=2)
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_AMBIGUIDADE_MODERADA
    assert d.include_context == CONTEXT_SUMMARY


# ---------------------------------------------------------------------
# Nível: alta ambiguidade
# ---------------------------------------------------------------------


def test_alta_ambiguidade_gap_pequeno():
    """Gap < ambiguity_gap → alta ambiguidade, contexto completo."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.89, n=2)  # gap=0.02 < 0.03
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_ALTA_AMBIGUIDADE
    assert d.include_context == CONTEXT_FULL
    assert "high_ambiguity" in d.reason


def test_alta_ambiguidade_zero_candidatos():
    """Sem candidatos → alta ambiguidade (sem evidência)."""
    cp = ContextPolicy()
    meta = RetrievalMeta(
        top1_score=0.0, top2_score=0.0, gap=0.0,
        num_candidates=0, top1_book="", top1_reference="",
        top1_num_versions=0,
    )
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_ALTA_AMBIGUIDADE
    assert d.include_context == CONTEXT_FULL


# ---------------------------------------------------------------------
# Critério: sem sermon_book
# ---------------------------------------------------------------------


def test_sem_sermon_book_sempre_omite():
    """Sem sermon_book → contexto omitido independentemente do nível."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.89, n=2)  # alta ambiguidade
    d = cp.decide(meta, sermon_book=None, sermon_confidence=0.0)
    assert d.include_context == CONTEXT_OMIT
    assert d.reason == "no_sermon_book"
    assert d.sermon_book == ""


def test_sermon_book_vazio_string_omito():
    """sermon_book="" → tratado como ausente."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.89, n=2)
    d = cp.decide(meta, sermon_book="", sermon_confidence=0.0)
    assert d.include_context == CONTEXT_OMIT
    assert d.reason == "no_sermon_book"


# ---------------------------------------------------------------------
# Critério: confiança do SermonMemory abaixo do mínimo
# ---------------------------------------------------------------------


def test_sermon_confidence_abaixo_do_minimo_omite_mesmo_alta_ambiguidade():
    """Confiança < min_confidence → omitido mesmo em alta ambiguidade."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.89, n=2)  # alta ambiguidade
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.20)
    # min_confidence default = 0.40, 0.20 < 0.40 → omit
    assert d.include_context == CONTEXT_OMIT
    assert "sermon_confidence_below_min" in d.reason


def test_sermon_confidence_exatamente_no_minimo_inclui():
    """Confiança == min_confidence → inclui (fronteira inclusiva)."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.89, n=2)  # alta ambiguidade
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.40)
    # 0.40 == min_confidence (não é < min) → full
    assert d.include_context == CONTEXT_FULL


# ---------------------------------------------------------------------
# Casos de aceite do enunciado
# ---------------------------------------------------------------------


def test_caso_aceitacao_1_numeros_6_24_com_contexto_salmos():
    """'O Senhor te abençoe' → Números 6:24 dominante, mesmo com
    contexto 'pregando em Salmos'. Deve omitir contexto."""
    cp = ContextPolicy()
    # Simula recuperação do BibleRetriever para Números 6:24
    # (score 1.00, gap grande vs 2º colocado)
    meta = _meta(top1=1.0, top2=0.91, n=2)
    d = cp.decide(meta, sermon_book="Salmos", sermon_confidence=0.85)
    assert d.level == LEVEL_ALTA_CONFIANCA
    assert d.include_context == CONTEXT_OMIT
    # Top1 (Números) deve prevalecer sobre contexto (Salmos)
    assert d.sermon_book == "Salmos"  # echo do que foi considerado


def test_caso_aceitacao_2_mateus_28_19_com_contexto_romanos():
    """'Portanto, vão e façam discípulos' → Mateus 28:19 dominante,
    mesmo com contexto 'Romanos'. Deve omitir contexto."""
    cp = ContextPolicy()
    meta = _meta(top1=1.0, top2=0.91, n=2)
    d = cp.decide(meta, sermon_book="Romanos", sermon_confidence=0.85)
    assert d.level == LEVEL_ALTA_CONFIANCA
    assert d.include_context == CONTEXT_OMIT


def test_caso_aceitacao_3_candidatos_empatados_contexto_participa():
    """Candidatos empatados → contexto completo para desambiguação."""
    cp = ContextPolicy()
    meta = _meta(top1=0.91, top2=0.90, n=2)  # gap=0.01 < 0.03
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_ALTA_AMBIGUIDADE
    assert d.include_context == CONTEXT_FULL


def test_caso_aceitacao_4_migracao_natural_nao_coberto_por_policy():
    """Caso 4 (migração do SermonMemory) é responsabilidade do
    SermonMemory + heurísticas do BookConfidence dinâmico (Sprint 22.3).
    A ContextPolicy apenas lê sermon_confidence. Aqui validamos que
    se a confiança cair abaixo do mínimo após migração, contexto é
    omitido, permitindo que nova inferência não seja ancorada."""
    cp = ContextPolicy()
    meta = _meta(top1=1.0, top2=0.91, n=2)
    # Após várias inferências contraditórias, confiança caiu
    d = cp.decide(meta, sermon_book="Velho_Livro", sermon_confidence=0.20)
    assert d.include_context == CONTEXT_OMIT
    assert "sermon_confidence_below_min" in d.reason


# ---------------------------------------------------------------------
# Configuração customizada
# ---------------------------------------------------------------------


def test_config_custom_dominant_score_mais_baixo():
    """Config com dominant_score=0.90 → top1=0.92 vira alta confiança."""
    rag = RagPolicyConfig(dominant_score=0.90, dominant_gap=0.08, ambiguity_gap=0.03)
    ctx = SermonContextPolicyConfig(min_confidence=0.40, remove_when_confidence_below=0.25)
    cp = ContextPolicy(rag=rag, context=ctx)
    meta = _meta(top1=0.92, top2=0.80, n=2)  # gap=0.12 >= 0.08, top1 >= 0.90
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.7)
    assert d.level == LEVEL_ALTA_CONFIANCA
    assert d.include_context == CONTEXT_OMIT


def test_config_custom_min_confidence_mais_alto():
    """Config com min_confidence=0.60 → 0.50 vira omitido."""
    rag = RagPolicyConfig()
    ctx = SermonContextPolicyConfig(min_confidence=0.60, remove_when_confidence_below=0.25)
    cp = ContextPolicy(rag=rag, context=ctx)
    meta = _meta(top1=0.91, top2=0.89, n=2)  # alta ambiguidade
    d = cp.decide(meta, sermon_book="Joao", sermon_confidence=0.50)
    assert d.include_context == CONTEXT_OMIT
    assert "sermon_confidence_below_min" in d.reason


# ---------------------------------------------------------------------
# compute_retrieval_meta (helper)
# ---------------------------------------------------------------------


def test_compute_retrieval_meta_lista_vazia():
    meta = compute_retrieval_meta([])
    assert meta.top1_score == 0.0
    assert meta.top2_score == 0.0
    assert meta.gap == 0.0
    assert meta.num_candidates == 0
    assert meta.top1_book == ""


def test_compute_retrieval_meta_um_candidato():
    c = _cand("Numeros", "Numeros 6:24", 0.99)
    meta = compute_retrieval_meta([c])
    assert meta.top1_score == 0.99
    assert meta.top2_score == 0.0
    assert meta.gap == 0.99  # top1 - 0
    assert meta.num_candidates == 1
    assert meta.top1_book == "Numeros"
    assert meta.top1_reference == "Numeros 6:24"


def test_compute_retrieval_meta_dois_candidatos():
    c1 = _cand("Numeros", "Numeros 6:24", 0.99, book_ref_id=4)
    c2 = _cand("Salmos", "Salmos 23:1", 0.91, book_ref_id=19)
    meta = compute_retrieval_meta([c1, c2])
    assert meta.top1_score == 0.99
    assert meta.top2_score == 0.91
    assert abs(meta.gap - 0.08) < 1e-6
    assert meta.num_candidates == 2


# ---------------------------------------------------------------------
# to_dict (telemetria)
# ---------------------------------------------------------------------


def test_context_decision_to_dict_campos_completos():
    cp = ContextPolicy()
    meta = _meta(top1=1.0, top2=0.91, n=2)
    d = cp.decide(meta, sermon_book="Salmos", sermon_confidence=0.85)
    d_dict = d.to_dict()
    assert d_dict["level"] == LEVEL_ALTA_CONFIANCA
    assert d_dict["include_context"] == CONTEXT_OMIT
    assert "reason" in d_dict
    assert d_dict["top1_score"] == 1.0
    assert d_dict["top2_score"] == 0.91
    assert d_dict["num_candidates"] == 2
    assert d_dict["sermon_book"] == "Salmos"
    assert d_dict["sermon_confidence"] == 0.85
