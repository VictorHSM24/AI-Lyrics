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
    print(f"\n=== {f} ===")
    print(f"tables: {tables}")
    for t in tables:
        cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}'")
        schema = cur.fetchone()
        if schema:
            print(f"schema [{t}]: {schema[0]}")
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"rows [{t}]: {count}")
        cur.execute(f"SELECT * FROM {t} LIMIT 2")
        cols = [d[0] for d in cur.description]
        print(f"cols [{t}]: {cols}")
        for row in cur.fetchall():
            print(f"  sample: {row}")
    c.close()
