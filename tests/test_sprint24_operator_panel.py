"""Sprint 24 — Testes do Painel do Operador (Operator Panel).

Valida:
1. GET /operator/books — lista 66 livros.
2. GET /operator/books/{id}/chapters — lista capítulos.
3. GET /operator/books/{id}/chapters/{c}/verses — lista versículos.
4. GET /operator/verse — obtém texto do versículo.
5. POST /operator/present — apresenta no Holyrics e publica VersePresented.
6. GET /operator/history — histórico de apresentações.
7. GET /operator/current — último versículo apresentado.
8. POST /operator/present com Holyrics offline — publica VersePresentationFailed.
9. Validação de book_id inválido.
10. Searcher.get_chapters / get_verse_numbers / get_verse_by_id.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures — mockar searcher e holyrics_client no composition root.
# ---------------------------------------------------------------------------


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
    """Searcher mockado com dados de João 3."""

    def __init__(self):
        self._book_table = FakeBookTable()
        self._joao_chapters = list(range(1, 22))
        self._joao3_verses = list(range(1, 37))

    def get_chapters(self, book_id, version=None):
        if book_id == 43:
            return self._joao_chapters
        return [1, 2, 3]

    def get_verse_numbers(self, book_id, chapter, version=None):
        if book_id == 43 and chapter == 3:
            return self._joao3_verses
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


class FakeShowResult:
    def __init__(self, status="ok"):
        self.status = status


@pytest.fixture(scope="module")
def client():
    from api.app import create_app
    from api.startup import get_root, set_root, create_composition_root

    # Criar composition root em modo teste (sem componentes pesados).
    root = create_composition_root()

    # Injetar mocks de searcher e holyrics_client.
    fake_searcher = FakeSearcher()
    fake_holyrics = MagicMock()
    fake_holyrics.show_verse.return_value = FakeShowResult("ok")
    object.__setattr__(root, "searcher", fake_searcher)
    object.__setattr__(root, "holyrics_client", fake_holyrics)
    set_root(root)

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# 1. GET /operator/books
# ---------------------------------------------------------------------------


class TestOperatorBooks:
    def test_list_books_returns_66(self, client):
        r = client.get("/operator/books")
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["count"] == 66
        assert len(body["books"]) == 66

    def test_books_have_id_and_canonical(self, client):
        r = client.get("/operator/books")
        books = r.json()["payload"]["books"]
        first = books[0]
        assert first["id"] == 1
        assert "canonical" in first
        assert "aliases" in first

    def test_books_response_is_versioned(self, client):
        r = client.get("/operator/books")
        body = r.json()
        assert "api" in body
        assert "payload" in body


# ---------------------------------------------------------------------------
# 2. GET /operator/books/{id}/chapters
# ---------------------------------------------------------------------------


class TestOperatorChapters:
    def test_list_chapters_joao(self, client):
        r = client.get("/operator/books/43/chapters")
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["book_id"] == 43
        assert len(body["chapters"]) == 21
        assert 1 in body["chapters"]

    def test_list_chapters_invalid_book_id(self, client):
        r = client.get("/operator/books/99/chapters")
        assert r.status_code == 400

    def test_list_chapters_zero_book_id(self, client):
        r = client.get("/operator/books/0/chapters")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 3. GET /operator/books/{id}/chapters/{c}/verses
# ---------------------------------------------------------------------------


class TestOperatorVerses:
    def test_list_verses_joao_3(self, client):
        r = client.get("/operator/books/43/chapters/3/verses")
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["book_id"] == 43
        assert body["chapter"] == 3
        assert len(body["verses"]) == 36
        assert 16 in body["verses"]

    def test_list_verses_invalid_chapter(self, client):
        r = client.get("/operator/books/43/chapters/0/verses")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4. GET /operator/verse
# ---------------------------------------------------------------------------


class TestOperatorVerse:
    def test_get_verse_joao_3_16(self, client):
        r = client.get("/operator/verse", params={"book_id": 43, "chapter": 3, "verse": 16})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["book_id"] == 43
        assert body["chapter"] == 3
        assert body["verse"] == 16
        assert body["reference"] != ""
        assert "Deus" in body["text"] or "amou" in body["text"]

    def test_get_verse_not_found(self, client):
        r = client.get("/operator/verse", params={"book_id": 43, "chapter": 3, "verse": 999})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 5. POST /operator/present
# ---------------------------------------------------------------------------


class TestOperatorPresent:
    def test_present_verse_calls_holyrics_and_publishes_event(self, client):
        from api.startup import get_root
        root = get_root()
        r = client.post("/operator/present", json={
            "book_id": 43, "chapter": 3, "verse": 16, "version": "ACF",
        })
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["ok"] is True
        assert body["reference"] != ""
        assert body["holyrics_status"] == "ok"
        root.holyrics_client.show_verse.assert_called_with(
            book_id=43, chapter=3, verse=16, version="ACF", quick=False,
        )

    def test_present_publishes_verse_presented_to_history(self, client):
        client.post("/operator/present", json={
            "book_id": 43, "chapter": 3, "verse": 16,
        })
        r = client.get("/operator/history")
        body = r.json()["payload"]
        assert body["count"] >= 1
        entry = body["entries"][0]
        assert entry["origin"] == "OperatorPanel"

    def test_present_with_quick_flag(self, client):
        from api.startup import get_root
        root = get_root()
        r = client.post("/operator/present", json={
            "book_id": 43, "chapter": 3, "verse": 16, "quick": True,
        })
        assert r.status_code == 200
        root.holyrics_client.show_verse.assert_called_with(
            book_id=43, chapter=3, verse=16, version="ACF", quick=True,
        )

    def test_present_holyrics_failure_returns_ok_false(self, client):
        from api.startup import get_root
        root = get_root()
        original = root.holyrics_client
        mock = MagicMock()
        mock.show_verse.side_effect = ConnectionError("Holyrics offline")
        object.__setattr__(root, "holyrics_client", mock)
        try:
            r = client.post("/operator/present", json={
                "book_id": 43, "chapter": 3, "verse": 16,
            })
            assert r.status_code == 200
            body = r.json()["payload"]
            assert body["ok"] is False
            assert "offline" in body["message"].lower() or "Holyrics" in body["message"]
        finally:
            object.__setattr__(root, "holyrics_client", original)

    def test_present_verse_not_found(self, client):
        r = client.post("/operator/present", json={
            "book_id": 43, "chapter": 3, "verse": 999,
        })
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# 6. GET /operator/history
# ---------------------------------------------------------------------------


class TestOperatorHistory:
    def test_history_returns_list(self, client):
        r = client.get("/operator/history")
        assert r.status_code == 200
        body = r.json()["payload"]
        assert "entries" in body
        assert "count" in body
        assert isinstance(body["entries"], list)

    def test_history_with_limit(self, client):
        r = client.get("/operator/history", params={"limit": 5})
        assert r.status_code == 200
        body = r.json()["payload"]
        assert body["count"] <= 5


# ---------------------------------------------------------------------------
# 7. GET /operator/current
# ---------------------------------------------------------------------------


class TestOperatorCurrent:
    def test_current_returns_null_or_entry(self, client):
        r = client.get("/operator/current")
        assert r.status_code == 200
        body = r.json()["payload"]
        assert "current" in body

    def test_current_returns_entry_after_present(self, client):
        client.post("/operator/present", json={
            "book_id": 43, "chapter": 3, "verse": 16,
        })
        r = client.get("/operator/current")
        assert r.status_code == 200
        cur = r.json()["payload"]["current"]
        assert cur is not None
        assert cur["origin"] == "OperatorPanel"


# ---------------------------------------------------------------------------
# 8. FakeSearcher — métodos de navegação estruturada.
# ---------------------------------------------------------------------------


class TestSearcherNavigation:
    def test_get_chapters_returns_sorted_list(self):
        s = FakeSearcher()
        chapters = s.get_chapters(43, version="ACF")
        assert chapters == sorted(chapters)
        assert len(chapters) == 21

    def test_get_verse_numbers_returns_sorted_list(self):
        s = FakeSearcher()
        verses = s.get_verse_numbers(43, 3, version="ACF")
        assert verses == sorted(verses)
        assert len(verses) == 36

    def test_get_verse_by_id_returns_text(self):
        s = FakeSearcher()
        result = s.get_verse_by_id(43, 3, 16, version="ACF")
        assert result is not None
        assert result.book_id == 43
        assert result.chapter == 3
        assert result.verse == 16
        assert result.text != ""

    def test_get_verse_by_id_not_found(self):
        s = FakeSearcher()
        result = s.get_verse_by_id(43, 3, 999, version="ACF")
        assert result is None
