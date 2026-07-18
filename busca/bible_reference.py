"""BibleReference — representação canônica de referências bíblicas.

Define:
  - BibleBook: identificador canônico para os 66 livros da Bíblia.
  - BibleReference: DTO imutável representando uma referência bíblica.
  - parse_bible_reference: parser de string → BibleReference.

Esta é a representação canônica que será utilizada por todas as próximas
fases (Context Memory, Feedback, Graph Traversal, Recommendation, etc.).

Design:
  - BibleBook é um enum int (1..66) com nomes canônicos e aliases.
  - BibleReference é frozen (imutável), hashable, ordenável.
  - O parser não lança exceções — retorna None quando inválido.
  - Suporta: capítulo apenas, versículo único, intervalo de versículos.
  - Normalização: lowercase, sem acentos, abreviações, numerais romanos.

Compatibilidade:
  - O JSON da Knowledge Base NÃO muda (continua com strings).
  - A conversão string → BibleReference acontece no carregamento.
  - BibleReference.to_string() produz a string de exibição.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Tuple


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Normaliza texto: lowercase, sem diacritics, whitespace único."""
    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


# ---------------------------------------------------------------------------
# BibleBook — identificador canônico (1..66)
# ---------------------------------------------------------------------------


class BibleBook(IntEnum):
    """Identificador canônico para os 66 livros da Bíblia.

    O valor int (1..66) segue a ordem canônica padrão.
    Novos livros não podem ser adicionados (a Bíblia é fechada).

    Métodos:
        canonical_name: nome canônico PT-BR (ex.: "João", "1 Coríntios").
        aliases: lista de aliases para matching.
        from_name: resolve string (nome/abreviação) → BibleBook.
    """

    GENESIS = 1
    EXODO = 2
    LEVITICO = 3
    NUMEROS = 4
    DEUTERONOMIO = 5
    JOSUE = 6
    JUIZES = 7
    RUTE = 8
    PRIMEIRO_SAMUEL = 9
    SEGUNDO_SAMUEL = 10
    PRIMEIRO_REIS = 11
    SEGUNDO_REIS = 12
    PRIMEIRO_CRONICAS = 13
    SEGUNDO_CRONICAS = 14
    ESDRAS = 15
    NEEMIAS = 16
    ESTER = 17
    JO = 18
    SALMOS = 19
    PROVERBIOS = 20
    ECLESIASTES = 21
    CANTICOS = 22
    ISAIAS = 23
    JEREMIAS = 24
    LAMENTACOES = 25
    EZEQUIEL = 26
    DANIEL = 27
    OSEIAS = 28
    JOEL = 29
    AMOS = 30
    OBADIAS = 31
    JONAS = 32
    MIQUEIAS = 33
    NAUM = 34
    HABACUQUE = 35
    SOFONIAS = 36
    AGEU = 37
    ZACARIAS = 38
    MALAQUIAS = 39
    MATEUS = 40
    MARCOS = 41
    LUCAS = 42
    JOAO = 43
    ATOS = 44
    ROMANOS = 45
    PRIMEIRO_CORINTIOS = 46
    SEGUNDO_CORINTIOS = 47
    GALATAS = 48
    EFESIOS = 49
    FILIPENSES = 50
    COLOSSENSES = 51
    PRIMEIRO_TESSALONICENSES = 52
    SEGUNDO_TESSALONICENSES = 53
    PRIMEIRO_TIMOTEO = 54
    SEGUNDO_TIMOTEO = 55
    TITO = 56
    FILEMOM = 57
    HEBREUS = 58
    TIAGO = 59
    PRIMEIRO_PEDRO = 60
    SEGUNDO_PEDRO = 61
    PRIMEIRO_JOAO = 62
    SEGUNDO_JOAO = 63
    TERCEIRO_JOAO = 64
    JUDAS = 65
    APOCALIPSE = 66

    @property
    def canonical_name(self) -> str:
        """Nome canônico PT-BR (ex.: 'João', '1 Coríntios')."""
        return _BOOK_NAMES[self]

    @property
    def aliases(self) -> tuple[str, ...]:
        """Aliases para matching (normalizadas: lowercase, sem acentos)."""
        return _BOOK_ALIASES.get(self, ())

    @classmethod
    def from_name(cls, name: str) -> BibleBook | None:
        """Resolve string (nome/abreviação) → BibleBook.

        Aceita: nomes completos, abreviações, com/sem acentos,
        maiúsculas/minúsculas, numerais romanos (I, II, III).

        Args:
            name: nome ou abreviação do livro.

        Returns:
            BibleBook correspondente, ou None se não reconhecido.
        """
        if not name:
            return None
        norm = _normalize_text(name)
        if not norm:
            return None

        # Busca direta no índice de aliases
        book = _ALIAS_INDEX.get(norm)
        if book is not None:
            return book

        # Tentar com numeral romano → arábico
        converted = _convert_roman_to_arabic(norm)
        if converted != norm:
            book = _ALIAS_INDEX.get(converted)
            if book is not None:
                return book

        return None


