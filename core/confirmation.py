"""Camada de confirmação para resultados de busca ambíguos.

Responsabilidade:
  - Detectar quando o Searcher retorna resultados ambíguos (ambiguous=True
    e >= 2 candidatos).
  - Construir um CandidateList DTO com os candidatos para a interface
    escolher.
  - Executar o candidato escolhido via DecisionEngine.execute(),
    reutilizando 100% da lógica existente.

Limites explícitos (o que este módulo NÃO faz):
  - Não modifica Searcher, Parser, LLM, DecisionEngine ou Holyrics.
  - Não reexecuta busca, LLM ou Parser.
  - Não altera LogEntry nem interfaces públicas existentes.
  - Não implementa interface gráfica — apenas expõe os dados.

Design:
  - CandidateSelector é a única classe pública.
  - Candidate e CandidateList são DTOs imutáveis (frozen dataclasses).
  - select() constrói [selected_result] e chama engine.execute() com
    um Decision modificado (outcome="execute"), preservando o
    search_results original intacto para logs, depuração e interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.exceptions import DecisionError
from core.types import Decision, VerseRef

if TYPE_CHECKING:
    from busca.searcher import SearchResult
    from core.decision import DecisionEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """Candidato individual para seleção do usuário.

    Atributos:
        index: índice 1-based para seleção pelo usuário (1, 2, 3, ...).
        book: nome canônico do livro ("João", "Gênesis").
        book_id: ID do livro (1..66).
        chapter: número do capítulo.
        verse: número do versículo (None para capítulo inteiro).
        version: versão bíblica ("ACF", "ARA", "NVI").
        reference: referência legível ("João 3:16").
        score: score combinado [0.0, 1.0] (RRF normalizado).
        c_search: confidence da busca [0.0, 1.0].
        snippet: texto do versículo truncado (para preview na UI).
        display_reference: referência com versão para apresentação na UI
            ("João 3:16 (ACF)"). Campo calculado — não armazenado, derivado
            de reference + version.
    """

    index: int
    book: str
    book_id: int
    chapter: int
    verse: int | None
    version: str
    reference: str
    score: float
    c_search: float
    snippet: str

    @property
    def display_reference(self) -> str:
        """Referência legível com versão: "João 3:16 (ACF)"."""
        return f"{self.reference} ({self.version})"


@dataclass(frozen=True)
class CandidateList:
    """Lista de candidatos para seleção do usuário.

    Atributos:
        candidates: lista de Candidate ordenada por score decrescente.
        query: query original da busca (para contexto na UI).
        total: número total de candidatos.
    """

    candidates: tuple[Candidate, ...]
    query: str | None = None
    total: int = 0

    def __len__(self) -> int:
        return len(self.candidates)

    def __iter__(self):
        return iter(self.candidates)

    def __getitem__(self, index: int) -> Candidate:
        return self.candidates[index]


@dataclass
class SelectionResult:
    """Resultado da execução de um candidato selecionado.

    Atributos:
        ref: VerseRef resolvido e enviado ao Holyrics (None se falhou).
        selected_result: SearchResult que foi selecionado e executado.
        success: True se a execução foi bem-sucedida.
        error: mensagem de erro se success=False, None caso contrário.
    """

    ref: VerseRef | None
    selected_result: SearchResult | None
    success: bool
    error: str | None = None


@dataclass
class ProcessResult:
    """Resultado detalhado de process_utterance_detailed().

    Diferente de LogEntry (que representa apenas o registro da execução
    do pipeline), ProcessResult expõe todos os objetos internos necessários
    para a interface decidir o próximo passo (seleção de candidato,
    confirmação, etc.).

    Atributos:
        log_entry: LogEntry canônico (inalterado, mesmo que process_utterance).
        decision: Decision retornado pelo DecisionEngine (None se stage falhou).
        search_results: resultados completos da busca (None se busca não
            executou ou falhou). Preservado intacto para logs e depuração.
        candidates: CandidateList se ambiguous + >= 2 resultados, senão None.
        requires_confirmation: True se a interface deve pedir confirmação/
            seleção ao usuário (outcome == "confirm" ou candidates != None).
    """

    log_entry: "object"  # LogEntry (evita import circular)
    decision: Decision | None = None
    search_results: list[SearchResult] | None = None
    candidates: CandidateList | None = None
    requires_confirmation: bool = False


# ---------------------------------------------------------------------------
# CandidateSelector
# ---------------------------------------------------------------------------


# Limite de caracteres do snippet para preview na UI
_SNIPPET_MAX_CHARS = 120


def _truncate_snippet(text: str, max_chars: int = _SNIPPET_MAX_CHARS) -> str:
    """Trunca o texto do versículo para preview."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


# ---------------------------------------------------------------------------
# ConfirmationPolicy
# ---------------------------------------------------------------------------


