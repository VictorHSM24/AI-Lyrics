"""Tipos canônicos compartilhados entre módulos.

Nenhum módulo redefine estes tipos (Blueprint §1: "Tipos canônicos em
core/types.py — nenhum módulo redefine Intent, VerseRef, SearchResult,
Confidence, Decision, LogEntry").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Action = Literal["show", "next", "previous", "search", "jump", "none", "uncertain"]
Outcome = Literal["execute", "confirm", "ignore", "forward_to_llm"]


@dataclass
class Intent:
    """Saída do parser ou do LLM. Unidade de intenção interpretada."""

    action: Action
    book: str | None = None        # nome canônico (ex.: "João", "1 Coríntios")
    book_id: int | None = None     # 1..66
    chapter: int | None = None     # int ou "current" (para jump)
    verse: int | None = None
    amount: int | None = None      # para next/previous/jump relativo
    query: str | None = None       # frase para busca (action=search)
    version: str | None = None
    confidence: float = 0.0        # c_intent (parser ou LLM)
    source: Literal["parser", "llm"] = "parser"
    raw: str = ""                  # texto original transcrito
    enrichment: dict | None = None  # dados enriquecidos do LLM (keywords,
                                     # tema, evento, personagens, etc.) —
                                     # usados pelo QueryPlanner


@dataclass(frozen=True)
class VerseRef:
    """Referência bíblica resolvida e validada."""

    book_id: int          # 1..66
    book: str             # nome canônico PT-BR
    chapter: int
    verse: int | None     # None = capítulo inteiro
    version: str = "ACF"

    @property
    def id(self) -> str:  # BBCCCVVV
        v = self.verse or 0
        return f"{self.book_id:02d}{self.chapter:03d}{v:03d}"

    @property
    def reference(self) -> str:  # "João 3:16"
        v = f":{self.verse}" if self.verse else ""
        return f"{self.book} {self.chapter}{v}"


@dataclass
class Confidence:
    """Confianças multi-etapa (STT, parser/LLM, busca).

    c_final = c_stt * c_intent * c_search (multiplicação conservadora).
    """

    c_stt: float = 1.0
    c_intent: float = 1.0    # parser ou LLM
    c_search: float = 1.0    # 1.0 se não é search

    @property
    def c_final(self) -> float:
        """Confiança final combinada (multiplicação)."""
        return self.c_stt * self.c_intent * self.c_search


@dataclass
class Decision:
    """Decisão do motor de decisão.

    Atributos:
        action: action original do Intent ("show", "next", "search", etc.).
        outcome: resultado da decisão ("execute", "confirm", "ignore",
            "forward_to_llm").
        confidence: confiança final [0.0, 1.0].
        requires_confirmation: True se outcome == "confirm".
        forward_to_llm: True se outcome == "forward_to_llm".
        ignore: True se outcome == "ignore".
        reason: justificativa humana-legível.
        intent: Intent original avaliado.
        ref: VerseRef resolvido (se aplicável e outcome == "execute").
        confidence_breakdown: Confidence com c_stt, c_intent, c_search.
    """

    action: str
    outcome: Outcome
    confidence: float
    requires_confirmation: bool
    forward_to_llm: bool
    ignore: bool
    reason: str
    intent: Intent
    ref: VerseRef | None = None
    confidence_breakdown: Confidence | None = None


@dataclass
class Utterance:
    """Saída do STT consumida pelo pipeline.

    Atributos:
        text: texto transcrito.
        c_stt: confiança da transcrição [0.0, 1.0].
        audio_ms: duração do áudio em milissegundos.
        segments: segmentos brutos do faster-whisper (para debug).
    """

    text: str
    c_stt: float = 1.0
    audio_ms: int = 0
    segments: list = field(default_factory=list)


@dataclass
class LogEntry:
    """Entrada de log estruturado do pipeline (Blueprint §0.1).

    Cada execução do pipeline produz uma LogEntry com timing e
    confiança de cada etapa. Serializada como JSONL pelo PipelineLogger.

    Atributos:
        ts: timestamp ISO 8601.
        id: identificador único da execução.
        audio_ms: duração do áudio em milissegundos.
        stt: dict com timing/confiança do STT.
        parser: dict com timing/resultado do parser.
        llm: dict com timing/resultado do LLM (vazio se não usado).
        search: dict com timing/resultado da busca (vazio se não usado).
        confidence: dict com c_stt, c_intent, c_search, c_final.
        decision: dict com outcome, confidence, reason.
        holyrics: dict com timing/resultado do Holyrics.
        cache: dict com hit/miss (vazio se cache não usado).
        total_ms: tempo total da execução em milissegundos.
    """

    ts: str
    id: str
    audio_ms: int
    stt: dict
    parser: dict
    llm: dict
    search: dict
    confidence: dict
    decision: dict
    holyrics: dict
    cache: dict
    total_ms: int