# ---------------------------------------------------------------------------
# Tabelas de dados (nomes e aliases)
# ---------------------------------------------------------------------------


_BOOK_NAMES: dict[BibleBook, str] = {
    BibleBook.GENESIS: "Gênesis",
    BibleBook.EXODO: "Êxodo",
    BibleBook.LEVITICO: "Levítico",
    BibleBook.NUMEROS: "Números",
    BibleBook.DEUTERONOMIO: "Deuteronômio",
    BibleBook.JOSUE: "Josué",
    BibleBook.JUIZES: "Juízes",
    BibleBook.RUTE: "Rute",
    BibleBook.PRIMEIRO_SAMUEL: "1 Samuel",
    BibleBook.SEGUNDO_SAMUEL: "2 Samuel",
    BibleBook.PRIMEIRO_REIS: "1 Reis",
    BibleBook.SEGUNDO_REIS: "2 Reis",
    BibleBook.PRIMEIRO_CRONICAS: "1 Crônicas",
    BibleBook.SEGUNDO_CRONICAS: "2 Crônicas",
    BibleBook.ESDRAS: "Esdras",
    BibleBook.NEEMIAS: "Neemias",
    BibleBook.ESTER: "Ester",
    BibleBook.JO: "Jó",
    BibleBook.SALMOS: "Salmos",
    BibleBook.PROVERBIOS: "Provérbios",
    BibleBook.ECLESIASTES: "Eclesiastes",
    BibleBook.CANTICOS: "Cânticos",
    BibleBook.ISAIAS: "Isaías",
    BibleBook.JEREMIAS: "Jeremias",
    BibleBook.LAMENTACOES: "Lamentações",
    BibleBook.EZEQUIEL: "Ezequiel",
    BibleBook.DANIEL: "Daniel",
    BibleBook.OSEIAS: "Oséias",
    BibleBook.JOEL: "Joel",
    BibleBook.AMOS: "Amós",
    BibleBook.OBADIAS: "Obadias",
    BibleBook.JONAS: "Jonas",
    BibleBook.MIQUEIAS: "Miqueias",
    BibleBook.NAUM: "Naum",
    BibleBook.HABACUQUE: "Habacuque",
    BibleBook.SOFONIAS: "Sofonias",
    BibleBook.AGEU: "Ageu",
    BibleBook.ZACARIAS: "Zacarias",
    BibleBook.MALAQUIAS: "Malaquias",
    BibleBook.MATEUS: "Mateus",
    BibleBook.MARCOS: "Marcos",
    BibleBook.LUCAS: "Lucas",
    BibleBook.JOAO: "João",
    BibleBook.ATOS: "Atos",
    BibleBook.ROMANOS: "Romanos",
    BibleBook.PRIMEIRO_CORINTIOS: "1 Coríntios",
    BibleBook.SEGUNDO_CORINTIOS: "2 Coríntios",
    BibleBook.GALATAS: "Gálatas",
    BibleBook.EFESIOS: "Efésios",
    BibleBook.FILIPENSES: "Filipenses",
    BibleBook.COLOSSENSES: "Colossenses",
    BibleBook.PRIMEIRO_TESSALONICENSES: "1 Tessalonicenses",
    BibleBook.SEGUNDO_TESSALONICENSES: "2 Tessalonicenses",
    BibleBook.PRIMEIRO_TIMOTEO: "1 Timóteo",
    BibleBook.SEGUNDO_TIMOTEO: "2 Timóteo",
    BibleBook.TITO: "Tito",
    BibleBook.FILEMOM: "Filemom",
    BibleBook.HEBREUS: "Hebreus",
    BibleBook.TIAGO: "Tiago",
    BibleBook.PRIMEIRO_PEDRO: "1 Pedro",
    BibleBook.SEGUNDO_PEDRO: "2 Pedro",
    BibleBook.PRIMEIRO_JOAO: "1 João",
    BibleBook.SEGUNDO_JOAO: "2 João",
    BibleBook.TERCEIRO_JOAO: "3 João",
    BibleBook.JUDAS: "Judas",
    BibleBook.APOCALIPSE: "Apocalipse",
}


