"""Diagnóstico versões por versículo + caso certeza."""
import sqlite3
import sys

sys.path.insert(0, '.')

DB = "data/bible.pt-br.sqlite"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Verificar versões por versículo via FTS5 MATCH com referência
print("=" * 70)
print("Versões disponíveis por versículo (via MATCH)")
print("=" * 70)

target = [
    ("Salmos 23:4", "sombra da morte"),
    ("Filipenses 4:13", "fortalece"),
    ("Romanos 8:28", "cooperam para o bem"),
    ("João 3:16", "deus amou o mundo"),
    ("Hebreus 11:1", "certeza"),
]

for ref, search_term in target:
    cur.execute(
        "SELECT book, chapter, verse, version, text "
        "FROM verses WHERE verses MATCH ? ORDER BY version",
        (search_term,)
    )
    rows = cur.fetchall()
    print(f"\n{ref} (busca por '{search_term}'):")
    for r in rows:
        print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

# Caso especial: Hebreus 11:1 — verificar texto real
print("\n" + "=" * 70)
print("Hebreus 11:1 — texto real em cada versão")
print("=" * 70)
cur.execute(
    "SELECT book, chapter, verse, version, text "
    "FROM verses WHERE verses MATCH 'hebreus' AND chapter = '11' AND verse = '1' "
    "ORDER BY version"
)
try:
    rows = cur.fetchall()
    for r in rows:
        print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}")
except Exception as e:
    print(f"  Erro: {e}")

# Buscar por "fe e a certeza" (sem acentos, como FTS5 normaliza)
print("\n--- Busca 'fe e a certeza' (sem acentos) ---")
cur.execute(
    "SELECT book, chapter, verse, version, text "
    "FROM verses WHERE verses MATCH 'fe e a certeza' ORDER BY version LIMIT 10"
)
rows = cur.fetchall()
print(f"Resultados: {len(rows)}")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

# Buscar por "certeza" apenas
print("\n--- Busca apenas 'certeza' ---")
cur.execute(
    "SELECT book, chapter, verse, version, substr(text, 1, 80) "
    "FROM verses WHERE verses MATCH 'certeza' AND version = 'ACF' ORDER BY bm25(verses) LIMIT 5"
)
rows = cur.fetchall()
print(f"ACF: {len(rows)} resultados")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}...")

cur.execute(
    "SELECT book, chapter, verse, version, substr(text, 1, 80) "
    "FROM verses WHERE verses MATCH 'certeza' ORDER BY bm25(verses) LIMIT 10"
)
rows = cur.fetchall()
print(f"\nTodas versões: {len(rows)} resultados")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}...")

# Verificar o texto exato de Hebreus 11:1 em ACF
print("\n--- Hebreus 11:1 em ACF (via LIKE) ---")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE text LIKE '%certeza% coisas que se esperam%' "
    "ORDER BY version"
)
rows = cur.fetchall()
print(f"LIKE '%certeza% coisas que se esperam%': {len(rows)} resultados")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}")

# Versões que têm Filipenses 4:13
print("\n--- Filipenses 4:13 em todas as versões ---")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH 'fortalece' ORDER BY version LIMIT 10"
)
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

# Versões que têm Romanos 8:28
print("\n--- Romanos 8:28 em todas as versões ---")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH 'cooperam' ORDER BY version LIMIT 10"
)
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

conn.close()
print("\n=== FIM ===")
