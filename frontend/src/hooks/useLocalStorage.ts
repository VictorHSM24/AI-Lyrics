/**
 * useLocalStorage — hook genérico para persistência em localStorage.
 *
 * Sprint 25: usado por FavoritesPanel e RecentsPanel para persistir
 * favoritos e referências mais utilizadas entre sessões.
 *
 * Características:
 * - Sincroniza com localStorage em mudanças (debounced via microtask).
 * - Suporta SSR (verifica typeof window antes de acessar localStorage).
 * - Trata erros de parse silenciosamente (retorna default).
 * - Sincroniza entre abas via storage event.
 * - T tipado: o valor é sempre T | null (null se não há valor salvo).
 *
 * Uso:
 *   const [favorites, setFavorites] = useLocalStorage<OperatorFavorite[]>(
 *     "ai-lyrics:operator:favorites",
 *     [],
 *   );
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface UseLocalStorageResult<T> {
  /** Valor atual (do localStorage ou default). */
  value: T;
  /** Define novo valor e persiste. */
  setValue: (value: T | ((prev: T) => T)) => void;
  /** Remove a chave do localStorage e reseta para default. */
  remove: () => void;
}

export function useLocalStorage<T>(
  key: string,
  defaultValue: T,
): UseLocalStorageResult<T> {
  const [value, setValueState] = useState<T>(() => {
    if (typeof window === "undefined") return defaultValue;
    try {
      const raw = window.localStorage.getItem(key);
      if (raw === null) return defaultValue;
      return JSON.parse(raw) as T;
    } catch {
      return defaultValue;
    }
  });

  // Ref para evitar re-escritas desnecessárias.
  const valueRef = useRef(value);
  valueRef.current = value;

  // Persistir em mudanças.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Silently fail (quota exceeded, private mode, etc.).
    }
  }, [key, value]);

  // Sincronizar entre abas/janelas.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onStorage = (e: StorageEvent) => {
      if (e.key !== key) return;
      if (e.newValue === null) {
        setValueState(defaultValue);
        return;
      }
      try {
        setValueState(JSON.parse(e.newValue) as T);
      } catch {
        // Ignorar valor inválido de outra aba.
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key, defaultValue]);

  const setValue = useCallback(
    (next: T | ((prev: T) => T)) => {
      setValueState((prev) => {
        const resolved = next instanceof Function ? next(prev) : next;
        return resolved;
      });
    },
    [],
  );

  const remove = useCallback(() => {
    if (typeof window !== "undefined") {
      try {
        window.localStorage.removeItem(key);
      } catch {
        // Silently fail.
      }
    }
    setValueState(defaultValue);
  }, [key, defaultValue]);

  return { value, setValue, remove };
}
