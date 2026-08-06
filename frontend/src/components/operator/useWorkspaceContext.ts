/**
 * useWorkspaceContext — constrói WorkspaceContext a partir dos stores
 * e services, para que comandos possam ser disparados de qualquer fonte
 * (keyboard, botões, busca, favoritos, histórico).
 *
 * Sprint 25 Fase B: centraliza a construção do contexto para que
 * KeyboardController e QuickNavigator não dupliquem lógica de
 * acesso a stores/services.
 */

import { useCallback, useMemo } from "react";
import { useServices, useStores, useVersePresentation } from "@/hooks";
import { useOperatorNavigation } from "@/hooks";
import type { OperatorRef } from "@/stores";
import type { WorkspaceContext } from "./WorkspaceCommands";

export function useWorkspaceContext(): WorkspaceContext {
  const services = useServices();
  const stores = useStores();
  const nav = useOperatorNavigation();
  const { current: presentedEntry } = useVersePresentation();

  // Snapshot do workspace store para selected e quickPresentation.
  // Nota: usamos o store diretamente (não hook) para evitar re-render
  // desnecessário neste hook; os componentes que precisam re-renderizar
  // já assinam o store via useStoreSnapshot.
  const workspaceStore = stores.workspace;
  const favoritesStore = stores.favorites;
  const recentsStore = stores.recents;

  const ctx: WorkspaceContext = useMemo(
    () => ({
      get selected(): OperatorRef | null {
        return workspaceStore.current?.data.selected ?? null;
      },
      get presented(): OperatorRef | null {
        if (!presentedEntry) return null;
        return {
          bookId: presentedEntry.bookId,
          chapter: presentedEntry.chapter,
          verse: presentedEntry.verse,
        };
      },
      get quickPresentation(): boolean {
        return workspaceStore.current?.data.quickPresentation ?? false;
      },
      get books(): Array<{ id: number; canonical: string }> {
        return nav.books;
      },
      getChapters: (bookId: number) => nav.getChapters(bookId),
      getVerses: (bookId: number, chapter: number) => nav.getVerses(bookId, chapter),
      getVerse: (bookId: number, chapter: number, verse: number) => nav.getVerse(bookId, chapter, verse),
      presentVerse: (req) => services.operator.presentVerse(req),
      setSelected: (ref: OperatorRef | null) => workspaceStore.setSelected(ref),
      recordUsage: (ref: OperatorRef, label: string) => {
        recentsStore.recordUsage(ref, label);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [services, workspaceStore, recentsStore, nav, presentedEntry],
  );

  // Garantir que books estão carregados.
  const loadBooksIfNeeded = useCallback(() => {
    if (nav.books.length === 0) {
      nav.loadBooks().catch(() => {
        // Erro tratado no hook (nav.error).
      });
    }
  }, [nav]);

  // Carregar books na primeira montagem do contexto.
  // Usar useEffect no componente que consome o contexto, não aqui
  // (hooks não podem ter efeitos colaterais em useMemo).

  // Expor via prop para o componente chamar.
  // Alternativa: carregar automaticamente. Vou carregar automaticamente
  // via useEffect separado no KeyboardController/QuickNavigator.

  // Nota: loadBooksIfNeeded é exposto via closure — componentes podem
  // chamar nav.loadBooks() diretamente se precisarem.
  void loadBooksIfNeeded;
  void favoritesStore;

  return ctx;
}