_BOOK_ALIASES: dict[BibleBook, tuple[str, ...]] = {
    BibleBook.GENESIS: ("genesis", "gn", "ge"),
    BibleBook.EXODO: ("exodo", "ex", "levidico"),
    BibleBook.LEVITICO: ("levitico", "lv", "le"),
    BibleBook.NUMEROS: ("numeros", "nm", "nu"),
    BibleBook.DEUTERONOMIO: ("deuteronomio", "dt", "de"),
    BibleBook.JOSUE: ("josue", "js", "jo"),
    BibleBook.JUIZES: ("juizes", "jz", "ju"),
    BibleBook.RUTE: ("rute", "rt", "ru"),
    BibleBook.PRIMEIRO_SAMUEL: ("1 samuel", "i samuel", "primeiro samuel", "1sm", "1 s"),
    BibleBook.SEGUNDO_SAMUEL: ("2 samuel", "ii samuel", "segundo samuel", "2sm", "2 s"),
    BibleBook.PRIMEIRO_REIS: ("1 reis", "i reis", "primeiro reis", "1rs", "1 r"),
    BibleBook.SEGUNDO_REIS: ("2 reis", "ii reis", "segundo reis", "2rs", "2 r"),
    BibleBook.PRIMEIRO_CRONICAS: ("1 cronicas", "i cronicas", "primeiro cronicas", "1cr", "1 c"),
    BibleBook.SEGUNDO_CRONICAS: ("2 cronicas", "ii cronicas", "segundo cronicas", "2cr", "2 c"),
    BibleBook.ESDRAS: ("esdras", "ed", "ezra"),
    BibleBook.NEEMIAS: ("neemias", "ne", "neh"),
    BibleBook.ESTER: ("ester", "et", "est"),
    BibleBook.JO: ("jo", "job"),
    BibleBook.SALMOS: ("salmos", "sl", "salmo", "sal"),
    BibleBook.PROVERBIOS: ("proverbios", "pv", "prov"),
    BibleBook.ECLESIASTES: ("eclesiastes", "ec", "ecclesiastes", "ecl"),
    BibleBook.CANTICOS: ("canticos", "ct", "cantares", "song"),
    BibleBook.ISAIAS: ("isaias", "is", "isa"),
    BibleBook.JEREMIAS: ("jeremias", "jr", "je", "jer"),
    BibleBook.LAMENTACOES: ("lamentacoes", "lm", "la", "lam"),
    BibleBook.EZEQUIEL: ("ezequiel", "ez", "ezk"),
    BibleBook.DANIEL: ("daniel", "dn", "dan", "da"),
    BibleBook.OSEIAS: ("oseias", "os", "hosea", "ho"),
    BibleBook.JOEL: ("joel", "jl", "joe"),
    BibleBook.AMOS: ("amos", "am", "amo"),
    BibleBook.OBADIAS: ("obadias", "ob", "abdias", "abd"),
    BibleBook.JONAS: ("jonas", "jn", "jon"),
    BibleBook.MIQUEIAS: ("miqueias", "mq", "mi", "mic"),
    BibleBook.NAUM: ("naum", "na", "nahum", "nahu"),
    BibleBook.HABACUQUE: ("habacuque", "hb", "ha", "hab"),
    BibleBook.SOFONIAS: ("sofonias", "sf", "so", "soph"),
    BibleBook.AGEU: ("ageu", "ag", "hag"),
    BibleBook.ZACARIAS: ("zacarias", "zc", "za", "zec"),
    BibleBook.MALAQUIAS: ("malaquias", "ml", "mal", "ma"),
    BibleBook.MATEUS: ("mateus", "mt", "mat"),
    BibleBook.MARCOS: ("marcos", "mc", "mar", "marc"),
    BibleBook.LUCAS: ("lucas", "lc", "lu", "luk"),
    BibleBook.JOAO: ("joao", "jo", "sao joao", "evangelho de joao", "john", "joh"),
    BibleBook.ATOS: ("atos", "at", "atos dos apostolos", "act"),
    BibleBook.ROMANOS: ("romanos", "rm", "ro", "rom"),
    BibleBook.PRIMEIRO_CORINTIOS: ("1 corintios", "i corintios", "primeiro corintios", "1co", "1 co"),
    BibleBook.SEGUNDO_CORINTIOS: ("2 corintios", "ii corintios", "segundo corintios", "2co", "2 co"),
    BibleBook.GALATAS: ("galatas", "gl", "ga", "gal"),
    BibleBook.EFESIOS: ("efesios", "ef", "ephesians", "eph"),
    BibleBook.FILIPENSES: ("filipenses", "fp", "fi", "phil"),
    BibleBook.COLOSSENSES: ("colossenses", "cl", "co", "col"),
    BibleBook.PRIMEIRO_TESSALONICENSES: ("1 tessalonicenses", "i tessalonicenses", "primeiro tessalonicenses", "1ts", "1 ts"),
    BibleBook.SEGUNDO_TESSALONICENSES: ("2 tessalonicenses", "ii tessalonicenses", "segundo tessalonicenses", "2ts", "2 ts"),
    BibleBook.PRIMEIRO_TIMOTEO: ("1 timoteo", "i timoteo", "primeiro timoteo", "1tm", "1 tm"),
    BibleBook.SEGUNDO_TIMOTEO: ("2 timoteo", "ii timoteo", "segundo timoteo", "2tm", "2 tm"),
    BibleBook.TITO: ("tito", "tt", "tit"),
    BibleBook.FILEMOM: ("filemom", "fm", "filemao", "phm"),
    BibleBook.HEBREUS: ("hebreus", "he", "hb", "heb"),
    BibleBook.TIAGO: ("tiago", "tg", "jas", "jam"),
    BibleBook.PRIMEIRO_PEDRO: ("1 pedro", "i pedro", "primeiro pedro", "1pe", "1 pe"),
    BibleBook.SEGUNDO_PEDRO: ("2 pedro", "ii pedro", "segundo pedro", "2pe", "2 pe"),
    BibleBook.PRIMEIRO_JOAO: ("1 joao", "i joao", "primeiro joao", "1jo", "1 jo"),
    BibleBook.SEGUNDO_JOAO: ("2 joao", "ii joao", "segundo joao", "2jo", "2 jo"),
    BibleBook.TERCEIRO_JOAO: ("3 joao", "iii joao", "terceiro joao", "3jo", "3 jo"),
    BibleBook.JUDAS: ("judas", "jd", "jud", "jude"),
    BibleBook.APOCALIPSE: ("apocalipse", "ap", "apoc", "rev", "revelation"),
}


