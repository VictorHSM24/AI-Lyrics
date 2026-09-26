"""Gramática determinística de referências bíblicas FALADAS (PT-BR).

Opera sobre tokens já normalizados pelo ``Normalizer`` em modo fala
(``protect_function_words=True``) e é pura: sem estado, sem EventBus.
O ``IncrementalBiblicalParser`` re-executa esta gramática sobre a
janela acumulada da utterance a cada chunk committed — o que elimina
a dependência de fronteiras de chunk (antes, "vinte | e três" virava
20:3 e "versículo | um" perdia o marcador).

Política (precisão > recall — nunca apresentar versículo errado):

1. Livro — só aliases "faláveis": nome canônico PT, formas compostas
   PT ("carta aos romanos", "primeira de joão") e poucas variantes
   faladas ("salmo", "cantares"). Abreviações digitadas ("rom",
   "mar", "jud"), nomes ingleses ("jude", "revelation") e aliases
   numéricos gerados por romanos ("mc" → 1100) NUNCA casam em fala.
   Aliases que são vocabulário comum ("atos", "números", "juiz"...)
   ficam num tier restrito (sem artigo antes; exigem marcador ou par
   capítulo+versículo).
2. Capítulo — marcado ("capítulo N", até ``MAX_MARKER_GAP`` palavras
   após o livro) ou número IMEDIATAMENTE após o livro. "Daniel orava
   três vezes" não é Daniel 3.
3. Versículo — marcado ("versículo N"), "do N" ("Atos 2 do 40 ao 47")
   ou número imediatamente após o capítulo ("João 3 16").
4. Limites canônicos — capítulo/versículo fora do cânon invalidam a
   leitura (Amós 19:99 nunca é emitido).
"""

from __future__ import annotations

from dataclasses import dataclass

from parser.books import Book, ParserBookTable
from parser.canon import CanonBounds
from parser.normalizer import Normalizer

__all__ = [
    "BookMention",
    "RefParse",
    "SpeechBookMatcher",
    "parse_mention",
    "parse_continuation",
    "number_token",
    "SINGLE_CHAPTER_BOOKS",
]

CHAPTER_MARKERS = frozenset({"capitulo", "capitulos", "cap"})
VERSE_MARKERS = frozenset({"versiculo", "versiculos", "verso", "versos", "vers", "v"})
RANGE_MARKERS = frozenset({"ao", "a", "ate"})
RANGE_FILLERS = frozenset({"o", "versiculo", "verso"})
RANGE_START_MARKERS = frozenset({"do", "de"})

# Máximo de palavras entre o fim do livro e "capítulo" ("Gênesis, vamos
# abrir no capítulo 1" = 4). Marcador é evidência forte de citação.
MAX_MARKER_GAP = 8
# Máximo de palavras entre o número do capítulo e "versículo".
MAX_VERSE_MARKER_GAP = 6
# Continuação cross-utterance ("Primeira Coríntios" [pausa] "capítulo
# 14...") precisa começar logo no início da nova fala.
MAX_CARRY_LEAD = 2

# Livros de capítulo único: "Judas 9" = 1:9. Obadias, Filemom, 2/3 João, Judas.
SINGLE_CHAPTER_BOOKS = frozenset({31, 57, 63, 64, 65})

_ORDINAL_PREFIX = {
    "1": 1, "2": 2, "3": 3,
    "primeiro": 1, "primeira": 1, "segundo": 2, "segunda": 2,
    "terceiro": 3, "terceira": 3,
}
_ORDINAL_FILLERS = frozenset({"de", "da", "do", "aos", "a", "carta", "epistola", "livro", "o"})
_NUMERIC_CONTEXT = CHAPTER_MARKERS | VERSE_MARKERS | RANGE_MARKERS | {"e"}

# Palavras que podem compor aliases compostas faláveis (além dos tokens
# dos nomes canônicos).
_ALIAS_FUNCTION_TOKENS = frozenset({
    "carta", "aos", "a", "de", "epistola", "evangelho", "sao", "livro",
    "do", "dos", "o", "moises", "apostolos", "cantico", "canticos",
    "segundo",
})

