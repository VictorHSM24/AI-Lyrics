"""Mecanismo de busca de versículos bíblicos.

Responsabilidades:
  - Abrir a base SQLite FTS5 criada pelo indexador (read-only).
  - Busca textual via FTS5 (BM25 ranking).
  - Busca textual aproximada via FTS5 + rapidfuzz (RRF fusion).
  - Busca por referência exata (João 3:16).
  - Busca por capítulo (João 3 → todos os versículos).
  - Busca contextual ("próximo") usando BibleState.
  - Ranquear resultados, limitar quantidade, calcular confidence.
  - Retornar SearchResult estruturado com métricas.

Arquitetura:
  - FTS5 é o mecanismo principal (tokenizador unicode61 remove_diacritics 2).
  - rapidfuzz fornece fuzzy matching para aproximação textual.
  - RRF (Reciprocal Rank Fusion) combina rankings quando múltiplas fontes.
  - Embeddings NÃO são implementados neste módulo (futuro: busca híbrida
    com embeddings será adicionada via Embedder injetável).

Sprint 18.0.1 — Thread Safety:
  - A conexão SQLite NÃO é mais mantida aberta entre chamadas.
  - Cada operação abre uma conexão nova (read-only, via URI) e fecha ao
    terminar. Isto elimina definitivamente o erro
    "SQLite objects created in a thread can only be used in that same
    thread" que ocorria quando o VersePresentationService chamava
    search_by_reference() a partir da thread SpeechWorker-Whisper.
  - O custo de abrir/fechar (~0.5-2ms) é desprezível frente ao tempo
    total de busca (~50ms) e garante segurança total em ambientes
    multithreaded sem recorrer a check_same_thread=False ou mutex.
  - O Searcher é agora verdadeiramente stateless após a construção.

Performance:
  - FTS5: 1-5ms para ~31k versículos.
  - rapidfuzz: ~5-10ms para top-50 candidatos.
  - RRF + ranking: <1ms.
  - Total: <50ms p95.

Bibliotecas permitidas: sqlite3, rapidfuzz, numpy.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterator, Literal

from busca.exceptions import SearchError
from busca.query_planner import QueryPlan, QueryPlanner
from busca.ranking import RankingPolicy
from config.books import BookTable
from config.models import SearchConfig

if TYPE_CHECKING:
    from busca.embedding_searcher import EmbeddingSearcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

_MATCH_TYPE = Literal["fts", "fuzzy", "hybrid", "reference", "chapter", "context"]

# FTS5 BM25 scores são negativos (mais negativo = melhor).
# Convertemos para positivo e normalizamos via sigmoid.
_BM25_SCALE = 5.0  # fator de escala para sigmoid (calibrado empiricamente)

# Número de candidatos FTS5 para re-ranking com rapidfuzz.
_FTS5_CANDIDATE_MULTIPLIER = 5

# Número máximo de versões no banco (para ajustar limit da query FTS5).
_MAX_VERSIONS = 5

# Bônus de preferência por versão (aplicado após RRF, antes do ranking final).
# Valores pequenos: desempatam versões com scores próximos, mas nunca
# fazem uma versão com match pior vencer uma com match muito melhor.
_VERSION_BONUS: dict[str, float] = {
    "ACF": 0.05,
    "ARC": 0.04,
    "JFAA": 0.03,
    "ARA": 0.02,
    "NAA": 0.01,
}

# Regex para detecção de referência (book chapter:verse ou book chapter).
_REF_PATTERN = re.compile(
    r"^(.+?)\s+(\d+)(?::(\d+))?$",
    re.IGNORECASE,
)

# Palavras-chave contextuais.
_CONTEXT_NEXT = {"proximo", "próximo", "seguinte", "next", "avancar", "avançar"}
_CONTEXT_PREV = {"anterior", "prev", "previous", "voltar", "retroceder"}


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchResult:
    """Resultado de uma busca de versículo.

    Atributos:
        reference: referência legível ("João 3:16").
        book: nome canônico do livro ("João").
        book_id: ID do livro (1..66).
        chapter: número do capítulo.
        verse: número do versículo (None para capítulo inteiro).
        text: texto do versículo.
        version: versão bíblica ("ACF", "NVI", "ARA").
        score: score combinado [0.0, 1.0] (RRF normalizado).
        c_search: confidence da busca [0.0, 1.0].
        ambiguous: True se gap top1/top2 < search_gap.
        match_type: tipo de match ("fts", "fuzzy", "hybrid", "reference",
            "chapter", "context").
    """

    reference: str
    book: str
    book_id: int
    chapter: int
    verse: int | None
    text: str
    version: str
    score: float
    c_search: float
    ambiguous: bool
    match_type: str


@dataclass
class SearchMetrics:
    """Métricas acumuladas de busca para monitoramento.

    Acumuladas desde a inicialização ou último reset.
    """

    total_searches: int = 0
    successful: int = 0
    failed: int = 0
    empty_results: int = 0
    total_results: int = 0
    total_time_ms: float = 0.0
    by_type: dict[str, int] = field(default_factory=dict)
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def avg_time_ms(self) -> float:
        """Tempo médio de busca em ms."""
        if self.total_searches == 0:
            return 0.0
        return self.total_time_ms / self.total_searches

    @property
    def avg_results(self) -> float:
        """Número médio de resultados por busca bem-sucedida."""
        if self.successful == 0:
            return 0.0
        return self.total_results / self.successful

    def reset(self) -> None:
        """Reseta todas as métricas."""
        self.total_searches = 0
        self.successful = 0
        self.failed = 0
        self.empty_results = 0
        self.total_results = 0
        self.total_time_ms = 0.0
        self.by_type.clear()
        self.cache_hits = 0
        self.cache_misses = 0


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------


def _normalize_query(text: str) -> str:
    """Normaliza query: lowercase, sem diacritics, whitespace único.

    Alinhado com o tokenizer FTS5 ``unicode61 remove_diacritics 2``.
    """
    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


def _parse_book_id_from_id(verse_id: str) -> int:
    """Extrai book_id dos primeiros 2 dígitos do ID BBCCCVVV."""
    return int(verse_id[:2])


def _build_reference(book: str, chapter: int, verse: int | None) -> str:
    """Constrói referência legível: 'João 3:16' ou 'João 3'."""
    if verse is not None:
        return f"{book} {chapter}:{verse}"
    return f"{book} {chapter}"


def _bm25_to_confidence(bm25_score: float) -> float:
    """Converte score BM25 (negativo) para confidence [0.0, 1.0].

    BM25 retorna valores negativos onde mais negativo = melhor match.
    Convertemos para positivo e aplicamos sigmoid.

    Mapeamento aproximado:
    - bm25 = -0.5 → confidence ~0.88
    - bm25 = -1.0 → confidence ~0.73
    - bm25 = -2.0 → confidence ~0.27
    - bm25 = -5.0 → confidence ~0.002
    """
    import math

    # BM25 é negativo; invertemos o sinal para que melhor match = maior valor
    positive = -bm25_score
    # Sigmoid com escala: confidence = 1 / (1 + exp(-positive / scale))
    confidence = 1.0 / (1.0 + math.exp(-positive / _BM25_SCALE))
    return max(0.0, min(1.0, confidence))


def _rrf_fuse(
    fts5_ranking: list[str],
    fuzzy_ranking: list[str],
    k: int,
) -> dict[str, float]:
    """Funde dois rankings via Reciprocal Rank Fusion (RRF).

    RRF: score(id) = Σ 1/(k + rank_i) sobre todos os rankings.

    Args:
        fts5_ranking: lista de IDs ordenados por relevância FTS5.
        fuzzy_ranking: lista de IDs ordenados por similaridade fuzzy.
        k: constante RRF (típico: 60).

    Returns:
        Dicionário {id: score_rff}.
    """
    scores: dict[str, float] = {}

    for rank, verse_id in enumerate(fts5_ranking):
        scores[verse_id] = scores.get(verse_id, 0.0) + 1.0 / (k + rank + 1)

    for rank, verse_id in enumerate(fuzzy_ranking):
        scores[verse_id] = scores.get(verse_id, 0.0) + 1.0 / (k + rank + 1)

    return scores


def _normalize_rrf_scores(scores: dict[str, float]) -> dict[str, float]:
    """Normaliza scores RRF para [0.0, 1.0]."""
    if not scores:
        return {}
    max_score = max(scores.values())
    if max_score == 0:
        return {vid: 0.0 for vid in scores}
    return {vid: s / max_score for vid, s in scores.items()}


# ---------------------------------------------------------------------------
# Searcher
# ---------------------------------------------------------------------------


class Searcher:
    """Mecanismo de busca de versículos bíblicos.

    Abre a base SQLite FTS5 em read-only e executa buscas textuais,
    por referência, por capítulo e contextuais.

    Args:
        config: SearchConfig com caminhos e parâmetros.
        book_table: BookTable para resolução de nomes de livros.
        version: versão bíblica padrão (default: do config ou "ACF").

    Example:
        >>> searcher = Searcher(config, book_table)
        >>> results = searcher.search("deus amou o mundo")
        >>> print(results[0].reference)
        "João 3:16"
    """

    def __init__(
        self,
        config: SearchConfig,
        book_table: BookTable,
        version: str | None = None,
        embedding_searcher: EmbeddingSearcher | None = None,
    ) -> None:
        self._config = config
        self._book_table = book_table
        self._default_version = version or "ACF"
        self._metrics = SearchMetrics()
        # Sprint 18.0.1 — Conexão NÃO é mais mantida aberta.
        # Cada operação abre/fecha sua própria conexão (thread-safe).
        self._db_path = config.fts5_db
        self._embedding_searcher = embedding_searcher
        self._validated = False

        # Cache simples de buscas recentes (query → resultados).
        self._cache: dict[str, list[SearchResult]] = {}
        self._cache_max = 50

        # Sprint 18.0.1 — Validar que o banco existe e tem a tabela
        # 'verses' na inicialização (fail-fast), mas SEM manter a
        # conexão aberta. A validação usa uma conexão temporária.
        self._validate_db()

        logger.info(
            "Searcher initialized: db=%s version=%s rrf_k=%d top_k=%d "
            "search_gap=%.2f embeddings=%s",
            self._db_path,
            self._default_version,
            config.rrf_k,
            config.top_k,
            config.search_gap,
            "enabled" if embedding_searcher else "disabled",
        )

    # ------------------------------------------------------------------
    # Sprint 18.0.1 — Thread-safe database access.
    # ------------------------------------------------------------------

    @contextmanager
    def _db_connection(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão SQLite read-only para esta operação.

        Sprint 18.0.1 — A conexão é criada e fechada dentro do
        context manager, garantindo que cada chamada use sua própria
        conexão na thread que a executou. Isto elimina o erro
        "SQLite objects created in a thread can only be used in that
        same thread" sem recorrer a check_same_thread=False.

        Uso:
            with self._db_connection() as db:
                cursor = db.execute("SELECT ...")
                rows = cursor.fetchall()
        """
        if not os.path.isfile(self._db_path):
            raise SearchError(
                f"FTS5 database not found: {self._db_path}. "
                "Run build_index.py to create it."
            )
        uri = f"file:{self._db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _validate_db(self) -> None:
        """Valida que o banco existe e tem a tabela 'verses'.

        Sprint 18.0.1 — Substitui o antigo _open_db() que mantinha
        a conexão aberta. Usa uma conexão temporária apenas para
        validação fail-fast na inicialização.
        """
        if not os.path.isfile(self._db_path):
            raise SearchError(
                f"FTS5 database not found: {self._db_path}. "
                "Run build_index.py to create it."
            )
        try:
            with self._db_connection() as db:
                cursor = db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='verses'"
                )
                if cursor.fetchone() is None:
                    raise SearchError(
                        f"FTS5 table 'verses' not found in {self._db_path}. "
                        "Run build_index.py to create it."
                    )
        except SearchError:
            raise
        except sqlite3.Error as e:
            raise SearchError(f"failed to verify FTS5 table: {e}") from e
        self._validated = True

    # ------------------------------------------------------------------
    # Busca principal (auto-detecção)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        version: str | None = None,
        state: object | None = None,
    ) -> list[SearchResult]:
        """Busca versículos por query textual ou referência.

        Auto-detecta o tipo de busca:
        1. Referência ("João 3:16") → busca por referência exata.
        2. Capítulo ("João 3") → busca por capítulo.
        3. Contextual ("próximo") → usa BibleState se fornecido.
        4. Textual ("deus amou o mundo") → FTS5 + fuzzy + RRF.

        Args:
            query: texto de busca.
            top_k: número máximo de resultados (default: config.top_k).
            version: versão bíblica (default: versão padrão).
            state: BibleState para busca contextual (opcional).

        Returns:
            Lista de SearchResult ordenada por score.
        """
        if not query or not query.strip():
            return []

        if not self._validated:
            raise SearchError("database not open")

        top_k = top_k or self._config.top_k
        version = version or self._default_version
        query_stripped = query.strip()

        t0 = time.monotonic()
        self._metrics.total_searches += 1

        try:
            results = self._dispatch_search(query_stripped, top_k, version, state)
        except SearchError:
            self._metrics.failed += 1
            raise
        except Exception as e:
            self._metrics.failed += 1
            raise SearchError(f"search failed: {e}") from e

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._metrics.total_time_ms += elapsed_ms

        if results:
            self._metrics.successful += 1
            self._metrics.total_results += len(results)
        else:
            self._metrics.empty_results += 1

        match_type = results[0].match_type if results else "none"
        self._metrics.by_type[match_type] = self._metrics.by_type.get(match_type, 0) + 1

        logger.info(
            "search: query=%r type=%s results=%d time=%.1fms version=%s",
            query_stripped[:80],
            match_type,
            len(results),
            elapsed_ms,
            version,
        )

        return results

    def search_with_plan(
        self,
        plan: QueryPlan,
        *,
        top_k: int | None = None,
        version: str | None = None,
        state: object | None = None,
    ) -> list[SearchResult]:
        """Busca versículos usando um QueryPlan estruturado com múltiplas estratégias.

        Diferente de search(), que usa uma única query FTS5 (AND implícito),
        este método executa múltiplas estratégias e funde os resultados:

        Estratégia 1 (or): FTS5 com OR — qualquer keyword match.
        Estratégia 2 (keyword_subset): FTS5 com subsets de keywords (AND).
        Estratégia 3 (book_filter): FTS5 restrito aos livros sugeridos.
        Estratégia 4 (fuzzy): rapidfuzz sobre candidatos.

        Todos os candidatos são unidos, duplicatas removidas, e ranking
        composto é aplicado via RankingPolicy.

        Args:
            plan: QueryPlan produzido pelo QueryPlanner.
            top_k: número máximo de resultados (default: config.top_k).
            version: versão bíblica (default: versão padrão).
            state: BibleState para busca contextual (opcional).

        Returns:
            Lista de SearchResult ordenada por score composto.
        """
        if not plan.original_query or not plan.original_query.strip():
            return []

        top_k = top_k or self._config.top_k
        version = version or self._default_version

        t0 = time.monotonic()
        self._metrics.total_searches += 1

        try:
            results = self._search_with_plan(plan, top_k, version, state)
        except SearchError:
            self._metrics.failed += 1
            raise
        except Exception as e:
            self._metrics.failed += 1
            raise SearchError(f"search_with_plan failed: {e}") from e

        elapsed_ms = (time.monotonic() - t0) * 1000
        self._metrics.total_time_ms += elapsed_ms

        if results:
            self._metrics.successful += 1
            self._metrics.total_results += len(results)
        else:
            self._metrics.empty_results += 1

        match_type = results[0].match_type if results else "none"
        self._metrics.by_type[match_type] = self._metrics.by_type.get(match_type, 0) + 1

        logger.info(
            "search_with_plan: query=%r keywords=%d strategies=%s results=%d "
            "time=%.1fms",
            plan.original_query[:80],
            len(plan.keywords),
            plan.search_modes,
            len(results),
            elapsed_ms,
        )

        return results

    def _search_with_plan(
        self,
        plan: QueryPlan,
        top_k: int,
        version: str,
        state: object | None,
    ) -> list[SearchResult]:
        """Executa múltiplas estratégias de busca e funde resultados."""
        # Se a query parece referência, tentar referência primeiro
        ref_result = self._try_reference_search(
            plan.original_query, top_k, version,
        )
        if ref_result is not None:
            return ref_result

        # Se é contextual
        normalized = plan.normalized_query
        if normalized in _CONTEXT_NEXT or normalized in _CONTEXT_PREV:
            if state is not None:
                direction = "next" if normalized in _CONTEXT_NEXT else "prev"
                return self.search_context(state, direction=direction, version=version)

        keywords = list(plan.keywords)
        if not keywords:
            # Sem keywords — fallback para busca textual tradicional
            return self._search_text(plan.original_query, top_k, version)

        # Resolver suggested_book_names para IDs
        suggested_book_ids: tuple[int, ...] = ()
        if plan.filters.get("suggested_book_names"):
            ids = []
            for name in plan.filters["suggested_book_names"]:
                match = self._book_table.resolve(name)
                if match is not None:
                    ids.append(match.book.id)
            suggested_book_ids = tuple(ids)

        # Coletar candidatos de múltiplas estratégias
        all_candidates: dict[str, dict] = {}  # uid → candidate dict
        # Rankings separados por estratégia para RRF fusion
        or_ranking: list[str] = []
        and_ranking: list[str] = []

        limit = top_k * _FTS5_CANDIDATE_MULTIPLIER * _MAX_VERSIONS

        # Combinar keywords + boost_terms (sinônimos) para busca OR
        # Sinônimos são usados como keywords adicionais na busca OR
        # para aumentar o recall de versículos com palavras equivalentes.
        or_keywords = list(keywords)
        for bt in plan.boost_terms:
            if bt not in or_keywords:
                or_keywords.append(bt)

        # Estratégia 2 (executar PRIMEIRO): AND query com keywords
        # AND é mais restritiva mas mais precisa — priorizar no RRF.
        if "keyword_subset" in plan.search_modes:
            if len(keywords) > 4:
                subsets = [keywords[:4], keywords[:3], keywords[1:4]]
            else:
                subsets = [keywords]
            for subset in subsets:
                and_results = self._fts5_search_and(subset, limit)
                for r in and_results:
                    if r["uid"] not in all_candidates:
                        all_candidates[r["uid"]] = r
                        and_ranking.append(r["uid"])

        # Estratégia 1: OR query com todas as keywords + sinônimos
        if "or" in plan.search_modes and len(or_keywords) >= 2:
            or_results = self._fts5_search_or(or_keywords, limit)
            for r in or_results:
                if r["uid"] not in all_candidates:
                    all_candidates[r["uid"]] = r
                or_ranking.append(r["uid"])

        # Estratégia 3: FTS5 restrito a livros sugeridos
        if "book_filter" in plan.search_modes and suggested_book_ids:
            book_results = self._fts5_search_book_filter(
                or_keywords, suggested_book_ids, limit,
            )
            for r in book_results:
                if r["uid"] not in all_candidates:
                    all_candidates[r["uid"]] = r
                # Adicionar ao OR ranking (usa OR query)
                if r["uid"] not in or_ranking:
                    or_ranking.append(r["uid"])

        # Se nenhuma estratégia retornou candidatos, tentar OR com a query original
        if not all_candidates:
            original_tokens = normalized.split()
            if original_tokens:
                or_results = self._fts5_search_or(original_tokens, limit)
                for r in or_results:
                    if r["uid"] not in all_candidates:
                        all_candidates[r["uid"]] = r
                        or_ranking.append(r["uid"])

        # Estratégia 5: Semantic search via embeddings (opcional)
        # Adiciona candidatos que FTS não encontrou mas que são
        # semanticamente similares à query original.
        semantic_ranking: list[str] = []
        semantic_scores: dict[str, float] = {}
        if (
            "semantic" in plan.search_modes
            and self._embedding_searcher is not None
            and self._embedding_searcher.is_available
        ):
            # Semantic top_k: menor que FTS limit para evitar ruído.
            # Apenas os top 50 semânticos mais similares contribuem para RRF.
            sem_top_k = min(50, limit)
            sem_results = self._embedding_searcher.search(
                plan.original_query, top_k=sem_top_k,
            )
            for sr in sem_results:
                semantic_ranking.append(sr.uid)
                semantic_scores[sr.uid] = sr.score
                # Adicionar candidatos que FTS não encontrou
                if sr.uid not in all_candidates:
                    cand = self._fetch_verse_by_uid(sr.uid)
                    if cand is not None:
                        all_candidates[sr.uid] = cand

        if not all_candidates:
            logger.debug(
                "search_with_plan: no candidates for query=%r keywords=%r",
                plan.original_query[:80],
                keywords,
            )
            return []

        # Converter para lista para fuzzy ranking
        candidates_list = list(all_candidates.values())

        # Estratégia 4: Fuzzy ranking sobre candidatos
        fuzzy_ranking = self._fuzzy_rank(normalized, candidates_list)

        # RRF fusion — combinar rankings: AND, OR, fuzzy, semantic
        # AND ranking tem peso maior (mais preciso) apenas quando há 2+ keywords.
        # Com 1 keyword, AND = OR, então o peso extra não ajuda.
        # Semantic ranking tem peso baixo (0.3x) — complementa FTS sem dominar.
        # Peso baixo porque embeddings podem trazer falsos positivos semânticos.
        rrf_scores: dict[str, float] = {}
        k = self._config.rrf_k
        and_weight = 2.0 if len(keywords) >= 2 else 1.0

        # AND ranking (peso maior — mais preciso)
        for rank, uid in enumerate(and_ranking):
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + and_weight / (k + rank + 1)

        # OR ranking (peso 1x — aumenta recall)
        for rank, uid in enumerate(or_ranking):
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)

        # Fuzzy ranking (peso 1x)
        for rank, uid in enumerate(fuzzy_ranking):
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + 1.0 / (k + rank + 1)

        # Semantic ranking (peso 0.3x — complementa FTS, não substitui)
        # Peso baixo para que embeddings não perturbem o ranking do FTS,
        # mas ainda contribuam para aumentar recall e desempatar.
        semantic_weight = 0.3
        for rank, uid in enumerate(semantic_ranking):
            rrf_scores[uid] = rrf_scores.get(uid, 0.0) + semantic_weight / (k + rank + 1)

        normalized_scores = _normalize_rrf_scores(rrf_scores)

        # Aplicar ranking composto
        policy = RankingPolicy()
        preferred_versions = plan.preferred_versions or (version,)

        # Calcular scores compostos
        # Query normalizada para phrase match
        plan_query_normalized = plan.normalized_query
        composite_scores: dict[str, float] = {}
        for uid, base_score in normalized_scores.items():
            cand = all_candidates[uid]
            text_normalized = _normalize_query(cand["text"])

            # Keyword hits
            keyword_hits = sum(
                1 for kw in keywords if kw in text_normalized
            )

            # Boost term hits
            boost_term_hits = sum(
                1 for bt in plan.boost_terms if bt in text_normalized
            )

            # Phrase match: query normalizada aparece como substring no texto
            phrase_match = (
                len(plan_query_normalized) > 5
                and plan_query_normalized in text_normalized
            )

            book_id = _parse_book_id_from_id(cand["id"])

            # Embedding score (opcional — apenas se semantic search ativo)
            emb_score = semantic_scores.get(uid)

            composite = policy.score(
                base_score,
                keyword_hits=keyword_hits,
                total_keywords=len(keywords),
                version=cand["version"],
                preferred_versions=preferred_versions,
                book_id=book_id,
                suggested_book_ids=suggested_book_ids,
                boost_term_hits=boost_term_hits,
                total_boost_terms=len(plan.boost_terms),
                phrase_match=phrase_match,
                embedding_score=emb_score,
            )
            composite_scores[uid] = composite

        # Construir resultados com scores compostos
        results = self._build_results_from_scores(
            composite_scores, all_candidates, top_k, "hybrid",
            preferred_version=version,
        )

        return results

    def _fetch_verse_by_uid(self, uid: str) -> dict | None:
        """Busca um versículo pelo UID (id_versão) no banco FTS5.

        Usado para adicionar candidatos encontrados via semantic search
        que não estão no resultado do FTS.

        Returns:
            Dict com metadados do versículo, ou None se não encontrado.
        """
        try:
            with self._db_connection() as db:
                row = db.execute(
                    "SELECT id, book, chapter, verse, text, version "
                    "FROM verses WHERE id = ? LIMIT 1",
                    (uid,),
                ).fetchone()
        except (sqlite3.OperationalError, SearchError):
            return None
        if row is None:
            return None
        return {
            "id": row[0],
            "book": row[1],
            "chapter": row[2],
            "verse": row[3],
            "text": row[4],
            "version": row[5],
            "uid": row[0],
            "bm25": 0.0,
        }

    def _fts5_search_or(
        self,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        """Busca FTS5 com OR — qualquer keyword match.

        Mais permissivo que AND: retorna versículos que contêm pelo menos
        uma das keywords. BM25 ranking prioriza versículos com mais matches.
        """
        if not keywords:
            return []

        # Construir query OR: "kw1" OR "kw2" OR ...
        quoted = [f'"{kw}"' for kw in keywords if kw]
        if not quoted:
            return []
        fts5_query = " OR ".join(quoted)

        try:
            with self._db_connection() as db:
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version, "
                    "bm25(verses) as bm25_score "
                    "FROM verses WHERE verses MATCH ? "
                    "ORDER BY bm25(verses) LIMIT ?",
                    (fts5_query, limit),
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 OR query failed: %s (query=%r)", e, fts5_query)
            return []
        except SearchError as e:
            logger.warning("FTS5 OR query failed (db): %s", e)
            return []

        return self._rows_to_candidates(rows)

    def _fts5_search_and(
        self,
        keywords: list[str],
        limit: int,
    ) -> list[dict]:
        """Busca FTS5 com AND — todas as keywords devem estar presentes."""
        if not keywords:
            return []

        quoted = [f'"{kw}"' for kw in keywords if kw]
        if not quoted:
            return []
        fts5_query = " ".join(quoted)

        try:
            with self._db_connection() as db:
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version, "
                    "bm25(verses) as bm25_score "
                    "FROM verses WHERE verses MATCH ? "
                    "ORDER BY bm25(verses) LIMIT ?",
                    (fts5_query, limit),
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 AND query failed: %s (query=%r)", e, fts5_query)
            return []
        except SearchError as e:
            logger.warning("FTS5 AND query failed (db): %s", e)
            return []

        return self._rows_to_candidates(rows)

    def _fts5_search_book_filter(
        self,
        keywords: list[str],
        book_ids: tuple[int, ...],
        limit: int,
    ) -> list[dict]:
        """Busca FTS5 com OR restrita a livros específicos."""
        if not keywords or not book_ids:
            return []

        quoted = [f'"{kw}"' for kw in keywords if kw]
        if not quoted:
            return []
        fts5_query = " OR ".join(quoted)

        # Construir filtro de book_ids: id LIKE '01%', '02%', etc.
        # id é BBCCCVVV (8 dígitos)
        book_filters = " OR ".join(
            f"substr(id, 1, 2) = '{bid:02d}'" for bid in book_ids
        )

        try:
            with self._db_connection() as db:
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version, "
                    "bm25(verses) as bm25_score "
                    "FROM verses WHERE verses MATCH ? "
                    f"AND ({book_filters}) "
                    "ORDER BY bm25(verses) LIMIT ?",
                    (fts5_query, limit),
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 book_filter query failed: %s", e)
            return []
        except SearchError as e:
            logger.warning("FTS5 book_filter query failed (db): %s", e)
            return []

        return self._rows_to_candidates(rows)

    @staticmethod
    def _rows_to_candidates(rows) -> list[dict]:
        """Converte rows do SQLite para dicts de candidatos."""
        results = []
        for row in rows:
            verse_id = row[0]
            ver = row[5]
            results.append({
                "id": verse_id,
                "uid": f"{verse_id}_{ver}",
                "book": row[1],
                "chapter": row[2],
                "verse": row[3],
                "text": row[4],
                "version": ver,
                "bm25": row[6],
            })
        return results

    def _build_results_from_scores(
        self,
        scores: dict[str, float],
        candidates: dict[str, dict],
        top_k: int,
        match_type: str,
        preferred_version: str = "ACF",
    ) -> list[SearchResult]:
        """Constrói SearchResult a partir de scores compostos.

        Similar a _build_results mas usa scores já calculados (com ranking
        composto) em vez de scores RRF puros.
        """
        if not scores:
            return []

        # Ordenar por score decrescente
        sorted_uids = sorted(scores, key=lambda u: scores[u], reverse=True)

        # Deduplicar por (book, chapter, verse) — manter melhor versão
        seen_refs: set[tuple] = set()
        deduped_uids: list[str] = []
        for uid in sorted_uids:
            meta = candidates.get(uid)
            if meta is None:
                continue
            ref_key = (meta["book"], meta["chapter"], meta["verse"])
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            deduped_uids.append(uid)
            if len(deduped_uids) >= top_k:
                break

        if not deduped_uids:
            return []

        # Calcular ambiguous (gap entre top1 e top2)
        top_score = scores[deduped_uids[0]]
        second_score = (
            scores[deduped_uids[1]] if len(deduped_uids) > 1 else 0.0
        )
        gap = top_score - second_score
        ambiguous = gap < self._config.search_gap and len(deduped_uids) > 1

        results = []
        for uid in deduped_uids:
            meta = candidates.get(uid)
            if meta is None:
                continue

            score = scores[uid]
            book_id = _parse_book_id_from_id(meta["id"])

            # c_search: combina score composto com BM25 confidence
            bm25_conf = _bm25_to_confidence(meta["bm25"])
            c_search = min(1.0, (score + bm25_conf) / 2.0)

            # FTS5 retorna colunas UNINDEXED como strings; converter para int
            chapter_val = int(meta["chapter"]) if meta["chapter"] is not None else None
            verse_val = int(meta["verse"]) if meta["verse"] is not None else None

            results.append(SearchResult(
                reference=_build_reference(
                    meta["book"], chapter_val, verse_val
                ),
                book=meta["book"],
                book_id=book_id,
                chapter=chapter_val,
                verse=verse_val,
                text=meta["text"],
                version=meta["version"],
                score=score,
                c_search=c_search,
                ambiguous=ambiguous,
                match_type=match_type,
            ))

        return results

    def _dispatch_search(
        self,
        query: str,
        top_k: int,
        version: str,
        state: object | None,
    ) -> list[SearchResult]:
        """Despacha para o tipo de busca apropriado."""
        normalized = _normalize_query(query)

        # 1. Busca contextual ("próximo", "anterior")
        if normalized in _CONTEXT_NEXT or normalized in _CONTEXT_PREV:
            if state is not None:
                direction = "next" if normalized in _CONTEXT_NEXT else "prev"
                return self.search_context(state, direction=direction, version=version)
            # Sem state → tratar como busca textual (pode encontrar versículos
            # com a palavra "próximo")
            return self._search_text(query, top_k, version)

        # 2. Busca por referência (book chapter:verse) ou capítulo (book chapter)
        ref_result = self._try_reference_search(query, top_k, version)
        if ref_result is not None:
            return ref_result

        # 3. Busca textual (FTS5 + fuzzy + RRF)
        return self._search_text(query, top_k, version)

    # ------------------------------------------------------------------
    # Busca textual (FTS5 + fuzzy + RRF)
    # ------------------------------------------------------------------

    def _search_text(
        self,
        query: str,
        top_k: int,
        version: str,
    ) -> list[SearchResult]:
        """Busca textual via FTS5 + rapidfuzz com RRF fusion (multiversão).

        Pipeline:
        1. Normalizar query.
        2. Consultar cache.
        3. FTS5: SELECT ... MATCH ? ORDER BY bm25(verses) LIMIT top_k * multiplier * max_versions.
        4. rapidfuzz: fuzzy match query vs texto de cada candidato FTS5.
        5. RRF: fundir rankings FTS5 e fuzzy (usando UIDs únicos por versão).
        6. Normalizar scores.
        7. _build_results: aplicar bônus de versão, deduplicar, calcular
           c_search e ambiguous.
        8. Atualizar cache.
        """
        normalized = _normalize_query(query)
        if not normalized:
            return []

        cache_key = f"text:{normalized}:{version}:{top_k}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # FTS5 search — buscar em todas as versões (sem filtro de versão).
        # Limit expandido para compensar múltiplas versões do mesmo versículo.
        fts5_results = self._fts5_search(
            normalized, version,
            top_k * _FTS5_CANDIDATE_MULTIPLIER * _MAX_VERSIONS,
        )

        if not fts5_results:
            # FTS5 não encontrou nada — tentar fuzzy em todos os versículos?
            # Seria muito lento sem embeddings. Retornar vazio.
            logger.debug("FTS5 returned no results for query=%r", normalized)
            self._cache_put(cache_key, [])
            return []

        # rapidfuzz fuzzy matching sobre os candidatos FTS5
        fuzzy_ranking = self._fuzzy_rank(normalized, fts5_results)

        # RRF fusion — usar UIDs (id_versão) para evitar colisões entre versões
        fts5_ranking = [r["uid"] for r in fts5_results]
        rrf_scores = _rrf_fuse(fts5_ranking, fuzzy_ranking, self._config.rrf_k)
        normalized_scores = _normalize_rrf_scores(rrf_scores)

        # Construir resultados — aplicar bônus de versão e deduplicar
        results = self._build_results(
            normalized_scores, fts5_results, top_k, "hybrid",
            preferred_version=version,
        )

        self._cache_put(cache_key, results)
        return results

    def _fts5_search(
        self,
        normalized_query: str,
        version: str,
        limit: int,
    ) -> list[dict]:
        """Executa busca FTS5 com BM25 ranking (multiversão).

        Busca em TODAS as versões (sem filtro ``AND version = ?``).
        A priorização da versão preferida é feita depois, em
        ``_build_results()``, via bônus small.

        Args:
            normalized_query: query normalizada.
            version: versão preferida (usada apenas para bônus posterior).
            limit: número máximo de candidatos (já ajustado para multiversão).

        Returns:
            Lista de dicionários com id, uid, book, chapter, verse, text,
            version, bm25.
        """
        # Escapar query FTS5 (tokens separados por espaço = AND implícito)
        # FTS5 trata tokens não reconhecidos como palavras individuais.
        fts5_query = self._build_fts5_query(normalized_query)

        try:
            with self._db_connection() as db:
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version, "
                    "bm25(verses) as bm25_score "
                    "FROM verses WHERE verses MATCH ? "
                    "ORDER BY bm25(verses) LIMIT ?",
                    (fts5_query, limit),
                )
                rows = cursor.fetchall()
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 query failed: %s (query=%r)", e, fts5_query)
            return []
        except SearchError as e:
            logger.warning("FTS5 query failed (db): %s", e)
            return []

        results = []
        for row in rows:
            verse_id = row[0]
            ver = row[5]
            results.append({
                "id": verse_id,
                "uid": f"{verse_id}_{ver}",
                "book": row[1],
                "chapter": row[2],
                "verse": row[3],
                "text": row[4],
                "version": ver,
                "bm25": row[6],
            })
        return results

    @staticmethod
    def _build_fts5_query(normalized_query: str) -> str:
        """Constrói query FTS5 segura a partir da query normalizada.

        FTS5 trata cada token separado por espaço como uma palavra.
        Tokens especiais (OR, AND, NOT, *) são escapados com aspas duplas.
        """
        tokens = normalized_query.split()
        if not tokens:
            return ""

        # Envolver cada token em aspas duplas para evitar interpretação
        # de operadores FTS5 (OR, AND, NOT, NEAR, *, etc).
        quoted = [f'"{t}"' for t in tokens if t]
        return " ".join(quoted)

    def _fuzzy_rank(
        self,
        normalized_query: str,
        candidates: list[dict],
    ) -> list[str]:
        """Ranqueia candidatos por similaridade fuzzy (rapidfuzz).

        Usa fuzz.partial_ratio que é robusto para queries parciais
        (query menor que o texto do versículo).

        Returns:
            Lista de UIDs ordenados por similaridade decrescente.
        """
        from rapidfuzz import fuzz

        scored: list[tuple[str, float]] = []
        for cand in candidates:
            text_norm = _normalize_query(cand["text"])
            score = fuzz.partial_ratio(normalized_query, text_norm)
            scored.append((cand["uid"], score))

        # Ordenar por score decrescente
        scored.sort(key=lambda x: x[1], reverse=True)
        return [uid for uid, _ in scored]

    # ------------------------------------------------------------------
    # Busca por referência exata
    # ------------------------------------------------------------------

    def search_by_reference(
        self,
        book_name: str,
        chapter: int,
        verse: int | None = None,
        *,
        version: str | None = None,
    ) -> SearchResult | None:
        """Busca versículo por referência exata.

        Args:
            book_name: nome do livro ("João", "1 Coríntios").
            chapter: número do capítulo.
            verse: número do versículo (None para capítulo inteiro).
            version: versão bíblica (default: versão padrão).

        Returns:
            SearchResult ou None se não encontrado.

        Raises:
            SearchError: se o livro não for reconhecido.
        """
        if not self._validated:
            raise SearchError("database not open")

        version = version or self._default_version

        # Resolver nome do livro via BookTable
        match = self._book_table.resolve(book_name)
        if match is None:
            raise SearchError(f"unknown book: {book_name!r}")

        book_id = match.book.id
        book_canonical = match.book.canonical

        with self._db_connection() as db:
            if verse is not None:
                # Buscar versículo exato
                verse_id = f"{book_id:02d}{chapter:03d}{verse:03d}"
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version "
                    "FROM verses WHERE id = ? AND version = ?",
                    (verse_id, version),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                return SearchResult(
                    reference=_build_reference(book_canonical, chapter, verse),
                    book=book_canonical,
                    book_id=book_id,
                    chapter=chapter,
                    verse=verse,
                    text=row[4],
                    version=row[5],
                    score=1.0,
                    c_search=1.0,
                    ambiguous=False,
                    match_type="reference",
                )
            else:
                # Buscar primeiro versículo do capítulo (para referência de capítulo)
                chapter_prefix = f"{book_id:02d}{chapter:03d}"
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version "
                    "FROM verses WHERE id LIKE ? AND version = ? "
                    "ORDER BY verse LIMIT 1",
                    (f"{chapter_prefix}%", version),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                # Sprint 21.3.2 — FTS5 retorna colunas UNINDEXED como strings;
                # converter para int para manter o contrato de tipos de
                # SearchResult (chapter: int, verse: int | None). Sem esta
                # conversão, _format_verse_id() no HolyricsClient falha com
                # "Unknown format code 'd' for object of type 'str'".
                verse_val = int(row[3]) if row[3] is not None else None

                return SearchResult(
                    reference=_build_reference(book_canonical, chapter, verse_val),
                    book=book_canonical,
                    book_id=book_id,
                    chapter=chapter,
                    verse=verse_val,
                    text=row[4],
                    version=row[5],
                    score=1.0,
                    c_search=1.0,
                    ambiguous=False,
                    match_type="reference",
                )

    # ------------------------------------------------------------------
    # Busca por capítulo
    # ------------------------------------------------------------------

    def search_chapter(
        self,
        book_name: str,
        chapter: int,
        *,
        version: str | None = None,
    ) -> list[SearchResult]:
        """Busca todos os versículos de um capítulo.

        Args:
            book_name: nome do livro ("João").
            chapter: número do capítulo.
            version: versão bíblica (default: versão padrão).

        Returns:
            Lista de SearchResult ordenada por versículo.

        Raises:
            SearchError: se o livro não for reconhecido.
        """
        if not self._validated:
            raise SearchError("database not open")

        version = version or self._default_version

        match = self._book_table.resolve(book_name)
        if match is None:
            raise SearchError(f"unknown book: {book_name!r}")

        book_id = match.book.id
        book_canonical = match.book.canonical

        chapter_prefix = f"{book_id:02d}{chapter:03d}"
        with self._db_connection() as db:
            cursor = db.execute(
                "SELECT id, book, chapter, verse, text, version "
                "FROM verses WHERE id LIKE ? AND version = ? "
                "ORDER BY verse",
                (f"{chapter_prefix}%", version),
            )
            rows = cursor.fetchall()

        results = []
        for row in rows:
            # Sprint 21.3.2 — FTS5 retorna colunas UNINDEXED como strings;
            # converter para int (mesma conversão já feita nos caminhos
            # híbridos — linhas 979-981 e 1608-1611).
            verse_val = int(row[3]) if row[3] is not None else None
            results.append(SearchResult(
                reference=_build_reference(book_canonical, chapter, verse_val),
                book=book_canonical,
                book_id=book_id,
                chapter=chapter,
                verse=verse_val,
                text=row[4],
                version=row[5],
                score=1.0,
                c_search=1.0,
                ambiguous=False,
                match_type="chapter",
            ))

        return results

    # ------------------------------------------------------------------
    # Busca contextual
    # ------------------------------------------------------------------

    def search_context(
        self,
        state: object,
        *,
        direction: Literal["next", "prev"] = "next",
        version: str | None = None,
    ) -> list[SearchResult]:
        """Busca versículo contextual baseado no estado atual.

        Para "próximo": retorna o versículo seguinte ao atual.
        Para "anterior": retorna o versículo anterior ao atual.

        Args:
            state: BibleState com book_id, chapter, verse atuais.
            direction: "next" ou "prev".
            version: versão bíblica.

        Returns:
            Lista com 0 ou 1 SearchResult.
        """
        if not self._validated:
            raise SearchError("database not open")

        version = version or self._default_version

        # BibleState tem: book_id, chapter, verse, version
        book_id = getattr(state, "book_id", None)
        chapter = getattr(state, "chapter", None)
        verse = getattr(state, "verse", None)

        if book_id is None or chapter is None:
            logger.debug("search_context: state is empty")
            return []

        try:
            book = self._book_table.by_id(book_id)
            book_canonical = book.canonical
        except KeyError:
            raise SearchError(f"invalid book_id in state: {book_id}")

        with self._db_connection() as db:
            if direction == "next":
                target_verse = (verse or 0) + 1
                target_id = f"{book_id:02d}{chapter:03d}{target_verse:03d}"
                cursor = db.execute(
                    "SELECT id, book, chapter, verse, text, version "
                    "FROM verses WHERE id = ? AND version = ?",
                    (target_id, version),
                )
                row = cursor.fetchone()

                if row is None:
                    # Tentar próximo capítulo, versículo 1
                    next_chapter = chapter + 1
                    cursor = db.execute(
                        "SELECT id, book, chapter, verse, text, version "
                        "FROM verses WHERE id LIKE ? AND version = ? "
                        "ORDER BY verse LIMIT 1",
                        (f"{book_id:02d}{next_chapter:03d}%", version),
                    )
                    row = cursor.fetchone()

            else:  # prev
                target_verse = (verse or 1) - 1
                if target_verse >= 1:
                    target_id = f"{book_id:02d}{chapter:03d}{target_verse:03d}"
                    cursor = db.execute(
                        "SELECT id, book, chapter, verse, text, version "
                        "FROM verses WHERE id = ? AND version = ?",
                        (target_id, version),
                    )
                    row = cursor.fetchone()
                else:
                    row = None
                    # Tentar capítulo anterior, último versículo
                    prev_chapter = chapter - 1
                    if prev_chapter >= 1:
                        cursor = db.execute(
                            "SELECT id, book, chapter, verse, text, version "
                            "FROM verses WHERE id LIKE ? AND version = ? "
                            "ORDER BY verse DESC LIMIT 1",
                            (f"{book_id:02d}{prev_chapter:03d}%", version),
                        )
                        row = cursor.fetchone()

        if row is None:
            return []

        # Sprint 21.3.2 — FTS5 retorna colunas UNINDEXED como strings;
        # converter para int (consistente com os caminhos híbridos).
        chapter_val = int(row[2]) if row[2] is not None else None
        verse_val = int(row[3]) if row[3] is not None else None

        return [SearchResult(
            reference=_build_reference(
                book_canonical, chapter_val, verse_val
            ),
            book=book_canonical,
            book_id=book_id,
            chapter=chapter_val,
            verse=verse_val,
            text=row[4],
            version=row[5],
            score=1.0,
            c_search=1.0,
            ambiguous=False,
            match_type="context",
        )]

    # ------------------------------------------------------------------
    # Detecção de referência
    # ------------------------------------------------------------------

    def _try_reference_search(
        self,
        query: str,
        top_k: int,
        version: str,
    ) -> list[SearchResult] | None:
        """Tenta interpretar query como referência bíblica.

        Padrões reconhecidos:
        - "João 3:16" → referência exata
        - "João 3" → capítulo inteiro
        - "1 Coríntios 13:4" → referência com ordinal

        Returns:
            Lista de SearchResult se reconhecido, None caso contrário.
        """
        match = _REF_PATTERN.match(query.strip())
        if not match:
            return None

        book_part = match.group(1)
        chapter_str = match.group(2)
        verse_str = match.group(3)

        # Verificar se book_part é um livro reconhecido
        book_match = self._book_table.resolve(book_part)
        if book_match is None:
            return None

        chapter = int(chapter_str)
        verse = int(verse_str) if verse_str else None

        try:
            if verse is not None:
                # Referência exata: "João 3:16"
                result = self.search_by_reference(
                    book_part, chapter, verse, version=version
                )
                if result:
                    return [result]
                return []
            else:
                # Capítulo: "João 3"
                results = self.search_chapter(
                    book_part, chapter, version=version
                )
                return results[:top_k] if top_k > 0 else results
        except SearchError as e:
            logger.debug("reference search failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # Construção de resultados
    # ------------------------------------------------------------------

    def _build_results(
        self,
        scores: dict[str, float],
        fts5_results: list[dict],
        top_k: int,
        match_type: str,
        *,
        preferred_version: str = "ACF",
    ) -> list[SearchResult]:
        """Constrói lista de SearchResult a partir de scores RRF (multiversão).

        Aplica bônus de preferência por versão, deduplica por
        (book, chapter, verse) mantendo a melhor versão, e calcula
        c_search e ambiguous.

        Args:
            scores: {uid: score_normalizado} de RRF (UIDs únicos por versão).
            fts5_results: resultados FTS5 com metadados (incluem uid).
            top_k: número máximo de resultados.
            match_type: tipo de match para os resultados.
            preferred_version: versão preferida para bônus (default: "ACF").

        Returns:
            Lista ordenada por score decrescente, limitada a top_k,
            deduplicada por (book, chapter, verse).
        """
        # Mapear uid → metadados
        meta_by_uid = {r["uid"]: r for r in fts5_results}

        # 1. Aplicar bônus de versão aos scores RRF normalizados
        scored: list[tuple[str, float]] = []
        for uid, rrf_score in scores.items():
            meta = meta_by_uid.get(uid)
            if meta is None:
                continue
            bonus = _VERSION_BONUS.get(meta["version"], 0.0)
            scored.append((uid, rrf_score + bonus))

        if not scored:
            return []

        # 2. Re-normalizar scores com bônus para [0.0, 1.0]
        max_score = max(s for _, s in scored)
        if max_score <= 0:
            final_scores = {uid: 0.0 for uid, _ in scored}
        else:
            final_scores = {uid: s / max_score for uid, s in scored}

        # 3. Ordenar por score com bônus (descrescente)
        sorted_uids = sorted(
            final_scores.keys(),
            key=lambda uid: final_scores[uid],
            reverse=True,
        )

        # 4. Deduplicar por (book, chapter, verse) — manter a melhor versão
        seen_refs: set[tuple[str, int, int]] = set()
        deduped_uids: list[str] = []
        for uid in sorted_uids:
            meta = meta_by_uid.get(uid)
            if meta is None:
                continue
            ref_key = (meta["book"], meta["chapter"], meta["verse"])
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            deduped_uids.append(uid)
            if len(deduped_uids) >= top_k:
                break

        if not deduped_uids:
            return []

        # 5. Calcular ambiguous (gap entre top1 e top2)
        top_score = final_scores[deduped_uids[0]]
        second_score = (
            final_scores[deduped_uids[1]] if len(deduped_uids) > 1 else 0.0
        )
        gap = top_score - second_score
        ambiguous = gap < self._config.search_gap and len(deduped_uids) > 1

        # 6. Construir SearchResult
        results = []
        for uid in deduped_uids:
            meta = meta_by_uid.get(uid)
            if meta is None:
                continue

            score = final_scores[uid]
            book_id = _parse_book_id_from_id(meta["id"])

            # c_search: combina score final com BM25 confidence, clamp [0, 1]
            bm25_conf = _bm25_to_confidence(meta["bm25"])
            c_search = min(1.0, (score + bm25_conf) / 2.0)

            # FTS5 retorna colunas UNINDEXED como strings; converter para int
            # para que DecisionEngine.execute() e BibleStateManager funcionem.
            chapter_val = int(meta["chapter"]) if meta["chapter"] is not None else None
            verse_val = int(meta["verse"]) if meta["verse"] is not None else None

            results.append(SearchResult(
                reference=_build_reference(
                    meta["book"], chapter_val, verse_val
                ),
                book=meta["book"],
                book_id=book_id,
                chapter=chapter_val,
                verse=verse_val,
                text=meta["text"],
                version=meta["version"],
                score=score,
                c_search=c_search,
                ambiguous=ambiguous,
                match_type=match_type,
            ))

        return results

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> list[SearchResult] | None:
        """Busca no cache de buscas recentes."""
        if key in self._cache:
            self._metrics.cache_hits += 1
            return self._cache[key]
        self._metrics.cache_misses += 1
        return None

    def _cache_put(self, key: str, results: list[SearchResult]) -> None:
        """Armazena no cache de buscas recentes (LRU simples)."""
        if len(self._cache) >= self._cache_max:
            # Remover entrada mais antiga (primeira chave)
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = results

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def _open_db(self) -> None:
        """Sprint 18.0.1 — Deprecated: não abre conexão persistente.

        Mantido por compatibilidade com código legado que chama
        _open_db() explicitamente. Agora é no-op — a validação
        acontece em __init__ via _validate_db(), e cada operação
        abre sua própria conexão via _db_connection().
        """
        # No-op: conexões são abertas por operação.
        pass

    def close(self) -> None:
        """Sprint 18.0.1 — Fecha recursos persistentes.

        Como não há mais conexão persistente, este método apenas
        marca o Searcher como fechado (is_open=False). Cada operação
        abria/fechava sua própria conexão; nada mais a fazer.
        Mantido por compatibilidade com código que chama close()
        explicitamente (ex: CompositionRoot em shutdown, context
        manager __exit__, testes).
        """
        self._validated = False

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> SearchMetrics:
        """Métricas acumuladas de busca."""
        return self._metrics

    @property
    def is_open(self) -> bool:
        """True se a base FTS5 está disponível e foi validada.

        Sprint 18.0.1 — Antes indicava se havia uma conexão SQLite
        aberta. Agora indica se o Searcher foi inicializado com
        sucesso (banco existe e tabela 'verses' presente). Cada
        operação abre/fecha sua própria conexão.
        """
        return self._validated

    @property
    def db_path(self) -> str:
        """Caminho da base FTS5."""
        return self._db_path

    @property
    def has_embeddings(self) -> bool:
        """True se EmbeddingSearcher está disponível e carregado."""
        return (
            self._embedding_searcher is not None
            and self._embedding_searcher.is_available
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Searcher:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
