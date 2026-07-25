"""Diagnóstico completo de busca — FASE 1 a 5."""
import sqlite3
import os
import sys

sys.path.insert(0, '.')

DB = "data/bible.pt-br.sqlite"
EMB = "data/bible.embeddings.npy"

print("=" * 70)
print("FASE 5 — Configuração")
print("=" * 70)
print(f"DB path: {DB}")
print(f"DB exists: {os.path.exists(DB)}")
print(f"DB size: {os.path.getsize(DB) if os.path.exists(DB) else 0} bytes")
print(f"EMB path: {EMB}")
print(f"EMB exists: {os.path.exists(EMB)}")
print(f"EMB size: {os.path.getsize(EMB) if os.path.exists(EMB) else 0} bytes")

conn = sqlite3.connect(DB)
cur = conn.cursor()

print("\n" + "=" * 70)
print("FASE 1 — Banco SQLite")
print("=" * 70)

# Tabelas
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"Tabelas: {tables}")

# Schema da tabela de versículos
for t in tables:
    cur.execute(f"PRAGMA table_info({t})")
    cols = cur.fetchall()
    print(f"\nSchema {t}:")
    for c in cols:
        print(f"  {c[1]} ({c[2]})")

# Quantidade total de versículos
for t in tables:
    if t.startswith('sqlite_') or t == 'fts5':
        continue
    try:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"\n{t}: {count} registros")
    except:
        pass

# Versões
try:
    cur.execute("SELECT DISTINCT version FROM verses LIMIT 10")
    versions = [r[0] for r in cur.fetchall()]
    print(f"\nVersões: {versions}")
except Exception as e:
    print(f"\nErro ao buscar versões: {e}")
    # Tentar outras tabelas
    for t in tables:
        if t.startswith('sqlite_'):
            continue
        try:
            cur.execute(f"SELECT * FROM {t} LIMIT 1")
            row = cur.fetchone()
            if row:
                print(f"  Amostra {t}: {row}")
        except:
            pass

# Livros
try:
    cur.execute("SELECT DISTINCT book FROM verses ORDER BY book")
    books = [r[0] for r in cur.fetchall()]
    print(f"\nLivros ({len(books)}): {books[:10]}... {books[-5:] if len(books)>10 else ''}")
except Exception as e:
    print(f"Erro ao buscar livros: {e}")

# Verificar versículos específicos
target_verses = [
    ("João", 3, 16),
    ("Romanos", 8, 28),
    ("Hebreus", 11, 1),
    ("Salmos", 23, 4),
    ("Filipenses", 4, 13),
]

print("\n--- Versículos específicos ---")
for book, ch, vs in target_verses:
    try:
        cur.execute(
            "SELECT book, chapter, verse, version, substr(text, 1, 80) FROM verses "
            "WHERE book=? AND chapter=? AND verse=?",
            (book, ch, vs)
        )
        rows = cur.fetchall()
        if rows:
            for r in rows:
                print(f"  {r[0]} {r[1]}:{r[2]} ({r[3]}) — {r[4]}...")
        else:
            print(f"  {book} {ch}:{vs} — NÃO ENCONTRADO")
    except Exception as e:
        print(f"  {book} {ch}:{vs} — Erro: {e}")

print("\n" + "=" * 70)
print("FASE 2 — FTS5")
print("=" * 70)

# Verificar tabela FTS5
fts_tables = [t for t in tables if 'fts' in t.lower()]
print(f"Tabelas FTS: {fts_tables}")

for ft in fts_tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM {ft}")
        count = cur.fetchone()[0]
        print(f"\n{ft}: {count} registros")
    except Exception as e:
        print(f"\n{ft}: Erro ao contar: {e}")

    # Schema FTS
    cur.execute(f"PRAGMA table_info({ft})")
    cols = cur.fetchall()
    print(f"Colunas FTS: {[c[1] for c in cols]}")

