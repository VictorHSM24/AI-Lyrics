"""Router /operator — Painel do Operador (Sprint 24).

Endpoints para navegação bíblica estruturada e apresentação manual
de versículos no Holyrics, permitindo controle rápido sem abrir o
Holyrics diretamente.

Princípios:
- Toda apresentação usa HolyricsClient.show_verse() (camada oficial).
- Toda apresentação publica VersePresented no EventBus, para que o
  painel do operador e todos os componentes atualizem automaticamente.
- Navegação usa Searcher (mesma base SQLite do pipeline de IA).
- Histórico vem do EventStore (eventos VersePresented persistidos).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from api.dependencies import get_composition_root
from api.schemas import versioned
from api.startup import CompositionRoot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/operator", tags=["operator"])


# ---------------------------------------------------------------------------
# Helpers — acesso aos serviços do CompositionRoot.
# ---------------------------------------------------------------------------


def _get_searcher(root: CompositionRoot):
    searcher = getattr(root, "searcher", None)
    if searcher is None:
        raise HTTPException(503, "Searcher não inicializado.")
    return searcher


def _get_holyrics(root: CompositionRoot):
    client = getattr(root, "holyrics_client", None)
    if client is None:
        raise HTTPException(503, "HolyricsClient não inicializado.")
    return client


def _get_book_table(root: CompositionRoot):
    """Obtém BookTable do searcher ou do composition root."""
    # O BookTable é usado internamente pelo Searcher. Expor via searcher.
    searcher = _get_searcher(root)
    book_table = getattr(searcher, "_book_table", None)
    if book_table is None:
        raise HTTPException(503, "BookTable não disponível.")
    return book_table


def _default_version(root: CompositionRoot) -> str:
    """Versão bíblica padrão da config."""
    cfg = root.config
    verse_cfg = getattr(cfg, "verse", None)
    if verse_cfg is not None:
        return getattr(verse_cfg, "default_version", "ACF") or "ACF"
    return "ACF"


# ---------------------------------------------------------------------------
# Schemas Pydantic.
# ---------------------------------------------------------------------------


class BookModel(BaseModel):
    """Livro bíblico para o seletor do operador."""
    model_config = ConfigDict(frozen=True)
    id: int
    canonical: str
    aliases: list[str] = []


class ChapterListModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    book_id: int
    chapters: list[int]


class VerseListModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    book_id: int
    chapter: int
    verses: list[int]


class VerseModel(BaseModel):
    """Versículo com texto para exibição no card."""
    model_config = ConfigDict(frozen=True)
    book_id: int
    book: str
    chapter: int
    verse: int
    reference: str
    text: str
    version: str


class ParseReferenceResult(BaseModel):
    """Resultado de GET /operator/parse — validação de referência bíblica.

    Sprint 25: usado pelo QuickSearch do frontend para validar que
    uma referência parseada no frontend realmente existe na Bíblia
    (parser híbrido: frontend sugere, backend confirma).
    """
    model_config = ConfigDict(frozen=True)
    ok: bool
    query: str
    book_id: int | None = None
    book: str | None = None
    chapter: int | None = None
    verse: int | None = None
    reference: str | None = None
    text: str | None = None
    version: str | None = None
    reason: str | None = None


class PresentVerseRequest(BaseModel):
    """Payload para POST /operator/present — apresenta versículo no Holyrics."""
    book_id: int
    chapter: int
    verse: int
    version: str | None = None
    quick: bool = False


class PresentVerseResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    ok: bool
    message: str
    reference: str
    book_id: int
    chapter: int
    verse: int
    version: str
    holyrics_status: str = ""
    latency_ms: int = 0


class HistoryEntryModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    reference: str
    book: str
    book_id: int
    chapter: int
    verse: int
    version: str
    timestamp: float
    holyrics_status: str = ""
    holyrics_latency_ms: int = 0
    total_latency_ms: int = 0
    quick_presentation: bool = False
    origin: str = ""


class HistoryModel(BaseModel):
    model_config = ConfigDict(frozen=True)
    entries: list[HistoryEntryModel]
    count: int


# ---------------------------------------------------------------------------
# Endpoints — Navegação bíblica.
# ---------------------------------------------------------------------------


@router.get("/books")
@router.get("/books/")
async def list_books(
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Lista os 66 livros da Bíblia para o seletor do operador."""
    book_table = _get_book_table(root)
    books = book_table.all_books()
    models = [
        BookModel(id=b.id, canonical=b.canonical, aliases=list(b.aliases))
        for b in books
    ]
    return versioned({"books": [m.model_dump() for m in models], "count": len(models)})


