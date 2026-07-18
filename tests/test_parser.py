"""Testes unitários do parser principal (parser/parser.py).

Cobre:
- exemplos do enunciado (referências diretas e navegação)
- referências com marcadores (capítulo/versículo)
- referências compactas (livro + N + N)
- referências com apenas capítulo (livro + N)
- navegação: próximo, anterior, volta, mais, continua/ainda
- números por extenso (via Normalizer)
- ordinais e romanos (via Normalizer)
- sinônimos de livros
- comandos semânticos NÃO interpretados → uncertain
- pregação (não-comando) → none
- confiança do parser (c_parser)
- uso de BibleState para contexto
"""

from __future__ import annotations

import pytest

from core.types import Intent
from estado.state import BibleState
from parser.books import ParserBookTable, load_parser_books
from parser.normalizer import Normalizer
from parser.parser import Parser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def books() -> ParserBookTable:
    return load_parser_books("config/books.json")


@pytest.fixture(scope="module")
def parser(books: ParserBookTable) -> Parser:
    return Parser(books=books)


@pytest.fixture(scope="module")
def normalizer() -> Normalizer:
    return Normalizer()


def _state(book_id: int = 43, chapter: int = 3, verse: int = 16) -> BibleState:
    """Estado de teste: João 3:16."""
    return BibleState(book_id=book_id, chapter=chapter, verse=verse)


# ---------------------------------------------------------------------------
# Exemplos do enunciado — Referências
# ---------------------------------------------------------------------------

class TestEnunciadoReferences:
    def test_joao_3_16(self, parser: Parser) -> None:
        r = parser.parse("joao 3 16")
        assert r.action == "show"
        assert r.book == "João"
        assert r.book_id == 43
        assert r.chapter == 3
        assert r.verse == 16
        assert r.source == "parser"

    def test_joao_capitulo_3_versiculo_16(self, parser: Parser) -> None:
        r = parser.parse("joao capitulo 3 versiculo 16")
        assert r.action == "show"
        assert r.book == "João"
        assert r.chapter == 3
        assert r.verse == 16
        # Com marcadores → confiança 0.98
        assert r.confidence == pytest.approx(0.98, abs=0.01)

    def test_romanos_oito_vinte_e_oito(self, parser: Parser) -> None:
        """Número por extenso: 'oito vinte e oito' → 8, 28."""
        r = parser.parse("romanos oito vinte e oito")
        assert r.action == "show"
        assert r.book == "Romanos"
        assert r.chapter == 8
        assert r.verse == 28

    def test_primeira_corintios_treze(self, parser: Parser) -> None:
        """Ordinal + extenso: 'primeira corintios treze' → 1 Coríntios 13."""
        r = parser.parse("primeira corintios treze")
        assert r.action == "show"
        assert r.book == "1 Coríntios"
        assert r.book_id == 46
        assert r.chapter == 13
        assert r.verse is None  # apenas capítulo


# ---------------------------------------------------------------------------
# Exemplos do enunciado — Navegação
# ---------------------------------------------------------------------------

class TestEnunciadoNavigation:
    def test_proximo(self, parser: Parser) -> None:
        r = parser.parse("proximo")
        assert r.action == "next"
        assert r.amount == 1
        assert r.confidence == pytest.approx(0.99, abs=0.01)

    def test_anterior(self, parser: Parser) -> None:
        r = parser.parse("anterior")
        assert r.action == "previous"
        assert r.amount == 1

    def test_volta(self, parser: Parser) -> None:
        r = parser.parse("volta")
        assert r.action == "previous"
        assert r.amount == 1

    def test_volta_dois(self, parser: Parser) -> None:
        r = parser.parse("volta dois")
        assert r.action == "previous"
        assert r.amount == 2

    def test_mais_tres(self, parser: Parser) -> None:
        r = parser.parse("mais tres")
        assert r.action == "next"
        assert r.amount == 3
        assert r.confidence == pytest.approx(0.97, abs=0.01)

    def test_continua_nesse_capitulo(self, parser: Parser) -> None:
        r = parser.parse("continua nesse capitulo")
        assert r.action == "jump"
        assert r.amount is None
        assert r.confidence == pytest.approx(0.90, abs=0.01)

    def test_ainda_nesse_texto(self, parser: Parser) -> None:
        r = parser.parse("ainda nesse texto")
        assert r.action == "jump"
        assert r.amount is None


