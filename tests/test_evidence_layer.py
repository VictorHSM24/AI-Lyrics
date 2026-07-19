"""Testes do Evidence Layer — DTOs, Policy, Factory, Builder.

Cobre:
  - EvidenceType (enum, valores, extensibilidade).
  - Evidence (imutabilidade, hashability, contribution, to_dict).
  - EvidencePolicy (pesos, prioridades, limites, sort_by_priority).
  - EvidenceFactory (todos os helpers de produção de evidências).
  - SignalBuilder (construção de IntelligenceSignal a partir de Evidences).
"""

from __future__ import annotations

import unittest

import sys
sys.path.insert(0, ".")

from intelligence import (
    Evidence,
    EvidenceFactory,
    EvidencePolicy,
    EvidenceType,
    IntelligenceSignal,
    SignalBuilder,
)


# ---------------------------------------------------------------------------
# EvidenceType
# ---------------------------------------------------------------------------


class TestEvidenceType(unittest.TestCase):
    """Testes do enum EvidenceType."""

    def test_evidence_type_is_str_enum(self):
        """EvidenceType deve ser str Enum (serializável como string)."""
        self.assertTrue(issubclass(EvidenceType, str))
        self.assertIsInstance(EvidenceType.CONTEXT_BOOK_MATCH, str)

    def test_evidence_type_values_are_uppercase_strings(self):
        """Todos os valores do enum devem ser strings em maiúsculas."""
        for et in EvidenceType:
            self.assertEqual(et.value, et.value.upper())
            self.assertIsInstance(et.value, str)

    def test_evidence_type_has_context_types(self):
        """Tipos de contexto devem existir."""
        self.assertIn(EvidenceType.CONTEXT_BOOK_MATCH, EvidenceType)
        self.assertIn(EvidenceType.CONTEXT_CHAPTER_MATCH, EvidenceType)
        self.assertIn(EvidenceType.CONTEXT_REFERENCE_MATCH, EvidenceType)
        self.assertIn(EvidenceType.CONTEXT_THEME_MATCH, EvidenceType)

    def test_evidence_type_has_feedback_types(self):
        """Tipos de feedback devem existir."""
        self.assertIn(EvidenceType.FEEDBACK_ACCEPTANCE, EvidenceType)
        self.assertIn(EvidenceType.FEEDBACK_REJECTION, EvidenceType)
        self.assertIn(EvidenceType.FEEDBACK_HISTORY, EvidenceType)

    def test_evidence_type_has_continuity_types(self):
        """Tipos de continuidade devem existir."""
        self.assertIn(EvidenceType.CONTINUITY_BOOK, EvidenceType)
        self.assertIn(EvidenceType.CONTINUITY_CHAPTER, EvidenceType)
        self.assertIn(EvidenceType.CONTINUITY_REFERENCE, EvidenceType)

    def test_evidence_type_has_evaluation_types(self):
        """Tipos de avaliação devem existir."""
        self.assertIn(EvidenceType.EVALUATION_PRECISION, EvidenceType)
        self.assertIn(EvidenceType.EVALUATION_VOLUME, EvidenceType)
        self.assertIn(EvidenceType.EVALUATION_RELIABILITY, EvidenceType)

    def test_evidence_type_has_custom(self):
        """Tipo CUSTOM deve existir para evidências ad-hoc."""
        self.assertIn(EvidenceType.CUSTOM, EvidenceType)

    def test_evidence_type_lookup_by_value(self):
        """Deve ser possível buscar EvidenceType por valor string."""
        et = EvidenceType("CONTEXT_BOOK_MATCH")
        self.assertIs(et, EvidenceType.CONTEXT_BOOK_MATCH)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class TestEvidence(unittest.TestCase):
    """Testes do DTO Evidence."""

    def test_evidence_is_frozen(self):
        """Evidence deve ser imutável."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.3, confidence=0.8,
        )
        with self.assertRaises(Exception):
            ev.value = 0.9  # type: ignore

    def test_evidence_is_hashable(self):
        """Evidence deve ser hashable (usável em sets/dicts)."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
        )
        self.assertIsInstance(hash(ev), int)
        # Mesma instância em set
        s = {ev, ev}
        self.assertEqual(len(s), 1)

    def test_evidence_default_values(self):
        """Defaults: value=0, weight=0, confidence=0, metadata=(), timestamp=0."""
        ev = Evidence(id="ev1", type=EvidenceType.CUSTOM, description="test")
        self.assertEqual(ev.value, 0.0)
        self.assertEqual(ev.weight, 0.0)
        self.assertEqual(ev.confidence, 0.0)
        self.assertEqual(ev.metadata, ())
        self.assertEqual(ev.timestamp, 0.0)

    def test_evidence_contribution(self):
        """contribution = value * weight."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.4,
        )
        self.assertAlmostEqual(ev.contribution, 0.2)

    def test_evidence_contribution_negative(self):
        """contribution negativa quando value é negativo."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=-0.5, weight=0.4,
        )
        self.assertAlmostEqual(ev.contribution, -0.2)

    def test_evidence_contribution_zero_weight(self):
        """contribution=0 quando weight=0."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.0,
        )
        self.assertEqual(ev.contribution, 0.0)

    def test_evidence_to_dict_keys(self):
        """to_dict deve ter todas as chaves esperadas."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.4, confidence=0.8,
            metadata=(("k", "v"),), timestamp=123.0,
        )
        d = ev.to_dict()
        expected_keys = {
            "id", "type", "description", "value", "weight",
            "confidence", "contribution", "metadata", "timestamp",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_evidence_to_dict_type_is_string(self):
        """to_dict deve serializar type como string."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CONTEXT_BOOK_MATCH, description="test",
        )
        d = ev.to_dict()
        self.assertEqual(d["type"], "CONTEXT_BOOK_MATCH")

    def test_evidence_to_dict_metadata_is_list(self):
        """to_dict deve serializar metadata como list."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            metadata=(("k1", "v1"), ("k2", "v2")),
        )
        d = ev.to_dict()
        self.assertIsInstance(d["metadata"], list)
        self.assertEqual(len(d["metadata"]), 2)

    def test_evidence_to_dict_contribution(self):
        """to_dict deve incluir contribution calculada."""
        ev = Evidence(
            id="ev1", type=EvidenceType.CUSTOM, description="test",
            value=0.5, weight=0.4,
        )
        d = ev.to_dict()
        self.assertAlmostEqual(d["contribution"], 0.2)


