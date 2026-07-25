import sqlite3

c = sqlite3.connect('data/sources/ACF.sqlite')
cur = c.cursor()
cur.execute("SELECT name FROM book WHERE id=1")
row = cur.fetchone()
name = row[0]
print(f"name repr: {name!r}")
print(f"name bytes: {name.encode('utf-8')!r}")
# Tentar decodificar como cp1252
try:
    # Se foi lido como utf-8 mas é cp1252, encode utf-8 e decode cp1252
    redecoded = name.encode('utf-8').decode('cp1252')
    print(f"utf-8 -> cp1252: {redecoded!r}")
except Exception as e:
    print(f"utf-8 -> cp1252 failed: {e}")
# Tentar latin1
try:
    redecoded = name.encode('utf-8').decode('latin1')
    print(f"utf-8 -> latin1: {redecoded!r}")
except Exception as e:
    print(f"utf-8 -> latin1 failed: {e}")
# Verificar bytes raw
cur.execute("SELECT CAST(name AS BLOB) FROM book WHERE id=1")
row = cur.fetchone()
print(f"raw bytes: {row[0]!r}")
c.close()
