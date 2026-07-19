/**
 * dev-log — telemetria de desenvolvimento.
 *
 * Logs só são emitidos em modo desenvolvimento.
 * Em produção, todas as chamadas são no-ops.
 *
 * Usado para validar o fluxo:
 *   Bootstrap → requisição → resposta → Store atualizado → Hooks re-renderizados
 */

// Detecta modo desenvolvimento.
// Vite define import.meta.env.DEV, mas o tipo pode não estar disponível
// em todos os contextos. Usamos uma verificação segura.
const IS_DEV: boolean =
  typeof import.meta !== "undefined" &&
  typeof (import.meta as unknown as { env?: { DEV?: boolean } }).env === "object" &&
  (import.meta as unknown as { env?: { DEV?: boolean } }).env?.DEV === true;

type LogFn = (...args: unknown[]) => void;

function noop(): void {
  // no-op em produção.
}

function makeLog(prefix: string, consoleFn: LogFn): LogFn {
  if (!IS_DEV) return noop;
  return (...args: unknown[]) => {
    consoleFn(`[AI Lyrics:${prefix}]`, ...args);
  };
}

export const devLog = {
  /** Log genérico — uso informativo. */
  info: makeLog("info", console.log as LogFn),
  /** Bootstrap — início, requisições, respostas, stores populados. */
  bootstrap: makeLog("bootstrap", console.log as LogFn),
  /** Bridge — eventos recebidos e stores atualizados. */
  bridge: makeLog("bridge", console.log as LogFn),
  /** Startup — etapas e transições de estado. */
  startup: makeLog("startup", console.log as LogFn),
  /** Avisos — condições inesperadas mas não fatais. */
  warn: makeLog("warn", console.warn as LogFn),
  /** Erros — falhas que impedem o fluxo. */
  error: makeLog("error", console.error as LogFn),
};

export type DevLog = typeof devLog;