# ---------------------------------------------------------------------------
# EvidencePolicy
# ---------------------------------------------------------------------------


class TestEvidencePolicy(unittest.TestCase):
    """Testes da EvidencePolicy."""

    def test_policy_default_confidence(self):
        """Policy deve ter default_confidence > 0."""
        p = EvidencePolicy()
        self.assertGreater(p.default_confidence, 0.0)
        self.assertLessEqual(p.default_confidence, 1.0)

    def test_policy_max_evidences_per_signal(self):
        """Policy deve ter limite máximo de evidências."""
        p = EvidencePolicy()
        self.assertGreater(p.max_evidences_per_signal, 0)

    def test_policy_weight_for_known_type(self):
        """weight_for deve retornar peso para tipo conhecido."""
        p = EvidencePolicy()
        w = p.weight_for(EvidenceType.CONTEXT_BOOK_MATCH)
        self.assertGreater(w, 0.0)
        self.assertLessEqual(w, 1.0)

    def test_policy_weight_for_custom(self):
        """CUSTOM deve ter peso definido."""
        p = EvidencePolicy()
        w = p.weight_for(EvidenceType.CUSTOM)
        self.assertGreaterEqual(w, 0.0)

    def test_policy_priority_for_chapter_higher_than_book(self):
        """CONTEXT_CHAPTER_MATCH deve ter prioridade >= CONTEXT_BOOK_MATCH."""
        p = EvidencePolicy()
        self.assertGreaterEqual(
            p.priority_for(EvidenceType.CONTEXT_CHAPTER_MATCH),
            p.priority_for(EvidenceType.CONTEXT_BOOK_MATCH),
        )

    def test_policy_priority_for_feedback_high(self):
        """FEEDBACK_ACCEPTANCE e FEEDBACK_REJECTION devem ter prioridade alta."""
        p = EvidencePolicy()
        self.assertGreater(p.priority_for(EvidenceType.FEEDBACK_ACCEPTANCE), 50)
        self.assertGreater(p.priority_for(EvidenceType.FEEDBACK_REJECTION), 50)

    def test_policy_all_types_returns_tuple(self):
        """all_types deve retornar tuple com todos os EvidenceType."""
        p = EvidencePolicy()
        types = p.all_types()
        self.assertIsInstance(types, tuple)
        self.assertEqual(len(types), len(list(EvidenceType)))

    def test_policy_is_valid_type(self):
        """is_valid_type deve reconhecer EvidenceType."""
        p = EvidencePolicy()
        self.assertTrue(p.is_valid_type(EvidenceType.CUSTOM))
        self.assertFalse(p.is_valid_type("CUSTOM"))  # string não é válido

    def test_policy_sort_by_priority_descending(self):
        """sort_by_priority deve ordenar por prioridade decrescente."""
        p = EvidencePolicy()
        ev_high = Evidence(
            id="h", type=EvidenceType.CONTEXT_CHAPTER_MATCH, description="h",
        )
        ev_low = Evidence(
            id="l", type=EvidenceType.CUSTOM, description="l",
        )
        sorted_ev = p.sort_by_priority((ev_low, ev_high))
        # Primeiro deve ser o de maior prioridade
        self.assertEqual(sorted_ev[0].id, "h")
        self.assertEqual(sorted_ev[1].id, "l")

    def test_policy_sort_by_priority_empty(self):
        """sort_by_priority com tuple vazio retorna tuple vazio."""
        p = EvidencePolicy()
        self.assertEqual(p.sort_by_priority(()), ())


if __name__ == "__main__":
    unittest.main()
