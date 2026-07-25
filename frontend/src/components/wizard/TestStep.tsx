/**
 * TestStep — Etapa 5 do Wizard: teste completo do pipeline (Sprint 23.0).
 *
 * Executa o diagnóstico integrado via /wizard/test e exibe o status de
 * cada componente (áudio, holyrics, ollama_api, ollama_model, bible).
 */

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import {
  apiGet,
  StatusRow,
  type ComponentStatus,
  type TestResult,
} from "./types";

export function TestStep({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [data, setData] = useState<TestResult | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await apiGet<TestResult>("/test");
      setData(r);
    } catch (e: unknown) {
      console.error("test error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (onBusyChange) onBusyChange(loading);
  }, [loading, onBusyChange]);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 5 de 5: Teste completo do pipeline</h2>
      <p className="text-sm text-text-muted">
        Diagnóstico integrado de todos os componentes.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Executando diagnóstico...
        </div>
      )}

      {!loading && data && (
        <>
          <div
            className={`p-4 border rounded ${
              data.all_ok ? "border-green-300 bg-green-50" : "border-amber-300 bg-amber-50"
            }`}
          >
            <div className="flex items-center gap-3">
              {data.all_ok ? (
                <CheckCircle2 className="h-6 w-6 text-green-600" />
              ) : (
                <XCircle className="h-6 w-6 text-amber-600" />
              )}
              <div>
                <div className="font-semibold">{data.message}</div>
                <div className="text-xs text-text-muted">
                  {data.all_ok ? "Tudo pronto para usar." : "Revise as etapas anteriores."}
                </div>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            {Object.entries(data.components).map(([key, val]: [string, ComponentStatus]) => (
              <StatusRow
                key={key}
                ok={val.ok ?? val.bible_retriever_ok ?? false}
                label={key}
                value={val.message ?? JSON.stringify(val)}
              />
            ))}
          </div>

          <button
            onClick={load}
            className="inline-flex items-center gap-2 text-sm text-text-muted hover:text-text"
          >
            <RefreshCw className="h-4 w-4" /> Re-executar diagnóstico
          </button>
        </>
      )}
    </div>
  );
}