# ---------------------------------------------------------------------------
# Comandos semânticos NÃO interpretados → uncertain
# ---------------------------------------------------------------------------

class TestSemanticNotInterpreted:
    def test_aquele_versiculo_da_fe(self, parser: Parser) -> None:
        r = parser.parse("aquele versiculo da fe")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_aquele_texto_deus_amou(self, parser: Parser) -> None:
        r = parser.parse("aquele texto que fala que deus amou o mundo")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_abre_aquele_texto(self, parser: Parser) -> None:
        r = parser.parse("abre aquele texto")
        assert r.action == "uncertain"

    def test_mostrar_versiculo_da_fe(self, parser: Parser) -> None:
        r = parser.parse("mostrar aquele versiculo da fe")
        assert r.action == "uncertain"


# ---------------------------------------------------------------------------
# Pregação (não-comando) → none
# ---------------------------------------------------------------------------

class TestNotCommand:
    def test_jesus_disse_discipulos(self, parser: Parser) -> None:
        r = parser.parse("e entao jesus disse aos discipulos")
        assert r.action == "none"

    def test_empty(self, parser: Parser) -> None:
        r = parser.parse("")
        assert r.action == "none"

    def test_whitespace(self, parser: Parser) -> None:
        r = parser.parse("   ")
        assert r.action == "none"

    def test_random_words(self, parser: Parser) -> None:
        r = parser.parse("o ceu e azul")
        assert r.action == "none"


# ---------------------------------------------------------------------------
# Referências com marcadores
# ---------------------------------------------------------------------------

class TestReferencesWithMarkers:
    def test_cap_vers_markers(self, parser: Parser) -> None:
        r = parser.parse("joao cap 3 vers 16")
        assert r.action == "show"
        assert r.chapter == 3
        assert r.verse == 16
        assert r.confidence == pytest.approx(0.98, abs=0.01)

    def test_capitulo_only(self, parser: Parser) -> None:
        r = parser.parse("joao capitulo 3")
        assert r.action == "show"
        assert r.chapter == 3
        assert r.verse is None

    def test_vamos_abrir_joao_capitulo_3_versiculo_16(self, parser: Parser) -> None:
        """Frase completa do Blueprint §5."""
        r = parser.parse("vamos abrir em joao capitulo 3 versiculo 16")
        assert r.action == "show"
        assert r.book == "João"
        assert r.chapter == 3
        assert r.verse == 16
        assert r.confidence == pytest.approx(0.98, abs=0.01)


# ---------------------------------------------------------------------------
# Referências compactas
# ---------------------------------------------------------------------------

class TestCompactReferences:
    def test_livro_cap_vers(self, parser: Parser) -> None:
        r = parser.parse("romanos 8 28")
        assert r.action == "show"
        assert r.book == "Romanos"
        assert r.chapter == 8
        assert r.verse == 28
        # Compacta com cap+vers → 0.95
        assert r.confidence == pytest.approx(0.95, abs=0.01)

    def test_livro_cap_only(self, parser: Parser) -> None:
        r = parser.parse("joao 3")
        assert r.action == "show"
        assert r.chapter == 3
        assert r.verse is None
        # Compacta com cap apenas → 0.92
        assert r.confidence == pytest.approx(0.92, abs=0.01)

    def test_primeira_corintios_13(self, parser: Parser) -> None:
        r = parser.parse("primeira corintios 13")
        assert r.action == "show"
        assert r.book == "1 Coríntios"
        assert r.chapter == 13
        assert r.verse is None


# ---------------------------------------------------------------------------
# Números por extenso
# ---------------------------------------------------------------------------

