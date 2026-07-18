"""SermonContextEngine — evolui o contexto do sermão via eventos.

Responsabilidade única:
  - Receber um SermonContext e um evento tipado.
  - Retornar um novo SermonContext atualizado.
  - Aplicar política de expiração e janela de contexto.

Limites explícitos:
  - Não conhece Searcher, Ranking, Holyrics, LLM, Parser, KnowledgeBase.
  - Não executa buscas.
  - Não interpreta intenção.
  - Não resolve pronomes.
  - Não persiste estado.
  - Não mantém estado global — o contexto é passado explicitamente.

Design:
  - process(context, event) → novo SermonContext (imutável).
  - reset() → SermonContext vazio.
  - Política de expiração: se um item (livro, tema, etc.) não é mencionado
    por N atualizações, ele expira do estado ativo.
  - Janela de contexto: histórico limitado a MAX_* itens.

Compatibilidade futura (Streaming Speech Pipeline):
  O engine processa eventos de alto nível. No futuro, eventos de baixo
  nível (BOOK_DETECTED, CHAPTER_DETECTED, etc.) podem ser:
    1. Agregados em eventos de alto nível antes de chegar ao engine.
    2. Ou o engine pode ser estendido para processá-los diretamente.
  A arquitetura suporta ambas as evoluções sem quebrar compatibilidade.
"""

from __future__ import annotations

import time
from dataclasses import replace

from busca.bible_reference import BibleReference
from context.dtos import SermonContext
from context.events import (
    BookChanged,
    ChapterChanged,
    ConceptMentioned,
    ContextReset,
    EntityMentioned,
    EventMentioned,
    ReferenceCompleted,
    ReferenceRepeated,
    ReferenceResolved,
    ThemeMentioned,
)


# ---------------------------------------------------------------------------
# Configuração da janela de contexto
# ---------------------------------------------------------------------------


class ContextWindowConfig:
    """Configuração da janela de contexto e política de expiração.

    Todos os valores são ajustáveis sem quebrar compatibilidade.
    Os defaults são conservadores para um sermão típico.

    Atributos:
        max_references: máximo de referências no histórico.
        max_books: máximo de livros no histórico.
        max_themes: máximo de temas no histórico.
        max_characters: máximo de personagens no histórico.
        max_concepts: máximo de conceitos no histórico.
        max_events: máximo de eventos no histórico.
        book_expiry: atualizações sem mencionar o livro para expirar.
        chapter_expiry: atualizações sem mencionar o capítulo para expirar.
        theme_expiry: atualizações sem mencionar tema para expirar.
        character_expiry: atualizações sem mencionar personagem para expirar.
        concept_expiry: atualizações sem mencionar conceito para expirar.
        event_expiry: atualizações sem mencionar evento para expirar.
    """

    def __init__(
        self,
        max_references: int = 10,
        max_books: int = 5,
        max_themes: int = 8,
        max_characters: int = 10,
        max_concepts: int = 8,
        max_events: int = 8,
        book_expiry: int = 15,
        chapter_expiry: int = 10,
        theme_expiry: int = 12,
        character_expiry: int = 12,
        concept_expiry: int = 12,
        event_expiry: int = 12,
    ) -> None:
        self.max_references = max_references
        self.max_books = max_books
        self.max_themes = max_themes
        self.max_characters = max_characters
        self.max_concepts = max_concepts
        self.max_events = max_events
        self.book_expiry = book_expiry
        self.chapter_expiry = chapter_expiry
        self.theme_expiry = theme_expiry
        self.character_expiry = character_expiry
        self.concept_expiry = concept_expiry
        self.event_expiry = event_expiry


# ---------------------------------------------------------------------------
# SermonContextEngine
# ---------------------------------------------------------------------------


