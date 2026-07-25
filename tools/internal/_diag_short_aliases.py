import json
books = json.load(open('config/books.json', encoding='utf-8'))
with open('_diag_short_aliases.txt', 'w', encoding='utf-8') as f:
    for b in books:
        short = [a for a in b.get('aliases', []) if len(a) <= 2]
        if short:
            f.write(f"{b['canonical']} (id={b['id']}): {short}\n")
print('done')