class TestExtensoNumbers:
    def test_oito_vinte_e_oito(self, parser: Parser) -> None:
        r = parser.parse("romanos oito vinte e oito")
        assert r.chapter == 8
        assert r.verse == 28

    def test_treze(self, parser: Parser) -> None:
        r = parser.parse("primeira corintios treze")
        assert r.chapter == 13

    def test_dezesseis(self, parser: Parser) -> None:
        r = parser.parse("joao tres dezesseis")
        assert r.chapter == 3
        assert r.verse == 16

    def test_cento_e_cinquenta(self, parser: Parser) -> None:
        """Número grande: cento e cinquenta → 150."""
        r = parser.parse("salmos cento e cinquenta")
        assert r.action == "show"
        assert r.book == "Salmos"
        assert r.chapter == 150


# ---------------------------------------------------------------------------
# Ordinais e romanos
# ---------------------------------------------------------------------------

class TestOrdinalsRomans:
    def test_primeira_corintios(self, parser: Parser) -> None:
        r = parser.parse("primeira corintios 13")
        assert r.book == "1 Coríntios"

    def test_i_corintios(self, parser: Parser) -> None:
        r = parser.parse("i corintios 13")
        assert r.book == "1 Coríntios"

    def test_segunda_pedro(self, parser: Parser) -> None:
        r = parser.parse("segunda pedro 1")
        assert r.book == "2 Pedro"

    def test_ii_pedro(self, parser: Parser) -> None:
        r = parser.parse("ii pedro 1")
        assert r.book == "2 Pedro"

    def test_terceira_joao(self, parser: Parser) -> None:
        r = parser.parse("terceira joao 1")
        assert r.book == "3 João"

    def test_iii_joao(self, parser: Parser) -> None:
        r = parser.parse("iii joao 1")
        assert r.book == "3 João"


# ---------------------------------------------------------------------------
# Sinônimos de livros
# ---------------------------------------------------------------------------

class TestSynonyms:
    def test_sao_joao(self, parser: Parser) -> None:
        r = parser.parse("sao joao 3 16")
        assert r.book == "João"

    def test_evangelho_de_joao(self, parser: Parser) -> None:
        r = parser.parse("evangelho de joao 3 16")
        assert r.book == "João"

    def test_primeira_carta_aos_corintios(self, parser: Parser) -> None:
        r = parser.parse("primeira carta aos corintios 13")
        assert r.book == "1 Coríntios"

    def test_abreviacao_gn(self, parser: Parser) -> None:
        r = parser.parse("gn 1 1")
        assert r.book == "Gênesis"
        assert r.chapter == 1
        assert r.verse == 1

    def test_abreviacao_sl(self, parser: Parser) -> None:
        r = parser.parse("sl 23")
        assert r.book == "Salmos"
        assert r.chapter == 23

    def test_abreviacao_ap(self, parser: Parser) -> None:
        r = parser.parse("ap 22 21")
        assert r.book == "Apocalipse"


# ---------------------------------------------------------------------------
# Variações PT-BR e diacritics
# ---------------------------------------------------------------------------

class TestVariations:
    def test_with_diacritics(self, parser: Parser) -> None:
        r = parser.parse("João 3:16")
        assert r.book == "João"
        assert r.chapter == 3
        assert r.verse == 16

    def test_uppercase(self, parser: Parser) -> None:
        r = parser.parse("JOÃO 3 16")
        assert r.book == "João"

    def test_mixed_case(self, parser: Parser) -> None:
        r = parser.parse("RoMaNoS 8 28")
        assert r.book == "Romanos"