# Construir índice reverso: alias normalizada → BibleBook
_ALIAS_INDEX: dict[str, BibleBook] = {}
for _book, _aliases in _BOOK_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_INDEX[_alias] = _book
    # Adicionar nome canônico normalizado também
    _canonical_norm = _normalize_text(_book.canonical_name)
    _ALIAS_INDEX[_canonical_norm] = _book


# ---------------------------------------------------------------------------
# Conversão de numerais romanos
# ---------------------------------------------------------------------------


_ROMAN_MAP: dict[str, str] = {
    "i ": "1 ",
    "ii ": "2 ",
    "iii ": "3 ",
    "i corintios": "1 corintios",
    "ii corintios": "2 corintios",
    "i samuel": "1 samuel",
    "ii samuel": "2 samuel",
    "i reis": "1 reis",
    "ii reis": "2 reis",
    "i cronicas": "1 cronicas",
    "ii cronicas": "2 cronicas",
    "i tessalonicenses": "1 tessalonicenses",
    "ii tessalonicenses": "2 tessalonicenses",
    "i timoteo": "1 timoteo",
    "ii timoteo": "2 timoteo",
    "i pedro": "1 pedro",
    "ii pedro": "2 pedro",
    "i joao": "1 joao",
    "ii joao": "2 joao",
    "iii joao": "3 joao",
}


