"""Sprint 22.0 — BibleRetriever: recuperação de candidatos da Bíblia local.

Componente responsável por recuperar candidatos bíblicos a partir de
texto livre (transcrição parcial), consultando simultaneamente todas
as versões disponíveis em data/sources/.

Arquitetura:
    data/sources/*.sqlite  →  descoberta automática
                              ↓
    Warm-up: carregar todas as versões em um índice FTS5 em memória
             (book_ref_id, chapter, verse, version, text)
                              ↓
    retrieve(text, top_k):
        1. Buscar no FTS5 por texto normalizado
        2. Converter BM25 → score [0,1]
        3. Agregar por (book_ref_id, chapter, verse)
        4. Ranquear por score agregado
        5. Retornar top_k BibleCandidate

Performance:
    O índice FTS5 em memória permite busca em <100ms mesmo com
    ~217k versículos (7 versões × 31102). O warm-up é feito uma
    única vez no startup.

Ranking (aggregated_score):
    Combina três fatores:
    - best_score: maior score entre as versões (peso 0.5)
    - mean_score: média dos scores (peso 0.3)
    - coverage: num_versions / total_versions_discovered (peso 0.2)
    Além disso, um bônus de posição é aplicado: candidatos que
    apareceram primeiro na busca recebem um pequeno boost.
"""
from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from config.books import BookTable
from knowledge.types import BibleCandidate, BibleVersionMatch

logger = logging.getLogger(__name__)

__all__ = [
    "BibleRetriever",
    "BibleRetrieverStats",
    "BibleRetrieverError",
    "discover_versions",
    "warmup_bible_retriever",
]


# ---------------------------------------------------------------------------
# Exceção
# ---------------------------------------------------------------------------


class BibleRetrieverError(Exception):
    """Erro do BibleRetriever (inicialização, busca, etc.)."""


# ---------------------------------------------------------------------------
# Estatísticas de warm-up
# ---------------------------------------------------------------------------


@dataclass
class BibleRetrieverStats:
    """Estatísticas coletadas durante o warm-up do BibleRetriever.

    Atributos:
        versions_discovered: lista de códigos de versão encontrados.
        total_versions: quantidade de versões carregadas.
        total_verses: quantidade total de versículos indexados
            (soma de todas as versões).
        unique_verses: quantidade de versículos únicos
            (agregados por book_ref_id + chapter + verse).
        init_time_ms: tempo de inicialização em milissegundos.
        sources_dir: diretório onde as bases foram encontradas.
    """

    versions_discovered: list[str] = field(default_factory=list)
    total_versions: int = 0
    total_verses: int = 0
    unique_verses: int = 0
    init_time_ms: float = 0.0
    sources_dir: str = ""


