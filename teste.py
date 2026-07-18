import sqlite3

conn = sqlite3.connect("ACF.sqlite")

cur = conn.cursor()

print(cur.execute(
    "SELECT COUNT(DISTINCT book_id) FROM verse"
).fetchone())

print(cur.execute(
    "SELECT MAX(chapter) FROM verse WHERE book_id = 1"
).fetchone())

conn.close()