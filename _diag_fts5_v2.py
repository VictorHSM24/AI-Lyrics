"""Diagnóstico FTS5 com filtro de versão e query quoted."""
import sqlite3
import sys

sys.path.insert(0, '.')

DB = "data/bible.pt-br.sqlite"
conn = sqlite3.connect(DB)
cur = conn.cursor()

test_phrases = [
    "vale da sombra da morte",
    "tudo posso naquele que me fortalece",
    "todas as coisas cooperam para o bem",
    "deus amou o mundo",
    "certeza das coisas que se esperam",
]

print("=" * 70)
print("TESTE 1: MATCH sem filtro de versão (todas as versões)")
print("=" * 70)
for phrase in test_phrases:
    cur.execute(
        "SELECT book, chapter, verse, version, bm25(verses) as score "
        "FROM verses WHERE verses MATCH ? ORDER BY score LIMIT 10",
        (phrase,)
    )
    rows = cur.fetchall()
    versions = set(r[3] for r in rows)
    print(f"\n  '{phrase}' → {len(rows)} resultados, versões: {versions}")
    for r in rows:
        print(f"    {r[0]} {r[1]}:{r[2]} ({r[3]}) score={r[4]:.2f}")

print("\n" + "=" * 70)
print("TESTE 2: MATCH com filtro version='ACF' (como o Searcher faz)")
print("=" * 70)
for phrase in test_phrases:
    cur.execute(
        "SELECT book, chapter, verse, version, bm25(verses) as score "
        "FROM verses WHERE verses MATCH ? AND version = 'ACF' "
        "ORDER BY bm25(verses) LIMIT 10",
        (phrase,)
    )
    rows = cur.fetchall()
    print(f"\n  '{phrase}' (ACF) → {len(rows)} resultados")
    for r in rows:
        print(f"    {r[0]} {r[1]}:{r[2]} ({r[3]}) score={r[4]:.2f}")

print("\n" + "=" * 70)
print("TESTE 3: MATCH com query quoted (como _build_fts5_query faz)")
print("=" * 70)
for phrase in test_phrases:
    tokens = phrase.split()
    quoted = " ".join(f'"{t}"' for t in tokens)
    cur.execute(
        "SELECT book, chapter, verse, version, bm25(verses) as score "
        "FROM verses WHERE verses MATCH ? AND version = 'ACF' "
        "ORDER BY bm25(verses) LIMIT 10",
        (quoted,)
    )
    rows = cur.fetchall()
    print(f"\n  '{phrase}' → quoted: {quoted}")
    print(f"  (ACF, quoted) → {len(rows)} resultados")
    for r in rows:
        print(f"    {r[0]} {r[1]}:{r[2]} ({r[3]}) score={r[4]:.2f}")

print("\n" + "=" * 70)
print("TESTE 4: Verificar versões disponíveis por versículo")
print("=" * 70)
target_verses = [
    ("Salmos", 23, 4),
    ("Filipenses", 4, 13),
    ("Romanos", 8, 28),
    ("João", 3, 16),
    ("Hebreus", 11, 1),
]
for book, ch, vs in target_verses:
    cur.execute(
        "SELECT version, substr(text, 1, 60) FROM verses_content "
        "WHERE c0=? AND c1=? AND c2=?",
        (book, str(ch), str(vs))
    )
    rows = cur.fetchall()
    print(f"\n  {book} {ch}:{vs}:")
    for r in rows:
        print(f"    {r[0]}: {r[1]}...")

# Também verificar com CAST para número
print("\n--- Com CAST(c1 AS INT) ---")
for book, ch, vs in target_verses:
    cur.execute(
        "SELECT version, substr(c3, 1, 60) FROM verses_content "
        "WHERE c0=? AND CAST(c1 AS INT)=? AND CAST(c2 AS INT)=?",
        (book, ch, vs)
    )
    rows = cur.fetchall()
    print(f"  {book} {ch}:{vs}: {len(rows)} versões: {[r[0] for r in rows]}")

conn.close()
print("\n=== FIM ===")
