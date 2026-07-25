"""semantic/types.py — Tipos da camada de compreensão semântica (Sprint 20).

Responsabilidade:
  - Definir SemanticCandidate (hipótese de referência bíblica).
  - Definir SemanticResult (resposta estruturada do provider).
  - Definir SemanticContext (contexto construído pelo ContextEngine).

Estes tipos são IMUTÁVEIS (frozen dataclasses) e não dependem de
nenhum outro módulo do AI Lyrics — podem ser serializados para JSON
e usados como contrato entre SemanticEngine, SemanticProvider e
ReferenceResolver.

Sprint 20 — Semantic Understanding Engine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


__all__ = [
    "SemanticCandidate",
    "SemanticResult",
    "SemanticContext",
    "SemanticError",
    "SemanticTimeout",
]


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------


class SemanticError(Exception):
    """Erro genérico da camada semântica."""


class SemanticTimeout(SemanticError):
    """Timeout na inferência do provider."""


# ---------------------------------------------------------------------------
# SemanticCandidate — uma hipótese de referência
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticCandidate:
    """Hipótese de referência bíblica gerada pelo LLM.

    Atributos:
        book: nome do livro ("João", "Provérbios", "1 Coríntios").
            Pode estar em qualquer forma ("joao", "joão", "I João") —
            o ReferenceResolver normaliza via BookTable.
        chapter: número do capítulo (0 se desconhecido).
        verse: número do versículo (0 se desconhecido — capítulo inteiro).
        confidence: confiança [0.0, 1.0] atribuída pelo LLM.
        reason: justificativa textual curta ("Jesus conversa com Nicodemos").
    """

    book: str = ""
    chapter: int = 0
    verse: int = 0
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SemanticResult — resposta estruturada do provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticResult:
    """Resposta estruturada do SemanticProvider.

    O provider NUNCA retorna texto livre — apenas este schema.
    Se o provider retornar algo que não pode ser parseado para este
    schema, o SemanticEngine descarta a resposta (Etapa 7 — Segurança).

    Atributos:
        intent: intenção detectada. Valores válidos:
            - "show_reference": usuário quer mostrar uma referência
            - "none": não é uma referência bíblica
        candidates: lista de candidatos (vazia se intent="none").
        inference_ms: tempo de inferência em milissegundos.
        provider: nome do provider ("local-llm", "stub", etc.).
        model: nome do modelo usado ("llama3.2:3b", etc.).
    """

    intent: str = "none"
    candidates: tuple[SemanticCandidate, ...] = field(default_factory=tuple)
    inference_ms: int = 0
    provider: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "candidates": [c.to_dict() for c in self.candidates],
            "inference_ms": self.inference_ms,
            "provider": self.provider,
            "model": self.model,
        }

    @property
    def has_candidates(self) -> bool:
        return self.intent == "show_reference" and len(self.candidates) > 0


# ---------------------------------------------------------------------------
# SemanticContext — contexto construído pelo ContextEngine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticContext:
    """Contexto enviado ao SemanticProvider.

    Construído pelo ContextEngine a partir do histórico de eventos.
    Inclui últimos 30-60s de fala, última referência encontrada,
    livro/capítulo atual e histórico recente.

    Sprint 21 — enriquecido com SermonContext (memória contínua):
      - sermon_book, sermon_chapter: livro/capítulo atual do sermão.
      - sermon_theme: tema provável.
      - sermon_entities: entidades reconhecidas (nomes).
      - sermon_confidence: confiança da memória.

    Atributos:
        current_text: texto atual sendo analisado.
        recent_text: últimos 30-60s de fala (concatenados).
        last_book: último livro referenciado ("João") ou "".
        last_chapter: último capítulo referenciado ou 0.
        last_reference: última referência completa ("João 3:16") ou "".
        session_id: ID da sessão atual.
        timestamp: timestamp do contexto (time.time()).
        sermon_book: livro atual do sermão (Sprint 21) ou "".
        sermon_chapter: capítulo atual do sermão (Sprint 21) ou 0.
        sermon_theme: tema provável do sermão (Sprint 21) ou "".
        sermon_entities: entidades reconhecidas (Sprint 21) — lista de nomes.
        sermon_confidence: confiança geral da memória do sermão (Sprint 21).
        sermon_book_confidence: Sprint 22.2 — confiança específica do
            sermon_book [0.0, 1.0]. Diferente de sermon_confidence (que
            mede o contexto geral), mede quão fortemente o SermonMemory
            acredita que o pregador ainda está no sermon_book. Usado
            pela ContextPolicy para decidir se inclui o contexto no
            prompt (Sprint 22.2).
    """

    current_text: str = ""
    recent_text: str = ""
    last_book: str = ""
    last_chapter: int = 0
    last_reference: str = ""
    session_id: str = ""
    timestamp: float = 0.0
    # Sprint 21 — Sermon Memory
    sermon_book: str = ""
    sermon_chapter: int = 0
    sermon_theme: str = ""
    sermon_entities: tuple[str, ...] = field(default_factory=tuple)
    sermon_confidence: float = 0.0
    # Sprint 22.2 — confiança específica do sermon_book.
    sermon_book_confidence: float = 0.0
    # Sprint 22.0 — RAG Local: candidatos recuperados da Bíblia local.
    # Lista de BibleCandidate (estrutura imutável do pacote knowledge).
    # Vazia quando o modo RAG está desabilitado ou não encontrou candidatos.
    rag_candidates: tuple[Any, ...] = field(default_factory=tuple)
    # ID de correlação para rastrear a consulta no retriever (Sprint 22.0).
    correlation_id: str = ""
    # Sprint 22.2 — decisão da ContextPolicy (quanto do contexto do
    # sermão incluir no prompt). Any para evitar import circular com
    # semantic.context_policy. None quando a ContextPolicy não foi
    # aplicada (modo não-RAG ou fallback).
    context_decision: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_text": self.current_text,
            "recent_text": self.recent_text,
            "last_book": self.last_book,
            "last_chapter": self.last_chapter,
            "last_reference": self.last_reference,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "sermon_book": self.sermon_book,
            "sermon_chapter": self.sermon_chapter,
            "sermon_theme": self.sermon_theme,
            "sermon_entities": list(self.sermon_entities),
            "sermon_confidence": self.sermon_confidence,
            "sermon_book_confidence": round(self.sermon_book_confidence, 4),
            "rag_candidates_count": len(self.rag_candidates),
            "correlation_id": self.correlation_id,
            "context_decision": (
                self.context_decision.to_dict()
                if self.context_decision is not None
                and hasattr(self.context_decision, "to_dict")
                else None
            ),
        }

    def context_hash(self) -> str:
        """Hash determinístico do contexto para cache.

        Hash apenas dos campos que afetam a inferência:
        current_text + recent_text + last_book + last_chapter +
        sermon_book + sermon_chapter + sermon_theme + rag_candidates.
        """
        import hashlib
        # Sprint 22.0 — incluir rag_candidates no hash, pois afeta o prompt.
        rag_key = "|".join(
            getattr(c, "canonical_reference", "") for c in self.rag_candidates
        )
        # Sprint 22.2 — incluir a decisão da ContextPolicy, pois afeta
        # qual variante do prompt é gerada (contexto omitido/resumido/completo).
        decision_key = ""
        if self.context_decision is not None:
            decision_key = getattr(self.context_decision, "include_context", "")
        key = "|".join([
            self.current_text.strip().lower(),
            self.recent_text.strip().lower(),
            self.last_book.strip().lower(),
            str(self.last_chapter),
            self.sermon_book.strip().lower(),
            str(self.sermon_chapter),
            self.sermon_theme.strip().lower(),
            rag_key,
            decision_key,
        ])
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
