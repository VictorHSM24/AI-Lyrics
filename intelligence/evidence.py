"""Evidence Layer — refinamento arquitetural do Sermon Intelligence.

Adiciona o conceito interno de Evidence: fatos concretos que sustentam
cada IntelligenceSignal. As Evidences aumentam a granularidade da
explicabilidade sem alterar o comportamento do sistema.

Fluxo após refinamento:
    Strategy → Evidence(s) → Signal → Score

Componentes:
  - EvidenceType: enum com tipos de evidência (extensível).
  - Evidence: DTO imutável (frozen dataclass).
  - EvidencePolicy: política centralizada (pesos, prioridades, limites).
  - EvidenceFactory: helpers para produzir evidências padronizadas.
  - SignalBuilder: transforma Evidences em IntelligenceSignal.

Compatibilidade:
  - Nenhuma API pública quebra.
  - IntelligenceSignal ganha campo opcional `evidences` (default vazio).
  - Strategies passam a produzir Evidences internamente.
  - Score preserva Evidences via Signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# EvidenceType — enum extensível
# ---------------------------------------------------------------------------


class EvidenceType(str, Enum):
    """Tipo de evidência produzida por uma Strategy.

    Arquitetura aberta: novos tipos podem ser adicionados sem quebrar
    existentes. CUSTOM permite evidências ad-hoc.

    Contexto:
        CONTEXT_BOOK_MATCH: livro do candidato = livro ativo.
        CONTEXT_CHAPTER_MATCH: capítulo do candidato = capítulo ativo.
        CONTEXT_REFERENCE_MATCH: referência recente corresponde.
        CONTEXT_THEME_MATCH: tema recente corresponde.

    Feedback:
        FEEDBACK_ACCEPTANCE: aceitações registradas.
        FEEDBACK_REJECTION: rejeições registradas.
        FEEDBACK_HISTORY: histórico/peso acumulado.

    Continuidade:
        CONTINUITY_BOOK: mesmo livro que referência recente.
        CONTINUITY_CHAPTER: mesmo capítulo que referência recente.
        CONTINUITY_REFERENCE: continuidade de referência.

    Livro:
        BOOK_RECENT: livro recentemente mencionado.

    Referência:
        REFERENCE_REPEAT: candidato = última referência resolvida.

    Tema:
        THEME_MATCH: tema corresponde ao display do candidato.
        THEME_HISTORY: histórico de temas.

    Avaliação:
        EVALUATION_PRECISION: precisão estatística.
        EVALUATION_VOLUME: volume de buscas.
        EVALUATION_RELIABILITY: confiabilidade estatística.

    Confiança:
        CONFIDENCE_CONSISTENCY: consistência entre sinais.

    Genérico:
        CUSTOM: evidência ad-hoc (metadata livre).
    """

    # Contexto
    CONTEXT_BOOK_MATCH = "CONTEXT_BOOK_MATCH"
    CONTEXT_CHAPTER_MATCH = "CONTEXT_CHAPTER_MATCH"
    CONTEXT_REFERENCE_MATCH = "CONTEXT_REFERENCE_MATCH"
    CONTEXT_THEME_MATCH = "CONTEXT_THEME_MATCH"

    # Feedback
    FEEDBACK_ACCEPTANCE = "FEEDBACK_ACCEPTANCE"
    FEEDBACK_REJECTION = "FEEDBACK_REJECTION"
    FEEDBACK_HISTORY = "FEEDBACK_HISTORY"

    # Continuidade
    CONTINUITY_BOOK = "CONTINUITY_BOOK"
    CONTINUITY_CHAPTER = "CONTINUITY_CHAPTER"
    CONTINUITY_REFERENCE = "CONTINUITY_REFERENCE"

    # Livro
    BOOK_RECENT = "BOOK_RECENT"

    # Referência
    REFERENCE_REPEAT = "REFERENCE_REPEAT"

    # Tema
    THEME_MATCH = "THEME_MATCH"
    THEME_HISTORY = "THEME_HISTORY"

    # Avaliação
    EVALUATION_PRECISION = "EVALUATION_PRECISION"
    EVALUATION_VOLUME = "EVALUATION_VOLUME"
    EVALUATION_RELIABILITY = "EVALUATION_RELIABILITY"

    # Confiança
    CONFIDENCE_CONSISTENCY = "CONFIDENCE_CONSISTENCY"

    # Genérico
    CUSTOM = "CUSTOM"


__all___evidence_type = tuple(EvidenceType)


# ---------------------------------------------------------------------------
# Evidence — DTO imutável
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """Evidência concreta que sustenta um IntelligenceSignal.

    Cada Evidence representa um fato observável que justifica parte da
    decisão de uma Strategy. Múltiplas Evidences podem sustentar um
    único Signal.

    Atributos:
        id: identificador único da evidência (string).
        type: EvidenceType da evidência.
        description: descrição legível do fato.
        value: valor da evidência [-1.0, 1.0] (pode ser negativa).
        weight: peso relativo da evidência [0.0, 1.0].
        confidence: confiança nesta evidência específica [0.0, 1.0].
        metadata: tuple de pares (chave, valor) para dados extras.
        timestamp: timestamp opcional (segundos desde epoch).

    Imutável, hashable, serializável.
    """

    id: str
    type: EvidenceType
    description: str
    value: float = 0.0
    weight: float = 0.0
    confidence: float = 0.0
    metadata: tuple = field(default_factory=tuple)
    timestamp: float = 0.0

    @property
    def contribution(self) -> float:
        """Contribuição ponderada = value * weight."""
        return self.value * self.weight

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "value": self.value,
            "weight": self.weight,
            "confidence": self.confidence,
            "contribution": self.contribution,
            "metadata": list(self.metadata),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# EvidencePolicy — política centralizada
# ---------------------------------------------------------------------------


# Pesos padrão por tipo de evidência (importância relativa dentro do Signal).
_EVIDENCE_WEIGHTS: dict[EvidenceType, float] = {
    EvidenceType.CONTEXT_BOOK_MATCH: 0.15,
    EvidenceType.CONTEXT_CHAPTER_MATCH: 0.20,
    EvidenceType.CONTEXT_REFERENCE_MATCH: 0.10,
    EvidenceType.CONTEXT_THEME_MATCH: 0.10,
    EvidenceType.FEEDBACK_ACCEPTANCE: 0.15,
    EvidenceType.FEEDBACK_REJECTION: 0.15,
    EvidenceType.FEEDBACK_HISTORY: 0.10,
    EvidenceType.CONTINUITY_BOOK: 0.10,
    EvidenceType.CONTINUITY_CHAPTER: 0.15,
    EvidenceType.CONTINUITY_REFERENCE: 0.10,
    EvidenceType.BOOK_RECENT: 0.10,
    EvidenceType.REFERENCE_REPEAT: 0.10,
    EvidenceType.THEME_MATCH: 0.10,
    EvidenceType.THEME_HISTORY: 0.05,
    EvidenceType.EVALUATION_PRECISION: 0.15,
    EvidenceType.EVALUATION_VOLUME: 0.10,
    EvidenceType.EVALUATION_RELIABILITY: 0.10,
    EvidenceType.CONFIDENCE_CONSISTENCY: 0.10,
    EvidenceType.CUSTOM: 0.05,
}

# Prioridades (maior = mais importante para explicabilidade).
_EVIDENCE_PRIORITIES: dict[EvidenceType, int] = {
    EvidenceType.CONTEXT_CHAPTER_MATCH: 90,
    EvidenceType.CONTEXT_BOOK_MATCH: 80,
    EvidenceType.FEEDBACK_ACCEPTANCE: 85,
    EvidenceType.FEEDBACK_REJECTION: 85,
    EvidenceType.CONTINUITY_CHAPTER: 75,
    EvidenceType.CONTINUITY_BOOK: 70,
    EvidenceType.REFERENCE_REPEAT: 65,
    EvidenceType.EVALUATION_PRECISION: 60,
    EvidenceType.THEME_MATCH: 55,
    EvidenceType.BOOK_RECENT: 50,
    EvidenceType.CONFIDENCE_CONSISTENCY: 40,
    EvidenceType.CUSTOM: 10,
}

# Confiança padrão por tipo de evidência.
_EVIDENCE_DEFAULT_CONFIDENCE: float = 0.5

# Limite máximo de evidências por signal (para evitar explosão).
_MAX_EVIDENCES_PER_SIGNAL: int = 20


class EvidencePolicy:
    """Política de evidências — pesos, prioridades, limites.

    Stateless. Centraliza todos os parâmetros relacionados a Evidences.
    Nenhum número mágico espalhado pelo código.
    """

    @property
    def default_confidence(self) -> float:
        return _EVIDENCE_DEFAULT_CONFIDENCE

    @property
    def max_evidences_per_signal(self) -> int:
        return _MAX_EVIDENCES_PER_SIGNAL

    def weight_for(self, etype: EvidenceType) -> float:
        """Peso padrão para um tipo de evidência."""
        return _EVIDENCE_WEIGHTS.get(etype, 0.05)

    def priority_for(self, etype: EvidenceType) -> int:
        """Prioridade de um tipo de evidência (para ordenação)."""
        return _EVIDENCE_PRIORITIES.get(etype, 0)

    def all_types(self) -> tuple[EvidenceType, ...]:
        """Todos os tipos de evidência suportados."""
        return tuple(EvidenceType)

    def is_valid_type(self, etype: EvidenceType) -> bool:
        return isinstance(etype, EvidenceType)

    def sort_by_priority(
        self, evidences: tuple[Evidence, ...]
    ) -> tuple[Evidence, ...]:
        """Ordena evidências por prioridade decrescente."""
        return tuple(sorted(
            evidences,
            key=lambda e: self.priority_for(e.type),
            reverse=True,
        ))


# ---------------------------------------------------------------------------
# EvidenceFactory — helpers para produzir evidências padronizadas
# ---------------------------------------------------------------------------


class EvidenceFactory:
    """Factory para produzir evidências padronizadas.

    Evita duplicação de código nas Strategies. Cada helper produz uma
    Evidence com tipo, descrição, value, weight e confidence apropriados.

    Uso:
        factory = EvidenceFactory(policy)
        ev = factory.book_match("ev_01", book="João", candidate_book="João")
    """

    def __init__(self, policy: EvidencePolicy | None = None) -> None:
        self._policy = policy or EvidencePolicy()

    @property
    def policy(self) -> EvidencePolicy:
        return self._policy

    # ------------------------------------------------------------------
    # Contexto
    # ------------------------------------------------------------------

    def book_match(
        self, eid: str, book: str, candidate_book: str, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTEXT_BOOK_MATCH,
            description=f"Livro ativo '{book}' = livro do candidato '{candidate_book}'",
            value=value, weight=self._policy.weight_for(EvidenceType.CONTEXT_BOOK_MATCH),
            confidence=self._policy.default_confidence,
        )

    def chapter_match(
        self, eid: str, book: str, chapter: int,
        candidate_book: str, candidate_chapter: int, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTEXT_CHAPTER_MATCH,
            description=f"Contexto {book} {chapter} = candidato {candidate_book} {candidate_chapter}",
            value=value, weight=self._policy.weight_for(EvidenceType.CONTEXT_CHAPTER_MATCH),
            confidence=self._policy.default_confidence,
        )

    def context_no_match(
        self, eid: str, context_desc: str, candidate_desc: str,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTEXT_BOOK_MATCH,
            description=f"Contexto '{context_desc}' não corresponde a '{candidate_desc}'",
            value=0.0, weight=self._policy.weight_for(EvidenceType.CONTEXT_BOOK_MATCH),
            confidence=self._policy.default_confidence,
        )

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    def feedback_acceptance(
        self, eid: str, acceptances: int, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.FEEDBACK_ACCEPTANCE,
            description=f"{acceptances} aceitações registradas",
            value=value, weight=self._policy.weight_for(EvidenceType.FEEDBACK_ACCEPTANCE),
            confidence=self._policy.default_confidence,
            metadata=(("acceptances", str(acceptances)),),
        )

    def feedback_rejection(
        self, eid: str, rejections: int, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.FEEDBACK_REJECTION,
            description=f"{rejections} rejeições registradas",
            value=value, weight=self._policy.weight_for(EvidenceType.FEEDBACK_REJECTION),
            confidence=self._policy.default_confidence,
            metadata=(("rejections", str(rejections)),),
        )

    def feedback_history(
        self, eid: str, total_weight: float, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.FEEDBACK_HISTORY,
            description=f"Peso acumulado de feedback: {total_weight:.1f}",
            value=value, weight=self._policy.weight_for(EvidenceType.FEEDBACK_HISTORY),
            confidence=self._policy.default_confidence,
            metadata=(("total_weight", str(total_weight)),),
        )

    def feedback_none(self, eid: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.FEEDBACK_HISTORY,
            description="Sem feedback registrado",
            value=0.0, weight=self._policy.weight_for(EvidenceType.FEEDBACK_HISTORY),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Continuidade
    # ------------------------------------------------------------------

    def continuity_book(
        self, eid: str, ref_book: str, candidate_book: str, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTINUITY_BOOK,
            description=f"Mesmo livro que referência recente: {ref_book}",
            value=value, weight=self._policy.weight_for(EvidenceType.CONTINUITY_BOOK),
            confidence=self._policy.default_confidence,
        )

    def continuity_chapter(
        self, eid: str, ref_book: str, ref_chapter: int,
        candidate_book: str, candidate_chapter: int, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTINUITY_CHAPTER,
            description=f"Mesmo livro e capítulo: {ref_book} {ref_chapter}",
            value=value, weight=self._policy.weight_for(EvidenceType.CONTINUITY_CHAPTER),
            confidence=self._policy.default_confidence,
        )

    def continuity_none(self, eid: str, ref_desc: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONTINUITY_REFERENCE,
            description=f"Sem continuidade com {ref_desc}",
            value=0.0, weight=self._policy.weight_for(EvidenceType.CONTINUITY_REFERENCE),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Livro
    # ------------------------------------------------------------------

    def book_recent(
        self, eid: str, book: str, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.BOOK_RECENT,
            description=f"Livro '{book}' recentemente mencionado",
            value=value, weight=self._policy.weight_for(EvidenceType.BOOK_RECENT),
            confidence=self._policy.default_confidence,
        )

    def book_not_recent(
        self, eid: str, book: str,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.BOOK_RECENT,
            description=f"Livro '{book}' não mencionado recentemente",
            value=0.0, weight=self._policy.weight_for(EvidenceType.BOOK_RECENT),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Referência
    # ------------------------------------------------------------------

    def reference_repeat(
        self, eid: str, ref_desc: str, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.REFERENCE_REPEAT,
            description=f"Candidato = última referência resolvida: {ref_desc}",
            value=value, weight=self._policy.weight_for(EvidenceType.REFERENCE_REPEAT),
            confidence=self._policy.default_confidence,
        )

    def reference_no_repeat(self, eid: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.REFERENCE_REPEAT,
            description="Candidato não é a última referência",
            value=0.0, weight=self._policy.weight_for(EvidenceType.REFERENCE_REPEAT),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Tema
    # ------------------------------------------------------------------

    def theme_match(
        self, eid: str, theme: str, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.THEME_MATCH,
            description=f"Tema recente '{theme}' corresponde ao candidato",
            value=value, weight=self._policy.weight_for(EvidenceType.THEME_MATCH),
            confidence=self._policy.default_confidence,
        )

    def theme_no_match(self, eid: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.THEME_MATCH,
            description="Nenhum tema recente corresponde",
            value=0.0, weight=self._policy.weight_for(EvidenceType.THEME_MATCH),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Avaliação
    # ------------------------------------------------------------------

    def evaluation_precision(
        self, eid: str, precision: float, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.EVALUATION_PRECISION,
            description=f"Precisão estatística: {precision*100:.1f}%",
            value=value, weight=self._policy.weight_for(EvidenceType.EVALUATION_PRECISION),
            confidence=self._policy.default_confidence,
            metadata=(("precision", str(precision)),),
        )

    def evaluation_volume(
        self, eid: str, total_searches: int, value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.EVALUATION_VOLUME,
            description=f"Volume de buscas: {total_searches}",
            value=value, weight=self._policy.weight_for(EvidenceType.EVALUATION_VOLUME),
            confidence=self._policy.default_confidence,
            metadata=(("total_searches", str(total_searches)),),
        )

    def evaluation_reliability(
        self, eid: str, is_reliable: bool, value: float = 0.0,
    ) -> Evidence:
        desc = "Confiável" if is_reliable else "Inconsistente"
        return Evidence(
            id=eid, type=EvidenceType.EVALUATION_RELIABILITY,
            description=f"Confiabilidade estatística: {desc}",
            value=value, weight=self._policy.weight_for(EvidenceType.EVALUATION_RELIABILITY),
            confidence=0.8 if is_reliable else 0.2,
        )

    def evaluation_none(self, eid: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.EVALUATION_PRECISION,
            description="Sem métricas de avaliação",
            value=0.0, weight=self._policy.weight_for(EvidenceType.EVALUATION_PRECISION),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Confiança
    # ------------------------------------------------------------------

    def confidence_consistency(
        self, eid: str, positive: int, negative: int, neutral: int,
        value: float = 0.0,
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONFIDENCE_CONSISTENCY,
            description=f"Consistência: {positive} positivos, {negative} negativos, {neutral} neutros",
            value=value, weight=self._policy.weight_for(EvidenceType.CONFIDENCE_CONSISTENCY),
            confidence=self._policy.default_confidence,
            metadata=(("positive", str(positive)), ("negative", str(negative)),
                      ("neutral", str(neutral))),
        )

    def confidence_none(self, eid: str) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CONFIDENCE_CONSISTENCY,
            description="Sem sinais para calcular confiança",
            value=0.0, weight=self._policy.weight_for(EvidenceType.CONFIDENCE_CONSISTENCY),
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Genérico
    # ------------------------------------------------------------------

    def custom(
        self, eid: str, description: str, value: float = 0.0,
        weight: float | None = None, confidence: float = 0.0,
        metadata: tuple = (),
    ) -> Evidence:
        return Evidence(
            id=eid, type=EvidenceType.CUSTOM,
            description=description, value=value,
            weight=weight if weight is not None
            else self._policy.weight_for(EvidenceType.CUSTOM),
            confidence=confidence, metadata=metadata,
        )


# ---------------------------------------------------------------------------
# SignalBuilder — transforma Evidences em IntelligenceSignal
# ---------------------------------------------------------------------------


class SignalBuilder:
    """Builder que transforma Evidences em IntelligenceSignal.

    Responsabilidade única:
      - Receber Evidences + signal_type + weight + explanation.
      - Calcular value agregado a partir das Evidences.
      - Produzir IntelligenceSignal com as Evidences anexadas.

    Nenhuma lógica de negócio fora dele. As Strategies coletam fatos,
    geram Evidences via EvidenceFactory, e usam SignalBuilder para
    produzir o Signal final.

    Cálculo do value:
      - Soma ponderada das contribuições das Evidences (value * weight).
      - Normalizada pelo soma dos pesos das Evidences.
      - Limitada ao intervalo [-1.0, 1.0].

    Uso:
        builder = SignalBuilder()
        signal = builder.build(
            signal_type="context",
            weight=0.20,
            evidences=(ev1, ev2),
            explanation="Contexto corresponde",
        )
    """

    def __init__(self, policy: EvidencePolicy | None = None) -> None:
        self._policy = policy or EvidencePolicy()

    @property
    def policy(self) -> EvidencePolicy:
        return self._policy

    def build(
        self,
        signal_type: str,
        weight: float,
        evidences: tuple[Evidence, ...] = (),
        explanation: str = "",
        value_override: float | None = None,
    ) -> "IntelligenceSignal":
        """Constrói um IntelligenceSignal a partir de Evidences.

        Args:
            signal_type: tipo do sinal ("context", "feedback", etc.).
            weight: peso do sinal (da IntelligencePolicy).
            evidences: tuple de Evidence que sustentam o sinal.
            explanation: explicação legível do sinal.
            value_override: se fornecido, usa este value em vez de
                calcular a partir das Evidences (para compatibilidade
                com lógica existente).

        Returns:
            IntelligenceSignal com evidences anexadas.
        """
        # Import tardio para evitar circular import
        from intelligence.dtos import IntelligenceSignal

        if value_override is not None:
            value = value_override
        elif evidences:
            total_weight = sum(e.weight for e in evidences)
            if total_weight > 0:
                weighted_sum = sum(e.contribution for e in evidences)
                value = weighted_sum / total_weight
            else:
                value = 0.0
        else:
            value = 0.0

        # Clamp [-1.0, 1.0]
        value = max(-1.0, min(1.0, value))

        # Limitar número de evidências
        if len(evidences) > self._policy.max_evidences_per_signal:
            evidences = self._policy.sort_by_priority(evidences)[
                :self._policy.max_evidences_per_signal
            ]

        return IntelligenceSignal(
            signal_type=signal_type,
            value=value,
            weight=weight,
            explanation=explanation,
            evidences=evidences,
        )


__all__ = [
    "EvidenceType",
    "Evidence",
    "EvidencePolicy",
    "EvidenceFactory",
    "SignalBuilder",
]
