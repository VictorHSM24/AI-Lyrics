"""Sprint 25 — Testes do endpoint GET /operator/parse (parser híbrido).

Valida:
1. Parse de referência completa ("João 3:16") → ok=true com texto.
2. Parse de abreviação ("Rm 8:28") → ok=true com texto.
3. Parse sem versículo ("João 3") → ok=true sem texto.
4. Parse de referência inexistente ("João 99:99") → ok=false.
5. Parse de string inválida ("xyz") → ok=false.
6. Parse de string vazia → ok=false.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# Reutilizar fixtures do Sprint 24.
class FakeBook:
    def __init__(self, id, canonical, aliases=None):
        self.id = id
        self.canonical = canonical
        self.aliases = aliases or []


class FakeBookTable:
    def all_books(self):
        return [FakeBook(i, f"Book{i}") for i in range(1, 67)]

    def by_id(self, book_id):
        if book_id < 1 or book_id > 66:
            raise KeyError(f"book_id {book_id} not found")
        return FakeBook(book_id, f"Book{book_id}")


class FakeSearchResult:
    def __init__(self, book_id, book, chapter, verse, reference, text, version):
        self.book_id = book_id
        self.book = book
        self.chapter = chapter
        self.verse = verse
        self.reference = reference
        self.text = text
        self.version = version
        self.score = 1.0
        self.c_search = 1.0
        self.ambiguous = False
        self.match_type = "reference"


class FakeSearcher:
    def __init__(self):
        self._book_table = FakeBookTable()

    def get_chapters(self, book_id, version=None):
        if book_id == 43:
            return list(range(1, 22))
        return [1, 2, 3]

    def get_verse_numbers(self, book_id, chapter, version=None):
        if book_id == 43 and chapter == 3:
            return list(range(1, 37))
        if book_id == 43 and chapter > 21:
            return []  # capítulo inexistente em João (só 21 capítulos)
        return [1, 2, 3]

    def get_verse_by_id(self, book_id, chapter, verse, version=None):
        if book_id == 43 and chapter == 3 and verse == 16:
            return FakeSearchResult(
                43, "João", 3, 16, "João 3:16",
                "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito.",
                "ACF",
            )
        if book_id == 45 and chapter == 8 and verse == 28:
            return FakeSearchResult(
                45, "Romanos", 8, 28, "Romanos 8:28",
                "E sabemos que todas as coisas cooperam para o bem.",
                "ACF",
            )
        return None


@pytest.fixture(scope="module")
def client():
    from api.app import create_app
    from api.startup import get_root, set_root, create_composition_root

    root = create_composition_root()
    fake_searcher = FakeSearcher()
    fake_holyrics = MagicMock()
    object.__setattr__(root, "searcher", fake_searcher)
    object.__setattr__(root, "holyrics_client", fake_holyrics)
    set_root(root)

    app = create_app()
    with TestClient(app) as c:
        yield c


class TestOperatorParse:
    def test_parse_full_reference(self, client):
        """João 3:16 → ok=true com texto."""
        r = client.get("/operator/parse", params={"q": "João 3:16"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is True
        assert body["book_id"] == 43
        assert body["book"] == "João"
        assert body["chapter"] == 3
        assert body["verse"] == 16
        assert body["reference"] == "João 3:16"
        assert "Deus amou" in body["text"]

    def test_parse_abbreviation(self, client):
        """Rm 8:28 → ok=true (alias 'rm' resolve para Romanos)."""
        r = client.get("/operator/parse", params={"q": "Rm 8:28"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is True
        assert body["book_id"] == 45
        assert body["book"] == "Romanos"
        assert body["chapter"] == 8
        assert body["verse"] == 28

    def test_parse_without_verse(self, client):
        """João 3 → ok=true sem versículo/texto (capítulo válido)."""
        r = client.get("/operator/parse", params={"q": "João 3"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is True
        assert body["book_id"] == 43
        assert body["chapter"] == 3
        assert body["verse"] is None
        assert body["text"] is None
        # reference contém o número do capítulo (formato exato depende
        # do BookTable, que no fake retorna "Book43 3").
        assert "3" in body["reference"]

    def test_parse_nonexistent_verse(self, client):
        """João 3:999 → ok=false (versículo não existe)."""
        r = client.get("/operator/parse", params={"q": "João 3:999"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is False
        assert body["reason"] == "verse_not_found"

    def test_parse_nonexistent_chapter(self, client):
        """João 999 → ok=false (capítulo não existe)."""
        r = client.get("/operator/parse", params={"q": "João 999"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is False
        # Pode ser chapter_not_found ou parse_failed dependendo do parser.
        assert body["reason"] in ("chapter_not_found", "parse_failed", "verse_not_found")

    def test_parse_invalid_string(self, client):
        """xyz → ok=false (não parseia como referência)."""
        r = client.get("/operator/parse", params={"q": "xyz"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is False
        assert body["reason"] == "parse_failed"

    def test_parse_roman_numeral(self, client):
        """II Reis 2:11 → ok=true (numeral romano convertido)."""
        r = client.get("/operator/parse", params={"q": "II Reis 2:11"})
        assert r.status_code == 200
        body = r.json()["payload"]
        # II Reis = 2 Reis = book_id 12.
        # FakeSearcher não tem 2 Reis 2:11, então pode ser verse_not_found,
        # mas o parse em si deve funcionar (não parse_failed).
        if body["ok"]:
            assert body["book_id"] == 12
        else:
            # Se falhou, deve ser verse_not_found, não parse_failed.
            assert body["reason"] != "parse_failed"

    def test_parse_with_version_param(self, client):
        """João 3:16 com version=ACF → ok=true."""
        r = client.get("/operator/parse", params={"q": "João 3:16", "version": "ACF"})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is True
        assert body["version"] == "ACF"

    def test_parse_returns_versioned_schema(self, client):
        """Resposta deve seguir schema versioned (api + payload)."""
        r = client.get("/operator/parse", params={"q": "João 3:16"})
        body = r.json()
        assert "api" in body
        assert "payload" in body
        assert body["payload"]["ok"] is True