# ---------------------------------------------------------------------------
# Confiança
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_ref_with_markers_confidence(self, parser: Parser) -> None:
        r = parser.parse("joao capitulo 3 versiculo 16")
        assert r.confidence == pytest.approx(0.98, abs=0.01)

    def test_ref_compact_cv_confidence(self, parser: Parser) -> None:
        r = parser.parse("joao 3 16")
        assert r.confidence == pytest.approx(0.95, abs=0.01)

    def test_ref_compact_c_confidence(self, parser: Parser) -> None:
        r = parser.parse("joao 3")
        assert r.confidence == pytest.approx(0.92, abs=0.01)

    def test_next_confidence(self, parser: Parser) -> None:
        r = parser.parse("proximo")
        assert r.confidence == pytest.approx(0.99, abs=0.01)

    def test_previous_confidence(self, parser: Parser) -> None:
        r = parser.parse("anterior")
        assert r.confidence == pytest.approx(0.99, abs=0.01)

    def test_more_confidence(self, parser: Parser) -> None:
        r = parser.parse("mais 3")
        assert r.confidence == pytest.approx(0.97, abs=0.01)

    def test_stay_confidence(self, parser: Parser) -> None:
        r = parser.parse("ainda nesse capitulo")
        assert r.confidence == pytest.approx(0.90, abs=0.01)

    def test_ambiguous_book_reduces_confidence(self, parser: Parser) -> None:
        """'jo' é ambíguo (confidence=0.5) → c_parser = 0.95 * 0.5 = 0.475."""
        r = parser.parse("jo 3 16")
        assert r.action == "show"
        assert r.confidence == pytest.approx(0.95 * 0.5, abs=0.01)


# ---------------------------------------------------------------------------
# Uso de BibleState para contexto
# ---------------------------------------------------------------------------

class TestStateContext:
    def test_stay_uses_state(self, parser: Parser) -> None:
        """STAY não precisa de estado para produzir Intent (apenas jump)."""
        r = parser.parse("continua nesse capitulo", state=_state())
        assert r.action == "jump"
        assert r.amount is None

    def test_vers_with_state_chapter(self, parser: Parser) -> None:
        """'joao versiculo 16' com state.chapter=3 → chapter=3, verse=16."""
        r = parser.parse("joao versiculo 16", state=_state(chapter=3))
        assert r.action == "show"
        assert r.chapter == 3
        assert r.verse == 16

    def test_vers_without_state(self, parser: Parser) -> None:
        """'joao versiculo 16' sem state → chapter=None (apenas verse)."""
        r = parser.parse("joao versiculo 16", state=None)
        assert r.action == "show"
        assert r.verse == 16
        # chapter pode ser None ou do state; sem state, é None
        assert r.chapter is None


# ---------------------------------------------------------------------------
# Navegação avançada
# ---------------------------------------------------------------------------

class TestNavigationAdvanced:
    def test_proximo_5(self, parser: Parser) -> None:
        r = parser.parse("proximo 5")
        assert r.action == "next"
        assert r.amount == 5

    def test_anterior_3(self, parser: Parser) -> None:
        r = parser.parse("anterior 3")
        assert r.action == "previous"
        assert r.amount == 3

    def test_seguinte(self, parser: Parser) -> None:
        r = parser.parse("seguinte")
        assert r.action == "next"
        assert r.amount == 1

    def test_voltar(self, parser: Parser) -> None:
        r = parser.parse("voltar")
        assert r.action == "previous"
        assert r.amount == 1

    def test_pula_2(self, parser: Parser) -> None:
        r = parser.parse("pula 2")
        assert r.action == "next"
        assert r.amount == 2

    def test_mais_cinco(self, parser: Parser) -> None:
        r = parser.parse("mais cinco")
        assert r.action == "next"
        assert r.amount == 5

    def test_avanca(self, parser: Parser) -> None:
        r = parser.parse("avanca")
        assert r.action == "next"
        assert r.amount == 1

    def test_proximo_versiculo(self, parser: Parser) -> None:
        """'proximo versiculo' → next amount=1."""
        r = parser.parse("proximo versiculo")
        assert r.action == "next"
        assert r.amount == 1