# Variantes faladas de palavra única além do canônico.
_SPEECH_SINGLE_EXTRA = frozenset({
    "salmo", "cantares", "abdias", "filemao", "lamentacao", "proverbio",
})

# Aliases extras só de fala (não existem no books.json).
# "Evangelho segundo João" = João (não 2 João!).
_SPEECH_EXTRA_ALIASES: dict[str, int] = {
    "evangelho segundo mateus": 40, "evangelho de mateus": 40,
    "evangelho segundo marcos": 41, "evangelho de marcos": 41,
    "evangelho segundo lucas": 42, "evangelho de lucas": 42,
    "evangelho segundo joao": 43,
    "cantico dos canticos": 22,
    # Placeholder produzido por SpeechBookMatcher.preprocess_raw para
    # "Jó" (sem acento colide com "jo" → João).
    "jo_livro": 18,
}

# Aliases que também são vocabulário comum de pregação.
_COMMON_WORD_ALIASES = frozenset({
    "atos", "numeros", "exodo", "juizes", "lamentacoes", "lamentacao",
    "canticos", "cantares", "proverbio", "proverbios",
})
# Determinantes que tornam uma palavra comum narrativa ("os nossos atos",
# "os números", "um provérbio"). Contrações ("no", "do") NÃO entram:
# "no livro de Números" é citação.
_DETERMINERS = frozenset({
    "o", "os", "a", "as", "um", "uma", "uns", "umas", "meu", "meus",
    "minha", "minhas", "teu", "teus", "seu", "seus", "sua", "suas",
    "nosso", "nossos", "nossa", "nossas", "esse", "esses", "essa",
    "essas", "este", "estes", "esta", "estas", "aquele", "aqueles",
    "todos", "todas", "bons", "maus", "grandes",
})

_NORM = Normalizer(protect_function_words=True)


def is_num(tok: str) -> bool:
    return tok.isdigit() and 1 <= int(tok) <= 200


def number_token(tok: str) -> int | None:
    """Número após marcador: dígito, extenso ou ordinal ("capítulo um")."""
    if tok.isdigit():
        return int(tok)
    val = _NORM.ordinal_to_int(tok)
    if val is not None:
        return val
    return _NORM.extenso_to_digit(tok)


@dataclass(frozen=True)
class BookMention:
    book: Book
    alias: str
    start: int          # índice do 1º token
    end: int            # índice após o último token
    confidence: float   # 1.0 alias única; 0.5 ambígua
    common_word: bool   # alias é vocabulário comum (tier restrito)


@dataclass(frozen=True)
class RefParse:
    """Resultado da gramática para uma menção/continuação."""

    book: Book
    confidence: float
    chapter: int | None = None
    verse: int | None = None
    verse_end: int | None = None
    end: int = 0             # índice após o último token consumido
    open: bool = False       # ainda pode completar com mais tokens
    rejected: str = ""       # motivo se invalidado (fora do cânon etc.)

    @property
    def completeness(self) -> str:
        if self.verse is not None:
            return "verse"
        if self.chapter is not None:
            return "chapter"
        return "book"


# ---------------------------------------------------------------------------
# Matcher de livros (índice por tokens)
# ---------------------------------------------------------------------------