@router.get("/books/{book_id}/chapters")
@router.get("/books/{book_id}/chapters/")
async def list_chapters(
    book_id: int,
    version: str | None = Query(None),
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Lista os capítulos disponíveis para um livro."""
    if book_id < 1 or book_id > 66:
        raise HTTPException(400, f"book_id inválido: {book_id} (1..66)")
    searcher = _get_searcher(root)
    ver = version or _default_version(root)
    try:
        chapters = searcher.get_chapters(book_id, version=ver)
    except Exception as e:
        logger.warning("operator: erro listando chapters: %s", e)
        raise HTTPException(500, f"Erro ao listar capítulos: {e}")
    model = ChapterListModel(book_id=book_id, chapters=chapters)
    return versioned(model)


@router.get("/books/{book_id}/chapters/{chapter}/verses")
@router.get("/books/{book_id}/chapters/{chapter}/verses/")
async def list_verses(
    book_id: int,
    chapter: int,
    version: str | None = Query(None),
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Lista os versículos disponíveis para um capítulo."""
    if book_id < 1 or book_id > 66:
        raise HTTPException(400, f"book_id inválido: {book_id}")
    if chapter < 1:
        raise HTTPException(400, f"chapter inválido: {chapter}")
    searcher = _get_searcher(root)
    ver = version or _default_version(root)
    try:
        verses = searcher.get_verse_numbers(book_id, chapter, version=ver)
    except Exception as e:
        logger.warning("operator: erro listando verses: %s", e)
        raise HTTPException(500, f"Erro ao listar versículos: {e}")
    model = VerseListModel(book_id=book_id, chapter=chapter, verses=verses)
    return versioned(model)


@router.get("/parse")
@router.get("/parse/")
async def parse_reference(
    q: str = Query(..., description="Referência bíblica a validar (ex.: 'João 3:16', 'Rm 8:28')"),
    version: str | None = Query(None),
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Valida uma referência bíblica e retorna IDs + texto se existir.

    Sprint 25: parser híbrido. O frontend faz parse instantâneo para
    sugestões (debounced 50ms), e ao selecionar chama este endpoint
    para confirmar que a referência realmente existe na versão
    solicitada (capítulo/versículo válidos).

    Diferença vs GET /verse: este endpoint aceita string livre
    ("João 3:16", "Rm 8:28") enquanto /verse exige IDs numéricos.

    Retorna ParseReferenceResult com ok=true se válido, ou ok=false
    com reason explicando a falha.
    """
    from busca.bible_reference import parse_bible_reference

    searcher = _get_searcher(root)
    ver = version or _default_version(root)

    ref = parse_bible_reference(q)
    if ref is None:
        model = ParseReferenceResult(ok=False, query=q, reason="parse_failed")
        return versioned(model)

    # ref tem book (BibleBook enum), chapter, verse_start, verse_end.
    book_id = int(ref.book)
    chapter = ref.chapter
    verse = ref.verse_start  # Pode ser None (ex.: "João 3" sem versículo).

    if verse is None:
        # Sem versículo: validar que o capítulo existe (get_verse_numbers).
        try:
            verses = searcher.get_verse_numbers(book_id, chapter, version=ver)
        except Exception as e:
            logger.warning("operator/parse: erro validando chapter: %s", e)
            model = ParseReferenceResult(ok=False, query=q, reason="search_error")
            return versioned(model)
        if not verses:
            model = ParseReferenceResult(ok=False, query=q, reason="chapter_not_found")
            return versioned(model)
        # Retornar sem texto (capítulo válido, versículo não especificado).
        book_table = _get_book_table(root)
        try:
            book_name = book_table.by_id(book_id).canonical
        except KeyError:
            book_name = str(book_id)
        model = ParseReferenceResult(
            ok=True,
            query=q,
            book_id=book_id,
            book=book_name,
            chapter=chapter,
            verse=None,
            reference=f"{book_name} {chapter}",
            version=ver,
        )
        return versioned(model)

    # Com versículo: buscar texto completo.
    try:
        result = searcher.get_verse_by_id(book_id, chapter, verse, version=ver)
    except Exception as e:
        logger.warning("operator/parse: erro obtendo verse: %s", e)
        model = ParseReferenceResult(ok=False, query=q, reason="search_error")
        return versioned(model)

    if result is None:
        model = ParseReferenceResult(ok=False, query=q, reason="verse_not_found")
        return versioned(model)

    model = ParseReferenceResult(
        ok=True,
        query=q,
        book_id=result.book_id,
        book=result.book,
        chapter=result.chapter,
        verse=result.verse,
        reference=result.reference,
        text=result.text,
        version=result.version,
    )
    return versioned(model)


@router.get("/verse")
@router.get("/verse/")
async def get_verse(
    book_id: int = Query(...),
    chapter: int = Query(...),
    verse: int = Query(...),
    version: str | None = Query(None),
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Obtém o texto de um versículo específico."""
    searcher = _get_searcher(root)
    ver = version or _default_version(root)
    try:
        result = searcher.get_verse_by_id(book_id, chapter, verse, version=ver)
    except Exception as e:
        logger.warning("operator: erro obtendo verse: %s", e)
        raise HTTPException(500, f"Erro ao obter versículo: {e}")
    if result is None:
        raise HTTPException(404, "Versículo não encontrado.")
    model = VerseModel(
        book_id=result.book_id,
        book=result.book,
        chapter=result.chapter,
        verse=result.verse,
        reference=result.reference,
        text=result.text,
        version=result.version,
    )
    return versioned(model)


# ---------------------------------------------------------------------------
# Endpoints — Apresentação no Holyrics.
# ---------------------------------------------------------------------------


@router.post("/present")
@router.post("/present/")
async def present_verse(
    req: PresentVerseRequest,
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Apresenta um versículo no Holyrics e publica VersePresented no EventBus.

    Sprint 24: usa HolyricsClient.show_verse() (camada oficial de
    integração), garantindo que toda apresentação, seja automática
    (pipeline de IA) ou manual (painel do operador), passe pela mesma
    camada. Após a apresentação, publica VersePresented no EventBus
    para que o painel e todos os componentes atualizem automaticamente.
    """
    searcher = _get_searcher(root)
    holyrics = _get_holyrics(root)
    ver = req.version or _default_version(root)

    # Resolver o versículo para obter texto e referência formatada.
    try:
        result = searcher.get_verse_by_id(req.book_id, req.chapter, req.verse, version=ver)
    except Exception as e:
        logger.warning("operator: erro resolvendo verse: %s", e)
        raise HTTPException(500, f"Erro ao resolver versículo: {e}")
    if result is None:
        raise HTTPException(404, "Versículo não encontrado na base bíblica.")

    # Apresentar no Holyrics via camada oficial.
    t0 = time.monotonic()
    try:
        show_result = holyrics.show_verse(
            book_id=req.book_id,
            chapter=req.chapter,
            verse=req.verse,
            version=ver,
            quick=req.quick,
        )
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.warning("operator: erro apresentando no Holyrics: %s", e)
        # Publicar VersePresentationFailed para o painel refletir o erro.
        _publish_failure(root, result, str(e), latency_ms)
        error_type = type(e).__name__
        return versioned(PresentVerseResult(
            ok=False,
            message=f"Falha ao apresentar no Holyrics: {e}",
            reference=result.reference,
            book_id=req.book_id,
            chapter=req.chapter,
            verse=req.verse,
            version=ver,
            latency_ms=latency_ms,
        ).model_dump())

    latency_ms = int((time.monotonic() - t0) * 1000)

    # Publicar VersePresented no EventBus para atualização automática.
    _publish_presented(root, result, show_result.status, ver, req.quick, latency_ms)

    return versioned(PresentVerseResult(
        ok=True,
        message=f"Versículo apresentado: {result.reference}",
        reference=result.reference,
        book_id=req.book_id,
        chapter=req.chapter,
        verse=req.verse,
        version=ver,
        holyrics_status=show_result.status,
        latency_ms=latency_ms,
    ).model_dump())


def _publish_presented(
    root: CompositionRoot,
    search_result: Any,
    holyrics_status: str,
    version: str,
    quick: bool,
    latency_ms: int,
) -> None:
    """Publica VersePresented no EventBus (mesmo formato do pipeline automático)."""
    from pipeline.events import VersePresented
    from pipeline.metadata import EventMetadata

    session_id = root.session.session_id
    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="OperatorPanel",
    )
    presented = VersePresented(
        meta=meta,
        book=search_result.book,
        book_id=search_result.book_id,
        chapter=search_result.chapter,
        verse=search_result.verse,
        version=version,
        reference=search_result.reference,
        quick_presentation=quick,
        holyrics_status=holyrics_status,
        holyrics_latency_ms=latency_ms,
        total_latency_ms=latency_ms,
    )
    root.bus.publish(presented)
    logger.info(
        "OperatorPanel presented %s (status=%s, latency=%dms)",
        search_result.reference,
        holyrics_status,
        latency_ms,
    )


def _publish_failure(
    root: CompositionRoot,
    search_result: Any,
    error_message: str,
    latency_ms: int,
) -> None:
    """Publica VersePresentationFailed no EventBus."""
    from pipeline.events import VersePresentationFailed
    from pipeline.metadata import EventMetadata

    session_id = root.session.session_id
    meta = EventMetadata.for_initial(
        session_id=session_id,
        origin="OperatorPanel",
    )
    failed = VersePresentationFailed(
        meta=meta,
        book=search_result.book,
        book_id=search_result.book_id,
        chapter=search_result.chapter,
        verse=search_result.verse,
        reference=search_result.reference,
        failure_stage="holyrics",
        error_type="operator_manual",
        error_message=error_message,
        latency_ms=latency_ms,
    )
    root.bus.publish(failed)


# ---------------------------------------------------------------------------
# Endpoints — Histórico e versículo atual.
# ---------------------------------------------------------------------------


@router.get("/history")
@router.get("/history/")
async def get_history(
    limit: int = Query(50, ge=1, le=500),
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Histórico de apresentações (eventos VersePresented).

    Sprint 24: consulta o EventStore por eventos VersePresented,
    retornando os mais recentes primeiro. O histórico é em memória
    (não persistido em arquivo/banco nesta sprint).
    """
    from pipeline.events import VersePresented

    try:
        events = root.store.by_event(VersePresented)
    except Exception as e:
        logger.warning("operator: erro consultando history: %s", e)
        raise HTTPException(500, f"Erro ao consultar histórico: {e}")

    # Mais recentes primeiro.
    entries: list[HistoryEntryModel] = []
    for ev in reversed(events[-limit:]):
        entries.append(HistoryEntryModel(
            reference=ev.reference,
            book=ev.book,
            book_id=ev.book_id,
            chapter=ev.chapter,
            verse=ev.verse,
            version=ev.version,
            timestamp=ev.timestamp,
            holyrics_status=ev.holyrics_status,
            holyrics_latency_ms=ev.holyrics_latency_ms,
            total_latency_ms=ev.total_latency_ms,
            quick_presentation=ev.quick_presentation,
            origin=ev.origin,
        ))
    model = HistoryModel(entries=entries, count=len(entries))
    return versioned(model)


@router.get("/current")
@router.get("/current/")
async def get_current(
    root: CompositionRoot = Depends(get_composition_root),
) -> dict:
    """Último versículo apresentado (ou null se nenhum)."""
    from pipeline.events import VersePresented

    try:
        events = root.store.by_event(VersePresented)
    except Exception as e:
        logger.warning("operator: erro consultando current: %s", e)
        raise HTTPException(500, f"Erro ao consultar versículo atual: {e}")

    if not events:
        return versioned({"current": None})

    ev = events[-1]
    entry = HistoryEntryModel(
        reference=ev.reference,
        book=ev.book,
        book_id=ev.book_id,
        chapter=ev.chapter,
        verse=ev.verse,
        version=ev.version,
        timestamp=ev.timestamp,
        holyrics_status=ev.holyrics_status,
        holyrics_latency_ms=ev.holyrics_latency_ms,
        total_latency_ms=ev.total_latency_ms,
        quick_presentation=ev.quick_presentation,
        origin=ev.origin,
    )
    return versioned({"current": entry.model_dump()})
