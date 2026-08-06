/**
 * LruCache — cache LRU (Least Recently Used) genérico.
 *
 * Sprint 25: usado pelo OperatorService para cachear respostas de
 * getChapters, getVerses e getVerse, evitando re-buscar dados que
 * não mudam durante a sessão (a Bíblia é estática).
 *
 * Características:
 * - Tamanho máximo fixo (padrão 128 entradas).
 * - Evict do item menos recentemente usado quando atinge o limite.
 * - Thread-safe para uso em single-thread JS (não precisa de locks).
 * - Não persiste em disco (memória apenas).
 */

export interface LruCacheEntry<V> {
  value: V;
  /** Timestamp da última acesso (para LRU eviction). */
  lastAccess: number;
}

export class LruCache<K, V> {
  private readonly map = new Map<K, LruCacheEntry<V>>();
  private readonly maxSize: number;

  constructor(maxSize = 128) {
    if (maxSize <= 0) throw new Error("LruCache: maxSize must be > 0");
    this.maxSize = maxSize;
  }

  /** Número de entradas atualmente no cache. */
  get size(): number {
    return this.map.size;
  }

  /** Verifica se a chave está no cache. */
  has(key: K): boolean {
    return this.map.has(key);
  }

  /**
   * Recupera um valor do cache, atualizando lastAccess.
   * Retorna undefined se não estiver no cache.
   */
  get(key: K): V | undefined {
    const entry = this.map.get(key);
    if (entry === undefined) return undefined;
    entry.lastAccess = Date.now();
    return entry.value;
  }

  /**
   * Insere um valor no cache. Se a chave já existe, atualiza o valor
   * e lastAccess. Se o cache exceder maxSize, evict do LRU.
   */
  set(key: K, value: V): void {
    this.map.set(key, { value, lastAccess: Date.now() });
    if (this.map.size > this.maxSize) {
      this.evictLru();
    }
  }

  /** Remove uma chave específica do cache. */
  delete(key: K): void {
    this.map.delete(key);
  }

  /** Limpa todo o cache. */
  clear(): void {
    this.map.clear();
  }

  /**
   * Evict do item com menor lastAccess.
   * Em caso de empate, evict o primeiro encontrado (ordem de inserção
   * do Map, que é insertion order em JS).
   */
  private evictLru(): void {
    let lruKey: K | null = null;
    let lruTime = Infinity;
    for (const [key, entry] of this.map) {
      if (entry.lastAccess < lruTime) {
        lruTime = entry.lastAccess;
        lruKey = key;
      }
    }
    if (lruKey !== null) {
      this.map.delete(lruKey);
    }
  }
}

/**
 * Cria uma chave de cache string a partir de partes.
 * Ex.: cacheKey("chapters", 43, "ACF") → "chapters:43:ACF"
 */
export function cacheKey(...parts: (string | number | boolean | null | undefined)[]): string {
  return parts
    .map((p) => String(p ?? ""))
    .join(":");
}
