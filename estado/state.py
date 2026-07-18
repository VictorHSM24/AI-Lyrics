"""Gerenciador de estado da Bíblia (livro/capítulo/versículo atual).

Responsabilidades:
  - Manter o versículo atual (book_id, chapter, verse, version).
  - Resolver navegação relativa (next/previous com amount).
  - Resolver jump (capítulo inteiro ou salto relativo de versículos).
  - Tratar transições entre capítulos e livros nos limites.
  - Manter histórico de navegação recente.
  - Manter última busca e última intenção executada.
  - Persistir estado em JSON (opcional).

Regras de navegação (doc. técnica §6.1, Blueprint §8):
  - next(amount): verse += amount; overflow de versículo → próximo capítulo v.1;
    overflow de capítulo → próximo livro cap.1 v.1.
  - previous(amount): análogo inverso; underflow de versículo → cap. anterior
    último v.; underflow de capítulo → livro anterior último cap. último v.
  - jump com chapter="current": mantém livro/capítulo, verse=None (cap. inteiro).
  - jump com amount=N: salto relativo de N versículos (equivalente a next(N)
    se N>0, previous(|N|) se N<0).

Limites:
  - Gênesis 1:1 + previous(1) → StateError (não há anterior).
  - Apocalipse 22:21 + next(1) → StateError (não há próximo).
  - Estado vazio + next/previous → StateError ("nenhum versículo aberto ainda").

Estrutura bíblica (chapter_counts, verse_counts):
  - Derivada do índice FTS5 no startup.
  - Injetada via BibleStructure para desacoplar do módulo de busca.
  - load_bible_structure(db_path) carrega de um DB FTS5 via sqlite3 stdlib.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from core.exceptions import StateError
from core.types import Intent, VerseRef

logger = logging.getLogger(__name__)

# Histórico padrão (configurável via BibleStateManager).
_DEFAULT_HISTORY_SIZE: int = 20


# ---------------------------------------------------------------------------
# Estrutura bíblica (limites de capítulo/versículo por livro)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BibleStructure:
    """Estrutura de capítulos e versículos por livro.

    ``chapter_counts[book_id]`` → número de capítulos do livro.
    ``verse_counts[(book_id, chapter)]`` → número de versículos do capítulo.

    Derivada do índice FTS5 no startup. Injetada em ``BibleStateManager``
    para desacoplar do módulo de busca.
    """

    chapter_counts: dict[int, int]
    verse_counts: dict[tuple[int, int], int]

    def chapter_count(self, book_id: int) -> int:
        """Retorna o número de capítulos do livro, ou 0 se desconhecido."""
        return self.chapter_counts.get(book_id, 0)

    def verse_count(self, book_id: int, chapter: int) -> int:
        """Retorna o número de versículos do capítulo, ou 0 se desconhecido."""
        return self.verse_counts.get((book_id, chapter), 0)

    def last_chapter(self, book_id: int) -> int:
        """Retorna o último capítulo do livro."""
        return self.chapter_count(book_id)

    def last_verse(self, book_id: int, chapter: int) -> int:
        """Retorna o último versículo do capítulo."""
        return self.verse_count(book_id, chapter)


def load_bible_structure(db_path: str) -> BibleStructure:
    """Carrega a estrutura bíblica de um banco SQLite FTS5.

    Lê a tabela ``verses`` (schema do ``busca/indexer.py``) e deriva
    chapter_counts e verse_counts. Usa apenas ``sqlite3`` da stdlib —
    não importa do módulo ``busca``.

    Args:
        db_path: caminho para o banco SQLite (ex.: ``"data/bible.pt-br.sqlite"``).

    Returns:
        ``BibleStructure`` populada.

    Raises:
        StateError: DB ausente, tabela não existe, ou erro de SQLite.
    """
    if not os.path.isfile(db_path):
        raise StateError(f"bible database not found: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        try:
            # Verificar se a tabela existe.
            row = conn.execute(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type='table' AND name='verses'"
            ).fetchone()
            if not row or row[0] == 0:
                raise StateError(f"table 'verses' does not exist in {db_path}")

            # chapter_counts: book_id -> max(chapter)
            chapter_counts: dict[int, int] = {}
            for r in conn.execute(
                "SELECT CAST(substr(id, 1, 2) AS INTEGER) AS book_id, "
                "MAX(CAST(substr(id, 3, 3) AS INTEGER)) AS max_chapter "
                "FROM verses GROUP BY book_id"
            ).fetchall():
                chapter_counts[int(r[0])] = int(r[1])

            # verse_counts: (book_id, chapter) -> max(verse)
            verse_counts: dict[tuple[int, int], int] = {}
            for r in conn.execute(
                "SELECT CAST(substr(id, 1, 2) AS INTEGER) AS book_id, "
                "CAST(substr(id, 3, 3) AS INTEGER) AS chapter, "
                "MAX(CAST(substr(id, 6, 3) AS INTEGER)) AS max_verse "
                "FROM verses WHERE CAST(substr(id, 6, 3) AS INTEGER) > 0 "
                "GROUP BY book_id, chapter"
            ).fetchall():
                verse_counts[(int(r[0]), int(r[1]))] = int(r[2])

            return BibleStructure(
                chapter_counts=chapter_counts,
                verse_counts=verse_counts,
            )
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise StateError(f"SQLite error loading bible structure: {e}") from e


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

@dataclass
class BibleState:
    """Estado atual da navegação bíblica.

    ``book_id``, ``chapter``, ``verse`` são ``None`` quando nenhum
    versículo foi aberto ainda.
    """

    book_id: int | None = None
    chapter: int | None = None
    verse: int | None = None       # None = capítulo inteiro
    version: str = "ACF"
    last_shown_at: float = 0.0

    def is_empty(self) -> bool:
        """True se nenhum versículo foi aberto ainda."""
        return self.book_id is None or self.chapter is None


# ---------------------------------------------------------------------------
# Gerenciador de estado
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    """Entrada do histórico de navegação."""

    ref: VerseRef
    timestamp: float
    action: str  # "show", "next", "previous", "jump"


class BibleStateManager:
    """Gerencia o estado da Bíblia e resolve navegação relativa.

    Args:
        structure: ``BibleStructure`` com limites de capítulo/versículo.
        book_names: mapeamento ``book_id -> nome canônico`` (ex.: ``{43: "João"}``).
            Usado para construir ``VerseRef`` com o nome do livro.
        persist_path: caminho para persistência JSON (opcional).
        history_size: número máximo de entradas no histórico (default: 20).
        default_version: versão padrão (default: ``"ACF"``).
    """

    def __init__(
        self,
        structure: BibleStructure,
        book_names: dict[int, str] | None = None,
        persist_path: str | None = None,
        history_size: int = _DEFAULT_HISTORY_SIZE,
        default_version: str = "ACF",
    ) -> None:
        self._structure = structure
        self._book_names = book_names or {}
        self._persist_path = persist_path
        self._history_size = history_size
        self._default_version = default_version
        self._state = BibleState(version=default_version)
        self._history: deque[HistoryEntry] = deque(maxlen=history_size)
        self._last_search: str | None = None  # query da última busca
        self._last_intent: Intent | None = None  # última intenção executada

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------

    def current(self) -> BibleState:
        """Retorna uma cópia do estado atual."""
        return BibleState(
            book_id=self._state.book_id,
            chapter=self._state.chapter,
            verse=self._state.verse,
            version=self._state.version,
            last_shown_at=self._state.last_shown_at,
        )

    def current_ref(self) -> VerseRef | None:
        """Retorna ``VerseRef`` do estado atual, ou ``None`` se vazio."""
        if self._state.is_empty():
            return None
        return VerseRef(
            book_id=self._state.book_id,  # type: ignore[arg-type]
            book=self._book_names.get(self._state.book_id, ""),  # type: ignore[arg-type]
            chapter=self._state.chapter,  # type: ignore[arg-type]
            verse=self._state.verse,
            version=self._state.version,
        )

    def history(self) -> list[HistoryEntry]:
        """Retorna o histórico de navegação (mais recente primeiro)."""
        return list(reversed(self._history))

    def last_search(self) -> str | None:
        """Retorna a query da última busca realizada."""
        return self._last_search

    def last_intent(self) -> Intent | None:
        """Retorna a última intenção executada."""
        return self._last_intent

    # ------------------------------------------------------------------
    # Atualização direta
    # ------------------------------------------------------------------

    def set(self, ref: VerseRef) -> None:
        """Atualiza o estado diretamente (após ShowVerse bem-sucedido).

        Args:
            ref: referência válida e validada.

        Raises:
            StateError: referência inválida (book_id fora de range, capítulo
                inexistente, versículo inexistente).
        """
        self._validate_ref(ref)
        self._state.book_id = ref.book_id
        self._state.chapter = ref.chapter
        self._state.verse = ref.verse
        self._state.version = ref.version
        self._state.last_shown_at = time.time()
        self._add_history(ref, "show")
        self._save_if_configured()

    def set_search(self, query: str) -> None:
        """Registra a última busca realizada."""
        self._last_search = query
        self._save_if_configured()

    def set_intent(self, intent: Intent) -> None:
        """Registra a última intenção executada."""
        self._last_intent = intent

    # ------------------------------------------------------------------
    # Aplicação de intenções (navegação)
    # ------------------------------------------------------------------

    def apply(self, intent: Intent) -> VerseRef:
        """Resolve uma intenção e atualiza o estado.

        Actions suportadas: ``show``, ``next``, ``previous``, ``jump``.

        Args:
            intent: intenção do parser ou LLM.

        Returns:
            ``VerseRef`` resolvido.

        Raises:
            StateError: estado vazio para navegação relativa, referência
                inválida, ou limite da Bíblia atingido.
        """
        self._last_intent = intent

        if intent.action == "show":
            return self._apply_show(intent)
        if intent.action == "next":
            return self._apply_next(intent)
        if intent.action == "previous":
            return self._apply_previous(intent)
        if intent.action == "jump":
            return self._apply_jump(intent)
        raise StateError(f"unsupported action for state.apply: {intent.action!r}")

    # ------------------------------------------------------------------
    # Implementações das actions
    # ------------------------------------------------------------------

    def _apply_show(self, intent: Intent) -> VerseRef:
        """Resolve action=show: valida ref, atualiza estado."""
        if intent.book_id is None or intent.chapter is None:
            raise StateError("show requires book_id and chapter")
        verse = intent.verse
        version = intent.version or self._default_version
        ref = VerseRef(
            book_id=intent.book_id,
            book=intent.book or self._book_names.get(intent.book_id, ""),
            chapter=intent.chapter,
            verse=verse,
            version=version,
        )
        self._validate_ref(ref)
        self._state.book_id = ref.book_id
        self._state.chapter = ref.chapter
        self._state.verse = ref.verse
        self._state.version = ref.version
        self._state.last_shown_at = time.time()
        self._add_history(ref, "show")
        self._save_if_configured()
        return ref

    def _apply_next(self, intent: Intent) -> VerseRef:
        """Resolve action=next: avança N versículos."""
        if self._state.is_empty():
            raise StateError("nenhum versículo aberto ainda")
        amount = intent.amount if intent.amount is not None else 1
        if amount < 0:
            raise StateError(f"next amount must be non-negative, got {amount}")
        ref = self._advance(amount)
        self._state.last_shown_at = time.time()
        self._add_history(ref, "next")
        self._save_if_configured()
        return ref

    def _apply_previous(self, intent: Intent) -> VerseRef:
        """Resolve action=previous: retrocede N versículos."""
        if self._state.is_empty():
            raise StateError("nenhum versículo aberto ainda")
        amount = intent.amount if intent.amount is not None else 1
        if amount < 0:
            raise StateError(f"previous amount must be non-negative, got {amount}")
        ref = self._retreat(amount)
        self._state.last_shown_at = time.time()
        self._add_history(ref, "previous")
        self._save_if_configured()
        return ref

    def _apply_jump(self, intent: Intent) -> VerseRef:
        """Resolve action=jump.

        Dois modos:
          - jump com amount=N: salto relativo de N versículos
            (N>0 → avança, N<0 → retrocede).
          - jump com chapter="current" (ou sem amount): mantém
            livro/capítulo, verse=None (capítulo inteiro).
        """
        if self._state.is_empty():
            raise StateError("nenhum versículo aberto ainda")

        # Modo 1: jump relativo com amount.
        if intent.amount is not None:
            if intent.amount > 0:
                ref = self._advance(intent.amount)
                action = "jump"
            elif intent.amount < 0:
                ref = self._retreat(-intent.amount)
                action = "jump"
            else:
                # amount=0: manter posição atual.
                ref = self._current_as_ref()
                action = "jump"
            self._state.last_shown_at = time.time()
            self._add_history(ref, action)
            self._save_if_configured()
            return ref

        # Modo 2: jump para capítulo inteiro (chapter="current").
        ref = VerseRef(
            book_id=self._state.book_id,  # type: ignore[arg-type]
            book=self._book_names.get(self._state.book_id, ""),  # type: ignore[arg-type]
            chapter=self._state.chapter,  # type: ignore[arg-type]
            verse=None,
            version=self._state.version,
        )
        self._state.verse = None
        self._state.last_shown_at = time.time()
        self._add_history(ref, "jump")
        self._save_if_configured()
        return ref

    # ------------------------------------------------------------------
    # Navegação interna (com transições de capítulo/livro)
    # ------------------------------------------------------------------

    def _advance(self, amount: int) -> VerseRef:
        """Avança ``amount`` versículos a partir do estado atual.

        Transições:
          - verse overflow → próximo capítulo, verse=1.
          - chapter overflow → próximo livro, chapter=1, verse=1.
          - Fim da Bíblia → StateError.
        """
        book_id = self._state.book_id  # type: ignore[assignment]
        chapter = self._state.chapter  # type: ignore[assignment]
        verse = self._state.verse
        version = self._state.version

        # Se verse é None (capítulo inteiro), começar do verso 0 (antes do v.1).
        current_verse = verse if verse is not None else 0

        remaining = amount

        while remaining > 0:
            current_verse += 1
            last_v = self._structure.last_verse(book_id, chapter)
            if current_verse > last_v:
                # Overflow de versículo → próximo capítulo.
                chapter += 1
                last_c = self._structure.last_chapter(book_id)
                if chapter > last_c:
                    # Overflow de capítulo → próximo livro.
                    book_id += 1
                    if book_id > 66:
                        raise StateError(
                            "não há versículo seguinte (fim da Bíblia)"
                        )
                    chapter = 1
                    # Garantir que o livro tem capítulo 1.
                    if self._structure.last_chapter(book_id) == 0:
                        raise StateError(
                            f"livro {book_id} não encontrado na estrutura"
                        )
                current_verse = 1
                # Verificar se o capítulo tem versículos.
                if self._structure.last_verse(book_id, chapter) == 0:
                    raise StateError(
                        f"capítulo {chapter} do livro {book_id} não encontrado"
                    )
            remaining -= 1

        ref = VerseRef(
            book_id=book_id,
            book=self._book_names.get(book_id, ""),
            chapter=chapter,
            verse=current_verse,
            version=version,
        )
        self._state.book_id = book_id
        self._state.chapter = chapter
        self._state.verse = current_verse
        return ref

    def _retreat(self, amount: int) -> VerseRef:
        """Retrocede ``amount`` versículos a partir do estado atual.

        Transições:
          - verse underflow → capítulo anterior, último verse.
          - chapter underflow → livro anterior, último capítulo, último verse.
          - Início da Bíblia → StateError.
        """
        book_id = self._state.book_id  # type: ignore[assignment]
        chapter = self._state.chapter  # type: ignore[assignment]
        verse = self._state.verse
        version = self._state.version

        # Se verse é None (capítulo inteiro), começar do último verso + 1.
        current_verse = verse if verse is not None else (
            self._structure.last_verse(book_id, chapter) + 1
        )

        remaining = amount

        while remaining > 0:
            current_verse -= 1
            if current_verse < 1:
                # Underflow de versículo → capítulo anterior.
                chapter -= 1
                if chapter < 1:
                    # Underflow de capítulo → livro anterior.
                    book_id -= 1
                    if book_id < 1:
                        raise StateError(
                            "não há versículo anterior (início da Bíblia)"
                        )
                    chapter = self._structure.last_chapter(book_id)
                    if chapter == 0:
                        raise StateError(
                            f"livro {book_id} não encontrado na estrutura"
                        )
                current_verse = self._structure.last_verse(book_id, chapter)
                if current_verse == 0:
                    raise StateError(
                        f"capítulo {chapter} do livro {book_id} não encontrado"
                    )
            remaining -= 1

        ref = VerseRef(
            book_id=book_id,
            book=self._book_names.get(book_id, ""),
            chapter=chapter,
            verse=current_verse,
            version=version,
        )
        self._state.book_id = book_id
        self._state.chapter = chapter
        self._state.verse = current_verse
        return ref

    def _current_as_ref(self) -> VerseRef:
        """Constrói VerseRef do estado atual."""
        return VerseRef(
            book_id=self._state.book_id,  # type: ignore[arg-type]
            book=self._book_names.get(self._state.book_id, ""),  # type: ignore[arg-type]
            chapter=self._state.chapter,  # type: ignore[arg-type]
            verse=self._state.verse,
            version=self._state.version,
        )

    # ------------------------------------------------------------------
    # Validação
    # ------------------------------------------------------------------

    def _validate_ref(self, ref: VerseRef) -> None:
        """Valida uma referência contra a estrutura bíblica.

        Raises:
            StateError: book_id fora de 1..66, capítulo inexistente,
                versículo inexistente.
        """
        if not (1 <= ref.book_id <= 66):
            raise StateError(f"book_id {ref.book_id} out of range [1..66]")
        last_c = self._structure.last_chapter(ref.book_id)
        if last_c == 0:
            raise StateError(f"book_id {ref.book_id} not in structure")
        if ref.chapter < 1 or ref.chapter > last_c:
            raise StateError(
                f"chapter {ref.chapter} out of range [1..{last_c}] "
                f"for book_id {ref.book_id}"
            )
        if ref.verse is not None:
            last_v = self._structure.last_verse(ref.book_id, ref.chapter)
            if last_v == 0:
                raise StateError(
                    f"chapter {ref.chapter} of book_id {ref.book_id} not in structure"
                )
            if ref.verse < 1 or ref.verse > last_v:
                raise StateError(
                    f"verse {ref.verse} out of range [1..{last_v}] "
                    f"for book_id {ref.book_id} chapter {ref.chapter}"
                )

    # ------------------------------------------------------------------
    # Histórico
    # ------------------------------------------------------------------

    def _add_history(self, ref: VerseRef, action: str) -> None:
        """Adiciona uma entrada ao histórico."""
        self._history.append(HistoryEntry(
            ref=ref,
            timestamp=time.time(),
            action=action,
        ))

    def clear_history(self) -> None:
        """Limpa o histórico de navegação."""
        self._history.clear()

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Carrega estado de ``state.json``.

        Se o arquivo não existir, mantém estado vazio.
        Se o arquivo estiver corrompido, ignora + warning + estado vazio.
        """
        if not self._persist_path:
            return
        if not os.path.isfile(self._persist_path):
            return
        try:
            with open(self._persist_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("state load failed (%s): %s — using empty state",
                           self._persist_path, e)
            return
        if not isinstance(data, dict):
            logger.warning("state file root is not a dict — using empty state")
            return
        try:
            self._state = BibleState(
                book_id=data.get("book_id"),
                chapter=data.get("chapter"),
                verse=data.get("verse"),
                version=str(data.get("version", self._default_version)),
                last_shown_at=float(data.get("last_shown_at", 0.0)),
            )
            # Carregar histórico se presente.
            hist_data = data.get("history", [])
            if isinstance(hist_data, list):
                self._history.clear()
                for entry in hist_data:
                    if not isinstance(entry, dict):
                        continue
                    ref_data = entry.get("ref")
                    if not isinstance(ref_data, dict):
                        continue
                    ref = VerseRef(
                        book_id=int(ref_data.get("book_id", 0)),
                        book=str(ref_data.get("book", "")),
                        chapter=int(ref_data.get("chapter", 0)),
                        verse=ref_data.get("verse"),
                        version=str(ref_data.get("version", self._default_version)),
                    )
                    self._history.append(HistoryEntry(
                        ref=ref,
                        timestamp=float(entry.get("timestamp", 0.0)),
                        action=str(entry.get("action", "")),
                    ))
            # Carregar última busca.
            self._last_search = data.get("last_search")
            logger.info("state loaded from %s", self._persist_path)
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("state parse error: %s — using empty state", e)
            self._state = BibleState(version=self._default_version)

    def save(self) -> None:
        """Salva estado em ``state.json``.

        Raises:
            StateError: se ``persist_path`` não configurado ou erro de I/O.
        """
        if not self._persist_path:
            raise StateError("persist_path not configured")
        self._save_to_path(self._persist_path)

    def _save_if_configured(self) -> None:
        """Salva automaticamente se ``persist_path`` estiver configurado."""
        if self._persist_path:
            try:
                self._save_to_path(self._persist_path)
            except StateError as e:
                logger.warning("auto-save failed: %s", e)

    def _save_to_path(self, path: str) -> None:
        """Salva estado em JSON no caminho especificado."""
        data: dict[str, Any] = {
            "book_id": self._state.book_id,
            "chapter": self._state.chapter,
            "verse": self._state.verse,
            "version": self._state.version,
            "last_shown_at": self._state.last_shown_at,
            "history": [
                {
                    "ref": asdict(entry.ref),
                    "timestamp": entry.timestamp,
                    "action": entry.action,
                }
                for entry in self._history
            ],
            "last_search": self._last_search,
        }
        # Garantir que o diretório existe.
        dir_path = os.path.dirname(path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            raise StateError(f"failed to save state to {path}: {e}") from e