class SermonContextEngine:
    """Engine que evolui o contexto do sermão via eventos.

    Uso:
        engine = SermonContextEngine()
        ctx = engine.reset()
        ctx = engine.process(ctx, BookChanged(book="João", book_id=43))
        ctx = engine.process(ctx, ChapterChanged(chapter=3))
        ctx = engine.process(ctx, ReferenceCompleted(reference=...))

    Imutabilidade:
        - process() NUNCA modifica o contexto recebido.
        - Sempre retorna um novo SermonContext.
        - O contexto anterior permanece válido.

    Desacoplamento:
        - Não conhece nenhum outro componente do sistema.
        - Recebe apenas SermonContext e eventos tipados.
    """

    def __init__(
        self,
        config: ContextWindowConfig | None = None,
        clock: callable = time.time,
    ) -> None:
        """Inicializa a engine.

        Args:
            config: configuração da janela de contexto. Se None, usa defaults.
            clock: função que retorna o timestamp atual (para testes).
        """
        self._config = config or ContextWindowConfig()
        self._clock = clock

    @property
    def config(self) -> ContextWindowConfig:
        """Configuração da janela de contexto."""
        return self._config

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self, reason: str = "") -> SermonContext:
        """Retorna um SermonContext vazio (reset completo).

        Args:
            reason: motivo do reset (apenas para log futuro).

        Returns:
            SermonContext vazio com timestamp atual.
        """
        now = self._clock()
        return SermonContext(created_at=now, updated_at=now)

    # ------------------------------------------------------------------
    # Processamento de eventos
    # ------------------------------------------------------------------

    def process(self, context: SermonContext, event) -> SermonContext:
        """Processa um evento e retorna um novo SermonContext.

        Não modifica o contexto recebido. Sempre retorna um novo contexto.

        Args:
            context: SermonContext atual.
            event: evento tipado (BookChanged, ReferenceResolved, etc.).

        Returns:
            Novo SermonContext com o estado atualizado.
        """
        # ContextReset é tratado separadamente (retorna contexto vazio)
        if isinstance(event, ContextReset):
            return self.reset(reason=event.reason)

        now = self._clock()

        # Dispatch por tipo de evento
        if isinstance(event, BookChanged):
            new_ctx = self._handle_book_changed(context, event, now)
        elif isinstance(event, ChapterChanged):
            new_ctx = self._handle_chapter_changed(context, event, now)
        elif isinstance(event, ReferenceResolved):
            new_ctx = self._handle_reference_resolved(context, event, now)
        elif isinstance(event, ReferenceCompleted):
            new_ctx = self._handle_reference_completed(context, event, now)
        elif isinstance(event, ReferenceRepeated):
            new_ctx = self._handle_reference_repeated(context, event, now)
        elif isinstance(event, ThemeMentioned):
            new_ctx = self._handle_theme_mentioned(context, event, now)
        elif isinstance(event, EntityMentioned):
            new_ctx = self._handle_entity_mentioned(context, event, now)
        elif isinstance(event, ConceptMentioned):
            new_ctx = self._handle_concept_mentioned(context, event, now)
        elif isinstance(event, EventMentioned):
            new_ctx = self._handle_event_mentioned(context, event, now)
        else:
            # Evento desconhecido — retornar contexto inalterado
            # (apenas incrementa update_count)
            new_ctx = context.with_update(updated_at=now)

        # Aplicar expiração após cada evento
        return self._apply_expiry(new_ctx)

    # ------------------------------------------------------------------
    # Handlers por tipo de evento
    # ------------------------------------------------------------------

    def _handle_book_changed(
        self, ctx: SermonContext, event: BookChanged, now: float
    ) -> SermonContext:
        """Processa BookChanged: atualiza livro ativo e histórico."""
        new_books = self._prepend_unique(
            ctx.recent_books, event.book, self._config.max_books
        )
        return ctx.with_update(
            book=event.book,
            book_id=event.book_id,
            last_book_update=ctx.update_count + 1,
            recent_books=new_books,
            updated_at=now,
        )

    def _handle_chapter_changed(
        self, ctx: SermonContext, event: ChapterChanged, now: float
    ) -> SermonContext:
        """Processa ChapterChanged: atualiza capítulo ativo."""
        return ctx.with_update(
            chapter=event.chapter,
            last_chapter_update=ctx.update_count + 1,
            updated_at=now,
        )

    def _handle_reference_resolved(
        self, ctx: SermonContext, event: ReferenceResolved, now: float
    ) -> SermonContext:
        """Processa ReferenceResolved: atualiza referência ativa e histórico."""
        ref = event.reference
        if ref is None:
            return ctx.with_update(updated_at=now)

        new_refs = self._prepend(
            ctx.recent_references, ref, self._config.max_references
        )
        # Atualizar livro e capítulo ativos a partir da referência
        book_name = ref.book.canonical_name
        book_id = ref.book_id
        chapter = ref.chapter
        new_books = self._prepend_unique(
            ctx.recent_books, book_name, self._config.max_books
        )

        return ctx.with_update(
            book=book_name,
            book_id=book_id,
            chapter=chapter,
            last_reference=ref,
            last_book_update=ctx.update_count + 1,
            last_chapter_update=ctx.update_count + 1,
            recent_references=new_refs,
            recent_books=new_books,
            updated_at=now,
        )

    def _handle_reference_completed(
        self, ctx: SermonContext, event: ReferenceCompleted, now: float
    ) -> SermonContext:
        """Processa ReferenceCompleted: referência completada do contexto ativo.

        Semelhante a ReferenceResolved, mas indica que a referência foi
        construída a partir do contexto (ex.: "João 3" + "versículo 16").
        """
        ref = event.reference
        if ref is None:
            return ctx.with_update(updated_at=now)

        new_refs = self._prepend(
            ctx.recent_references, ref, self._config.max_references
        )
        return ctx.with_update(
            last_reference=ref,
            chapter=ref.chapter,
            last_chapter_update=ctx.update_count + 1,
            recent_references=new_refs,
            updated_at=now,
        )

    def _handle_reference_repeated(
        self, ctx: SermonContext, event: ReferenceRepeated, now: float
    ) -> SermonContext:
        """Processa ReferenceRepeated: mantém a referência ativa.

        Apenas atualiza o timestamp e contador. Não adiciona ao histórico
        (a referência já está lá).
        """
        if ctx.last_reference is not None:
            # Re-adicionar ao topo do histórico (mais recente primeiro)
            new_refs = self._prepend(
                ctx.recent_references, ctx.last_reference, self._config.max_references
            )
            return ctx.with_update(
                recent_references=new_refs,
                updated_at=now,
            )
        return ctx.with_update(updated_at=now)

    def _handle_theme_mentioned(
        self, ctx: SermonContext, event: ThemeMentioned, now: float
    ) -> SermonContext:
        """Processa ThemeMentioned: adiciona tema ao histórico."""
        if not event.theme:
            return ctx.with_update(updated_at=now)
        new_themes = self._prepend_unique(
            ctx.recent_themes, event.theme, self._config.max_themes
        )
        return ctx.with_update(
            recent_themes=new_themes,
            last_theme_update=ctx.update_count + 1,
            updated_at=now,
        )

    def _handle_entity_mentioned(
        self, ctx: SermonContext, event: EntityMentioned, now: float
    ) -> SermonContext:
        """Processa EntityMentioned: adiciona personagem/lugar ao histórico."""
        if not event.name:
            return ctx.with_update(updated_at=now)
        new_chars = self._prepend_unique(
            ctx.recent_characters, event.name, self._config.max_characters
        )
        return ctx.with_update(
            recent_characters=new_chars,
            last_character_update=ctx.update_count + 1,
            updated_at=now,
        )

    def _handle_concept_mentioned(
        self, ctx: SermonContext, event: ConceptMentioned, now: float
    ) -> SermonContext:
        """Processa ConceptMentioned: adiciona conceito ao histórico."""
        if not event.concept_id:
            return ctx.with_update(updated_at=now)
        new_concepts = self._prepend_unique(
            ctx.recent_concepts, event.concept_id, self._config.max_concepts
        )
        return ctx.with_update(
            recent_concepts=new_concepts,
            last_concept_update=ctx.update_count + 1,
            updated_at=now,
        )

    def _handle_event_mentioned(
        self, ctx: SermonContext, event: EventMentioned, now: float
    ) -> SermonContext:
        """Processa EventMentioned: adiciona evento ao histórico."""
        if not event.event:
            return ctx.with_update(updated_at=now)
        new_events = self._prepend_unique(
            ctx.recent_events, event.event, self._config.max_events
        )
        return ctx.with_update(
            recent_events=new_events,
            last_event_update=ctx.update_count + 1,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Política de expiração
    # ------------------------------------------------------------------

    def _apply_expiry(self, ctx: SermonContext) -> SermonContext:
        """Aplica política de expiração ao contexto.

        Se um item não foi mencionado por N atualizações, ele expira do
        estado ativo (mas permanece no histórico).

        Args:
            ctx: SermonContext após processar o evento.

        Returns:
            SermonContext com expiração aplicada (pode ser o mesmo se
            nada expirou).
        """
        updates_since_book = ctx.update_count - ctx.last_book_update
        updates_since_chapter = ctx.update_count - ctx.last_chapter_update

        changes = {}

        # Expirar livro ativo
        if ctx.book is not None and updates_since_book > self._config.book_expiry:
            changes["book"] = None
            changes["book_id"] = None

        # Expirar capítulo ativo
        if ctx.chapter is not None and updates_since_chapter > self._config.chapter_expiry:
            changes["chapter"] = None

        # Expirar referência ativa (segue a expiração do livro)
        if ctx.last_reference is not None and updates_since_book > self._config.book_expiry:
            changes["last_reference"] = None

        if not changes:
            return ctx

        return replace(ctx, **changes)

    # ------------------------------------------------------------------
    # Helpers de lista imutável
    # ------------------------------------------------------------------

    @staticmethod
    def _prepend(tup: tuple, item, max_size: int) -> tuple:
        """Adiciona item no início de uma tuple, limitando ao tamanho máximo.

        Não remove duplicatas (útil para referências, onde a mesma referência
        pode aparecer múltiplas vezes em momentos diferentes).

        Args:
            tup: tuple atual.
            item: item a adicionar no início.
            max_size: tamanho máximo da tuple.

        Returns:
            Nova tuple com item no início, limitada a max_size.
        """
        new = (item,) + tup
        if len(new) > max_size:
            new = new[:max_size]
        return new

    @staticmethod
    def _prepend_unique(tup: tuple, item, max_size: int) -> tuple:
        """Adiciona item no início, removendo duplicatas anteriores.

        Se o item já existe na tuple, ele é movido para o início (mais recente).
        Útil para livros, temas, personagens (deduplicação).

        Args:
            tup: tuple atual.
            item: item a adicionar/mover para o início.
            max_size: tamanho máximo da tuple.

        Returns:
            Nova tuple com item no início, sem duplicatas, limitada a max_size.
        """
        # Remover o item se já existe (vai ser re-adicionado no início)
        filtered = tuple(x for x in tup if x != item)
        new = (item,) + filtered
        if len(new) > max_size:
            new = new[:max_size]
        return new
