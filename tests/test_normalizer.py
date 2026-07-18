"""Testes unitários do normalizador PT-BR.

Cobre:
- lowercase e diacritics
- remoção de pontuação
- colapso de whitespace
- ordinais (masculino/feminino, 1–10)
- números romanos (I–VIII, exceto "v")
- números por extenso (0–199, composição com "e")
- variações PT-BR vs PT-PT (catorze/quatorze, dezassete/dezesete)
- exemplos completos do enunciado
- casos extremos (vazio, só pontuação, números já em dígitos)
"""

from __future__ import annotations

import pytest

from parser.normalizer import Normalizer


@pytest.fixture
def norm() -> Normalizer:
    return Normalizer()


# ---------------------------------------------------------------------------
# normalize — casos básicos
# ---------------------------------------------------------------------------

class TestNormalizeBasic:
    def test_lowercase(self, norm: Normalizer) -> None:
        # lowercase + diacritics; "tres" é extenso → "3"
        assert norm.normalize("JOÃO CAPÍTULO TRÊS") == "joao capitulo 3"

    def test_remove_diacritics(self, norm: Normalizer) -> None:
        assert "á" not in norm.normalize("São João capítulo três")
        assert "ã" not in norm.normalize("São João capítulo três")

    def test_remove_punctuation_colon(self, norm: Normalizer) -> None:
        assert norm.normalize("João 3 : 16") == "joao 3 16"

    def test_remove_punctuation_period(self, norm: Normalizer) -> None:
        assert norm.normalize("cap. 3 vers. 16") == "cap 3 vers 16"

    def test_remove_punctuation_comma(self, norm: Normalizer) -> None:
        assert norm.normalize("João, 3, 16") == "joao 3 16"

    def test_remove_punctuation_parens(self, norm: Normalizer) -> None:
        assert norm.normalize("(João 3:16)") == "joao 3 16"

    def test_collapse_whitespace(self, norm: Normalizer) -> None:
        assert norm.normalize("João   3    16") == "joao 3 16"

    def test_strip(self, norm: Normalizer) -> None:
        assert norm.normalize("  João 3:16  ") == "joao 3 16"

    def test_empty(self, norm: Normalizer) -> None:
        assert norm.normalize("") == ""

    def test_only_punctuation(self, norm: Normalizer) -> None:
        assert norm.normalize("...---,,,") == ""

    def test_only_spaces(self, norm: Normalizer) -> None:
        assert norm.normalize("     ") == ""

    def test_preserve_digits(self, norm: Normalizer) -> None:
        assert norm.normalize("Romanos 8 28") == "romanos 8 28"

    def test_preserve_alphanumeric(self, norm: Normalizer) -> None:
        assert norm.normalize("1co 13") == "1co 13"


# ---------------------------------------------------------------------------
# normalize — ordinais
# ---------------------------------------------------------------------------

class TestNormalizeOrdinals:
    def test_primeira(self, norm: Normalizer) -> None:
        assert norm.normalize("Primeira Coríntios") == "1 corintios"

    def test_primeiro(self, norm: Normalizer) -> None:
        assert norm.normalize("primeiro João") == "1 joao"

    def test_segunda(self, norm: Normalizer) -> None:
        assert norm.normalize("Segunda Pedro") == "2 pedro"

    def test_terceiro(self, norm: Normalizer) -> None:
        assert norm.normalize("Terceiro João") == "3 joao"

    def test_quarto(self, norm: Normalizer) -> None:
        assert norm.normalize("quarto Reis") == "4 reis"

    def test_decimo(self, norm: Normalizer) -> None:
        assert norm.normalize("décimo capítulo") == "10 capitulo"


# ---------------------------------------------------------------------------
# normalize — romanos
# ---------------------------------------------------------------------------

