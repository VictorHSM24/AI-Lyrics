import sys
sys.path.insert(0, '.')
from parser import load_parser_books, Parser
parser = Parser(load_parser_books('config/books.json'))

cases_uncertain = [
    'vale da sombra da morte',
    'todas as coisas cooperam para o bem daqueles que amam a Deus',
    'a fe e a certeza das coisas que se esperam',
    'tudo posso naquele que me fortalece',
    'deus amou o mundo de tal maneira',
]
cases_none = [
    'boa noite igreja',
    'amen irmaos',
    'paz do senhor',
    'vamos cantar',
    'podem sentar',
    'vamos orar',
]
cases_ok = [
    'Joao 3:16',
    'Hebreus 11:1',
    'Romanos 8:28',
    'proximo',
    'anterior',
    'mais dois',
]

with open('_diag_result.txt', 'w', encoding='utf-8') as f:
    f.write('=== DEVE ser uncertain ===\n')
    for t in cases_uncertain:
        r = parser.parse(t)
        ok = 'OK' if r.action == 'uncertain' else 'FAIL'
        f.write(f'{t} | {r.action} | {r.confidence:.2f} | {ok}\n')
    f.write('\n=== DEVE ser none ===\n')
    for t in cases_none:
        r = parser.parse(t)
        ok = 'OK' if r.action == 'none' else 'FAIL'
        f.write(f'{t} | {r.action} | {r.confidence:.2f} | {ok}\n')
    f.write('\n=== DEVE continuar funcionando ===\n')
    for t in cases_ok:
        r = parser.parse(t)
        f.write(f'{t} | {r.action} | {r.confidence:.2f} | book={r.book} ch={r.chapter} v={r.verse}\n')
print('done')
