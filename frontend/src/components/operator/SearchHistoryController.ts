/**
 * SearchHistoryController (Sprint 26 D9) — histórico terminal-style.
 *
 * Mantém o histórico de queries confirmadas (Enter) e permite
 * navegação com ↑↓ quando o campo está vazio, como um terminal.
 *
 * Comportamento:
 * - Após Enter em "Rm 828", a query é adicionada ao histórico.
 * - Campo vazio + ↑ → recupera "Rm 828".
 * - Campo vazio + ↑↑ → recupera a query anterior.
 * - Campo vazio + ↓ → navega de volta para o presente.
 * - Se o operador está digitando e pressiona ↑, NÃO navega o histórico
 *   (apenas navega sugestões). O histórico só ativa com campo vazio.
 *
 * O histórico existe apenas para consultas realizadas (confirmadas
 * com Enter). Não registra cada tecla.
 *
 * Persistência: em memória (por sessão). Pode ser estendido para
 * localStorage no futuro.
 */

// ============================================================
// Tipos
// ============================================================

export interface SearchHistoryState {
  /** Lista de queries (mais recente primeiro). */
  entries: string[];
  /** Cursor atual (-1 = no presente, 0 = mais recente, etc.). */
  cursor: number;
}

// ============================================================
// Controller
// ============================================================

export class SearchHistoryController {
  private entries: string[] = [];
  private cursor = -1;
  private readonly maxEntries: number;

  constructor(maxEntries = 50) {
    this.maxEntries = maxEntries;
  }

  /**
   * Adiciona uma query ao histórico (após Enter bem-sucedido).
   * Não duplica se a última entry for igual.
   */
  push(query: string): void {
    const trimmed = query.trim();
    if (!trimmed) return;
    // Não duplicar se a última entry for igual.
    if (this.entries[0] === trimmed) {
      this.cursor = -1;
      return;
    }
    this.entries.unshift(trimmed);
    if (this.entries.length > this.maxEntries) {
      this.entries.pop();
    }
    this.cursor = -1;
  }

  /**
   * Navega para a entry anterior (mais antiga).
   * Só funciona se o cursor estiver ativo ou se o campo estiver vazio.
   * @param currentQuery Query atual do campo (para decidir se ativa).
   * @returns Query anterior, ou null se não há histórico.
   */
  previous(currentQuery: string): string | null {
    // Só ativa o histórico se o campo estiver vazio.
    if (currentQuery.trim() !== "" && this.cursor === -1) {
      return null;
    }
    if (this.entries.length === 0) return null;
    if (this.cursor < this.entries.length - 1) {
      this.cursor += 1;
      return this.entries[this.cursor] ?? null;
    }
    return this.entries[this.cursor] ?? null;
  }

  /**
   * Navega para a próxima entry (mais recente).
   * @returns Query mais recente, ou "" se voltou ao presente.
   */
  next(): string {
    if (this.cursor <= 0) {
      this.cursor = -1;
      return "";
    }
    this.cursor -= 1;
    return this.entries[this.cursor] ?? "";
  }

  /**
   * Reseta o cursor para o presente (-1).
   */
  resetCursor(): void {
    this.cursor = -1;
  }

  /**
   * Limpa todo o histórico.
   */
  clear(): void {
    this.entries = [];
    this.cursor = -1;
  }

  /**
   * Retorna o estado atual (para testes/debug).
   */
  get state(): SearchHistoryState {
    return { entries: [...this.entries], cursor: this.cursor };
  }

  /**
   * True se há histórico disponível.
   */
  get hasHistory(): boolean {
    return this.entries.length > 0;
  }
}
