"""Testes do RankingPolicy.

Cobre:
  - score() com diferentes combinações de sinais
  - Pesos centralizados (sem valores mágicos)
  - Phrase match bonus
  - All keywords bonus (AND match)
  - First book bonus (priorização do livro mais provável)
  - Parâmetros futuros aceitos mas ignorados
  - Clamp [0.0, 1.0]
"""

from __future__ import annotations

import pytest

from busca.ranking import RankingPolicy


class TestRankingPolicy:
    """Testes da política de ranking composto."""

    def setup_method(self) -> None:
        self.policy = RankingPolicy()

    def test_base_score_only(self) -> None:
        """Sem nenhum bonus, score = WEIGHT_BASE * base_score."""
        score = self.policy.score(0.8)
        # WEIGHT_BASE = 0.40
        assert abs(score - 0.40 * 0.8) < 0.001

    def test_clamp_max(self) -> None:
        """Score nunca excede 1.0."""
        score = self.policy.score(
            1.0,
            keyword_hits=10,
            total_keywords=10,
            version="ACF",
            preferred_versions=("ACF",),
            book_id=43,
            suggested_book_ids=(43,),
            boost_term_hits=10,
            total_boost_terms=10,
            phrase_match=True,
        )
        assert score <= 1.0

    def test_clamp_min(self) -> None:
        """Score nunca é negativo."""
        score = self.policy.score(0.0)
        assert score >= 0.0

    def test_keyword_match_bonus(self) -> None:
        score_no_kw = self.policy.score(0.5)
        score_with_kw = self.policy.score(
            0.5, keyword_hits=3, total_keywords=3,
        )
        assert score_with_kw > score_no_kw

    def test_all_keywords_bonus(self) -> None:
        """Quando todas as keywords estão presentes, bonus extra."""
        score_partial = self.policy.score(
            0.5, keyword_hits=1, total_keywords=3,
        )
        score_all = self.policy.score(
            0.5, keyword_hits=3, total_keywords=3,
        )
        # all keywords deve ter bonus significativamente maior
        assert score_all > score_partial + 0.05

    def test_all_keywords_requires_min_2(self) -> None:
        """All keywords bonus só aplica com 2+ keywords."""
        score_1_kw = self.policy.score(
            0.5, keyword_hits=1, total_keywords=1,
        )
        score_2_kw = self.policy.score(
            0.5, keyword_hits=2, total_keywords=2,
        )
        # Com 2 keywords, o all-keywords bonus aplica
        # Com 1 keyword, não aplica
        # A diferença deve ser maior que apenas o ratio difference
        assert score_2_kw > score_1_kw

    def test_version_bonus(self) -> None:
        score_no_ver = self.policy.score(0.5)
        score_with_ver = self.policy.score(
            0.5, version="ACF", preferred_versions=("ACF",),
        )
        assert score_with_ver > score_no_ver

    def test_version_no_bonus_if_not_preferred(self) -> None:
        score = self.policy.score(
            0.5, version="NVI", preferred_versions=("ACF",),
        )
        score_base = self.policy.score(0.5)
        assert score == score_base  # sem bonus

    def test_first_book_bonus_larger(self) -> None:
        """Primeiro livro sugerido recebe bonus maior que os demais."""
        score_first = self.policy.score(
            0.5, book_id=43, suggested_book_ids=(43, 45),
        )
        score_second = self.policy.score(
            0.5, book_id=45, suggested_book_ids=(43, 45),
        )
        assert score_first > score_second

    def test_book_no_bonus_if_not_suggested(self) -> None:
        score = self.policy.score(
            0.5, book_id=50, suggested_book_ids=(43, 45),
        )
        score_base = self.policy.score(0.5)
        assert score == score_base

    def test_phrase_match_bonus(self) -> None:
        score_no_phrase = self.policy.score(0.5)
        score_phrase = self.policy.score(0.5, phrase_match=True)
        assert score_phrase > score_no_phrase
        # WEIGHT_PHRASE_MATCH = 0.15
        assert abs(score_phrase - score_no_phrase - 0.15) < 0.001

    def test_boost_term_bonus(self) -> None:
        score_no_boost = self.policy.score(0.5)
        score_with_boost = self.policy.score(
            0.5, boost_term_hits=2, total_boost_terms=2,
        )
        assert score_with_boost > score_no_boost

    def test_future_params_accepted(self) -> None:
        """Parâmetros futuros devem ser aceitos sem erro."""
        score = self.policy.score(
            0.5,
            embedding_score=0.9,
            rerank_score=0.85,
            llm_confidence=0.92,
        )
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_future_params_ignored(self) -> None:
        """Parâmetros futuros (rerank_score, llm_confidence) não afetam o score.
        embedding_score agora é usado (FASE 6)."""
        score_without = self.policy.score(0.5)
        score_with = self.policy.score(
            0.5,
            rerank_score=0.99,
            llm_confidence=0.99,
        )
        assert score_without == score_with

    def test_embedding_score_bonus(self) -> None:
        """embedding_score > 0 deve aumentar o score."""
        score_without = self.policy.score(0.5)
        score_with = self.policy.score(0.5, embedding_score=0.9)
        assert score_with > score_without

    def test_embedding_score_zero_no_bonus(self) -> None:
        """embedding_score = 0 ou None não deve dar bonus."""
        score_none = self.policy.score(0.5)
        score_zero = self.policy.score(0.5, embedding_score=0.0)
        assert score_none == score_zero

    def test_policy_is_stateless(self) -> None:
        """Policy não tem estado — mesma instância reutilizável."""
        s1 = self.policy.score(0.5, keyword_hits=2, total_keywords=2)
        s2 = self.policy.score(0.5, keyword_hits=2, total_keywords=2)
        assert s1 == s2

    def test_book_match_bonus_property(self) -> None:
        """book_match_bonus property retorna o bonus fixo."""
        assert self.policy.book_match_bonus > 0

    def test_combined_signals(self) -> None:
        """Todos os sinais combinados produzem score maior que base."""
        base_only = self.policy.score(0.5)
        all_signals = self.policy.score(
            0.5,
            keyword_hits=3, total_keywords=3,
            version="ACF", preferred_versions=("ACF",),
            book_id=43, suggested_book_ids=(43,),
            boost_term_hits=2, total_boost_terms=2,
            phrase_match=True,
        )
        assert all_signals > base_only + 0.3