class ConfirmationPolicy:
    """Política de confirmação para resultados de busca ambíguos.

    Encapsula a decisão de whether o pipeline deve pedir confirmação/
    seleção ao usuário. Hoje a política é trivial:

        requires_confirmation = ambiguous

    Futuramente pode evoluir para incorporar critérios adicionais
    (score_gap, top_k, confidence, embedding_score, rerank_score,
    llm_confidence) sem necessidade de alterar o restante do pipeline.

    Design:
        - Classe sem estado (stateless) — pode ser instanciada uma vez
          e reutilizada.
        - Método único requires_confirmation() com assinatura extensível.
        - Parâmetros futuros são aceitos mas ignorados nesta versão.
        - Não altera nenhum threshold, score ou heurística.
    """

    def requires_confirmation(
        self,
        ambiguous: bool,
        total_results: int = 0,
        *,
        score_gap: float | None = None,
        top_k: int | None = None,
        confidence: float | None = None,
        embedding_score: float | None = None,
        rerank_score: float | None = None,
        llm_confidence: float | None = None,
    ) -> bool:
        """Decide se o pipeline deve pedir confirmação ao usuário.

        Hoje: retorna ``ambiguous`` inalterado.
        Futuramente pode combinar ``ambiguous`` com outros critérios.

        Args:
            ambiguous: flag de ambiguidade do Searcher (gap top1/top2
                < search_gap).
            total_results: número total de resultados da busca.
            score_gap: diferença de score entre top1 e top2 (reservado).
            top_k: número máximo de resultados solicitados (reservado).
            confidence: confiança combinada c_final (reservado).
            embedding_score: score de embedding (reservado).
            rerank_score: score de reranking (reservado).
            llm_confidence: confiança do LLM (reservado).

        Returns:
            True se o pipeline deve pedir confirmação, False caso contrário.
        """
        return ambiguous


class CandidateSelector:
    """Gerencia a seleção de candidatos quando a busca é ambígua.

    Fluxo:
        1. build_candidates(search_results) → CandidateList | None
        2. (interface mostra candidatos e usuário escolhe um índice)
        3. select(candidates, search_results, decision, index) → SelectionResult

    Example:
        >>> selector = CandidateSelector(engine)
        >>> candidates = selector.build_candidates(search_results, query="amor")
        >>> if candidates is not None:
        ...     # interface mostra candidates
        ...     result = selector.select(candidates, search_results, decision, 2)
        ...     if result.success:
        ...         print(f"Aberto: {result.ref.reference}")
    """

    def __init__(self, engine: DecisionEngine) -> None:
        self._engine = engine

    def build_candidates(
        self,
        search_results: list[SearchResult] | None,
        query: str | None = None,
    ) -> CandidateList | None:
        """Constrói CandidateList se a busca for ambígua com >= 2 resultados.

        Args:
            search_results: resultados completos da busca (do Searcher).
            query: query original da busca (opcional, para contexto).

        Returns:
            CandidateList se ambiguous=True e >= 2 resultados, senão None.
        """
        if search_results is None or len(search_results) < 2:
            return None

        # Verificar flag ambiguous do top1 (Searcher replica para todos)
        if not search_results[0].ambiguous:
            return None

        candidates = tuple(
            Candidate(
                index=i + 1,
                book=r.book,
                book_id=r.book_id,
                chapter=r.chapter,
                verse=r.verse,
                version=r.version,
                reference=r.reference,
                score=r.score,
                c_search=r.c_search,
                snippet=_truncate_snippet(r.text),
            )
            for i, r in enumerate(search_results)
        )

        return CandidateList(
            candidates=candidates,
            query=query,
            total=len(candidates),
        )

    def select(
        self,
        candidates: CandidateList,
        search_results: list[SearchResult],
        decision: Decision,
        index: int,
    ) -> SelectionResult:
        """Executa o candidato selecionado pelo usuário.

        Constrói uma nova lista [selected_result] contendo apenas o
        SearchResult escolhido, modifica decision.outcome para "execute",
        e chama engine.execute(decision, [selected_result]).

        Não modifica search_results original — apenas constrói uma nova
        lista de 1 elemento. Não reexecuta busca, LLM ou Parser.

        Args:
            candidates: CandidateList construído por build_candidates().
            search_results: resultados originais da busca (intactos).
            decision: Decision original (outcome="confirm" ou similar).
            index: índice 1-based escolhido pelo usuário (1, 2, ...).

        Returns:
            SelectionResult com ref, selected_result, success e error.

        Raises:
            ValueError: se índice fora do range [1, total].
        """
        if index < 1 or index > len(candidates):
            raise ValueError(
                f"index {index} fora do range [1, {len(candidates)}]"
            )

        # SearchResult correspondente ao índice (0-based na lista original)
        selected_result = search_results[index - 1]

        # Construir nova lista com apenas o resultado selecionado
        # — preserva search_results original intacto
        selected_list = [selected_result]

        # Criar uma cópia do Decision com outcome="execute"
        # — não modificar o Decision original
        from dataclasses import replace as _replace
        exec_decision = _replace(
            decision,
            outcome="execute",
            requires_confirmation=False,
        )

        logger.info(
            "CandidateSelector.select: index=%d ref=%s version=%s",
            index,
            selected_result.reference,
            selected_result.version,
        )

        try:
            ref = self._engine.execute(exec_decision, selected_list)
            logger.info(
                "CandidateSelector.select: success ref=%s",
                ref.reference if ref else "None",
            )
            return SelectionResult(
                ref=ref,
                selected_result=selected_result,
                success=True,
                error=None,
            )
        except DecisionError as e:
            logger.error("CandidateSelector.select: DecisionError: %s", e)
            return SelectionResult(
                ref=None,
                selected_result=selected_result,
                success=False,
                error=str(e),
            )
