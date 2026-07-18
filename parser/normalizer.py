"""Normalizador de texto PT-BR para o parser determinístico.

Responsabilidades:
  - lowercase
  - remoção de diacritics
  - remoção de pontuação desnecessária
  - colapso de whitespace
  - conversão de ordinais ("primeiro"/"primeira" → "1")
  - conversão de números romanos ("viii" → "8", exceto "v" = versículo)
  - conversão de números por extenso ("vinte e oito" → "28", "treze" → "13")
  - normalização de variações comuns (PT-BR vs PT-PT, indicadores ordinais)

Referências:
  - Doc. técnica §3.2–3.5
  - Blueprint §5 (Normalizer)

Nota sobre o exemplo "Primeira carta aos Coríntios capítulo treze":
  O normalizer produz "1 carta aos corintios capitulo 13" — a remoção de
  "carta aos" é resolução de sinônimo de livro, responsabilidade do parser
  via BookTable, não do normalizer.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

# ---------------------------------------------------------------------------
# Tabelas de números por extenso (doc. técnica §3.3)
# ---------------------------------------------------------------------------

# Cardinais 0–19 e dezenas/centenas.
_EXTENSO_UNITS: Final[dict[str, int]] = {
    "zero": 0, "um": 1, "dois": 2, "tres": 3, "quatro": 4,
    "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "quatorze": 14, "catorze": 14,  # PT-BR / PT-PT
    "quinze": 15,
    "dezesseis": 16, "dezassete": 17, "dezesete": 17,  # PT-BR / PT-PT
    "dezoito": 18, "dezenove": 19,
}

_EXTENSO_TENS: Final[dict[str, int]] = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
}

_EXTENSO_HUNDREDS: Final[dict[str, int]] = {
    "cem": 100, "cento": 100,
}

# Vocabulário completo (tokens que podem aparecer em um número por extenso).
_EXTENSO_VOCAB: Final[frozenset[str]] = frozenset(
    set(_EXTENSO_UNITS.keys())
    | set(_EXTENSO_TENS.keys())
    | set(_EXTENSO_HUNDREDS.keys())
    | {"e"}
)

# ---------------------------------------------------------------------------
# Tabela de ordinais (doc. técnica §3.5)
# ---------------------------------------------------------------------------

_ORDINALS: Final[dict[str, int]] = {
    "primeiro": 1, "primeira": 1,
    "segundo": 2, "segunda": 2,
    "terceiro": 3, "terceira": 3,
    "quarto": 4, "quarta": 4,
    "quinto": 5, "quinta": 5,
    "sexto": 6, "sexta": 6,
    "setimo": 7, "setima": 7,
    "oitavo": 8, "oitava": 8,
    "nono": 9, "nona": 9,
    "decimo": 10, "decima": 10,
}

# ---------------------------------------------------------------------------
# Números romanos
# ---------------------------------------------------------------------------

_ROMAN_VALUES: Final[dict[str, int]] = {
    "i": 1, "v": 5, "x": 10, "l": 50,
    "c": 100, "d": 500, "m": 1000,
}

# "v" isolado é marcador de versículo (doc. §3.5), não numeral romano 5.
_ROMAN_SKIP: Final[frozenset[str]] = frozenset({"v"})

_ROMAN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Regex de pontuação e whitespace
# ---------------------------------------------------------------------------

# Remove tudo que não é letra, dígito ou whitespace.
_PUNCTUATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\w\s]")

# Colapso de whitespace.
_WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")


class Normalizer:
    """Normalizador de texto PT-BR para o parser determinístico.

    Métodos públicos:
      - ``normalize(text)``: normalização completa (lowercase, diacritics,
        pontuação, whitespace, ordinais, romanos, extenso).
      - ``extenso_to_digit(token)``: converte um número por extenso para int.
      - ``ordinal_to_int(token)``: converte um ordinal para int.
      - ``roman_to_int(token)``: converte um numeral romano para int.

    Totalmente determinístico, sem LLM, sem dependências externas.
    """

    # ------------------------------------------------------------------
    # Normalização principal
    # ------------------------------------------------------------------

    def normalize(self, text: str) -> str:
        """Normaliza texto completo para o parser.

        Pipeline:
          1. lowercase
          2. remoção de diacritics (NFKD)
          3. remoção de pontuação (mantém letras, dígitos, whitespace)
          4. colapso de whitespace
          5. conversão de ordinais ("primeira" → "1")
          6. conversão de romanos ("viii" → "8", exceto "v")
          7. conversão de extenso ("vinte e oito" → "28", "treze" → "13")

        Args:
            text: texto transcrito (saída do STT).

        Returns:
            Texto normalizado, pronto para o parser principal.
        """
        # 1. lowercase
        s = text.lower()

        # 2. remover diacritics
        s = self._remove_diacritics(s)

        # 3. remover pontuação (substituir por espaço)
        s = _PUNCTUATION_PATTERN.sub(" ", s)

        # 4. colapsar whitespace
        s = _WHITESPACE_PATTERN.sub(" ", s).strip()

        if not s:
            return s

        # 5–7. conversões token a token / sequência
        tokens = s.split(" ")
        tokens = self._replace_ordinals(tokens)
        tokens = self._replace_romans(tokens)
        tokens = self._replace_extenso_sequences(tokens)

        return " ".join(tokens)

    # ------------------------------------------------------------------
    # Conversões individuais (públicas, para uso pelo parser)
    # ------------------------------------------------------------------

    def extenso_to_digit(self, token: str) -> int | None:
        """Converte um número por extenso para int (range 0–199).

        Suporta composições com "e": "vinte e oito" → 28.
        Tokens individuais: "treze" → 13, "vinte" → 20.

        Args:
            token: número por extenso (pode conter espaços e "e").

        Returns:
            Inteiro 0–199, ou ``None`` se não for um número válido.
        """
        parts = token.strip().split()
        if not parts:
            return None

        total = 0
        for part in parts:
            if part == "e":
                continue
            val = _EXTENSO_UNITS.get(part)
            if val is None:
                val = _EXTENSO_TENS.get(part)
            if val is None:
                val = _EXTENSO_HUNDREDS.get(part)
            if val is None:
                return None
            total += val

        if total > 199:
            return None
        return total if parts else None

    def ordinal_to_int(self, token: str) -> int | None:
        """Converte um ordinal para int.

        Suporta formas masculinas e femininas: "primeiro"→1, "primeira"→1.
        Range: 1–10 (suficiente para livros da Bíblia).

        Args:
            token: ordinal (ex.: "primeira", "terceiro").

        Returns:
            Inteiro 1–10, ou ``None`` se não for um ordinal.
        """
        return _ORDINALS.get(token.strip().lower())

    def roman_to_int(self, token: str) -> int | None:
        """Converte um numeral romano para int.

        Suporta I a MMMCMXCIX (1 a 3999) via algoritmo padrão.
        Exceção: "v" isolado NÃO é convertido (é marcador de versículo).

        Args:
            token: numeral romano (ex.: "viii", "xii", "i").

        Returns:
            Inteiro, ou ``None`` se não for um numeral romano válido.
        """
        t = token.strip().lower()
        if not t or t in _ROMAN_SKIP:
            return None
        if not _ROMAN_PATTERN.match(t):
            return None

        total = 0
        prev = 0
        for ch in reversed(t):
            val = _ROMAN_VALUES.get(ch)
            if val is None:
                return None
            if val < prev:
                total -= val
            else:
                total += val
                prev = val
        return total if total > 0 else None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _remove_diacritics(text: str) -> str:
        """Remove diacritics via NFKD."""
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    @staticmethod
    def _replace_ordinals(tokens: list[str]) -> list[str]:
        """Substitui ordinais por dígitos in-place."""
        result: list[str] = []
        for token in tokens:
            val = _ORDINALS.get(token)
            result.append(str(val) if val is not None else token)
        return result

    @staticmethod
    def _replace_romans(tokens: list[str]) -> list[str]:
        """Substitui numerais romanos por dígitos (exceto "v")."""
        result: list[str] = []
        for token in tokens:
            if token in _ROMAN_SKIP:
                result.append(token)
                continue
            if _ROMAN_PATTERN.match(token):
                total = 0
                prev = 0
                valid = True
                for ch in reversed(token):
                    val = _ROMAN_VALUES.get(ch)
                    if val is None:
                        valid = False
                        break
                    if val < prev:
                        total -= val
                    else:
                        total += val
                        prev = val
                if valid and total > 0:
                    result.append(str(total))
                else:
                    result.append(token)
            else:
                result.append(token)
        return result

    @staticmethod
    def _replace_extenso_sequences(tokens: list[str]) -> list[str]:
        """Identifica e substitui sequências de números por extenso.

        Regras de composição (gramática do português):
          - Um token de dezena/centena pode ser seguido de "e" + unidade
            (ex.: "vinte e oito" → 28, "cento e cinquenta" → 150).
          - "cento e" + dezena + "e" + unidade (ex.: "cento e vinte e oito" → 128).
          - Dois tokens extenso adjacentes SEM "e" são números separados
            (ex.: "três dezesseis" → "3 16", não "19").
          - Um único token extenso é convertido isoladamente.

        Ou seja: a composição só acontece através do conectivo "e".
        """
        result: list[str] = []
        i = 0
        n = len(tokens)

        while i < n:
            token = tokens[i]
            if token not in _EXTENSO_VOCAB or token == "e":
                result.append(token)
                i += 1
                continue

            # Iniciar sequência extenso com o token atual.
            seq: list[str] = [token]
            j = i + 1

            # Estender apenas via conectivo "e" seguido de extenso.
            # Sem "e", a sequência termina (números separados).
            while j + 1 < n and tokens[j] == "e" and tokens[j + 1] in _EXTENSO_VOCAB and tokens[j + 1] != "e":
                seq.append("e")
                seq.append(tokens[j + 1])
                j += 2

            # Tentar converter a sequência.
            value = 0
            valid = True
            for part in seq:
                if part == "e":
                    continue
                val = _EXTENSO_UNITS.get(part)
                if val is None:
                    val = _EXTENSO_TENS.get(part)
                if val is None:
                    val = _EXTENSO_HUNDREDS.get(part)
                if val is None:
                    valid = False
                    break
                value += val

            if valid and 0 <= value <= 199 and len(seq) > 0:
                result.append(str(value))
                i = j
            else:
                # Não é extenso válido; manter token original e avançar.
                result.append(token)
                i += 1

        return result
