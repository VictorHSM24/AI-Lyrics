"""Verificar Romanos 8:28 em ACF e outras versões."""
import sqlite3
import sys
sys.path.insert(0, '.')

DB = "data/bible.pt-br.sqlite"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Buscar Romanos 8:28 em todas as versões via LIKE
print("=== Romanos 8:28 em todas as versões ===")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE text LIKE '%romanos%' AND text LIKE '%8:28%'"
)
# FTS5 virtual table — tentar via content
cur.execute(
    "SELECT c0, c1, c2, c4, c3 FROM verses_content "
    "WHERE c0='Romanos' AND CAST(c1 AS INTEGER)=8 AND CAST(c2 AS INTEGER)=28"
)
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}")

# Buscar por "contribuem" ou "cooperam" em Romanos 8
print("\n=== Romanos 8:28 via MATCH 'romanos' ===")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH 'romanos 8 28' ORDER BY version"
)
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}")

# Buscar ACF versículos com "cooperam"
print("\n=== ACF versículos com 'cooperam' ===")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH 'cooperam' AND version='ACF'"
)
rows = cur.fetchall()
print(f"Total: {len(rows)}")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

# Buscar ACF versículos com "todas as coisas"
print("\n=== ACF versículos com 'todas as coisas' ===")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH '\"todas\" \"coisas\"' AND version='ACF' LIMIT 10"
)
rows = cur.fetchall()
print(f"Total: {len(rows)}")
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4][:80]}...")

# Buscar Filipenses 4:13 em ACF
print("\n=== Filipenses 4:13 em ACF ===")
cur.execute(
    "SELECT book, chapter, verse, version, text FROM verses "
    "WHERE verses MATCH 'filipenses 4 13' AND version='ACF'"
)
rows = cur.fetchall()
for r in rows:
    print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}")

# Resumo: versões que têm cada frase
print("\n=== RESUMO: versões por frase de busca ===")
phrases = [
    ("vale da sombra da morte", "Salmos 23:4"),
    ("tudo posso naquele que me fortalece", "Filipenses 4:13"),
    ("todas as coisas cooperam para o bem", "Romanos 8:28"),
    ("deus amou o mundo", "João 3:16"),
    ("fe e a certeza", "Hebreus 11:1"),
]
for phrase, ref in phrases:
    cur.execute(
        "SELECT DISTINCT version FROM verses WHERE verses MATCH ? ORDER BY version",
        (phrase,)
    )
    versions = [r[0] for r in cur.fetchall()]
    has_acf = "ACF" in versions
    print(f"  '{phrase}' → {ref}")
    print(f"    Versões: {versions}")
    print(f"    ACF tem: {'SIM' if has_acf else 'NAO'}")

conn.close()
