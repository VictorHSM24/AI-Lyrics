"""Diagnóstico FTS5 — estrutura e buscas."""
import sqlite3
import sys

sys.path.insert(0, '.')

DB = "data/bible.pt-br.sqlite"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# Verificar se 'verses' é virtual table
cur.execute("SELECT type, sql FROM sqlite_master WHERE name='verses'")
row = cur.fetchone()
print(f"Tipo: {row[0]}")
print(f"SQL: {row[1]}")

# Verificar verses_config
cur.execute("SELECT * FROM verses_config")
configs = cur.fetchall()
print(f"\nverses_config: {configs}")

# Verificar tokenizer
cur.execute("SELECT sql FROM sqlite_master WHERE name LIKE 'verses%'")
for r in cur.fetchall():
    print(f"  {r[0][:200] if r[0] else 'None'}")

# Buscar versículos específicos via content
print("\n--- Versículos via verses_content ---")
cur.execute("SELECT * FROM verses_content LIMIT 3")
cols = [d[0] for d in cur.description]
print(f"Colunas: {cols}")
rows = cur.fetchall()
for r in rows:
    print(f"  {r}")

# Buscar João 3:16 via content
print("\n--- João 3:16 via verses_content ---")
cur.execute("SELECT * FROM verses_content WHERE c0='João' AND c1=3 AND c2=16 LIMIT 5")
rows = cur.fetchall()
for r in rows:
    print(f"  {r}")

# Tentar MATCH em verses (virtual table)
print("\n--- MATCH em verses (FTS5) ---")
test_phrases = [
    "vale da sombra da morte",
    "tudo posso naquele que me fortalece",
    "todas as coisas cooperam para o bem",
    "deus amou o mundo",
    "certeza das coisas que se esperam",
]

for phrase in test_phrases:
    try:
        cur.execute(
            "SELECT book, chapter, verse, version, bm25(verses) as score "
            "FROM verses WHERE verses MATCH ? ORDER BY score LIMIT 3",
            (phrase,)
        )
        rows = cur.fetchall()
        if rows:
            print(f"\n  '{phrase}' → {len(rows)} resultados:")
            for r in rows:
                print(f"    {r[0]} {r[1]}:{r[2]} ({r[3]}) score={r[4]:.4f}")
        else:
            print(f"\n  '{phrase}' → 0 resultados")
    except Exception as e:
        print(f"\n  '{phrase}' → Erro: {e}")

    # Tentar com OR
    try:
        tokens = phrase.split()
        or_query = " OR ".join(tokens)
        cur.execute(
            "SELECT book, chapter, verse, version, bm25(verses) as score "
            "FROM verses WHERE verses MATCH ? ORDER BY score LIMIT 3",
            (or_query,)
        )
        rows = cur.fetchall()
        if rows:
            print(f"  (OR) → {len(rows)}: {rows[0][0]} {rows[0][1]}:{rows[0][2]}")
        else:
            print(f"  (OR) → 0 resultados")
    except Exception as e:
        print(f"  (OR) → Erro: {e}")

# Verificar se o problema é acentos
print("\n--- Teste de acentos no FTS5 ---")
tests_accent = [
    ("deus amou o mundo", "deus amou o mundo"),
    ("fé é a certeza", "fe e a certeza"),
    ("sombra da morte", "sombra da morte"),
]
for original, normalized in tests_accent:
    try:
        cur.execute(
            "SELECT book, chapter, verse, bm25(verses) as score "
            "FROM verses WHERE verses MATCH ? ORDER BY score LIMIT 1",
            (original,)
        )
        r1 = cur.fetchall()
        cur.execute(
            "SELECT book, chapter, verse, bm25(verses) as score "
            "FROM verses WHERE verses MATCH ? ORDER BY score LIMIT 1",
            (normalized,)
        )
        r2 = cur.fetchall()
        print(f"  '{original}' → {len(r1)} | '{normalized}' → {len(r2)}")
    except Exception as e:
        print(f"  '{original}' → Erro: {e}")

# Verificar termos indexados
print("\n--- Termos indexados (amostra) ---")
cur.execute("SELECT term, COUNT(*) FROM verses_idx GROUP BY term ORDER BY term LIMIT 20")
for r in cur.fetchall():
    print(f"  term='{r[0]}' count={r[1]}")

# Verificar se há termo 'sombra' ou 'sombra'
cur.execute("SELECT DISTINCT term FROM verses_idx WHERE term LIKE '%sombra%' OR term LIKE '%morte%' OR term LIKE '%cooperam%' OR term LIKE '%fortalece%' OR term LIKE '%certeza%'")
terms = cur.fetchall()
print(f"\nTermos relevantes: {[t[0] for t in terms]}")

conn.close()
print("\n=== FIM ===")