# ---------------------------------------------------------------------------
# Normalização (alinhada com o Searcher)
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Normaliza texto: lowercase, sem diacritics, whitespace único.

    Alinhada com o tokenizer FTS5 ``unicode61 remove_diacritics 2``.
    """
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


# ---------------------------------------------------------------------------
# Conversão BM25 → score [0,1]
# ---------------------------------------------------------------------------


_BM25_SCALE = 1.5  # Mesmo scale do Searcher para consistência.


def _bm25_to_score(bm25_score: float) -> float:
    """Converte score BM25 (negativo) para [0.0, 1.0].

    BM25 retorna valores negativos onde mais negativo = melhor match.
    Aplicamos sigmoid para normalizar.
    """
    positive = -bm25_score
    if positive <= 0:
        return 0.0
    confidence = 1.0 / (1.0 + math.exp(-positive / _BM25_SCALE))
    return max(0.0, min(1.0, confidence))


# ---------------------------------------------------------------------------
# Descoberta automática de versões
# ---------------------------------------------------------------------------


def discover_versions(sources_dir: str = "data/sources") -> list[Path]:
    """Descobre automaticamente todas as bases SQLite em sources_dir.

    Retorna lista de caminhos absolutos para arquivos .sqlite,
    ordenados alfabeticamente. Levanta BibleRetrieverError se o
    diretório não existir ou não contiver nenhuma base.
    """
    if not os.path.isdir(sources_dir):
        raise BibleRetrieverError(
            f"sources directory not found: {sources_dir}"
        )
    files = []
    for f in sorted(os.listdir(sources_dir)):
        if f.lower().endswith(".sqlite"):
            files.append(Path(sources_dir) / f)
    if not files:
        raise BibleRetrieverError(
            f"no .sqlite files found in {sources_dir}"
        )
    return files


def _version_code_from_path(path: Path) -> str:
    """Extrai o código da versão do nome do arquivo (ex.: ACF.sqlite → ACF)."""
    return path.stem.upper()


# ---------------------------------------------------------------------------
# BibleRetriever
# ---------------------------------------------------------------------------


# Schema do FTS5 em memória. text é a coluna indexada; as demais são
# UNINDEXED para armazenar metadados sem custar tokenização.
_FTS5_SCHEMA = """
CREATE VIRTUAL TABLE verses USING fts5(
    text,
    book_ref_id UNINDEXED,
    chapter UNINDEXED,
    verse UNINDEXED,
    version UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
)
"""


class BibleRetriever:
    """Recupera candidatos bíblicos da base local (RAG Local).

    No warm-up, carrega todas as versões de data/sources/*.sqlite em
    um índice FTS5 em memória. No retrieve, busca por texto normalizado,
    agrega por versículo e ranqueia.

    Args:
        sources_dir: diretório com as bases .sqlite (default: data/sources).
        book_table: BookTable para resolver book_ref_id → nome canônico.
        top_k_default: número padrão de candidatos a retornar (default: 20).

    Lifecycle:
        warmup() — carrega bases, cria índice FTS5, valida integridade.
        retrieve(text, top_k) — busca e retorna candidatos.
        close() — fecha índice em memória (libera RAM).

    Thread-safety:
        O índice FTS5 em memória é acessado via conexões por-thread
        (check_same_thread=False com lock). Cada retrieve abre sua
        própria conexão ao índice in-memory compartilhado.
    """

    def __init__(
        self,
        sources_dir: str = "data/sources",
        book_table: BookTable | None = None,
        top_k_default: int = 20,
    ) -> None:
        self._sources_dir = sources_dir
        self._book_table = book_table
        self._top_k_default = top_k_default

        # Índice FTS5 em memória (criado no warmup).
        self._mem_conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._warmed_up = False
        self._stats = BibleRetrieverStats(sources_dir=sources_dir)

        # Mapa book_ref_id → nome canônico, populado no warmup.
        self._book_names: dict[int, str] = {}

        # Métricas de retrieve.
        self._total_retrieves = 0
        self._total_candidates_returned = 0
        self._total_retrieve_ms = 0.0

    # ------------------------------------------------------------------
    # Propriedades
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True se o warm-up foi concluído com sucesso."""
        return self._warmed_up and self._mem_conn is not None

    @property
    def stats(self) -> BibleRetrieverStats:
        """Estatísticas do warm-up."""
        return self._stats

    @property
    def versions(self) -> list[str]:
        """Lista de códigos de versão carregados."""
        return list(self._stats.versions_discovered)

    # ------------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------------

    def warmup(self) -> BibleRetrieverStats:
        """Carrega todas as versões e cria o índice FTS5 em memória.

        Passos:
        1. Descobrir bases .sqlite em sources_dir.
        2. Para cada base: validar schema, ler versões, carregar versículos.
        3. Criar índice FTS5 em memória com todos os versículos.
        4. Construir mapa book_ref_id → nome canônico.
        5. Registrar estatísticas (versões, versículos, tempo).

        Returns:
            BibleRetrieverStats com as estatísticas do warm-up.

        Raises:
            BibleRetrieverError se nenhuma base for encontrada ou se
            houver erro de schema/IO.
        """
        t0 = time.monotonic()
        # 1. Descobrir bases.
        sqlite_files = discover_versions(self._sources_dir)
        logger.info(
            "BibleRetriever: discovered %d SQLite bases in %s",
            len(sqlite_files), self._sources_dir,
        )

        # 2. Criar índice FTS5 em memória.
        # Usar shared in-memory db (:memory: não é compartilhável entre
        # threads; usamos file:...?mode=memory&cache=shared para permitir
        # múltiplas conexões na mesma thread-safe DB).
        # Na prática, vamos usar uma única conexão com lock, pois o
        # retrieve é rápido (<100ms) e o lock não é gargalo.
        self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._mem_conn.execute(_FTS5_SCHEMA)
        self._mem_conn.commit()

        total_verses = 0
        unique_keys: set[tuple[int, int, int]] = set()
        versions_loaded: list[str] = []

        for sqlite_path in sqlite_files:
            version_code = _version_code_from_path(sqlite_path)
            try:
                verses_loaded = self._load_version(
                    sqlite_path, version_code, unique_keys
                )
                total_verses += verses_loaded
                versions_loaded.append(version_code)
                logger.info(
                    "BibleRetriever: loaded %s — %d verses",
                    version_code, verses_loaded,
                )
            except Exception as e:
                logger.warning(
                    "BibleRetriever: failed to load %s: %s — skipping",
                    version_code, e,
                )

        if not versions_loaded:
            raise BibleRetrieverError(
                f"no Bible versions could be loaded from {self._sources_dir}"
            )

        # 3. Construir mapa book_ref_id → nome canônico.
        self._build_book_names()

        # 4. Commit final e estatísticas.
        self._mem_conn.commit()
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        self._stats = BibleRetrieverStats(
            versions_discovered=versions_loaded,
            total_versions=len(versions_loaded),
            total_verses=total_verses,
            unique_verses=len(unique_keys),
            init_time_ms=round(elapsed_ms, 2),
            sources_dir=self._sources_dir,
        )
        self._warmed_up = True

        logger.info(
            "BibleRetriever: warmup complete — versions=%d, total_verses=%d, "
            "unique_verses=%d, init_time=%.1fms",
            self._stats.total_versions, self._stats.total_verses,
            self._stats.unique_verses, self._stats.init_time_ms,
        )

        # Sprint 22.0 — Telemetria do warm-up.
        try:
            from telemetry import hooks as telemetry_hooks
            telemetry_hooks.bible_retriever_warmup(
                versions_discovered=self._stats.versions_discovered,
                total_versions=self._stats.total_versions,
                total_verses=self._stats.total_verses,
                unique_verses=self._stats.unique_verses,
                init_time_ms=self._stats.init_time_ms,
                sources_dir=self._stats.sources_dir,
            )
        except Exception:
            pass  # Telemetria nunca deve quebrar o pipeline.

        return self._stats

    def _load_version(
        self,
        sqlite_path: Path,
        version_code: str,
        unique_keys: set[tuple[int, int, int]],
    ) -> int:
        """Carrega uma versão da base SQLite para o índice FTS5 em memória.

        Returns: quantidade de versículos carregados.
        """
        uri = f"file:{sqlite_path.as_posix()}?mode=ro"
        src_conn = sqlite3.connect(uri, uri=True)
        src_conn.row_factory = sqlite3.Row
        count = 0
        try:
            # Validar schema mínimo.
            cur = src_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('book', 'verse')"
            )
            tables = {r[0] for r in cur.fetchall()}
            if "book" not in tables or "verse" not in tables:
                raise BibleRetrieverError(
                    f"{sqlite_path.name}: missing 'book' or 'verse' table"
                )

            # Ler todos os versículos com book_reference_id via JOIN.
            rows = src_conn.execute(
                """
                SELECT b.book_reference_id AS book_ref_id,
                       v.chapter AS chapter,
                       v.verse AS verse,
                       v.text AS text
                FROM verse v
                JOIN book b ON v.book_id = b.id
                WHERE v.text IS NOT NULL AND v.text != ''
                """
            ).fetchall()

            # Inserir em lotes no FTS5 em memória.
            batch: list[tuple[str, int, int, int, str]] = []
            BATCH_SIZE = 5000
            for row in rows:
                book_ref_id = int(row["book_ref_id"])
                chapter = int(row["chapter"])
                verse = int(row["verse"])
                text = str(row["text"])
                batch.append((
                    text, book_ref_id, chapter, verse, version_code,
                ))
                unique_keys.add((book_ref_id, chapter, verse))
                if len(batch) >= BATCH_SIZE:
                    self._insert_batch(batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                self._insert_batch(batch)
                count += len(batch)
        finally:
            src_conn.close()
        return count

    def _insert_batch(
        self, batch: list[tuple[str, int, int, int, str]]
    ) -> None:
        """Insere um lote de versículos no FTS5 em memória."""
        assert self._mem_conn is not None
        self._mem_conn.executemany(
            "INSERT INTO verses (text, book_ref_id, chapter, verse, version) "
            "VALUES (?, ?, ?, ?, ?)",
            batch,
        )

    def _build_book_names(self) -> None:
        """Constrói mapa book_ref_id → nome canônico a partir do BookTable.

        Se BookTable não estiver disponível, lê os nomes da primeira
        base SQLite (menos confiável por encoding, mas funcional).
        """
        self._book_names.clear()
        if self._book_table is not None:
            # BookTable tem _by_id: dict[int, Book].
            for book_id, book in self._book_table._by_id.items():
                self._book_names[book_id] = book.canonical
            return
        # Fallback: ler da primeira base SQLite.
        sqlite_files = discover_versions(self._sources_dir)
        if not sqlite_files:
            return
        uri = f"file:{sqlite_files[0].as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            rows = conn.execute(
                "SELECT book_reference_id, name FROM book ORDER BY book_reference_id"
            ).fetchall()
            for row in rows:
                ref_id = int(row[0])
                name = str(row[1])
                if ref_id not in self._book_names:
                    self._book_names[ref_id] = name
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Retrieve
    # ------------------------------------------------------------------

    def retrieve(
        self, text: str, top_k: int | None = None
    ) -> list[BibleCandidate]:
        """Recupera candidatos bíblicos para o texto dado.

        Args:
            text: texto da transcrição (parcial ou completa).
            top_k: número máximo de candidatos (default: top_k_default).

        Returns:
            Lista de BibleCandidate ordenada por aggregated_score (desc).
            Vazia se nenhuma versículo corresponder.

        Raises:
            BibleRetrieverError se o retriever não estiver aquecido.
        """
        if not self._warmed_up or self._mem_conn is None:
            raise BibleRetrieverError(
                "BibleRetriever not warmed up — call warmup() first"
            )
        if not text or not text.strip():
            return []
        k = top_k if top_k is not None and top_k > 0 else self._top_k_default

        t0 = time.monotonic()
        self._total_retrieves += 1

        # 1. Normalizar query.
        query = _normalize_text(text)
        if not query:
            return []

        # 2. Buscar no FTS5 com ranking BM25.
        # Buscar mais candidatos que top_k para permitir agregação
        # (várias versões do mesmo versículo colapsam em um candidato).
        search_limit = k * 4
        raw_results, strategy = self._fts_search(query, limit=search_limit)

        if not raw_results:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            self._total_retrieve_ms += elapsed_ms
            self._emit_telemetry(
                text, k, [], elapsed_ms, strategy,
                correlation_id=None,
            )
            return []

        # 3. Agregar por (book_ref_id, chapter, verse).
        candidates = self._aggregate(raw_results, total_versions=self._stats.total_versions)

        # 4. Ordenar por aggregated_score (desc) e limitar a top_k.
        candidates.sort(key=lambda c: c.aggregated_score, reverse=True)
        result = candidates[:k]

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        self._total_retrieve_ms += elapsed_ms
        self._total_candidates_returned += len(result)

        logger.debug(
            "BibleRetriever: retrieve(%d chars) → %d candidates in %.1fms",
            len(text), len(result), elapsed_ms,
        )

        self._emit_telemetry(
            text, k, result, elapsed_ms, strategy,
            correlation_id=None,
        )
        return result

    def _emit_telemetry(
        self,
        text: str,
        top_k: int,
        candidates: list[BibleCandidate],
        retrieve_ms: float,
        strategy: str,
        *,
        correlation_id: str | None = None,
    ) -> None:
        """Emite evento de telemetria da consulta (no-op se desabilitada)."""
        try:
            from telemetry import hooks as telemetry_hooks
            telemetry_hooks.bible_retriever_query(
                correlation_id=correlation_id,
                query=text,
                versions_searched=self._stats.versions_discovered,
                top_k_requested=top_k,
                candidates_found=len(candidates),
                candidates=[c.to_dict() for c in candidates],
                retrieve_ms=retrieve_ms,
                strategy=strategy,
            )
        except Exception:
            pass  # Telemetria nunca deve quebrar o pipeline.

    def _fts_search(
        self, query: str, limit: int
    ) -> tuple[list[dict[str, Any]], str]:
        """Busca no FTS5 por texto normalizado.

        Estratégia híbrida para performance:
        1. AND de todos os termos (rápido, ~15ms, preciso para citações).
        2. Se AND retornar poucos resultados (< limit/4), fallback para
           OR dos termos mais longos (mais distintivos) para matching amplo.

        Returns:
            Tuplo (resultados, estratégia_usada).
            estratégia_usada: "and", "or_fallback", ou "and_empty".
        """
        assert self._mem_conn is not None
        terms = query.split()
        if not terms:
            return [], "and_empty"

        # Estratégia 1: AND de todos os termos (padrão FTS5).
        fts_and = " ".join(f'"{t}"' for t in terms if t)
        if not fts_and:
            return [], "and_empty"

        with self._lock:
            cur = self._mem_conn.execute(
                """
                SELECT book_ref_id, chapter, verse, version, text,
                       bm25(verses) AS bm25_score,
                       rank
                FROM verses
                WHERE verses MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_and, limit),
            )
            rows = cur.fetchall()

        # Se AND retornou resultados suficientes, usar.
        if len(rows) >= max(limit // 4, 5):
            return self._rows_to_dicts(rows), "and"

        # Estratégia 2 (fallback): OR dos termos mais longos (distintivos).
        # Termos longos (>4 chars) são mais distintivos e evitam ruído.
        distinctive = [t for t in terms if len(t) > 4]
        if not distinctive:
            distinctive = terms  # fallback: usar todos
        fts_or = " OR ".join(f'"{t}"' for t in distinctive if t)
        if not fts_or:
            return self._rows_to_dicts(rows), "and"

        with self._lock:
            cur = self._mem_conn.execute(
                """
                SELECT book_ref_id, chapter, verse, version, text,
                       bm25(verses) AS bm25_score,
                       rank
                FROM verses
                WHERE verses MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_or, limit),
            )
            or_rows = cur.fetchall()

        # Combinar resultados (deduplicar por row_id implícito).
        # Manter ordem por rank; rows já estão ordenados.
        seen_ids: set[tuple[int, int, int, str]] = set()
        combined: list = []
        for row in list(rows) + list(or_rows):
            key = (int(row[0]), int(row[1]), int(row[2]), str(row[3]))
            if key not in seen_ids:
                seen_ids.add(key)
                combined.append(row)
        return self._rows_to_dicts(combined[:limit]), "or_fallback"

    @staticmethod
    def _rows_to_dicts(rows: list) -> list[dict[str, Any]]:
        """Converte rows do SQLite em lista de dicts."""
        results = []
        for row in rows:
            results.append({
                "book_ref_id": int(row[0]),
                "chapter": int(row[1]),
                "verse": int(row[2]),
                "version": str(row[3]),
                "text": str(row[4]),
                "bm25_score": float(row[5]),
                "rank": int(row[6]),
            })
        return results

    def _aggregate(
        self,
        raw_results: list[dict[str, Any]],
        total_versions: int,
    ) -> list[BibleCandidate]:
        """Agrega resultados brutos por (book_ref_id, chapter, verse).

        Para cada versículo único, coleta todas as versões que
        corresponderam, calcula best_score, mean_score, num_versions,
        e aggregated_score.

        Estratégia de aggregated_score:
            aggregated = 0.5 * best_score
                       + 0.3 * mean_score
                       + 0.2 * coverage
            Onde coverage = num_versions / total_versions.
            Um bônus de posição é aplicado: candidatos com melhor
            rank médio recebem +0.05 * (1 - normalized_rank).
        """
        # Agrupar por (book_ref_id, chapter, verse).
        groups: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for r in raw_results:
            key = (r["book_ref_id"], r["chapter"], r["verse"])
            groups.setdefault(key, []).append(r)

        candidates: list[BibleCandidate] = []
        max_rank = max((r["rank"] for r in raw_results), default=1) or 1

        for (book_ref_id, chapter, verse), matches in groups.items():
            version_matches: list[BibleVersionMatch] = []
            scores: list[float] = []
            ranks: list[int] = []
            for m in matches:
                score = _bm25_to_score(m["bm25_score"])
                version_matches.append(BibleVersionMatch(
                    version=m["version"],
                    text=m["text"],
                    score=score,
                ))
                scores.append(score)
                ranks.append(m["rank"])

            best_score = max(scores)
            mean_score = sum(scores) / len(scores)
            num_versions = len(matches)
            coverage = num_versions / total_versions if total_versions > 0 else 0.0
            avg_rank = sum(ranks) / len(ranks)
            normalized_rank = avg_rank / max_rank if max_rank > 0 else 0.0
            position_bonus = 0.05 * (1.0 - normalized_rank)

            aggregated = (
                0.5 * best_score
                + 0.3 * mean_score
                + 0.2 * coverage
                + position_bonus
            )
            aggregated = max(0.0, min(1.0, aggregated))

            book_name = self._book_names.get(book_ref_id, f"Book{book_ref_id}")
            canonical_ref = f"{book_name} {chapter}:{verse}"

            # search_rank = melhor rank entre as versões.
            search_rank = min(ranks)

            candidates.append(BibleCandidate(
                book=book_name,
                book_reference_id=book_ref_id,
                chapter=chapter,
                verse=verse,
                canonical_reference=canonical_ref,
                aggregated_score=aggregated,
                versions=tuple(version_matches),
                best_score=best_score,
                mean_score=mean_score,
                num_versions=num_versions,
                search_rank=search_rank,
            ))

        return candidates

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Fecha o índice em memória e libera recursos."""
        with self._lock:
            if self._mem_conn is not None:
                self._mem_conn.close()
                self._mem_conn = None
            self._warmed_up = False
        logger.info(
            "BibleRetriever: closed (retrieves=%d, candidates=%d, avg_time=%.1fms)",
            self._total_retrieves,
            self._total_candidates_returned,
            self._total_retrieve_ms / max(1, self._total_retrieves),
        )


# ---------------------------------------------------------------------------
# Warm-up standalone (para uso no composition root)
# ---------------------------------------------------------------------------


def warmup_bible_retriever(
    sources_dir: str = "data/sources",
    book_table: BookTable | None = None,
    top_k_default: int = 20,
) -> tuple[BibleRetriever, BibleRetrieverStats]:
    """Cria e aquece um BibleRetriever, retornando (retriever, stats).

    Função de conveniência para o composition root.
    """
    retriever = BibleRetriever(
        sources_dir=sources_dir,
        book_table=book_table,
        top_k_default=top_k_default,
    )
    stats = retriever.warmup()
    return retriever, stats
