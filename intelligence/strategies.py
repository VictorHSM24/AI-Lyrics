"""Estratégias do Sermon Intelligence.

Cada estratégia analisa um aspecto específico e produz um IntelligenceSignal.
Estratégias são independentes — nenhuma conhece outra.

Design:
  - Cada estratégia é stateless.
  - Recebe (candidate, request, policy) e retorna IntelligenceSignal.
  - Usa apenas interfaces públicas (getattr, duck-typing).
  - Não conhece implementação interna de nenhum módulo.

Estratégias implementadas:
  - ContextStrategy: contexto do sermão favorece o candidato?
  - FeedbackStrategy: há feedback aprendido?
  - ContinuityStrategy: o candidato continua a sequência?
  - ThemeStrategy: o candidato corresponde a temas recentes?
  - BookStrategy: o candidato é do livro ativo/recente?
  - ReferenceStrategy: o candidato é a última referência resolvida?
  - ConfidenceStrategy: sinal agregado de confiança.
  - EvaluationStrategy: estatísticas favorecem o candidato?
"""

from __future__ import annotations

from intelligence.dtos import CandidateInfo, IntelligenceRequest, IntelligenceSignal
from intelligence.evidence import EvidenceFactory, SignalBuilder
from intelligence.policy import IntelligencePolicy
from intelligence.signals import (
    BookSignal,
    ConfidenceSignal,
    ContextSignal,
    ContinuitySignal,
    EvaluationSignal,
    FeedbackSignal,
    ReferenceSignal,
    ThemeSignal,
)


# ---------------------------------------------------------------------------
# Helpers (duck-typing seguro)
# ---------------------------------------------------------------------------


def _safe_getattr(obj, attr, default=None):
    """getattr seguro que retorna default se obj é None."""
    if obj is None:
        return default
    return getattr(obj, attr, default)


# Instâncias compartilhadas (stateless) — criadas uma vez.
_FACTORY = EvidenceFactory()
_BUILDER = SignalBuilder()


# ---------------------------------------------------------------------------
# ContextStrategy
# ---------------------------------------------------------------------------