def _convert_roman_to_arabic(text: str) -> str:
    """Converte numerais romanos no início de nomes de livros para arábicos.

    Ex.: "II Reis" → "2 Reis", "I João" → "1 João".
    """
    for roman, arabic in _ROMAN_MAP.items():
        if text.startswith(roman):
            return arabic + text[len(roman):]
    return text


# ---------------------------------------------------------------------------
# BibleReference — DTO imutável
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BibleReference:
    """Referência bíblica canônica (imutável, hashable, ordenável).

    Representa uma referência como "João 3:16", "Lucas 15", "Mateus 5:1-12".
    Todos os campos são opcionais exceto `book` e `chapter`.

    Atributos:
        book: BibleBook (enum 1..66). Obrigatório.
        book_id: int (1..66). Conveniência = int(book).
        chapter: número do capítulo. Obrigatório.
        verse_start: versículo inicial (None se capítulo inteiro).
        verse_end: versículo final (None se versículo único ou capítulo).
        version: versão bíblica (ex.: "ACF"). Opcional.
        display: string de exibição canônica (ex.: "João 3:16").
        is_range: True se verse_start != verse_end (intervalo).
        metadata: metadados extras para expansão futura.

    Properties:
        is_single_verse: True se verse_start == verse_end (versículo único).
        is_chapter: True se verse_start is None (capítulo inteiro).
        length: número de versículos no intervalo (1 se único, None se capítulo).

    Methods:
        to_string(): string de exibição ("João 3:16").
        to_dict(): serialização para dict.
        from_dict(): desserialização de dict.
        from_string(): parser de string → BibleReference.

    Ordering:
        BibleReference é ordenável: por book_id, depois chapter, depois verse_start.
        Permite sorted(), min(), max().

    Hashing:
        BibleReference é hashable (pode ser usado em set/dict keys).
        metadata é excluído do hash (não afeta identidade da referência).

    Example:
        >>> ref = BibleReference.from_string("João 3:16")
        >>> print(ref.book.canonical_name, ref.chapter, ref.verse_start)
        João 3 16
        >>> print(ref.to_string())
        João 3:16
        >>> ref2 = BibleReference.from_string("Lucas 15")
        >>> print(ref2.is_chapter)
        True
    """

    book: BibleBook
    chapter: int
    verse_start: int | None = None
    verse_end: int | None = None
    version: str = ""
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def book_id(self) -> int:
        """ID do livro (1..66). Conveniência = int(book)."""
        return int(self.book)

    @property
    def display(self) -> str:
        """String de exibição canônica (ex.: 'João 3:16', 'Lucas 15')."""
        return self.to_string()

    @property
    def is_range(self) -> bool:
        """True se é um intervalo de versículos (verse_start != verse_end)."""
        return (
            self.verse_start is not None
            and self.verse_end is not None
            and self.verse_start != self.verse_end
        )

    @property
    def is_single_verse(self) -> bool:
        """True se é um versículo único (verse_start == verse_end, não None)."""
        return (
            self.verse_start is not None
            and (self.verse_end is None or self.verse_end == self.verse_start)
        )

    @property
    def is_chapter(self) -> bool:
        """True se é capítulo inteiro (verse_start is None)."""
        return self.verse_start is None

    @property
    def length(self) -> int | None:
        """Número de versículos no intervalo.

        Returns:
            1 se versículo único, N se intervalo, None se capítulo inteiro.
        """
        if self.verse_start is None:
            return None
        if self.verse_end is None:
            return 1
        return self.verse_end - self.verse_start + 1

    @property
    def id(self) -> str:
        """Identificador canônico compacto (calculado dinamicamente).

        Formato: ``book_id:chapter[:verse_start[-verse_end]]``

        Exemplos:
            - "43:3"       → João 3 (capítulo)
            - "43:3:16"    → João 3:16 (versículo único)
            - "42:15:11-32"→ Lucas 15:11-32 (intervalo)
            - "1:1:1"      → Gênesis 1:1
            - "66:21"      → Apocalipse 21

        O ID é sempre derivado do estado atual do objeto — nunca é
        armazenado, garantindo consistência total. É somente leitura.

        Returns:
            String com o identificador canônico.
        """
        parts = [str(self.book_id), str(self.chapter)]
        if self.verse_start is not None:
            if self.verse_end is not None and self.verse_end != self.verse_start:
                parts.append(f"{self.verse_start}-{self.verse_end}")
            else:
                parts.append(str(self.verse_start))
        return ":".join(parts)

    def __hash__(self) -> int:
        """Hash baseado em book, chapter, verse_start, verse_end (sem metadata)."""
        return hash((self.book, self.chapter, self.verse_start, self.verse_end))

    def __lt__(self, other: BibleReference) -> bool:
        """Ordenação: por book_id, depois chapter, depois verse_start."""
        if not isinstance(other, BibleReference):
            return NotImplemented
        self_key = (self.book_id, self.chapter, self.verse_start or 0)
        other_key = (other.book_id, other.chapter, other.verse_start or 0)
        return self_key < other_key

    def to_string(self) -> str:
        """Converte para string de exibição canônica.

        Returns:
            'João 3:16' (versículo único)
            'Mateus 5:1-12' (intervalo)
            'Lucas 15' (capítulo inteiro)
        """
        name = self.book.canonical_name
        if self.verse_start is None:
            return f"{name} {self.chapter}"
        if self.verse_end is None or self.verse_end == self.verse_start:
            return f"{name} {self.chapter}:{self.verse_start}"
        return f"{name} {self.chapter}:{self.verse_start}-{self.verse_end}"

    def to_dict(self) -> dict[str, object]:
        """Serializa para dict (para JSON, persistência, etc.)."""
        return {
            "book_id": self.book_id,
            "book": self.book.canonical_name,
            "chapter": self.chapter,
            "verse_start": self.verse_start,
            "verse_end": self.verse_end,
            "version": self.version,
            "display": self.to_string(),
            "is_range": self.is_range,
            "is_chapter": self.is_chapter,
            "is_single_verse": self.is_single_verse,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BibleReference | None:
        """Desserializa de dict.

        Args:
            data: dict com campos book_id/book, chapter, verse_start, verse_end.

        Returns:
            BibleReference ou None se inválido.
        """
        try:
            # Resolver livro por book_id ou por nome
            book_id = data.get("book_id")
            book: BibleBook | None = None
            if book_id is not None:
                book = BibleBook(int(book_id))
            elif data.get("book"):
                book = BibleBook.from_name(str(data["book"]))

            if book is None:
                return None

            chapter = int(data.get("chapter", 0))
            if chapter <= 0:
                return None

            verse_start = data.get("verse_start")
            verse_end = data.get("verse_end")
            version = str(data.get("version", ""))

            return cls(
                book=book,
                chapter=chapter,
                verse_start=int(verse_start) if verse_start is not None else None,
                verse_end=int(verse_end) if verse_end is not None else None,
                version=version,
            )
        except (ValueError, TypeError, KeyError):
            return None

    @classmethod
    def from_string(cls, text: str) -> BibleReference | None:
        """Parser de string → BibleReference.

        Aceita:
            - "João 3:16" (versículo único)
            - "Lucas 15" (capítulo inteiro)
            - "Mateus 5:1-12" (intervalo)
            - "Salmo 23" (capítulo)
            - "1 Coríntios 13" (capítulo)
            - "II Reis 2" (numeral romano)
            - "1 João 4:8" (versículo único)
            - "Apocalipse 21" (capítulo)
            - "Gênesis 1:1" (versículo único)

        Não lança exceções. Retorna None se inválido.

        Args:
            text: string da referência bíblica.

        Returns:
            BibleReference ou None se não conseguir parsear.
        """
        return parse_bible_reference(text)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


# Regex para extrair capítulo e versículo(s) após o nome do livro.
# Grupos: 1=chapter, 2=verse_start (opcional), 3=verse_end (opcional)
_REF_PATTERN = re.compile(
    r"(\d+)"               # chapter (obrigatório)
    r"(?::(\d+))?"         # :verse_start (opcional)
    r"(?:-(\d+))?"         # -verse_end (opcional)
    r"\s*$"                # fim da string
)


def parse_bible_reference(text: str) -> BibleReference | None:
    """Parser de string → BibleReference.

    Não lança exceções. Retorna None se inválido.

    Args:
        text: string da referência (ex.: "João 3:16", "Lucas 15").

    Returns:
        BibleReference ou None.
    """
    if not text or not text.strip():
        return None

    normalized = _normalize_text(text)
    if not normalized:
        return None

    # Converter numerais romanos no início (II Reis → 2 Reis)
    normalized = _convert_roman_to_arabic(normalized)

    # Encontrar o padrão capítulo:versículo-versículo no final da string
    match = _REF_PATTERN.search(normalized)
    if not match:
        return None

    chapter_str, verse_start_str, verse_end_str = match.groups()
    chapter = int(chapter_str)
    if chapter <= 0:
        return None

    verse_start = int(verse_start_str) if verse_start_str else None
    verse_end = int(verse_end_str) if verse_end_str else None

    # Validar versículos
    if verse_start is not None and verse_start <= 0:
        return None
    if verse_end is not None and verse_end <= 0:
        return None
    if verse_end is not None and verse_start is not None and verse_end < verse_start:
        return None

    # Extrair nome do livro (tudo antes do capítulo)
    book_part = normalized[:match.start()].strip()
    if not book_part:
        return None

    # Resolver livro
    book = BibleBook.from_name(book_part)
    if book is None:
        return None

    return BibleReference(
        book=book,
        chapter=chapter,
        verse_start=verse_start,
        verse_end=verse_end,
    )


# ---------------------------------------------------------------------------
# Helpers para conversão em lote
# ---------------------------------------------------------------------------


def parse_references(strings: list[str]) -> list[BibleReference]:
    """Converte lista de strings para lista de BibleReference.

    Strings inválidas são silenciosamente ignoradas.

    Args:
        strings: lista de strings de referência.

    Returns:
        Lista de BibleReference (apenas válidas).
    """
    result: list[BibleReference] = []
    for s in strings:
        ref = parse_bible_reference(s)
        if ref is not None:
            result.append(ref)
    return result


def references_to_strings(refs: list[BibleReference]) -> list[str]:
    """Converte lista de BibleReference para lista de strings.

    Args:
        refs: lista de BibleReference.

    Returns:
        Lista de strings de exibição.
    """
    return [r.to_string() for r in refs]