class SpeechBookMatcher:
    """Encontra menções de livros em tokens normalizados de fala."""

    def __init__(self, books: ParserBookTable) -> None:
        self._books = books
        by_id = {b.id: b for b in books.all_books()}
        canon_norm = {b.id: _NORM.normalize(b.canonical) for b in by_id.values()}
        vocab = set(_ALIAS_FUNCTION_TOKENS)
        for name in canon_norm.values():
            vocab.update(t for t in name.split() if not t.isdigit())

        # plain: 1º token → [(tokens, book, alias, conf, common)] (maior 1º)
        # numbered: (n, 1º token do resto) → [(resto, book, alias, conf)]
        self._plain: dict[str, list[tuple[tuple[str, ...], Book, str, float, bool]]] = {}
        self._numbered: dict[tuple[int, str], list[tuple[tuple[str, ...], Book, str, float]]] = {}

        entries = [(n, b, o, amb) for n, b, o, amb in books.alias_entries()]
        entries += [(a, by_id[i], a, False) for a, i in _SPEECH_EXTRA_ALIASES.items()]
        seen: set[tuple[str, int]] = set()
        for norm, book, orig, amb in entries:
            toks = tuple(norm.split())
            if not toks or (norm, book.id) in seen:
                continue
            if not self._eligible(toks, norm, book, canon_norm, vocab):
                continue
            seen.add((norm, book.id))
            conf = 0.5 if amb else 1.0
            if toks[0].isdigit():
                n = int(toks[0])
                if n in (1, 2, 3) and len(toks) >= 2:
                    self._numbered.setdefault((n, toks[1]), []).append(
                        (toks[1:], book, orig, conf))
                continue
            self._plain.setdefault(toks[0], []).append(
                (toks, book, orig, conf, norm in _COMMON_WORD_ALIASES))
        for lst in self._plain.values():
            lst.sort(key=lambda e: len(e[0]), reverse=True)
        for lst in self._numbered.values():
            lst.sort(key=lambda e: len(e[0]), reverse=True)

    @staticmethod
    def _eligible(toks, norm, book, canon_norm, vocab) -> bool:
        if norm in _SPEECH_EXTRA_ALIASES:
            return True
        if all(t.isdigit() for t in toks):
            return False  # "mc" → "1100" etc. (numeral romano)
        if len(toks) == 1:
            if norm == canon_norm[book.id]:
                return len(norm) >= 3
            return norm in _SPEECH_SINGLE_EXTRA
        return all(t.isdigit() or t in vocab for t in toks) and any(
            len(t) >= 4 and t not in _ALIAS_FUNCTION_TOKENS for t in toks)

    @staticmethod
    def preprocess_raw(raw_tokens: list[str]) -> list[str]:
        """Ajustes em tokens CRUS antes da normalização.

        "Jó" perde o acento na normalização e colide com "jo" (João);
        preservamos a identidade como placeholder "jo_livro".
        """
        out = []
        for t in raw_tokens:
            bare = t.strip(".,;:!?\"'()").lower()
            out.append("jo_livro" if bare == "jó" else t)
        return out

    def eligible_aliases(self) -> list[tuple[str, str]]:
        """(alias, livro) aceitos em fala — diagnóstico/testes."""
        out = [(" ".join(t), b.canonical) for lst in self._plain.values() for t, b, *_ in lst]
        out += [(f"{n} " + " ".join(t), b.canonical)
                for (n, _), lst in self._numbered.items() for t, b, *_ in lst]
        return sorted(out)

    def find(self, tokens: list[str], start: int = 0, end: int | None = None) -> list[BookMention]:
        """Menções de livro não sobrepostas em ``tokens[start:end]``."""
        end = len(tokens) if end is None else end
        out: list[BookMention] = []
        i = start
        while i < end:
            m = self._match_at(tokens, i, end)
            if m is None:
                i += 1
                continue
            out.append(m)
            i = m.end
        return out

    def _match_at(self, tokens: list[str], i: int, end: int) -> BookMention | None:
        tok = tokens[i]
        n = _ORDINAL_PREFIX.get(tok)
        if n is not None and not (tok.isdigit() and i > 0 and (
                tokens[i - 1] in _NUMERIC_CONTEXT or tokens[i - 1].isdigit())):
            j = i + 1
            skipped = 0
            while j < end and tokens[j] in _ORDINAL_FILLERS and skipped < 3:
                if (n, tokens[j]) in self._numbered:
                    break
                j += 1
                skipped += 1
            if j < end:
                for rest, book, alias, conf in self._numbered.get((n, tokens[j]), []):
                    if tuple(tokens[j:j + len(rest)]) == rest and j + len(rest) <= end:
                        return BookMention(book, alias, i, j + len(rest), conf, False)
        for toks, book, alias, conf, common in self._plain.get(tok, []):
            k = i + len(toks)
            if k > end or tuple(tokens[i:k]) != toks:
                continue
            if common and i > 0 and tokens[i - 1] in _DETERMINERS:
                return None  # "os nossos atos", "um provérbio"
            return BookMention(book, alias, i, k, conf, common)
        return None


