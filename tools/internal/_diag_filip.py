import sqlite3, sys
sys.path.insert(0, '.')
conn = sqlite3.connect('data/bible.pt-br.sqlite')
cur = conn.cursor()
cur.execute("SELECT c0, c1, c2, c4, c3 FROM verses_content WHERE c0 LIKE 'Filip%' AND CAST(c1 AS INTEGER)=4 AND CAST(c2 AS INTEGER)=13")
for r in cur.fetchall():
    print(f"{r[0]} {r[1]}:{r[2]} ({r[3]})")
    print(f"  {r[4]}")
conn.close()
