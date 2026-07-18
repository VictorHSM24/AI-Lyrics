"""Migracao definitiva da base biblica de testes para base completa.

Le os bancos SQLite do projeto damarals/biblias em data/sources/ e cria
um novo data/bible.pt-br.sqlite com tabela FTS5 no schema esperado pelo
Searcher, BibleStateManager e demais modulos do pipeline.

Schema FTS5 (identico ao atual):
    CREATE VIRTUAL TABLE verses USING fts5(
        book,
        chapter UNINDEXED,
        verse UNINDEXED,
        text,
        version UNINDEXED,
        id UNINDEXED,            -- BBCCCVVV
        tokenize = 'unicode61 remove_diacritics 2'
    );

Transformacoes aplicadas:
    - id: BBCCCVVV derivado de book_id + chapter + verse
    - book: nome canonico de config/books.json (nao do banco fonte)
    - version: etiqueta da versao (ACF, ARC, ARA, NAA, JFAA)
    - chapter/verse: int -> str (FTS5 armazena como texto)

Uso:
    python tools/migrate_bible_db.py
    python tools/migrate_bible_db.py --versions ACF
    python tools/migrate_bible_db.py --versions ACF ARC ARA
    python tools/migrate_bible_db.py --no-backup
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

# Forcar UTF-8 no stdout/stderr (Windows cp1252 quebra acentos)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# Fallback: se __file__ resolver para um caminho que nao contem config/books.json,
# usar o diretorio de trabalho atual.
if not (_PROJECT_ROOT / "config" / "books.json").is_file():
    _PROJECT_ROOT = Path(os.getcwd())
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Schema FTS5 identico ao de busca/indexer.py (_FTS5_SCHEMA)
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

# Tamanho do lote para inserts batched (mesmo valor de busca/indexer.py)
_BATCH_SIZE = 1000

# Versoes disponiveis e seus arquivos fonte
_VERSION_FILES: dict[str, str] = {
    "ACF": "data/sources/ACF.sqlite",
    "ARC": "data/sources/ARC.sqlite",
    "ARA": "data/sources/ARA.sqlite",
    "NAA": "data/sources/NAA.sqlite",
    "JFAA": "data/sources/JFAA.sqlite",
}


# ---------------------------------------------------------------------------
# Carregamento de nomes canonicos
# ---------------------------------------------------------------------------


def load_canonical_names(books_json_path: str) -> dict[int, str]:
    """Carrega book_id -> nome canonico de config/books.json.

    Args:
        books_json_path: caminho para config/books.json.

    Returns:
        Dicionario {book_id: canonical_name}.

    Raises:
        FileNotFoundError: arquivo nao encontrado.
        ValueError: JSON invalido ou estrutura inesperada.
    """
    with open(books_json_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(
            f"books.json deve ser uma lista, got {type(data).__name__}"
        )
    names: dict[int, str] = {}
    for entry in data:
        bid = entry.get("id")
        canonical = entry.get("canonical")
        if bid is None or canonical is None:
            continue
        names[int(bid)] = str(canonical)
    return names


# ---------------------------------------------------------------------------
# Leitura dos bancos fonte
# ---------------------------------------------------------------------------


def read_source_verses(
    source_db_path: str,
    version_label: str,
    canonical_names: dict[int, str],
) -> list[tuple[str, str, str, str, str, str]]:
    """Le todos os versiculos de um banco fonte SQLite.

    Args:
        source_db_path: caminho para o banco fonte (ex.: data/sources/ACF.sqlite).
        version_label: etiqueta da versao (ex.: "ACF").
        canonical_names: dicionario {book_id: nome_canonico} de config/books.json.

    Returns:
        Lista de tuplas (book, chapter, verse, text, version, id) no formato
        esperado pelo FTS5.

    Raises:
        FileNotFoundError: banco fonte nao encontrado.
        sqlite3.Error: erro de leitura.
    """
    if not os.path.isfile(source_db_path):
        raise FileNotFoundError(f"banco fonte nao encontrado: {source_db_path}")

    rows: list[tuple[str, str, str, str, str, str]] = []
    conn = sqlite3.connect(source_db_path)
    try:
        cursor = conn.execute(
            "SELECT book_id, chapter, verse, text FROM verse ORDER BY book_id, chapter, verse"
        )
        for book_id, chapter, verse, text in cursor:
            book_id = int(book_id)
            chapter = int(chapter)
            verse = int(verse)
            # Nome canonico de config/books.json (fallback: nome do banco fonte)
            book_name = canonical_names.get(book_id, "")
            if not book_name:
                print(
                    f"  AVISO: book_id={book_id} nao encontrado em books.json — pulando",
                    file=sys.stderr,
                )
                continue
            # Texto vazio -> pular
            if text is None or not str(text).strip():
                continue
            # ID no formato BBCCCVVV
            verse_id = f"{book_id:02d}{chapter:03d}{verse:03d}"
            rows.append((
                book_name,           # book
                str(chapter),        # chapter
                str(verse),          # verse
                str(text).strip(),   # text
                version_label,       # version
                verse_id,            # id
            ))
    finally:
        conn.close()

    return rows


# ---------------------------------------------------------------------------
# Criacao do banco FTS5
# ---------------------------------------------------------------------------


def create_fts5_db(db_path: str) -> sqlite3.Connection:
    """Cria (ou recria) o banco FTS5 com o schema esperado.

    Se o banco ja existir, ele sera removido e recriado do zero.

    Args:
        db_path: caminho do banco destino.

    Returns:
        Conexao SQLite aberta.
    """
    # Remover banco existente (recriacao completa)
    if os.path.isfile(db_path):
        os.remove(db_path)

    # Garantir que o diretorio existe
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.execute(_FTS5_SCHEMA)
    conn.commit()
    return conn


def insert_batch(
    conn: sqlite3.Connection,
    batch: list[tuple[str, str, str, str, str, str]],
) -> None:
    """Insere um lote de versiculos na tabela FTS5."""
    conn.executemany(
        "INSERT INTO verses (book, chapter, verse, text, version, id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        batch,
    )


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------


def validate_db(
    db_path: str,
    expected_books: int = 66,
    expected_genesis_chapters: int = 50,
    expected_apocalypse_chapters: int = 22,
    min_total_verses: int = 150_000,
) -> dict[str, object]:
    """Valida o banco FTS5 recem-criado.

    Args:
        db_path: caminho do banco.
        expected_books: numero esperado de livros distintos.
        expected_genesis_chapters: capitulos esperados de Genesis.
        expected_apocalypse_chapters: capitulos esperados de Apocalipse.
        min_total_verses: numero minimo de versiculos.

    Returns:
        Dicionario com resultados da validacao.
    """
    conn = sqlite3.connect(db_path)
    try:
        # Total de versiculos
        total = conn.execute("SELECT COUNT(*) FROM verses").fetchone()[0]

        # Livros distintos (extrair book_id dos primeiros 2 digitos do id)
        books = conn.execute(
            "SELECT COUNT(DISTINCT CAST(substr(id, 1, 2) AS INTEGER)) FROM verses"
        ).fetchone()[0]

        # Capitulos de Genesis (book_id=1)
        genesis_chapters = conn.execute(
            "SELECT MAX(CAST(substr(id, 3, 3) AS INTEGER)) "
            "FROM verses WHERE CAST(substr(id, 1, 2) AS INTEGER) = 1"
        ).fetchone()[0]

        # Capitulos de Apocalipse (book_id=66)
        apocalypse_chapters = conn.execute(
            "SELECT MAX(CAST(substr(id, 3, 3) AS INTEGER)) "
            "FROM verses WHERE CAST(substr(id, 1, 2) AS INTEGER) = 66"
        ).fetchone()[0]

        # Versiculos por versao
        versions = conn.execute(
            "SELECT version, COUNT(*) FROM verses GROUP BY version ORDER BY version"
        ).fetchall()
        versions_dict = {v[0]: v[1] for v in versions}

        return {
            "total_verses": total,
            "books": books,
            "genesis_chapters": genesis_chapters,
            "apocalypse_chapters": apocalypse_chapters,
            "versions": versions_dict,
            "valid_books": books == expected_books,
            "valid_genesis": genesis_chapters == expected_genesis_chapters,
            "valid_apocalypse": apocalypse_chapters == expected_apocalypse_chapters,
            "valid_total": total >= min_total_verses,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Relatorio
# ---------------------------------------------------------------------------


def print_report(
    results: dict[str, object],
    per_version_counts: dict[str, int],
    elapsed_ms: float,
) -> bool:
    """Imprime relatorio final da migracao.

    Args:
        results: resultado de validate_db().
        per_version_counts: contagem de versiculos importados por versao.
        elapsed_ms: tempo total de processamento em ms.

    Returns:
        True se todas as validacoes passaram.
    """
    print()
    print("=" * 60)
    print("RELATORIO DE MIGRACAO")
    print("=" * 60)
    print()
    print("Versiculos por versao:")
    for version, count in sorted(per_version_counts.items()):
        print(f"  {version:6s}: {count:>7,}")
    print()
    total_imported = sum(per_version_counts.values())
    print(f"Total importado: {total_imported:,}")
    print(f"Tempo de processamento: {elapsed_ms:.0f} ms")
    print()
    print("-" * 60)
    print("Validacao:")
    print(f"  Total de versiculos:  {results['total_verses']:>7,}  "
          f"{'OK' if results['valid_total'] else 'FALHOU'} (min=150.000)")
    print(f"  Livros distintos:     {results['books']:>7}  "
          f"{'OK' if results['valid_books'] else 'FALHOU'} (esperado=66)")
    print(f"  Genesis capitulos:    {results['genesis_chapters']:>7}  "
          f"{'OK' if results['valid_genesis'] else 'FALHOU'} (esperado=50)")
    print(f"  Apocalipse capitulos: {results['apocalypse_chapters']:>7}  "
          f"{'OK' if results['valid_apocalypse'] else 'FALHOU'} (esperado=22)")
    print()
    print("Versiculos por versao no banco:")
    for v, c in sorted(results["versions"].items()):
        print(f"  {v:6s}: {c:>7,}")
    print()

    all_valid = (
        results["valid_books"]
        and results["valid_genesis"]
        and results["valid_apocalypse"]
        and results["valid_total"]
    )
    if all_valid:
        print("=" * 60)
        print("MIGRACAO CONCLUIDA COM SUCESSO")
        print("=" * 60)
    else:
        print("=" * 60)
        print("MIGRACAO FALHOU — validacao nao passou")
        print("=" * 60)
    return all_valid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migracao definitiva da base biblica — cria data/bible.pt-br.sqlite "
            "completo a partir de data/sources/*.sqlite."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python tools/migrate_bible_db.py\n"
            "  python tools/migrate_bible_db.py --versions ACF\n"
            "  python tools/migrate_bible_db.py --versions ACF ARC ARA\n"
            "  python tools/migrate_bible_db.py --no-backup\n"
        ),
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        default=list(_VERSION_FILES.keys()),
        choices=list(_VERSION_FILES.keys()),
        help="Versoes a importar (default: todas).",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Nao criar backup do banco atual.",
    )
    parser.add_argument(
        "--books-json",
        type=str,
        default="config/books.json",
        help="Caminho para config/books.json (default: config/books.json).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/bible.pt-br.sqlite",
        help="Caminho do banco destino (default: data/bible.pt-br.sqlite).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    output_db = str(_PROJECT_ROOT / args.output)
    books_json = str(_PROJECT_ROOT / args.books_json)

    print("=" * 60)
    print("MIGRACAO DA BASE BIBLICA")
    print("=" * 60)
    print()
    print(f"Banco destino:  {output_db}")
    print(f"Books JSON:     {books_json}")
    print(f"Versoes:        {', '.join(args.versions)}")
    print(f"Backup:         {'nao' if args.no_backup else 'sim'}")
    print()

    # 1. Carregar nomes canonicos
    print("-" * 60)
    print("Carregando nomes canonicos de config/books.json...")
    try:
        canonical_names = load_canonical_names(books_json)
    except Exception as e:
        print(f"ERRO: {e}")
        return 1
    print(f"  {len(canonical_names)} livros carregados")
    print()

    # 2. Backup do banco atual
    if not args.no_backup:
        if os.path.isfile(output_db):
            backup_path = output_db + ".bak"
            print("-" * 60)
            print(f"Backup: {output_db} -> {backup_path}")
            shutil.copy2(output_db, backup_path)
            print(f"  Backup criado: {backup_path}")
            print()
        else:
            print("-" * 60)
            print("Backup: banco atual nao existe — nada a backup")
            print()

    # 3. Criar novo banco FTS5
    print("-" * 60)
    print("Criando novo banco FTS5...")
    t_start = time.monotonic()
    try:
        conn = create_fts5_db(output_db)
    except Exception as e:
        print(f"ERRO ao criar banco: {e}")
        return 1
    print(f"  Banco criado: {output_db}")
    print(f"  Schema: verses(book, chapter, verse, text, version, id) FTS5")
    print()

    # 4. Importar versoes
    per_version_counts: dict[str, int] = {}
    for version_label in args.versions:
        source_path = str(_PROJECT_ROOT / _VERSION_FILES[version_label])
        print("-" * 60)
        print(f"Importando versao {version_label}...")
        print(f"  Fonte: {source_path}")

        if not os.path.isfile(source_path):
            print(f"  AVISO: arquivo fonte nao encontrado — pulando")
            print()
            continue

        try:
            rows = read_source_verses(source_path, version_label, canonical_names)
        except Exception as e:
            print(f"  ERRO: {e}")
            print()
            continue

        print(f"  {len(rows):,} versiculos lidos")

        # Inserir em lotes
        inserted = 0
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = rows[i:i + _BATCH_SIZE]
            insert_batch(conn, batch)
            inserted += len(batch)
        conn.commit()

        per_version_counts[version_label] = inserted
        print(f"  {inserted:,} versiculos inseridos")
        print()

    conn.close()

    elapsed_ms = (time.monotonic() - t_start) * 1000

    # 5. Validar
    print("-" * 60)
    print("Validando banco...")
    results = validate_db(output_db)
    print(f"  Validacao concluida")
    print()

    # 6. Relatorio
    all_valid = print_report(results, per_version_counts, elapsed_ms)
    return 0 if all_valid else 1


if __name__ == "__main__":
    sys.exit(main())