class ContextStrategy:
    """Estratégia de contexto do sermão.

    Analisa se o contexto atual (livro/capítulo ativo) favorece o candidato.

    Evidences produzidas:
      - CONTEXT_BOOK_MATCH: livro do candidato = livro ativo.
      - CONTEXT_CHAPTER_MATCH: capítulo do candidato = capítulo ativo.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> ContextSignal:
        ctx = request.context
        book = _safe_getattr(ctx, "book", None)
        chapter = _safe_getattr(ctx, "chapter", None)

        if book is None:
            ev = _FACTORY.context_no_match("ctx_01", "vazio", candidate.display or "")
            return _BUILDER.build(
                signal_type="context", weight=policy.weight_context,
                evidences=(ev,), explanation="Sem contexto ativo",
                value_override=0.0,
            )

        if candidate.book and candidate.book == book:
            if chapter is not None and candidate.chapter == chapter:
                ev_book = _FACTORY.book_match(
                    "ctx_01", book, candidate.book,
                    value=policy.context_book_match_bonus)
                ev_ch = _FACTORY.chapter_match(
                    "ctx_02", book, chapter, candidate.book, candidate.chapter,
                    value=policy.context_chapter_match_bonus)
                return _BUILDER.build(
                    signal_type="context", weight=policy.weight_context,
                    evidences=(ev_book, ev_ch),
                    explanation=f"Contexto {book} {chapter} corresponde "
                                f"ao candidato",
                    value_override=policy.context_chapter_match_bonus,
                )
            ev_book = _FACTORY.book_match(
                "ctx_01", book, candidate.book,
                value=policy.context_book_match_bonus)
            return _BUILDER.build(
                signal_type="context", weight=policy.weight_context,
                evidences=(ev_book,),
                explanation=f"Contexto {book} corresponde ao livro do candidato",
                value_override=policy.context_book_match_bonus,
            )

        ev = _FACTORY.context_no_match("ctx_01", book, candidate.book or "")
        return _BUILDER.build(
            signal_type="context", weight=policy.weight_context,
            evidences=(ev,),
            explanation=f"Contexto {book} não corresponde ao candidato",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# FeedbackStrategy
# ---------------------------------------------------------------------------


class FeedbackStrategy:
    """Estratégia de feedback aprendido.

    Analisa se há feedback operacional que favorece o candidato.
    Usa duck-typing para acessar FeedbackSummary.

    Evidences produzidas:
      - FEEDBACK_ACCEPTANCE: aceitações registradas.
      - FEEDBACK_REJECTION: rejeições registradas.
      - FEEDBACK_HISTORY: peso acumulado.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> FeedbackSignal:
        summary = request.feedback_summaries.get(candidate.candidate_id)
        if summary is None:
            ev = _FACTORY.feedback_none("fb_01")
            return _BUILDER.build(
                signal_type="feedback", weight=policy.weight_feedback,
                evidences=(ev,), explanation="Sem feedback registrado",
                value_override=0.0,
            )

        has_feedback = _safe_getattr(summary, "has_feedback", False)
        if not has_feedback:
            ev = _FACTORY.feedback_none("fb_01")
            return _BUILDER.build(
                signal_type="feedback", weight=policy.weight_feedback,
                evidences=(ev,), explanation="Sem feedback registrado",
                value_override=0.0,
            )

        total_weight = _safe_getattr(summary, "total_weight", 0.0)
        acceptances = _safe_getattr(summary, "acceptances", 0)
        rejections = _safe_getattr(summary, "rejections", 0)

        # Coletar evidências
        evidences = []
        if acceptances > 0:
            evidences.append(_FACTORY.feedback_acceptance(
                "fb_acc", acceptances, value=float(acceptances)))
        if rejections > 0:
            evidences.append(_FACTORY.feedback_rejection(
                "fb_rej", rejections, value=-float(rejections)))
        evidences.append(_FACTORY.feedback_history(
            "fb_hist", total_weight, value=total_weight))
        ev_tuple = tuple(evidences)

        if acceptances > rejections and total_weight > 0:
            bonus = policy.feedback_strong_bonus if total_weight >= 5.0 \
                else policy.feedback_weak_bonus
            return _BUILDER.build(
                signal_type="feedback", weight=policy.weight_feedback,
                evidences=ev_tuple,
                explanation=f"Feedback positivo ({acceptances} aceites, "
                            f"peso {total_weight:.1f})",
                value_override=bonus,
            )
        if rejections > acceptances or total_weight < 0:
            return _BUILDER.build(
                signal_type="feedback", weight=policy.weight_feedback,
                evidences=ev_tuple,
                explanation=f"Feedback negativo ({rejections} rejeições, "
                            f"peso {total_weight:.1f})",
                value_override=-policy.feedback_weak_bonus,
            )

        return _BUILDER.build(
            signal_type="feedback", weight=policy.weight_feedback,
            evidences=ev_tuple, explanation="Feedback neutro",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# ContinuityStrategy
# ---------------------------------------------------------------------------


class ContinuityStrategy:
    """Estratégia de continuidade de referências.

    Analisa se o candidato continua a sequência lógica de referências
    recentes (ex.: João 3 → João 3:17).

    Evidences produzidas:
      - CONTINUITY_BOOK: mesmo livro que referência recente.
      - CONTINUITY_CHAPTER: mesmo capítulo que referência recente.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> ContinuitySignal:
        ctx = request.context
        recent_refs = _safe_getattr(ctx, "recent_references", ())
        if not recent_refs:
            ev = _FACTORY.continuity_none("cont_01", "referências recentes")
            return _BUILDER.build(
                signal_type="continuity", weight=policy.weight_continuity,
                evidences=(ev,), explanation="Sem referências recentes",
                value_override=0.0,
            )

        last_ref = recent_refs[0] if recent_refs else None
        if last_ref is None:
            ev = _FACTORY.continuity_none("cont_01", "referência anterior")
            return _BUILDER.build(
                signal_type="continuity", weight=policy.weight_continuity,
                evidences=(ev,), explanation="Sem referência anterior",
                value_override=0.0,
            )

        ref_book = _safe_getattr(last_ref, "book", None)
        ref_chapter = _safe_getattr(last_ref, "chapter", None)
        ref_book_name = _safe_getattr(ref_book, "canonical_name", None) \
            if ref_book is not None else None
        ref_book_str = ref_book_name or (str(ref_book) if ref_book else "")

        if candidate.book and ref_book_str and candidate.book == ref_book_str:
            if candidate.chapter is not None and ref_chapter is not None \
                    and candidate.chapter == ref_chapter:
                ev = _FACTORY.continuity_chapter(
                    "cont_01", ref_book_str, ref_chapter,
                    candidate.book, candidate.chapter,
                    value=policy.continuity_match_bonus)
                return _BUILDER.build(
                    signal_type="continuity", weight=policy.weight_continuity,
                    evidences=(ev,),
                    explanation=f"Continuidade: mesmo livro e capítulo "
                                f"que {ref_book_str} {ref_chapter}",
                    value_override=policy.continuity_match_bonus,
                )
            ev = _FACTORY.continuity_book(
                "cont_01", ref_book_str, candidate.book,
                value=policy.continuity_match_bonus * 0.5)
            return _BUILDER.build(
                signal_type="continuity", weight=policy.weight_continuity,
                evidences=(ev,),
                explanation=f"Continuidade parcial: mesmo livro "
                            f"({ref_book_str})",
                value_override=policy.continuity_match_bonus * 0.5,
            )

        ev = _FACTORY.continuity_none("cont_01", f"{ref_book_str} {ref_chapter}")
        return _BUILDER.build(
            signal_type="continuity", weight=policy.weight_continuity,
            evidences=(ev,),
            explanation="Sem continuidade com referência anterior",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# ReferenceStrategy
# ---------------------------------------------------------------------------


class ReferenceStrategy:
    """Estratégia de referência resolvida.

    Indica se o candidato é exatamente a última referência resolvida
    (repetição direta).

    Evidences produzidas:
      - REFERENCE_REPEAT: candidato = última referência.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> ReferenceSignal:
        ctx = request.context
        last_ref = _safe_getattr(ctx, "last_reference", None)
        if last_ref is None:
            ev = _FACTORY.reference_no_repeat("ref_01")
            return _BUILDER.build(
                signal_type="reference", weight=policy.weight_reference,
                evidences=(ev,), explanation="Sem referência resolvida",
                value_override=0.0,
            )

        ref_book = _safe_getattr(last_ref, "book", None)
        ref_chapter = _safe_getattr(last_ref, "chapter", None)
        ref_verse = _safe_getattr(last_ref, "verse_start", None)
        ref_book_name = _safe_getattr(ref_book, "canonical_name", None) \
            if ref_book is not None else None
        ref_book_str = ref_book_name or (str(ref_book) if ref_book else "")

        if (candidate.book and ref_book_str
                and candidate.book == ref_book_str
                and candidate.chapter == ref_chapter
                and candidate.verse == ref_verse):
            ref_desc = f"{ref_book_str} {ref_chapter}:{ref_verse}"
            ev = _FACTORY.reference_repeat(
                "ref_01", ref_desc, value=policy.reference_repeat_bonus)
            return _BUILDER.build(
                signal_type="reference", weight=policy.weight_reference,
                evidences=(ev,),
                explanation="Candidato é a última referência resolvida",
                value_override=policy.reference_repeat_bonus,
            )

        ev = _FACTORY.reference_no_repeat("ref_01")
        return _BUILDER.build(
            signal_type="reference", weight=policy.weight_reference,
            evidences=(ev,), explanation="Não é a última referência",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# ThemeStrategy
# ---------------------------------------------------------------------------


class ThemeStrategy:
    """Estratégia temática.

    Analisa se o candidato corresponde a temas recentemente mencionados.
    Usa heurística simples: verifica se o display do candidato contém
    algum tema recente.

    Evidences produzidas:
      - THEME_MATCH: tema corresponde ao display do candidato.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> ThemeSignal:
        ctx = request.context
        recent_themes = _safe_getattr(ctx, "recent_themes", ())
        if not recent_themes:
            ev = _FACTORY.theme_no_match("theme_01")
            return _BUILDER.build(
                signal_type="theme", weight=policy.weight_theme,
                evidences=(ev,), explanation="Sem temas recentes",
                value_override=0.0,
            )

        # Heurística: se o candidato tem display e algum tema aparece no display
        display = (candidate.display or "").lower()
        if not display:
            ev = _FACTORY.theme_no_match("theme_01")
            return _BUILDER.build(
                signal_type="theme", weight=policy.weight_theme,
                evidences=(ev,),
                explanation="Candidato sem display para verificar temas",
                value_override=0.0,
            )

        for theme in recent_themes:
            theme_lower = theme.lower() if isinstance(theme, str) else ""
            if theme_lower and theme_lower in display:
                ev = _FACTORY.theme_match(
                    "theme_01", theme, value=policy.theme_match_bonus)
                return _BUILDER.build(
                    signal_type="theme", weight=policy.weight_theme,
                    evidences=(ev,),
                    explanation=f"Tema recente '{theme}' corresponde ao candidato",
                    value_override=policy.theme_match_bonus,
                )

        ev = _FACTORY.theme_no_match("theme_01")
        return _BUILDER.build(
            signal_type="theme", weight=policy.weight_theme,
            evidences=(ev,), explanation="Nenhum tema recente corresponde",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# BookStrategy
# ---------------------------------------------------------------------------


class BookStrategy:
    """Estratégia de livro.

    Analisa se o candidato pertence ao livro ativo ou a livros recentemente
    mencionados.

    Evidences produzidas:
      - BOOK_RECENT: livro do candidato foi recentemente mencionado.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> BookSignal:
        ctx = request.context
        recent_books = _safe_getattr(ctx, "recent_books", ())
        if not candidate.book:
            ev = _FACTORY.book_not_recent("book_01", "?")
            return _BUILDER.build(
                signal_type="book", weight=policy.weight_book,
                evidences=(ev,), explanation="Candidato sem livro",
                value_override=0.0,
            )

        if not recent_books:
            ev = _FACTORY.book_not_recent("book_01", candidate.book)
            return _BUILDER.build(
                signal_type="book", weight=policy.weight_book,
                evidences=(ev,), explanation="Sem livros recentes",
                value_override=0.0,
            )

        if candidate.book in recent_books:
            ev = _FACTORY.book_recent(
                "book_01", candidate.book,
                value=policy.book_recent_match_bonus)
            return _BUILDER.build(
                signal_type="book", weight=policy.weight_book,
                evidences=(ev,),
                explanation=f"Livro {candidate.book} recentemente mencionado",
                value_override=policy.book_recent_match_bonus,
            )

        ev = _FACTORY.book_not_recent("book_01", candidate.book)
        return _BUILDER.build(
            signal_type="book", weight=policy.weight_book,
            evidences=(ev,),
            explanation=f"Livro {candidate.book} não mencionado recentemente",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# ConfidenceStrategy
# ---------------------------------------------------------------------------


class ConfidenceStrategy:
    """Estratégia de confiança agregada.

    Produz um sinal de confiança baseado na consistência dos outros sinais.
    Recebe os sinais já calculados e verifica concordância.

    Evidences produzidas:
      - CONFIDENCE_CONSISTENCY: consistência entre sinais.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
        other_signals: tuple[IntelligenceSignal, ...] = (),
    ) -> ConfidenceSignal:
        if not other_signals:
            ev = _FACTORY.confidence_none("conf_01")
            return _BUILDER.build(
                signal_type="confidence", weight=policy.weight_confidence,
                evidences=(ev,), explanation="Sem sinais para calcular confiança",
                value_override=0.0,
            )

        # Contar sinais positivos (value > 0) e negativos (value < 0)
        positive = sum(1 for s in other_signals if s.value > 0)
        negative = sum(1 for s in other_signals if s.value < 0)
        neutral = sum(1 for s in other_signals if s.value == 0)
        total = len(other_signals)

        # Consistência: sinais positivos vs negativos
        if total == 0:
            ev = _FACTORY.confidence_none("conf_01")
            return _BUILDER.build(
                signal_type="confidence", weight=policy.weight_confidence,
                evidences=(ev,), explanation="Sem sinais",
                value_override=0.0,
            )

        consistency = (positive - negative) / total  # [-1.0, 1.0]
        # Bônus de confiança proporcional à consistência
        bonus = consistency * 0.05  # máximo ±0.05

        ev = _FACTORY.confidence_consistency(
            "conf_01", positive, negative, neutral, value=bonus)

        if positive > 0 and negative == 0:
            return _BUILDER.build(
                signal_type="confidence", weight=policy.weight_confidence,
                evidences=(ev,),
                explanation=f"Alta consistência ({positive} positivos, "
                            f"0 negativos)",
                value_override=bonus,
            )
        if negative > 0 and positive == 0:
            return _BUILDER.build(
                signal_type="confidence", weight=policy.weight_confidence,
                evidences=(ev,),
                explanation=f"Baixa consistência ({negative} negativos, "
                            f"0 positivos)",
                value_override=bonus,
            )

        return _BUILDER.build(
            signal_type="confidence", weight=policy.weight_confidence,
            evidences=(ev,),
            explanation=f"Consistência mista ({positive} pos, {negative} neg, "
                        f"{neutral} neutros)",
            value_override=bonus,
        )


# ---------------------------------------------------------------------------
# EvaluationStrategy
# ---------------------------------------------------------------------------


class EvaluationStrategy:
    """Estratégia estatística (Continuous Evaluation).

    Analisa se estatísticas de avaliação favorecem o candidato.
    Usa duck-typing para acessar EvaluationMetrics.

    Evidences produzidas:
      - EVALUATION_PRECISION: precisão estatística.
      - EVALUATION_VOLUME: volume de buscas.
      - EVALUATION_RELIABILITY: confiabilidade estatística.
    """

    def evaluate(
        self, candidate: CandidateInfo, request: IntelligenceRequest,
        policy: IntelligencePolicy,
    ) -> EvaluationSignal:
        metrics = request.evaluation_metrics
        if metrics is None:
            ev = _FACTORY.evaluation_none("eval_01")
            return _BUILDER.build(
                signal_type="evaluation", weight=policy.weight_evaluation,
                evidences=(ev,), explanation="Sem métricas de avaliação",
                value_override=0.0,
            )

        precision = _safe_getattr(metrics, "precision", 0.0)
        total_searches = _safe_getattr(metrics, "total_searches", 0)

        ev_vol = _FACTORY.evaluation_volume(
            "eval_vol", total_searches, value=float(total_searches))

        if total_searches < policy.eval_min_searches:
            ev_prec = _FACTORY.evaluation_precision(
                "eval_prec", precision, value=0.0)
            return _BUILDER.build(
                signal_type="evaluation", weight=policy.weight_evaluation,
                evidences=(ev_vol, ev_prec),
                explanation=f"Poucas buscas ({total_searches}) para avaliação",
                value_override=0.0,
            )

        is_reliable = precision >= policy.eval_precision_threshold
        ev_prec = _FACTORY.evaluation_precision(
            "eval_prec", precision, value=0.05 if is_reliable else 0.0)
        ev_rel = _FACTORY.evaluation_reliability(
            "eval_rel", is_reliable, value=0.05 if is_reliable else 0.0)
        evidences = (ev_vol, ev_prec, ev_rel)

        if precision >= policy.eval_precision_threshold:
            return _BUILDER.build(
                signal_type="evaluation", weight=policy.weight_evaluation,
                evidences=evidences,
                explanation=f"Avaliação positiva (precisão {precision*100:.1f}%)",
                value_override=0.05,
            )

        if precision < 0.50:
            return _BUILDER.build(
                signal_type="evaluation", weight=policy.weight_evaluation,
                evidences=evidences,
                explanation=f"Avaliação negativa (precisão {precision*100:.1f}%)",
                value_override=-0.03,
            )

        return _BUILDER.build(
            signal_type="evaluation", weight=policy.weight_evaluation,
            evidences=evidences,
            explanation=f"Avaliação neutra (precisão {precision*100:.1f}%)",
            value_override=0.0,
        )


# ---------------------------------------------------------------------------
# Registry de estratégias
# ---------------------------------------------------------------------------


def all_strategies() -> tuple:
    """Retorna instâncias de todas as estratégias ativas.

    A ordem não importa — o Coordinator coleta todos os sinais.
    ConfidenceStrategy é tratada separadamente pelo Coordinator pois
    depende dos outros sinais.
    """
    return (
        ContextStrategy(),
        FeedbackStrategy(),
        ContinuityStrategy(),
        ReferenceStrategy(),
        ThemeStrategy(),
        BookStrategy(),
        EvaluationStrategy(),
    )


__all__ = [
    "ContextStrategy",
    "FeedbackStrategy",
    "ContinuityStrategy",
    "ReferenceStrategy",
    "ThemeStrategy",
    "BookStrategy",
    "ConfidenceStrategy",
    "EvaluationStrategy",
    "all_strategies",
]
