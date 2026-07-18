"""Eventos tipados para o Feedback Learning.

Os eventos representam decisões do operador — não comandos.
Eles são emitidos pelo pipeline (atualmente não conectado) e processados
pelo FeedbackEngine para atualizar estatísticas.

Design:
  - Todos os eventos são frozen dataclasses (imutáveis).
  - Todos herdam de FeedbackEvent.
  - Cada evento carrega apenas os dados necessários.
  - Eventos não conhecem o FeedbackEngine — apenas o engine os processa.
  - Novos eventos podem ser adicionados sem quebrar eventos existentes.

Compatibilidade futura:
  Novos eventos podem ser adicionados (ex.: CandidateEdited,
  ResultReordered) sem quebrar o engine existente.

Eventos implementados:
  - CandidateAccepted: operador aceitou um candidato sugerido.
  - CandidateRejected: operador rejeitou um candidato sugerido.
  - ManualReferenceSelected: operador selecionou uma referência manualmente
      (não estava nas sugestões ou escolheu uma diferente).
  - ManualSearch: operador fez uma busca manual (não usou sugestão).
  - SuggestionIgnored: operador ignorou uma sugestão (não agiu).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from feedback.dtos import FeedbackKey, FeedbackScope


# ---------------------------------------------------------------------------
# Evento base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackEvent:
    """Base abstrata para eventos de feedback.

    Todos os eventos herdam desta classe. O campo `timestamp` é opcional
    e pode ser usado para ordenação cronológica e cálculo de decaimento.

    Atributos:
        timestamp: timestamp do evento (segundos desde epoch).
    """

    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Eventos de decisão do operador
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateAccepted(FeedbackEvent):
    """Operador aceitou um candidato sugerido.

    Emitido quando o operador seleciona um candidato que estava na lista
    de sugestões. Indica preferência positiva.

    Ex.: Sistema sugere "João 3:16", operador aceita.

    Atributos:
        key: FeedbackKey (scope + query + context + candidate).
    """

    key: FeedbackKey = field(default_factory=lambda: FeedbackKey(
        scope=FeedbackScope.GLOBAL, query="", context_signature="", candidate_id=""))


@dataclass(frozen=True)
class CandidateRejected(FeedbackEvent):
    """Operador rejeitou um candidato sugerido.

    Emitido quando o operador explicitamente rejeita um candidato
    (ex.: fecha, descarta, ou escolhe outro). Indica preferência negativa.

    Ex.: Sistema sugere "João 3:16", operador rejeita e busca outra.

    Atributos:
        key: FeedbackKey.
    """

    key: FeedbackKey = field(default_factory=lambda: FeedbackKey(
        scope=FeedbackScope.GLOBAL, query="", context_signature="", candidate_id=""))


@dataclass(frozen=True)
class ManualReferenceSelected(FeedbackEvent):
    """Operador selecionou uma referência manualmente.

    Emitido quando o operador digita/seleciona uma referência que NÃO
    estava nas sugestões, ou escolhe uma sugestão diferente da top-1.
    Indica preferência forte por aquele candidato naquele contexto.

    Ex.: Sistema sugere top-1 "Lucas 15", operador escolhe "João 21".

    Atributos:
        key: FeedbackKey.
    """

    key: FeedbackKey = field(default_factory=lambda: FeedbackKey(
        scope=FeedbackScope.GLOBAL, query="", context_signature="", candidate_id=""))


@dataclass(frozen=True)
class ManualSearch(FeedbackEvent):
    """Operador fez uma busca manual (não usou sugestão).

    Emitido quando o operador faz uma busca manual em vez de usar
    uma sugestão. Indica que as sugestões não foram úteis para
    aquela consulta/contexto.

    Atributos:
        key: FeedbackKey.
        query_text: texto original da busca manual (para log).
    """

    key: FeedbackKey = field(default_factory=lambda: FeedbackKey(
        scope=FeedbackScope.GLOBAL, query="", context_signature="", candidate_id=""))
    query_text: str = ""


@dataclass(frozen=True)
class SuggestionIgnored(FeedbackEvent):
    """Operador ignorou uma sugestão (não agiu).

    Emitido quando uma sugestão foi apresentada mas o operador não
    agiu (nem aceitou, nem rejeitou, nem buscou manualmente) dentro
    de um prazo. Indica preferência negativa leve.

    Atributos:
        key: FeedbackKey.
    """

    key: FeedbackKey = field(default_factory=lambda: FeedbackKey(
        scope=FeedbackScope.GLOBAL, query="", context_signature="", candidate_id=""))


# ---------------------------------------------------------------------------
# Union de todos os eventos (para type hints)
# ---------------------------------------------------------------------------


FeedbackEventUnion = Union[
    CandidateAccepted,
    CandidateRejected,
    ManualReferenceSelected,
    ManualSearch,
    SuggestionIgnored,
]


__all__ = [
    "FeedbackEvent",
    "CandidateAccepted",
    "CandidateRejected",
    "ManualReferenceSelected",
    "ManualSearch",
    "SuggestionIgnored",
    "FeedbackEventUnion",
]
