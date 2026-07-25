import sqlite3
import os

sources_dir = 'data/sources'
for f in sorted(os.listdir(sources_dir)):
    if not f.endswith('.sqlite'):
        continue
    path = os.path.join(sources_dir, f)
    c = sqlite3.connect(path)
    cur = c.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    has_fts = any('fts' in t.lower() for t in tables)
    print(f"{f}: tables={tables}, has_fts={has_fts}")
    # Verificar encoding dos nomes dos livros
    cur.execute("SELECT id, book_reference_id, name FROM book ORDER BY id LIMIT 5")
    for row in cur.fetchall():
        print(f"  book id={row[0]} ref_id={row[1]} name={row[2]!r}")
    # Verificar Números 6:24
    cur.execute("""
        SELECT v.book_id, v.chapter, v.verse, v.text, b.name, b.book_reference_id
        FROM verse v JOIN book b ON v.book_id = b.id
        WHERE b.book_reference_id = 4 AND v.chapter = 6 AND v.verse = 24
    """)
    row = cur.fetchone()
    if row:
        print(f"  Num 6:24: book_name={row[4]!r} text={row[3]!r}")
    c.close()