# Testar buscas FTS5
test_phrases = [
    "vale da sombra da morte",
    "tudo posso naquele que me fortalece",
    "todas as coisas cooperam para o bem",
    "fé é a certeza das coisas que se esperam",
    "deus amou o mundo",
]

for ft in fts_tables:
    print(f"\n--- Buscas em {ft} ---")
    for phrase in test_phrases:
        # Tentar MATCH direto
        try:
            sql = f"SELECT book, chapter, verse, bm25({ft}) as score FROM {ft} WHERE {ft} MATCH ? ORDER BY score LIMIT 3"
            cur.execute(sql, (phrase,))
            rows = cur.fetchall()
            if rows:
                print(f"\n  '{phrase}' → {len(rows)} resultados:")
                for r in rows:
                    print(f"    {r[0]} {r[1]}:{r[2]} score={r[3]:.4f}")
            else:
                print(f"\n  '{phrase}' → 0 resultados (MATCH)")
        except Exception as e:
            print(f"\n  '{phrase}' → Erro MATCH: {e}")

        # Tentar com tokens individuais
        try:
            tokens = phrase.split()
            token_query = " OR ".join(tokens)
            sql = f"SELECT book, chapter, verse, bm25({ft}) as score FROM {ft} WHERE {ft} MATCH ? ORDER BY score LIMIT 3"
            cur.execute(sql, (token_query,))
            rows = cur.fetchall()
            if rows:
                print(f"  (OR tokens) → {len(rows)} resultados: {rows[0][0]} {rows[0][1]}:{rows[0][2]}")
            else:
                print(f"  (OR tokens) → 0 resultados")
        except Exception as e:
            print(f"  (OR tokens) → Erro: {e}")

# Verificar tokenizer
print("\n--- Tokenizer FTS5 ---")
for ft in fts_tables:
    try:
        cur.execute(f"SELECT sql FROM sqlite_master WHERE name='{ft}'")
        sql_def = cur.fetchone()
        if sql_def:
            print(f"  {ft}: {sql_def[0]}")
    except:
        pass

# Verificar se há versículos com as frases (busca LIKE)
print("\n--- Busca LIKE (controle) ---")
for phrase in test_phrases:
    # Remover acentos para busca
    import unicodedata
    normalized = ''.join(c for c in unicodedata.normalize('NFD', phrase) if unicodedata.category(c) != 'Mn')
    try:
        cur.execute(
            "SELECT book, chapter, verse, substr(text, 1, 80) FROM verses "
            "WHERE text LIKE ? LIMIT 3",
            (f"%{phrase}%",)
        )
        rows = cur.fetchall()
        if rows:
            print(f"  '{phrase}' → {len(rows)} resultados LIKE:")
            for r in rows:
                print(f"    {r[0]} {r[1]}:{r[2]} — {r[3]}...")
        else:
            # Tentar sem acentos
            cur.execute(
                "SELECT book, chapter, verse, substr(text, 1, 80) FROM verses "
                "WHERE text LIKE ? LIMIT 3",
                (f"%{normalized}%",)
            )
            rows = cur.fetchall()
            if rows:
                print(f"  '{phrase}' (sem acento) → {len(rows)} resultados LIKE:")
                for r in rows:
                    print(f"    {r[0]} {r[1]}:{r[2]} — {r[3]}...")
            else:
                print(f"  '{phrase}' → 0 resultados LIKE (mesmo sem acento)")
    except Exception as e:
        print(f"  '{phrase}' → Erro LIKE: {e}")

print("\n" + "=" * 70)
print("FASE 3 — Embeddings")
print("=" * 70)
print(f"Arquivo: {EMB}")
print(f"Existe: {os.path.exists(EMB)}")
if os.path.exists(EMB):
    import numpy as np
    arr = np.load(EMB)
    print(f"Shape: {arr.shape}")
    print(f"Dtype: {arr.dtype}")
else:
    print("EMBEDDINGS NÃO EXISTEM — busca semântica não disponível!")

conn.close()
print("\n=== DIAGNÓSTICO COMPLETO ===")