# ---------------------------------------------------------------------------
# Gramática capítulo / versículo / intervalo
# ---------------------------------------------------------------------------


def _find_verse(tokens: list[str], k: int, limit: int) -> tuple[int | None, int, bool]:
    """Versículo a partir de ``k`` (logo após o capítulo).

    Returns (verse, pos_do_número, marcador_pendente). marcador_pendente
    indica "versículo" no fim sem número ainda (pode chegar no próximo chunk).
    """
    if k >= limit:
        return None, -1, False
    if is_num(tokens[k]):
        return int(tokens[k]), k, False
    if tokens[k] in RANGE_START_MARKERS and k + 1 < limit and is_num(tokens[k + 1]):
        return int(tokens[k + 1]), k + 1, False
    for j in range(k, min(k + MAX_VERSE_MARKER_GAP + 1, limit)):
        if tokens[j] in CHAPTER_MARKERS:
            break
        if tokens[j] in VERSE_MARKERS:
            if j + 1 >= limit:
                return None, -1, True
            num = number_token(tokens[j + 1])
            return (num, j + 1, False) if num else (None, -1, False)
    return None, -1, False


def _find_range_end(tokens: list[str], v_pos: int, verse: int, limit: int) -> tuple[int | None, int]:
    r = v_pos + 1
    if r >= limit:
        return None, v_pos
    if tokens[r] in RANGE_MARKERS:
        j = r + 1
        while j < limit and j - r <= 2 and tokens[j] in RANGE_FILLERS:
            j += 1
        if j < limit:
            end = number_token(tokens[j])
            if end is not None and end > verse:
                return end, j
    elif tokens[r] == "e" and r + 1 < limit and tokens[r + 1].isdigit() \
            and int(tokens[r + 1]) == verse + 1:
        return verse + 1, r + 1
    return None, v_pos


def _finish(book: Book, conf: float, bounds: CanonBounds, tokens: list[str],
            limit: int, final: bool, ch: int | None, ch_pos: int,
            verse: int | None, v_pos: int, pending_marker: bool,
            base_end: int, *, require_pair: bool = False) -> RefParse:
    """Valida limites, busca intervalo e decide se a leitura está aberta."""
    at_tail = limit == len(tokens) and not final
    if ch is not None and not bounds.valid_chapter(book.id, ch):
        return RefParse(book, conf, end=ch_pos + 1, rejected="chapter_out_of_bounds")
    if verse is not None and not bounds.valid_verse(book.id, ch, verse):
        return RefParse(book, conf, chapter=ch, end=v_pos + 1,
                        rejected="verse_out_of_bounds")
    if verse is not None:
        verse_end, last = _find_range_end(tokens, v_pos, verse, limit)
        if verse_end is not None and not bounds.valid_verse(book.id, ch, verse_end):
            verse_end, last = None, v_pos
        return RefParse(book, conf, ch, verse, verse_end, end=last + 1)
    if ch is not None:
        if require_pair and not at_tail:
            # Tier comum ("atos 2 mil anos"): capítulo sem versículo não vale.
            return RefParse(book, conf, end=ch_pos + 1, rejected="common_word_unpaired")
        is_open = at_tail and (pending_marker or len(tokens) - 1 - ch_pos <= MAX_VERSE_MARKER_GAP)
        return RefParse(book, conf, chapter=None if require_pair else ch,
                        end=ch_pos + 1, open=is_open)
    is_open = at_tail and (pending_marker or len(tokens) - base_end <= MAX_MARKER_GAP)
    return RefParse(book, conf, end=base_end, open=is_open)


