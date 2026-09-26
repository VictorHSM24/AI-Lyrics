"""Gera config/canon_bounds.json a partir da base FTS5 local.

Para cada livro (id 1..66), lista o maior versículo de cada capítulo.
A versificação varia levemente entre traduções, então usamos o maior
valor sustentado por >= 2 versões (o segundo maior máximo): tolera
variações legítimas e descarta importações corrompidas de uma única
versão (ex.: NTLH 2 Samuel 24 importado como capítulos 25-38; NAA
2 Samuel 23 com 51 versículos). O número de capítulos é limitado ao
cânon protestante padrão (1189 capítulos).

Uso: python scripts/build_canon_bounds.py [db] [saida]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# Capítulos por livro no cânon protestante (Gênesis..Apocalipse).
STANDARD_CHAPTERS = [
    50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42,
    150, 31, 12, 8, 66, 52, 5, 48, 12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4,
    28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5,
    3, 5, 1, 1, 1, 22,
]


def build(db_path: Path) -> dict[str, list[int]]:
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT CAST(substr(id, 1, 2) AS INTEGER) AS b, "
            "CAST(chapter AS INTEGER) AS c, version, "
            "MAX(CAST(verse AS INTEGER)) FROM verses GROUP BY b, c, version"
        ).fetchall()
    finally:
        con.close()
    per_chapter: dict[tuple[int, int], list[int]] = {}
    for b, c, _version, v in rows:
        per_chapter.setdefault((int(b), int(c)), []).append(int(v))
    out: dict[str, list[int]] = {}
    for b in range(1, 67):
        verses: list[int] = []
        for c in range(1, STANDARD_CHAPTERS[b - 1] + 1):
            maxima = sorted(per_chapter.get((b, c), [0]), reverse=True)
            verses.append(maxima[1] if len(maxima) >= 2 else maxima[0])
        out[str(b)] = verses
    return out


def main() -> None:
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "bible.pt-br.sqlite"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "config" / "canon_bounds.json"
    data = build(db)
    missing = [(b, c + 1) for b, vs in data.items() for c, v in enumerate(vs) if v <= 0]
    if missing:
        raise SystemExit(f"capítulos sem versículos na base: {missing[:10]}")
    dest.write_text(
        json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8",
    )
    total = sum(len(v) for v in data.values())
    print(f"{dest}: 66 livros, {total} capítulos.")


if __name__ == "__main__":
    main()
