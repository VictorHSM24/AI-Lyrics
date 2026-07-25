"""Diagnóstico: classificar frases pelo Parser para entender none vs uncertain."""
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config import load_books
from parser import Parser, ParserBookTable

books_path = str(_PROJECT_ROOT / "config" / "books.json")
book_table = load_books(books_path)
all_books = book_table.all_books()
parser = Parser(ParserBookTable(all_books))

cases = [
    "vale da sombra da morte",
    "todas as coisas cooperam para o bem daqueles que amam a Deus",
    "a fé é a certeza das coisas que se esperam",
    "boa noite igreja",
    "amém irmãos",
    # Casos que funcionam (uncertain) para comparação:
    "aquele texto que diz que todas as coisas cooperam para o bem",
    "o versículo sobre a fé ser a certeza das coisas que se esperam",
    "o salmo do vale da sombra da morte",
    "abre aquele texto que fala de deus amou o mundo",
    "vamos abrir o salmo do vale da sombra da morte",
]

print(f"{'Frase':<70} {'action':<12} {'conf':>5} {'source':<8}")
print("-" * 100)
for text in cases:
    intent = parser.parse(text)
    print(f"{text:<70} {intent.action:<12} {intent.confidence:>5.2f} {intent.source:<8}")

# Analisar gatilhos
print("\n\nAnalise de gatilhos:")
_COMMAND_TRIGGERS = {"abre", "abrir", "abreai", "abra", "abrirai",
    "mostra", "mostrar", "mostre", "mostrai",
    "exibe", "exibir", "exibai",
    "vamos", "vamo", "va"}
_INDIRECT_TRIGGERS = {"aquele", "aquela", "aqueles", "aquelas",
    "versiculo", "texto", "passagem", "trecho", "passagem"}

from parser.normalizer import Normalizer
norm = Normalizer()

print(f"\n{'Frase':<70} {'normalizada':<70} {'triggers'}")
print("-" * 160)
for text in cases:
    n = norm.normalize(text)
    tokens = set(n.split()) if n else set()
    cmd = tokens & _COMMAND_TRIGGERS
    ind = tokens & _INDIRECT_TRIGGERS
    triggers = []
    if cmd:
        triggers.append(f"cmd={cmd}")
    if ind:
        triggers.append(f"indirect={ind}")
    if not triggers:
        triggers.append("NENHUM")
    print(f"{text:<70} {n:<70} {', '.join(triggers)}")
