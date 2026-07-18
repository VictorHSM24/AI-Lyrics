"""Parser determinístico de comandos bíblicos PT-BR.

Interpreta comandos estruturados da fala transcrita **sem LLM**,
produzindo ``Intent`` com ``confidence`` (c_parser).

Pipeline (doc. técnica §3.2):
  1. Normalização (lowercase, diacritics, extenso→dígito, ordinais, romanos)
  2. Detecção de navegação (próximo, anterior, volta, mais, continua/ainda)
  3. Detecção de referência direta (livro + cap/vers com ou sem marcadores)
  4. Se nada casou: verificar gatilhos → uncertain (encaminha ao LLM)
  4b. Sem gatilhos: verificar pistas bíblicas → uncertain (busca semântica)
  5. Sem gatilho, sem pistas: action="none" (não é comando)

Confiança (doc. técnica §3.7):
  - REF com marcadores (cap/vers): 0.98
  - REF compacta (livro + N + N): 0.95
  - REF compacta (livro + N, capítulo only): 0.92
  - NEXT: 0.99
  - PREV: 0.99
  - MORE: 0.97
  - STAY: 0.90

Se o livro for ambíguo (confidence=0.5 do ParserBookTable), a
confiança final é multiplicada: c_parser = c_pattern * c_book.
"""

from __future__ import annotations

import re
from typing import Final

from core.types import Intent
from estado.state import BibleState
from parser.books import ParserBookTable
from parser.normalizer import Normalizer

__all__ = ["Parser"]

# ---------------------------------------------------------------------------
# Constantes de confiança (doc. técnica §3.7)
# ---------------------------------------------------------------------------

_C_REF_MARKERS: Final[float] = 0.98   # "joao capitulo 3 versiculo 16"
_C_REF_COMPACT_CV: Final[float] = 0.95  # "romanos 8 28"
_C_REF_COMPACT_C: Final[float] = 0.92   # "primeira corintios 13"
_C_NEXT: Final[float] = 0.99
_C_PREV: Final[float] = 0.99
_C_MORE: Final[float] = 0.97
_C_STAY: Final[float] = 0.90

# ---------------------------------------------------------------------------
# Padrões de navegação (após normalização)
# ---------------------------------------------------------------------------

# Próximo / seguinte / avança / avancar + amount opcional
_RE_NEXT = re.compile(
    r"(?:proximo|seguinte|avancar|avanca)"
    r"(?:\s+(?P<n>\d+))?"
    r"(?:\s+versiculo|\s+vers|\s+v)?\s*$",
    re.IGNORECASE,
)

# Anterior / voltar / volta / voltou / retroceder + amount opcional
_RE_PREV = re.compile(
    r"(?:anterior|voltar|volta|voltou|retroceder)"
    r"(?:\s+(?P<n>\d+))?"
    r"(?:\s+versiculo|\s+vers|\s+v)?\s*$",
    re.IGNORECASE,
)

# Mais / pula + amount obrigatório
_RE_MORE = re.compile(
    r"(?:mais|pula)\s+(?P<n>\d+)",
    re.IGNORECASE,
)