class TestNormalizeRomans:
    def test_viii(self, norm: Normalizer) -> None:
        assert norm.normalize("Romanos VIII vinte e oito") == "romanos 8 28"

    def test_i(self, norm: Normalizer) -> None:
        assert norm.normalize("I Coríntios") == "1 corintios"

    def test_ii(self, norm: Normalizer) -> None:
        assert norm.normalize("II Pedro") == "2 pedro"

    def test_iii(self, norm: Normalizer) -> None:
        assert norm.normalize("III João") == "3 joao"

    def test_x(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos X") == "salmos 10"

    def test_xii(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos XII") == "salmos 12"

    def test_v_not_converted(self, norm: Normalizer) -> None:
        """'v' isolado é marcador de versículo, não numeral romano 5."""
        assert norm.normalize("João 3 v 16") == "joao 3 v 16"

    def test_vi(self, norm: Normalizer) -> None:
        assert norm.normalize("Romanos VI") == "romanos 6"

    def test_ix(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos IX") == "salmos 9"

    def test_xv(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos XV") == "salmos 15"

    def test_xx(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos XX") == "salmos 20"

    def test_xxx(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos XXX") == "salmos 30"

    def test_c(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos C") == "salmos 100"

    def test_cl(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos CL") == "salmos 150"


# ---------------------------------------------------------------------------
# normalize — extenso
# ---------------------------------------------------------------------------

class TestNormalizeExtenso:
    def test_tres(self, norm: Normalizer) -> None:
        assert norm.normalize("João três dezesseis") == "joao 3 16"

    def test_dezesseis(self, norm: Normalizer) -> None:
        assert "16" in norm.normalize("versículo dezesseis")

    def test_vinte_e_oito(self, norm: Normalizer) -> None:
        assert norm.normalize("Romanos oito vinte e oito") == "romanos 8 28"

    def test_treze(self, norm: Normalizer) -> None:
        assert norm.normalize("corintios treze") == "corintios 13"

    def test_cento_e_cinquenta(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos cento e cinquenta") == "salmos 150"

    def test_cento_e_vinte_e_oito(self, norm: Normalizer) -> None:
        assert norm.normalize("cento e vinte e oito") == "128"

    def test_cem(self, norm: Normalizer) -> None:
        assert norm.normalize("Salmos cem") == "salmos 100"

    def test_cento(self, norm: Normalizer) -> None:
        assert norm.normalize("cento e noventa e nove") == "199"

    def test_quatorze(self, norm: Normalizer) -> None:
        assert norm.normalize("capítulo quatorze") == "capitulo 14"

    def test_catorze(self, norm: Normalizer) -> None:
        """Variante PT-PT de 14."""
        assert norm.normalize("capítulo catorze") == "capitulo 14"

    def test_dezassete(self, norm: Normalizer) -> None:
        """Variante PT-PT de 17."""
        assert norm.normalize("capítulo dezassete") == "capitulo 17"

    def test_dezesete(self, norm: Normalizer) -> None:
        """Variante PT-BR de 17."""
        assert norm.normalize("capítulo dezesete") == "capitulo 17"

    def test_vinte_sem_e(self, norm: Normalizer) -> None:
        """'vinte oito' sem 'e' são dois números separados (20 e 8)."""
        assert norm.normalize("vinte oito") == "20 8"

    def test_oito_isolado(self, norm: Normalizer) -> None:
        assert norm.normalize("Romanos oito") == "romanos 8"

    def test_um_isolado(self, norm: Normalizer) -> None:
        assert norm.normalize("João um") == "joao 1"

    def test_e_nao_extenso(self, norm: Normalizer) -> None:
        """'e' entre palavras não-extenso não deve ser consumido."""
        assert norm.normalize("João e Maria") == "joao e maria"

    def test_vinte_e_joao(self, norm: Normalizer) -> None:
        """'vinte e joao' — 'e' seguido de não-extenso não faz parte da sequência."""
        result = norm.normalize("vinte e joao")
        assert "20" in result
        assert "joao" in result


# ---------------------------------------------------------------------------
# normalize — exemplos completos do enunciado
# ---------------------------------------------------------------------------

class TestNormalizeExamples:
    def test_example_1(self, norm: Normalizer) -> None:
        """João capítulo três versículo dezesseis → joao capitulo 3 versiculo 16"""
        result = norm.normalize("João capítulo três versículo dezesseis")
        assert result == "joao capitulo 3 versiculo 16"

    def test_example_2(self, norm: Normalizer) -> None:
        """Primeira carta aos Coríntios capítulo treze → 1 carta aos corintios capitulo 13

        Nota: a remoção de "carta aos" é resolução de sinônimo de livro
        (responsabilidade do parser via BookTable), não do normalizer.
        """
        result = norm.normalize("Primeira carta aos Coríntios capítulo treze")
        assert result == "1 carta aos corintios capitulo 13"

    def test_example_3(self, norm: Normalizer) -> None:
        """Romanos VIII vinte e oito → romanos 8 28"""
        result = norm.normalize("Romanos VIII vinte e oito")
        assert result == "romanos 8 28"

    def test_example_4(self, norm: Normalizer) -> None:
        """João   3 : 16 → joao 3 16"""
        result = norm.normalize("João   3 : 16")
        assert result == "joao 3 16"


# ---------------------------------------------------------------------------
# extenso_to_digit
# ---------------------------------------------------------------------------

class TestExtensoToDigit:
    def test_unities(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("zero") == 0
        assert norm.extenso_to_digit("um") == 1
        assert norm.extenso_to_digit("dois") == 2
        assert norm.extenso_to_digit("dez") == 10
        assert norm.extenso_to_digit("dezesseis") == 16
        assert norm.extenso_to_digit("dezenove") == 19

    def test_tens(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("vinte") == 20
        assert norm.extenso_to_digit("trinta") == 30
        assert norm.extenso_to_digit("noventa") == 90

    def test_hundreds(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("cem") == 100
        assert norm.extenso_to_digit("cento") == 100

    def test_composition_with_e(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("vinte e oito") == 28
        assert norm.extenso_to_digit("vinte e um") == 21
        assert norm.extenso_to_digit("cento e vinte") == 120
        assert norm.extenso_to_digit("cento e cinquenta") == 150
        assert norm.extenso_to_digit("cento e noventa e nove") == 199

    def test_composition_without_e(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("vinte oito") == 28
        assert norm.extenso_to_digit("cento vinte") == 120

    def test_variants(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("quatorze") == 14
        assert norm.extenso_to_digit("catorze") == 14
        assert norm.extenso_to_digit("dezassete") == 17
        assert norm.extenso_to_digit("dezesete") == 17

    def test_invalid(self, norm: Normalizer) -> None:
        assert norm.extenso_to_digit("joao") is None
        assert norm.extenso_to_digit("") is None
        assert norm.extenso_to_digit("vinte e joao") is None

    def test_over_199(self, norm: Normalizer) -> None:
        """Acima de 199 não é suportado (spec: 1–199)."""
        # "duzentos" não está no vocabulário.
        assert norm.extenso_to_digit("duzentos") is None


# ---------------------------------------------------------------------------
# ordinal_to_int
# ---------------------------------------------------------------------------

class TestOrdinalToInt:
    def test_basic(self, norm: Normalizer) -> None:
        assert norm.ordinal_to_int("primeiro") == 1
        assert norm.ordinal_to_int("primeira") == 1
        assert norm.ordinal_to_int("segundo") == 2
        assert norm.ordinal_to_int("segunda") == 2
        assert norm.ordinal_to_int("terceiro") == 3
        assert norm.ordinal_to_int("terceira") == 3

    def test_extended(self, norm: Normalizer) -> None:
        assert norm.ordinal_to_int("quarto") == 4
        assert norm.ordinal_to_int("quinta") == 5
        assert norm.ordinal_to_int("decimo") == 10

    def test_invalid(self, norm: Normalizer) -> None:
        assert norm.ordinal_to_int("joao") is None
        assert norm.ordinal_to_int("") is None
        assert norm.ordinal_to_int("primeiros") is None  # plural não suportado


# ---------------------------------------------------------------------------
# roman_to_int
# ---------------------------------------------------------------------------

class TestRomanToInt:
    def test_basic(self, norm: Normalizer) -> None:
        assert norm.roman_to_int("i") == 1
        assert norm.roman_to_int("ii") == 2
        assert norm.roman_to_int("iii") == 3
        assert norm.roman_to_int("iv") == 4
        assert norm.roman_to_int("vi") == 6
        assert norm.roman_to_int("viii") == 8
        assert norm.roman_to_int("ix") == 9
        assert norm.roman_to_int("x") == 10
        assert norm.roman_to_int("xii") == 12
        assert norm.roman_to_int("xv") == 15
        assert norm.roman_to_int("xx") == 20
        assert norm.roman_to_int("xxx") == 30
        assert norm.roman_to_int("xl") == 40
        assert norm.roman_to_int("l") == 50
        assert norm.roman_to_int("c") == 100
        assert norm.roman_to_int("cl") == 150

    def test_case_insensitive(self, norm: Normalizer) -> None:
        assert norm.roman_to_int("VIII") == 8
        assert norm.roman_to_int("viii") == 8
        assert norm.roman_to_int("Viii") == 8

    def test_v_skipped(self, norm: Normalizer) -> None:
        """'v' isolado não é convertido (marcador de versículo)."""
        assert norm.roman_to_int("v") is None

    def test_invalid(self, norm: Normalizer) -> None:
        assert norm.roman_to_int("joao") is None
        assert norm.roman_to_int("") is None
        assert norm.roman_to_int("abc") is None
        assert norm.roman_to_int("xiiij") is None


# ---------------------------------------------------------------------------
# Casos extremos
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_mixed_digits_and_extenso(self, norm: Normalizer) -> None:
        assert norm.normalize("João 3 dezesseis") == "joao 3 16"

    def test_ordinal_and_roman(self, norm: Normalizer) -> None:
        """Ordinal e romano não conflitam — ordinal primeiro."""
        assert norm.normalize("primeira II") == "1 2"

    def test_multiple_extenso(self, norm: Normalizer) -> None:
        assert norm.normalize("vinte e oito trinta e sete") == "28 37"

    def test_extenso_at_end(self, norm: Normalizer) -> None:
        assert norm.normalize("João capítulo vinte e oito") == "joao capitulo 28"

    def test_extenso_at_start(self, norm: Normalizer) -> None:
        assert norm.normalize("vinte e oito Romanos") == "28 romanos"

    def test_already_normalized(self, norm: Normalizer) -> None:
        """Texto já normalizado não deve mudar."""
        assert norm.normalize("joao 3 16") == "joao 3 16"

    def test_ordinal_indicator_symbol(self, norm: Normalizer) -> None:
        """1º e 1ª (indicadores ordinais) devem ter o símbolo removido."""
        # º e ª são removidos como pontuação.
        result = norm.normalize("1º capítulo 1ª carta")
        assert "1" in result
        assert "º" not in result
        assert "ª" not in result