def parse_mention(tokens: list[str], m: BookMention, limit: int,
                  bounds: CanonBounds, final: bool = False) -> RefParse:
    """Lê capítulo/versículo/intervalo após a menção ``m``.

    ``limit`` = início da próxima menção (ou ``len(tokens)``): números
    depois de outro livro pertencem a ele. ``final`` = fim da utterance.
    """
    book, conf, i = m.book, m.confidence, m.end
    single = book.id in SINGLE_CHAPTER_BOOKS
    ch = verse = None
    ch_pos = v_pos = -1
    marked = pending = False

    for j in range(i, min(i + MAX_MARKER_GAP + 1, limit)):
        tok = tokens[j]
        if tok in CHAPTER_MARKERS or (single and tok in VERSE_MARKERS):
            if j + 1 >= limit:
                pending = True
                break
            num = number_token(tokens[j + 1])
            if num is None:
                break
            marked = True
            if tok in CHAPTER_MARKERS:
                ch, ch_pos = num, j + 1
            else:
                ch, ch_pos, verse, v_pos = 1, j + 1, num, j + 1
            break
        if is_num(tok) and j > i:
            break  # número solto no meio: narrativa, não citação

    if ch is None and not pending and i < limit and is_num(tokens[i]):
        n = int(tokens[i])
        if single:
            if n == 1 and i + 1 < limit and is_num(tokens[i + 1]):
                ch, ch_pos, verse, v_pos = 1, i, int(tokens[i + 1]), i + 1
            else:
                ch, ch_pos, verse, v_pos = 1, i, n, i
        else:
            ch, ch_pos = n, i

    vpending = False
    if ch is not None and verse is None:
        verse, v_pos, vpending = _find_verse(tokens, ch_pos + 1, limit)
    return _finish(book, conf, bounds, tokens, limit, final, ch, ch_pos,
                   verse, v_pos, pending or vpending, i,
                   require_pair=m.common_word and not marked)


def parse_continuation(tokens: list[str], start: int, limit: int,
                       book: Book, conf: float, chapter: int | None,
                       bounds: CanonBounds, *, lead: int | None,
                       final: bool = False) -> RefParse | None:
    """Continuação sem nome do livro (contexto já conhecido).

    Usado para (a) correções após detecção na mesma utterance
    ("versículo 4", "capítulo 5") — ``lead=None``, qualquer posição;
    (b) continuação cross-utterance após pausa ("Primeira Coríntios"
    [pausa] "capítulo 14, versículo 10") — ``lead=MAX_CARRY_LEAD``, só
    no início da fala. Só aceita marcadores explícitos ou o par
    compacto "N M" (ex.: "10:27"); nunca um número solto.
    """
    scan_end = limit if lead is None else min(limit, start + lead + 1)
    for j in range(start, scan_end):
        tok = tokens[j]
        num = number_token(tokens[j + 1]) if j + 1 < limit else None
        if tok in CHAPTER_MARKERS and num is not None:
            verse, v_pos, vpend = _find_verse(tokens, j + 2, limit)
            return _finish(book, conf, bounds, tokens, limit, final, num, j + 1,
                           verse, v_pos, vpend, j + 2)
        if tok in VERSE_MARKERS and chapter is not None and num is not None:
            return _finish(book, conf, bounds, tokens, limit, final, chapter, j,
                           num, j + 1, False, j + 2)
        if (lead is not None and chapter is None and is_num(tok)
                and j + 1 < limit and is_num(tokens[j + 1])):
            return _finish(book, conf, bounds, tokens, limit, final, int(tok), j,
                           int(tokens[j + 1]), j + 1, False, j + 2)
        if lead is not None and (is_num(tok) or tok in VERSE_MARKERS):
            return None
    return None