# ---------------------------------------------------------------------------
# Casos extremos
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_livro_inexistente(self, parser: Parser) -> None:
        """Livro não reconhecido → uncertain (se há gatilho) ou none."""
        r = parser.parse("mostra o livro de xyz")
        assert r.action == "uncertain"

    def test_so_numero(self, parser: Parser) -> None:
        """Apenas número → none (não é comando)."""
        r = parser.parse("42")
        assert r.action == "none"

    def test_so_livro_sem_numero(self, parser: Parser) -> None:
        """Apenas 'joao' sem números → uncertain (há referência ao livro)."""
        r = parser.parse("joao")
        # Livro encontrado mas sem cap/vers → uncertain
        assert r.action == "uncertain"

    def test_raw_preserved(self, parser: Parser) -> None:
        r = parser.parse("João 3:16")
        assert r.raw == "João 3:16"

    def test_source_is_parser(self, parser: Parser) -> None:
        r = parser.parse("joao 3 16")
        assert r.source == "parser"


# ---------------------------------------------------------------------------
# Pistas bíblicas para busca semântica → uncertain
# ---------------------------------------------------------------------------


class TestBiblicalSearchHints:
    """Testa frases bíblicas descritivas que devem retornar uncertain
    para encaminhamento ao LLM, mesmo sem gatilhos explícitos."""

    # --- DEVE retornar uncertain ---

    def test_vale_da_sombra_da_morte(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("vale da sombra da morte")
        assert r.action == "uncertain"
        assert r.confidence == 0.0
        assert r.source == "parser"

    def test_todas_as_coisas_cooperam(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("todas as coisas cooperam para o bem daqueles que amam a Deus")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_fe_e_a_certeza(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("a fé é a certeza das coisas que se esperam")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_tudo_posso_naquele(self, parser: Parser) -> None:
        """Múltiplas pistas bíblicas (posso + naquele + fortalece) → uncertain."""
        r = parser.parse("tudo posso naquele que me fortalece")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_deus_amou_o_mundo(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("deus amou o mundo de tal maneira")
        assert r.action == "uncertain"
        assert r.confidence == 0.0

    def test_sal_da_terra(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("vós sois o sal da terra")
        assert r.action == "uncertain"

    def test_luz_do_mundo(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("vós sois a luz do mundo")
        assert r.action == "uncertain"

    def test_senhor_e_meu_pastor(self, parser: Parser) -> None:
        """Frase bíblica forte → uncertain."""
        r = parser.parse("o senhor é meu pastor")
        assert r.action == "uncertain"

    # --- DEVE retornar none (frases comuns de culto) ---

    def test_boa_noite_igreja(self, parser: Parser) -> None:
        """Saudação comum → none (não ativa LLM)."""
        r = parser.parse("boa noite igreja")
        assert r.action == "none"

    def test_amem_irmaos(self, parser: Parser) -> None:
        """Saudação comum → none."""
        r = parser.parse("amém irmãos")
        assert r.action == "none"

    def test_paz_do_senhor(self, parser: Parser) -> None:
        """Saudação comum → none (senhor isolado não pontua)."""
        r = parser.parse("paz do senhor")
        assert r.action == "none"

    def test_vamos_cantar(self, parser: Parser) -> None:
        """Anúncio comum → none (vamos removido dos command triggers)."""
        r = parser.parse("vamos cantar")
        assert r.action == "none"

    def test_podem_sentar(self, parser: Parser) -> None:
        """Anúncio comum → none."""
        r = parser.parse("podem sentar")
        assert r.action == "none"

    def test_vamos_orar(self, parser: Parser) -> None:
        """Anúncio comum → none."""
        r = parser.parse("vamos orar")
        assert r.action == "none"

    def test_podem_ficar_em_pe(self, parser: Parser) -> None:
        """Anúncio comum → none."""
        r = parser.parse("podem ficar em pé")
        assert r.action == "none"

    def test_abram_os_hinarios(self, parser: Parser) -> None:
        """Anúncio comum → none (os removido de aliases de Oséias)."""
        r = parser.parse("abram os hinários")
        assert r.action == "none"

    def test_gloria_a_deus(self, parser: Parser) -> None:
        """Saudação comum → none (deus e gloria removidos dos hints)."""
        r = parser.parse("glória a Deus")
        assert r.action == "none"

    # --- DEVE continuar funcionando (regressão) ---

    def test_joao_3_16_still_works(self, parser: Parser) -> None:
        """Referência direta continua funcionando."""
        r = parser.parse("João 3:16")
        assert r.action == "show"
        assert r.book == "João"
        assert r.chapter == 3
        assert r.verse == 16

    def test_hebreus_11_1_still_works(self, parser: Parser) -> None:
        """Referência direta continua funcionando."""
        r = parser.parse("Hebreus 11:1")
        assert r.action == "show"
        assert r.book == "Hebreus"

    def test_romanos_8_28_still_works(self, parser: Parser) -> None:
        """Referência direta continua funcionando."""
        r = parser.parse("Romanos 8:28")
        assert r.action == "show"
        assert r.book == "Romanos"

    def test_proximo_still_works(self, parser: Parser) -> None:
        """Navegação continua funcionando."""
        r = parser.parse("próximo")
        assert r.action == "next"

    def test_anterior_still_works(self, parser: Parser) -> None:
        """Navegação continua funcionando."""
        r = parser.parse("anterior")
        assert r.action == "previous"

    def test_mais_dois_still_works(self, parser: Parser) -> None:
        """Navegação continua funcionando."""
        r = parser.parse("mais dois")
        assert r.action == "next"
        assert r.amount == 2

    # --- Gatilhos existentes continuam funcionando ---

    def test_abre_aquele_texto_still_uncertain(self, parser: Parser) -> None:
        """Gatilho de comando + gatilho indireto → uncertain."""
        r = parser.parse("abre aquele texto")
        assert r.action == "uncertain"

    def test_mostrar_versiculo_da_fe_still_uncertain(self, parser: Parser) -> None:
        """Gatilho de comando + gatilho indireto → uncertain."""
        r = parser.parse("mostrar aquele versículo da fé")
        assert r.action == "uncertain"


# ---------------------------------------------------------------------------
# Alias "da" de Daniel removido — regressão
# ---------------------------------------------------------------------------


class TestDanielAliasFix:
    """Testa que a remoção do alias "da" de Daniel não quebra a resolução
    de Daniel e não causa falsos positivos com a preposição "da"."""

    def test_daniel_full_name_works(self, parser: Parser) -> None:
        """'Daniel' continua resolvendo."""
        r = parser.parse("Daniel 3:16")
        assert r.action == "show"
        assert r.book == "Daniel"

    def test_daniel_dn_alias_works(self, parser: Parser) -> None:
        """'Dn' (alias) continua resolvendo."""
        r = parser.parse("Dn 3:16")
        assert r.action == "show"
        assert r.book == "Daniel"

    def test_daniel_dan_alias_works(self, parser: Parser) -> None:
        """'Dan' (alias) continua resolvendo."""
        r = parser.parse("Dan 3:16")
        assert r.action == "show"
        assert r.book == "Daniel"

    def test_da_preposition_no_false_book(self, parser: Parser) -> None:
        """'vale da sombra da morte' não casa 'da' como Daniel."""
        r = parser.parse("vale da sombra da morte")
        # Não deve ter book=Daniel — deve ser uncertain via pistas bíblicas
        assert r.book is None or r.book != "Daniel"


# ---------------------------------------------------------------------------
# Alias "os" de Oséias removido — regressão
# ---------------------------------------------------------------------------


class TestOseiasAliasFix:
    """Testa que a remoção do alias "os" de Oséias não quebra a resolução
    de Oséias e não causa falsos positivos com o artigo "os"."""

    def test_oseias_full_name_works(self, parser: Parser) -> None:
        """'Oséias' continua resolvendo."""
        r = parser.parse("Oséias 1:1")
        assert r.action == "show"
        assert r.book == "Oséias"

    def test_oseias_hos_alias_works(self, parser: Parser) -> None:
        """'hos' (alias) continua resolvendo."""
        r = parser.parse("hos 1:1")
        assert r.action == "show"
        assert r.book == "Oséias"

    def test_os_article_no_false_book(self, parser: Parser) -> None:
        """'abram os hinários' não casa 'os' como Oséias."""
        r = parser.parse("abram os hinários")
        assert r.action == "none"
        assert r.book is None or r.book != "Oséias"
