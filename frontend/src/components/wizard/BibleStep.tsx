/**
 * BibleStep — Etapa 4 do Wizard: Bíblia (Sprint 23.0).
 *
 * Valida bases SQLite (data/sources/*.sqlite), BibleRetriever,
 * base FTS5 (data/bible.pt-br.sqlite) e embeddings (data/bible.embeddings.npy).
 */

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, XCircle } from "lucide-react";
import {
  apiGet,
  StatusRow,
  type BibleValidation,
} from "./types";

export function BibleStep() {
  const [data, setData] = useState<BibleValidation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await apiGet<BibleValidation>("/bible/validate");
      setData(r);
    } catch (e: any) {
      setError(e.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Validando bases bíblicas...
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-sm text-red-600">
        <XCircle className="h-4 w-4" /> {error}
      </div>
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Etapa 4 de 5: Bíblia</h2>
      <p className="text-sm text-text-muted">
        Validação das bases SQLite e do BibleRetriever (Sprint 22.0).
      </p>

      <StatusRow
        ok={data.versions_count >= 1}
        label="Versões SQLite"
        value={`${data.versions_count} versão(ões): ${data.versions_found.join(", ")}`}
      />
      <StatusRow
        ok={data.bible_retriever_ok}
        label="BibleRetriever"
        value={
          data.bible_retriever_stats
            ? `${data.bible_retriever_stats.total_versions} versões · ${data.bible_retriever_stats.total_verses} versículos · ${data.bible_retriever_stats.unique_verses} únicos · init ${data.bible_retriever_stats.init_time_ms.toFixed(0)} ms`
            : "Não inicializado"
        }
      />
      <StatusRow
        ok={data.fts5_db_exists}
        label="Base FTS5 (Searcher)"
        value={data.fts5_db_exists ? data.fts5_db_path : "Ausente — rode build_embeddings.py"}
      />
      <StatusRow
        ok={data.embeddings_npy_exists}
        label="Embeddings (busca semântica)"
        value={data.embeddings_npy_exists ? data.embeddings_npy_path : "Ausente — rode build_embeddings.py"}
      />

      <button
        onClick={load}
        className="inline-flex items-center gap-2 text-sm text-text-muted hover:text-text"
      >
        <RefreshCw className="h-4 w-4" /> Re-validar
      </button>
    </div>
  );
}
