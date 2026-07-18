"""Indexador FTS5 para versículos da Bíblia.

Cria e popula uma tabela SQLite FTS5 com tokenizer ``unicode61`` e remoção de
diacritics, suportando múltiplas versões bíblicas.

Schema FTS5 (doc. técnica §5.5):
    CREATE VIRTUAL TABLE verses USING fts5(
        book,
        chapter UNINDEXED,
        verse UNINDEXED,
        text,
        version UNINDEXED,
        id UNINDEXED,            -- BBCCCVVV
        tokenize = 'unicode61 remove_diacritics 2'
    );

Formato ``bible_source.json`` (Blueprint §2):
    [
      {"book":"João","book_id":43,"chapter":3,"verse":16,
       "text":"Porque Deus amou o mundo...",
       "version":"ACF"}
    ]
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Iterator

from busca.exceptions import IndexerError
from busca.models import IndexStats, VerseRow

logger = logging.getLogger(__name__)

# Schema FTS5 conforme doc. técnica §5.5.
_FTS5_SCHEMA = (
    "CREATE VIRTUAL TABLE verses USING fts5("
    "book, "
    "chapter UNINDEXED, "
    "verse UNINDEXED, "
    "text, "
    "version UNINDEXED, "
    "id UNINDEXED, "
    "tokenize = 'unicode61 remove_diacritics 2'"
    ")"
)

# Tamanho do lote para inserts batched.
_BATCH_SIZE = 1000

# Range válido de book_id (66 livros canônicos).
_MIN_BOOK_ID = 1
_MAX_BOOK_ID = 66


def _validate_verse_entry(entry: dict[str, Any], index: int) -> VerseRow | None:
    """Valida uma entrada do JSON e retorna ``VerseRow`` ou ``None`` se inválida.

    Regras (Blueprint §2 tratamento de erros):
      - book_id fora de 1..66 → pula + warning.
      - texto vazio → pula + warning.
      - campos obrigatórios ausentes → pula + warning.
    """
    required = ("book", "book_id", "chapter", "verse", "text", "version")
    for field in required:
        if field not in entry:
            logger.warning("bible_source[%d]: missing field '%s' — skipping", index, field)
            return None

    book_id = entry["book_id"]
    if not isinstance(book_id, int) or not (_MIN_BOOK_ID <= book_id <= _MAX_BOOK_ID):
        logger.warning(
            "bible_source[%d]: book_id=%r out of range [%d..%d] — skipping",
            index, book_id, _MIN_BOOK_ID, _MAX_BOOK_ID,
        )
        return None

    text = entry["text"]
    if not isinstance(text, str) or not text.strip():
        logger.warning("bible_source[%d]: empty text — skipping", index)
        return None

    chapter = entry["chapter"]
    verse = entry["verse"]
    if not isinstance(chapter, int) or chapter < 1:
        logger.warning("bible_source[%d]: invalid chapter=%r — skipping", index, chapter)
        return None
    if not isinstance(verse, int) or verse < 0:
        logger.warning("bible_source[%d]: invalid verse=%r — skipping", index, verse)
        return None

    return VerseRow(
        book=str(entry["book"]),
        book_id=book_id,
        chapter=chapter,
        verse=verse,
        text=text.strip(),
        version=str(entry["version"]),
    )


def _iter_bible_source(source_path: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """Itera sobre as entradas de ``bible_source.json`` com índice.

    Raises:
        IndexerError: arquivo ausente ou JSON inválido.
    """
    if not os.path.isfile(source_path):
        raise IndexerError(f"bible source file not found: {source_path}")
    try:
        with open(source_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise IndexerError(f"invalid JSON in {source_path}: {e}") from e
    if not isinstance(data, list):
        raise IndexerError(
            f"bible source root must be a list, got {type(data).__name__}"
        )
    for i, entry in enumerate(data):
        yield i, entry


class BibleIndexer:
    """Indexador FTS5 para versículos da Bíblia.

    Cria, popula e reconstrói a tabela ``verses`` em um banco SQLite.
    Suporta múltiplas versões bíblicas (filtragem por coluna ``version``).

    Args:
        db_path: caminho do arquivo SQLite (ex.: ``"data/bible.pt-br.sqlite"``).
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Operações públicas
    # ------------------------------------------------------------------

    def build(
        self,
        source_path: str,
        *,
        version: str | None = None,
        rebuild: bool = False,
    ) -> IndexStats:
        """Importa versículos de ``bible_source.json`` para o índice FTS5.

        Args:
            source_path: caminho para ``bible_source.json``.
            version: se informado, filtra apenas versículos dessa versão
                (ignora versões diferentes no JSON). Se ``None``, importa todas.
            rebuild: se ``True``, dropa e recria a tabela antes de importar
                (reconstrução completa). Se ``False``, apenas adiciona à tabela
                existente (incremental).

        Returns:
            ``IndexStats`` com estatísticas da importação.

        Raises:
            IndexerError: fonte ausente, JSON inválido, erro de SQLite.
        """
        t0 = time.monotonic()
        logger.info(
            "build: source=%s db=%s version=%s rebuild=%s",
            source_path, self._db_path, version, rebuild,
        )

        # Garantir que o diretório do DB existe.
        db_dir = os.path.dirname(self._db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        conn = self._connect()
        try:
            if rebuild:
                self._drop_table(conn)
            self._create_table_if_not_exists(conn)

            total_inserted = 0
            skipped = 0
            versions_seen: dict[str, int] = {}
            batch: list[tuple[str, int, int, str, str, str]] = []

            for i, entry in _iter_bible_source(source_path):
                row = _validate_verse_entry(entry, i)
                if row is None:
                    skipped += 1
                    continue
                if version is not None and row.version != version:
                    continue
                batch.append((
                    row.book,
                    row.chapter,
                    row.verse,
                    row.text,
                    row.version,
                    row.id,
                ))
                versions_seen[row.version] = versions_seen.get(row.version, 0) + 1
                if len(batch) >= _BATCH_SIZE:
                    self._insert_batch(conn, batch)
                    total_inserted += len(batch)
                    batch.clear()

            # Insert remainder.
            if batch:
                self._insert_batch(conn, batch)
                total_inserted += len(batch)
                batch.clear()

            conn.commit()
            duration_ms = (time.monotonic() - t0) * 1000

            # Coletar estatísticas finais da tabela.
            total_in_table = self._count_verses(conn)
            table_versions = self._list_versions(conn)
            verses_per_version = self._count_per_version(conn)

            stats = IndexStats(
                db_path=self._db_path,
                total_verses=total_in_table,
                versions=table_versions,
                verses_per_version=verses_per_version,
                skipped_invalid=skipped,
                duration_ms=duration_ms,
                rebuilt=rebuild,
            )
            logger.info(
                "build: inserted=%d total_in_table=%d skipped=%d versions=%s "
                "duration=%.1fms",
                total_inserted, total_in_table, skipped,
                table_versions, duration_ms,
            )
            return stats
        except sqlite3.Error as e:
            conn.rollback()
            raise IndexerError(f"SQLite error during build: {e}") from e
        finally:
            conn.close()

    def rebuild(self, source_path: str, *, version: str | None = None) -> IndexStats:
        """Reconstrução completa do índice (drop + create + import).

        Equivalente a ``build(source_path, version=version, rebuild=True)``.
        """
        return self.build(source_path, version=version, rebuild=True)

    def add_version(self, source_path: str, version: str) -> IndexStats:
        """Adiciona versículos de uma versão específica ao índice existente.

        Não dropa a tabela — apenas adiciona linhas onde ``version`` bate.
        Útil para adicionar uma nova tradução sem reconstruir tudo.

        Args:
            source_path: caminho para ``bible_source.json`` contendo a versão.
            version: versão a importar (ex.: ``"NVI"``).

        Returns:
            ``IndexStats`` com estatísticas.
        """
        return self.build(source_path, version=version, rebuild=False)

    def get_stats(self) -> IndexStats:
        """Retorna estatísticas do índice atual sem modificar nada.

        Raises:
            IndexerError: DB ausente ou tabela não existe.
        """
        if not os.path.isfile(self._db_path):
            raise IndexerError(f"database not found: {self._db_path}")
        conn = self._connect()
        try:
            if not self._table_exists(conn):
                raise IndexerError(f"table 'verses' does not exist in {self._db_path}")
            total = self._count_verses(conn)
            versions = self._list_versions(conn)
            per_version = self._count_per_version(conn)
            return IndexStats(
                db_path=self._db_path,
                total_verses=total,
                versions=versions,
                verses_per_version=per_version,
                skipped_invalid=0,
                duration_ms=0.0,
                rebuilt=False,
            )
        finally:
            conn.close()

    def drop(self) -> None:
        """Remove a tabela FTS5 (e o arquivo DB se ficar vazio).

        Raises:
            IndexerError: erro de SQLite.
        """
        conn = self._connect()
        try:
            self._drop_table(conn)
            conn.commit()
            logger.info("drop: table 'verses' removed from %s", self._db_path)
        except sqlite3.Error as e:
            raise IndexerError(f"SQLite error during drop: {e}") from e
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Abre conexão SQLite com o DB."""
        try:
            return sqlite3.connect(self._db_path)
        except sqlite3.Error as e:
            raise IndexerError(f"cannot open SQLite DB {self._db_path}: {e}") from e

    @staticmethod
    def _table_exists(conn: sqlite3.Connection) -> bool:
        """Verifica se a tabela ``verses`` existe."""
        row = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='verses'"
        ).fetchone()
        return row is not None and row[0] > 0

    @staticmethod
    def _create_table_if_not_exists(conn: sqlite3.Connection) -> None:
        """Cria a tabela FTS5 se não existir."""
        if not BibleIndexer._table_exists(conn):
            conn.execute(_FTS5_SCHEMA)
            logger.debug("created FTS5 table 'verses'")

    @staticmethod
    def _drop_table(conn: sqlite3.Connection) -> None:
        """Dropa a tabela FTS5 se existir."""
        if BibleIndexer._table_exists(conn):
            conn.execute("DROP TABLE verses")
            logger.debug("dropped FTS5 table 'verses'")

    @staticmethod
    def _insert_batch(
        conn: sqlite3.Connection,
        batch: list[tuple[str, int, int, str, str, str]],
    ) -> None:
        """Insere um lote de versículos na tabela FTS5."""
        conn.executemany(
            "INSERT INTO verses (book, chapter, verse, text, version, id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )

    @staticmethod
    def _count_verses(conn: sqlite3.Connection) -> int:
        """Conta o total de linhas na tabela."""
        row = conn.execute("SELECT count(*) FROM verses").fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _list_versions(conn: sqlite3.Connection) -> list[str]:
        """Lista as versões distintas presentes na tabela."""
        rows = conn.execute(
            "SELECT DISTINCT version FROM verses ORDER BY version"
        ).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _count_per_version(conn: sqlite3.Connection) -> dict[str, int]:
        """Conta versículos por versão."""
        rows = conn.execute(
            "SELECT version, count(*) FROM verses GROUP BY version ORDER BY version"
        ).fetchall()
        return {r[0]: int(r[1]) for r in rows}
