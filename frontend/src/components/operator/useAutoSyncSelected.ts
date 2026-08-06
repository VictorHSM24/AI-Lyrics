/**
 * useAutoSyncSelected (Sprint 25 Fase B) — sincronização automática.
 *
 * Sempre que uma apresentação ocorre (IA, operador, reapresentação),
 * o `presented` no VersePresentationStore muda. Este hook sincroniza
 * `selected` no WorkspaceStore para a mesma referência, permitindo
 * que o operador continue navegando daquele ponto.
 *
 * Regra da máquina de estados (B0):
 *   APRESENTADO → SINCRONIZADO → selected = presented
 *
 * Importante: a sincronização só acontece quando `presented` muda
 * para uma referência DIFERENTE da atual. Se o operador reapresenta
 * o mesmo versículo, `selected` não é sobrescrito (preserva a navegação
 * atual do operador).
 */

import { useEffect, useRef } from "react";
import { useStores, useVersePresentation } from "@/hooks";

export function useAutoSyncSelected(): void {
  const workspaceStore = useStores().workspace;
  const { current: presentedEntry } = useVersePresentation();

  // Track do último presented que sincronizamos, para evitar
  // re-sincronização quando o operador navega após a apresentação.
  const lastSyncedRef = useRef<{ bookId: number; chapter: number; verse: number } | null>(null);

  useEffect(() => {
    if (!presentedEntry || presentedEntry.status !== "presented") return;

    const presentedRef = {
      bookId: presentedEntry.bookId,
      chapter: presentedEntry.chapter,
      verse: presentedEntry.verse,
    };

    // Já sincronizamos esta apresentação? Se sim, não fazer nada.
    if (lastSyncedRef.current) {
      const same =
        lastSyncedRef.current.bookId === presentedRef.bookId &&
        lastSyncedRef.current.chapter === presentedRef.chapter &&
        lastSyncedRef.current.verse === presentedRef.verse;
      if (same) return;
    }

    // Sincronizar selected = presented.
    workspaceStore.setSelected(presentedRef);
    lastSyncedRef.current = presentedRef;
  }, [presentedEntry, workspaceStore]);
}
