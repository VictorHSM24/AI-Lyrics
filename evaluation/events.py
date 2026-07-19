"""Eventos tipados para o Continuous Evaluation.

Os eventos representam observações do sistema — não comandos.
Eles são emitidos pelo pipeline (atualmente não conectado) e processados
pelo EvaluationEngine para registrar métricas.

Design:
  - Todos os eventos são frozen dataclasses (imutáveis).
  - Todos herdam de EvaluationEvent.
  - Cada evento carrega apenas os dados necessários.
  - Eventos não conhecem o EvaluationEngine — apenas o engine os processa.
  - Novos eventos podem ser adicionados sem quebrar eventos existentes.

Eventos implementados:
  - SearchExecuted: uma busca foi executada.
  - CandidatePresented: um candidato foi apresentado ao operador.
  - CandidateAccepted: um candidato foi aceito pelo operador.
  - CandidateRejected: um candidato foi rejeitado pelo operador.
  - ManualCorrection: o operador corrigiu manualmente um resultado.
  - SearchFailed: uma busca falhou tecnicamente.
  - NoResultFound: uma busca não retornou resultados.
  - EvaluationReset: as métricas foram resetadas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from evaluation.dtos import QueryClassification


# ---------------------------------------------------------------------------
# Evento base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationEvent:
    """Base abstrata para eventos de avaliação.

    Atributos:
        timestamp: timestamp do evento (segundos desde epoch).
        query: consulta normalizada do operador (ou "").
        classification: classificação da consulta.
        context_signature: assinatura do contexto do sermão (ou "").
        operator_id: ID do operador (default "").
    """

    timestamp: float = 0.0
    query: str = ""
    classification: QueryClassification = QueryClassification.UNKNOWN
    context_signature: str = ""
    operator_id: str = ""


# ---------------------------------------------------------------------------
# Eventos de busca
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchExecuted(EvaluationEvent):
    """Uma busca foi executada.

    Emitido sempre que uma busca é realizada, independentemente do
    resultado. Usado para contar total de buscas e calcular tempo médio.

    Atributos:
        duration_ms: duração da busca em milissegundos.
        result_count: número de resultados retornados.
        book: livro envolvido na busca (se aplicável, ou "").
    """

    duration_ms: float = 0.0
    result_count: int = 0
    book: str = ""


@dataclass(frozen=True)
class CandidatePresented(EvaluationEvent):
    """Um candidato foi apresentado ao operador.

    Emitido quando um candidato é mostrado na lista de sugestões.
    Usado para contar total de candidatos apresentados.

    Atributos:
        candidate_id: ID do candidato apresentado.
        rank_position: posição na lista (1 = top-1).
    """

    candidate_id: str = ""
    rank_position: int = 0


@dataclass(frozen=True)
class CandidateAccepted(EvaluationEvent):
    """Um candidato foi aceito pelo operador.

    Emitido quando o operador aceita um candidato sugerido.
    Indica acerto do sistema.

    Atributos:
        candidate_id: ID do candidato aceito.
        book: livro do candidato (se aplicável).
    """

    candidate_id: str = ""
    book: str = ""


@dataclass(frozen=True)
class CandidateRejected(EvaluationEvent):
    """Um candidato foi rejeitado pelo operador.

    Emitido quando o operador explicitamente rejeita um candidato.
    Indica erro do sistema.

    Atributos:
        candidate_id: ID do candidato rejeitado.
        book: livro do candidato (se aplicável).
    """

    candidate_id: str = ""
    book: str = ""


@dataclass(frozen=True)
class ManualCorrection(EvaluationEvent):
    """O operador corrigiu manualmente um resultado.

    Emitido quando o operador substitui um resultado sugerido por outro
    escolhido manualmente. Indica erro do sistema.

    Atributos:
        original_candidate_id: ID do candidato original (sugerido).
        corrected_candidate_id: ID do candidato correto (manual).
        book: livro do candidato corrigido (se aplicável).
    """

    original_candidate_id: str = ""
    corrected_candidate_id: str = ""
    book: str = ""


@dataclass(frozen=True)
class SearchFailed(EvaluationEvent):
    """Uma busca falhou tecnicamente.

    Emitido quando uma busca não pode ser executada por erro técnico
    (ex.: banco indisponível, timeout). Indica problema de infraestrutura.

    Atributos:
        error_message: mensagem de erro (para log).
    """

    error_message: str = ""


@dataclass(frozen=True)
class NoResultFound(EvaluationEvent):
    """Uma busca não retornou resultados.

    Emitido quando uma busca é executada mas retorna zero resultados.
    Indica que o sistema não conseguiu encontrar nada para a consulta.

    Atributos:
        book: livro consultado (se aplicável).
    """

    book: str = ""


@dataclass(frozen=True)
class EvaluationReset(EvaluationEvent):
    """As métricas de avaliação foram resetadas.

    Emitido quando o operador ou administrador decide limpar todas as
    métricas acumuladas. O engine reseta os registros.

    Atributos:
        reason: motivo do reset (para log).
    """

    reason: str = ""


# ---------------------------------------------------------------------------
# Union de todos os eventos (para type hints)
# ---------------------------------------------------------------------------


EvaluationEventUnion = Union[
    SearchExecuted,
    CandidatePresented,
    CandidateAccepted,
    CandidateRejected,
    ManualCorrection,
    SearchFailed,
    NoResultFound,
    EvaluationReset,
]


__all__ = [
    "EvaluationEvent",
    "SearchExecuted",
    "CandidatePresented",
    "CandidateAccepted",
    "CandidateRejected",
    "ManualCorrection",
    "SearchFailed",
    "NoResultFound",
    "EvaluationReset",
    "EvaluationEventUnion",
]
