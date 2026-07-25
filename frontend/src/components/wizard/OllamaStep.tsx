/**
 * OllamaStep — Etapa 3 do Wizard: Ollama (Sprint 23.0).
 *
 * Detecta instalação do Ollama, verifica API e modelo configurado.
 * Permite baixar o modelo automaticamente via /wizard/ollama/pull
 * (executa `ollama pull` em background no backend, com polling de
 * status a cada 1 segundo).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Download,
  Loader2,
  RefreshCw,
} from "lucide-react";
import {
  apiGet,
  apiPost,
  StatusRow,
  type OllamaApi,
  type OllamaDetect,
  type OllamaModel,
  type PullStatus,
} from "./types";

export function OllamaStep({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [detect, setDetect] = useState<OllamaDetect | null>(null);
  const [api, setApi] = useState<OllamaApi | null>(null);
  const [model, setModel] = useState<OllamaModel | null>(null);
  const [pull, setPull] = useState<PullStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [pulling, setPulling] = useState(false);
  const pollRef = useRef<number | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const d = await apiGet<OllamaDetect>("/ollama/detect");
      setDetect(d);
      const a = await apiGet<OllamaApi>("/ollama/api");
      setApi(a);
      const m = await apiGet<OllamaModel>("/ollama/model");
      setModel(m);
    } catch (e: unknown) {
      console.error("ollama load error", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const busy = loading || pulling;
  useEffect(() => {
    if (onBusyChange) onBusyChange(busy);
  }, [busy, onBusyChange]);

  const startPull = async () => {
    if (pulling) return; // previne cliques duplicados
    setPulling(true);
    setPull(null);
    // Limpa polling anterior se existir.
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    const modelToPull = model?.configured_model ?? "qwen3:8b-q4_K_M";
    try {
      // Sprint 23.1: salvar config do Ollama antes de baixar.
      try {
        await apiPost("/ollama/save", { model: modelToPull });
      } catch {
        /* não bloquear o download se salvar falhar */
      }
      await apiPost("/ollama/pull", { model: modelToPull });
      let mounted = true;
      pollRef.current = window.setInterval(async () => {
        if (!mounted) return;
        try {
          const s = await apiGet<PullStatus>("/ollama/pull/status");
          if (!mounted) return;
          setPull(s);
          if (!s.running) {
            if (pollRef.current) window.clearInterval(pollRef.current);
            pollRef.current = null;
            setPulling(false);
            loadAll();
          }
        } catch {
          /* silencioso */
        }
      }, 1000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setPull({
        running: false, completed: false, failed: true,
        progress: "", error: msg, elapsed_s: 0,
      });
      setPulling(false);
    }
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, []);

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 3 de 5: Ollama (IA local)</h2>
      <p className="text-sm text-text-muted">
        O AI Lyrics usa Ollama para inferência semântica local. Verifique
        instalação, API e modelo configurado.
      </p>

      {loading && (
        <div className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Verificando Ollama...
        </div>
      )}

      {!loading && detect && (
        <StatusRow
          ok={detect.installed}
          label="Instalação"
          value={detect.installed
            ? `${detect.version ?? "—"} (${detect.executable})`
            : detect.message}
        />
      )}
      {!loading && api && (
        <StatusRow
          ok={api.ok}
          label="API"
          value={api.ok
            ? `${api.api_url} · ${api.latency_ms} ms · ${api.models_count} modelo(s)`
            : (api.error ?? "API offline")}
        />
      )}
      {!loading && model && (
        <StatusRow
          ok={model.installed}
          label="Modelo configurado"
          value={`${model.configured_model} — ${model.installed ? "instalado" : "NÃO instalado"}`}
        />
      )}

      {!loading && model && !model.installed && (
        <div className="border border-amber-300 bg-amber-50 rounded p-4 space-y-3">
          <div className="text-sm text-amber-800">
            O modelo {model.configured_model} não está instalado (~5 GB).
            Você pode baixar agora ou pular e instalar manualmente depois.
          </div>
          <button
            onClick={startPull}
            disabled={pulling}
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded hover:opacity-90 disabled:opacity-50"
          >
            {pulling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            {pulling ? "Baixando..." : "Baixar modelo agora"}
          </button>
          {pull && (
            <div className="text-xs space-y-1">
              <div className="font-mono bg-amber-100 p-2 rounded">
                {pull.progress || "Iniciando..."}
              </div>
              {pull.failed && <div className="text-red-700">Erro: {pull.error}</div>}
              {pull.completed && <div className="text-green-700">Download concluído.</div>}
              {pull.running && <div>Decorrido: {pull.elapsed_s.toFixed(0)}s</div>}
            </div>
          )}
        </div>
      )}

      <button
        onClick={loadAll}
        disabled={loading || pulling}
        className="inline-flex items-center gap-2 text-sm text-text-muted hover:text-text"
      >
        <RefreshCw className="h-4 w-4" /> Re-verificar
      </button>
    </div>
  );
}
