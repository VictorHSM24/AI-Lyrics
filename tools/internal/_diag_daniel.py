import sys
sys.path.insert(0, '.')
from config import load_books
from parser.normalizer import Normalizer
from parser import ParserBookTable

norm = Normalizer()
books_path = 'config/books.json'
book_table = load_books(books_path)
all_books = book_table.all_books()
pbt = ParserBookTable(all_books)

text = 'vale da sombra da morte'
n = norm.normalize(text)
r = pbt.resolve(n)
with open('_diag_daniel.txt', 'w', encoding='utf-8') as f:
    f.write(f'text={text}\n')
    f.write(f'norm={n}\n')
    f.write(f'book={r.book.canonical} id={r.book.id} conf={r.confidence}\n')
    f.write(f'start={r.start} end={r.end}\n')
    f.write(f'matched="{n[r.start:r.end]}"\n')
    f.write(f'prefix="{n[:r.start]}"\n')
    f.write(f'suffix="{n[r.end:]}"\n')
print('done')