# Continua / ainda / permanece + (neste/nesse/desse) + capítulo/texto
_RE_STAY = re.compile(
    r"(?:continua|ainda|permanece)"
    r"(?:\s+(?:neste|nesse|desse|naquele|deste|desse))?"
    r"\s+(?:capitulo|cap|texto|versiculo|vers)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Marcadores de capítulo e versículo
# ---------------------------------------------------------------------------

_CHAPTER_MARKERS: Final[frozenset[str]] = frozenset({"capitulo", "cap"})
_VERSE_MARKERS: Final[frozenset[str]] = frozenset({"versiculo", "vers", "v"})

# ---------------------------------------------------------------------------
# Gatilhos para uncertain (doc. técnica §3.9)
# ---------------------------------------------------------------------------

_COMMAND_TRIGGERS: Final[frozenset[str]] = frozenset({
    "abre", "abrir", "abreai", "abra", "abrirai",
    "mostra", "mostrar", "mostre", "mostrai",
    "exibe", "exibir", "exibai",
})

_INDIRECT_TRIGGERS: Final[frozenset[str]] = frozenset({
    "aquele", "aquela", "aqueles", "aquelas",
    "versiculo", "texto", "passagem", "trecho",
    "passagem",
})

# Palavras que indicam que o usuário está pedindo algo mas de forma indireta
_INDIRECT_PHRASES: Final[frozenset[str]] = frozenset({
    "que fala", "que diz", "que lemos", "que leu",
    "da fe", "do amor", "da esperanca",
})

# ---------------------------------------------------------------------------
# Pistas bíblicas para busca semântica (doc. técnica §3.9 — extensão)
# ---------------------------------------------------------------------------
# Palavras isoladas que, quando presentes em uma frase sem padrão nem
# gatilho, sugerem que o usuário está descrevendo um versículo.
# O score mínimo (_BIBLICAL_HINT_MIN_SCORE) evita falsos positivos.

_BIBLICAL_SEARCH_HINTS: Final[frozenset[str]] = frozenset({
    # Termos teológicos centrais (exclui palavras comuns em saudações
    # de culto como "deus", "senhor", "jesus", "gloria" — essas só
    # ativam uncertain via frases fortes ou combinadas com outras pistas)
    "fe", "esperanca", "amor", "graca", "salvacao", "promessa",
    "evangelho", "perdao", "misericordia", "justica", "santidade",
    "reino", "alianca", "redencao", "ressurreicao",
    "pecado", "tentacao", "oracao", "adoracao", "louvor",
    # Palavras que aparecem em versículos conhecidos
    "fortalece", "cooperam", "sombra", "morte", "vale",
    "certeza", "esperam", "mundo", "amou", "unigenito",
    "temerei", "mal", "posso", "naquele", "todas", "coisas",
    "bem", "amam", "proposito", "chamados", "sal",
    "luz", "trevas", "vida", "verdade", "caminho",
    "pastor", "ovelhas", "banquete", "inimigos",
    "cura", "liberta", "espera", "confia",
})

# Frases bíblicas fortes — quando presentes, ativam uncertain diretamente
# (independentemente do score de pistas isoladas).
_BIBLICAL_SEARCH_PHRASES: Final[frozenset[str]] = frozenset({
    "cooperam para o bem",
    "tudo posso naquele",
    "vale da sombra da morte",
    "fe e a certeza",
    "deus amou o mundo",
    "nao temerei mal algum",
    "certeza das coisas que se esperam",
    "sal da terra",
    "luz do mundo",
    "o senhor e meu pastor",
    "ainda que eu andasse",
    "todas as coisas cooperam",
})

# Score mínimo de pistas bíblicas para ativar uncertain.
# Cada palavra isolada vale 1 ponto; frases fortes valem 3 pontos.
# Frases comuns de culto ("boa noite", "vamos orar") não pontuam.
_BIBLICAL_HINT_MIN_SCORE: Final[int] = 2


class Parser:
    """Parser determinístico de comandos bíblicos PT-BR.

    Args:
        books: ``ParserBookTable`` para resolução de livros.
        normalizer: instância de ``Normalizer`` (criada internamente se
            omitida).
    """

    def __init__(
        self,
        books: ParserBookTable,
        normalizer: Normalizer | None = None,
    ) -> None:
        self._norm = normalizer or Normalizer()
        self._books = books

    def parse(self, text: str, state: BibleState | None = None) -> Intent:
        """Interpreta ``text`` e produz ``Intent``.

        Args:
            text: texto transcrito (saída do STT).
            state: estado atual da Bíblia (read-only, para contexto).

        Returns:
            ``Intent`` com ``source="parser"`` e ``confidence=c_parser``.
            Pode ser ``action="uncertain"`` para encaminhar ao LLM,
            ou ``action="none"`` se não é comando.
        """
        if not text or not text.strip():
            return Intent(action="none", raw=text, source="parser")

        # 1. Normalizar
        norm = self._norm.normalize(text)
        if not norm:
            return Intent(action="none", raw=text, source="parser")

        # 2. Tentar navegação (alta prioridade, alta confiança)
        intent = self._try_navigation(norm, text)
        if intent is not None:
            return intent

        # 3. Tentar referência direta
        intent = self._try_reference(norm, text, state)
        if intent is not None:
            return intent

        # 4. Verificar gatilhos → uncertain
        if self._has_trigger(norm):
            return Intent(
                action="uncertain",
                raw=text,
                source="parser",
                confidence=0.0,
            )

        # 4b. Verificar pistas bíblicas → uncertain (busca semântica)
        if self._has_biblical_hints(norm):
            return Intent(
                action="uncertain",
                raw=text,
                source="parser",
                confidence=0.0,
            )

        # 5. Sem gatilho, sem padrão, sem pistas → none
        return Intent(action="none", raw=text, source="parser")

    # ------------------------------------------------------------------
    # Navegação
    # ------------------------------------------------------------------

    def _try_navigation(self, norm: str, raw: str) -> Intent | None:
        """Tenta padrões de navegação: next, previous, more, stay."""
        # STAY (continua/ainda nesse capítulo)
        if _RE_STAY.search(norm):
            return Intent(
                action="jump",
                amount=None,
                confidence=_C_STAY,
                source="parser",
                raw=raw,
            )

        # MORE (mais N / pula N) — amount obrigatório
        m = _RE_MORE.search(norm)
        if m:
            n = int(m.group("n"))
            return Intent(
                action="next",
                amount=n,
                confidence=_C_MORE,
                source="parser",
                raw=raw,
            )

        # NEXT (próximo / seguinte / avança) — amount opcional
        m = _RE_NEXT.search(norm)
        if m:
            n_str = m.group("n")
            n = int(n_str) if n_str else 1
            return Intent(
                action="next",
                amount=n,
                confidence=_C_NEXT,
                source="parser",
                raw=raw,
            )

        # PREV (anterior / voltar / volta) — amount opcional
        m = _RE_PREV.search(norm)
        if m:
            n_str = m.group("n")
            n = int(n_str) if n_str else 1
            return Intent(
                action="previous",
                amount=n,
                confidence=_C_PREV,
                source="parser",
                raw=raw,
            )

        return None

    # ------------------------------------------------------------------
    # Referência direta
    # ------------------------------------------------------------------

    def _try_reference(
        self,
        norm: str,
        raw: str,
        state: BibleState | None,
    ) -> Intent | None:
        """Tenta resolver referência direta: livro + cap/vers."""
        # Resolver livro no texto normalizado
        result = self._books.resolve(norm)
        if result is None:
            return None

        book = result.book
        book_conf = result.confidence

        # Extrair sufixo (texto após o nome do livro)
        suffix = norm[result.end:].strip()
        # Também extrair prefixo (texto antes do livro) — pode ter "versiculo"
        prefix = norm[:result.start].strip()

        # Parsear números do sufixo
        chapter, verse, has_markers = self._parse_ref_suffix(suffix, state)

        # Se não há números nem no sufixo nem no prefixo → uncertain
        # (livro encontrado mas sem referência)
        if chapter is None and verse is None:
            # Verificar se há números no prefixo (caso raro)
            prefix_nums = self._extract_numbers(prefix)
            if not prefix_nums:
                return Intent(
                    action="uncertain",
                    raw=raw,
                    source="parser",
                    confidence=0.0,
                )
            # Usar números do prefixo
            if len(prefix_nums) >= 2:
                chapter, verse = prefix_nums[0], prefix_nums[1]
            else:
                chapter = prefix_nums[0]
            has_markers = False

        # Determinar confiança do padrão
        if has_markers:
            pattern_conf = _C_REF_MARKERS
        elif verse is not None:
            pattern_conf = _C_REF_COMPACT_CV
        else:
            pattern_conf = _C_REF_COMPACT_C

        # Confiança final = padrão * livro
        final_conf = pattern_conf * book_conf

        return Intent(
            action="show",
            book=book.canonical,
            book_id=book.id,
            chapter=chapter,
            verse=verse,
            confidence=round(final_conf, 4),
            source="parser",
            raw=raw,
        )

    def _parse_ref_suffix(
        self,
        suffix: str,
        state: BibleState | None,
    ) -> tuple[int | None, int | None, bool]:
        """Extrai capítulo e versículo do sufixo após o nome do livro.

        Returns:
            ``(chapter, verse, has_markers)`` onde ``has_markers`` indica
            se marcadores explícitos (cap/vers) foram usados.
        """
        if not suffix:
            return None, None, False

        tokens = suffix.split()
        chapter: int | None = None
        verse: int | None = None
        unmarked_nums: list[int] = []
        has_markers = False

        i = 0
        while i < len(tokens):
            tok = tokens[i]

            if tok in _CHAPTER_MARKERS:
                # Próximo token deve ser o número do capítulo
                has_markers = True
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    chapter = int(tokens[i + 1])
                    i += 2
                    continue
            elif tok in _VERSE_MARKERS:
                # Próximo token deve ser o número do versículo
                has_markers = True
                if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                    verse = int(tokens[i + 1])
                    i += 2
                    continue
            elif tok.isdigit():
                unmarked_nums.append(int(tok))

            i += 1

        # Atribuir números sem marcador
        if chapter is None and unmarked_nums:
            chapter = unmarked_nums.pop(0)
        if verse is None and unmarked_nums:
            verse = unmarked_nums.pop(0)

        # Se verse foi encontrado via marcador mas chapter não,
        # tentar usar o chapter do estado atual
        if verse is not None and chapter is None and state is not None:
            if not state.is_empty():
                chapter = state.chapter

        return chapter, verse, has_markers

    @staticmethod
    def _extract_numbers(text: str) -> list[int]:
        """Extrai todos os números (dígitos) de ``text``."""
        return [int(m) for m in re.findall(r"\d+", text)]

    # ------------------------------------------------------------------
    # Gatilhos para uncertain
    # ------------------------------------------------------------------

    def _has_trigger(self, norm: str) -> bool:
        """Verifica se há gatilhos para encaminhar ao LLM.

        Gatilhos (doc. técnica §3.9):
          - Verbos de comando: abre, mostrar, exibe, vamos...
          - Pronomes demonstrativos: aquele, aquela...
          - Palavras de referência indireta: versiculo, texto, passagem...
        """
        tokens = set(norm.split())

        # Verbos de comando
        if tokens & _COMMAND_TRIGGERS:
            return True

        # Pronomes demonstrativos (indireta)
        if tokens & _INDIRECT_TRIGGERS:
            return True

        return False

    def _has_biblical_hints(self, norm: str) -> bool:
        """Verifica se há pistas bíblicas suficientes para encaminhar ao LLM.

        Diferente de ``_has_trigger`` (que usa gatilhos lexicais explícitos),
        este método usa um score heurístico baseado em:

        - Palavras isoladas do vocabulário bíblico (1 ponto cada)
        - Frases bíblicas fortes (3 pontos cada)

        Retorna ``True`` se o score >= ``_BIBLICAL_HINT_MIN_SCORE``.

        Filtro anti-falso-positivo:
          - Frases comuns de culto ("boa noite", "vamos orar") não pontuam
            porque não contêm palavras do conjunto ``_BIBLICAL_SEARCH_HINTS``.
          - Palavras como "deus", "senhor", "jesus" isoladas (1 ponto) não
            atingem o mínimo de 2 pontos.
        """
        score = 0

        # Frases bíblicas fortes (3 pontos cada)
        for phrase in _BIBLICAL_SEARCH_PHRASES:
            if phrase in norm:
                score += 3

        # Palavras isoladas (1 ponto cada)
        if score < _BIBLICAL_HINT_MIN_SCORE:
            tokens = set(norm.split())
            score += len(tokens & _BIBLICAL_SEARCH_HINTS)

        return score >= _BIBLICAL_HINT_MIN_SCORE
