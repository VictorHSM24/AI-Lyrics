/**
 * SemanticPanel — painel de depuração da camada semântica (Sprint 20).
 *
 * Mostra:
 * - Contexto enviado ao LLM (texto atual + recente + livro/capítulo atual)
 * - Candidatos gerados pelo provider (livro, capítulo, versículo, confiança, motivo)
 * - Confiança de cada candidato (barra visual)
 * - Tempo de inferência + provider + modelo
 * - Candidato escolhido pelo ReferenceResolver
 * - Motivo da decisão (highest_confidence | all_invalid | parser_already_resolved)
 * - Histórico das últimas inferências e resoluções
 *
 * Atualização em tempo real via EventStream → SemanticStore → useSemantic.
 *
 * Eventos que alimentam este painel:
 *   SemanticInferenceCompleted → atualiza inferência atual
 *   IntentCandidate            → complementa com candidatos
 *   SemanticResolutionCompleted → atualiza resolução atual
 */

import {
  Brain,
  CheckCircle2,
  XCircle,
  Clock,
  History,
  Sparkles,
  Zap,
  Database,
  AlertCircle,
} from "lucide-react";
import { useSemantic } from "@/hooks";
import type {
  SemanticInferenceEntry,
  SemanticResolutionEntry,
  SemanticCandidateEntry,
} from "@/stores";
import { cn } from "@/utils";

interface SemanticPanelProps {
  className?: string;
}

export function SemanticPanel({ className }: SemanticPanelProps) {
  const {
    currentInference,
    currentResolution,
    inferenceHistory,
    resolutionHistory,
    loading,
  } = useSemantic();

  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-lg border border-border bg-surface p-4",
        className,
      )}
      data-testid="semantic-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <Brain className="h-4 w-4 text-purple-400" />
        <h3 className="text-sm font-semibold text-text">
          Semantic Engine
        </h3>
        <span className="ml-auto text-[10px] text-text-muted">
          Sprint 20
        </span>
      </div>

      {loading ? (
        <p className="text-xs text-text-muted">Carregando...</p>
      ) : !currentInference && !currentResolution ? (
        <p className="text-xs text-text-muted italic">
          Nenhuma inferência semântica executada ainda.
        </p>
      ) : (
        <>
          {/* Inferência atual */}
          {currentInference && (
            <CurrentInference entry={currentInference} />
          )}

          {/* Resolução atual */}
          {currentResolution && (
            <CurrentResolution entry={currentResolution} />
          )}

          {/* Histórico de inferências */}
          {inferenceHistory.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
                <History className="h-3 w-3" />
                Histórico de Inferências
              </div>
              <div
                className="flex flex-col gap-1.5 max-h-40 overflow-y-auto"
                data-testid="semantic-inference-history"
              >
                {inferenceHistory.slice(0, 10).map((entry, i) => (
                  <InferenceRow key={`${entry.id}-${i}`} entry={entry} />
                ))}
              </div>
            </div>
          )}

          {/* Histórico de resoluções */}
          {resolutionHistory.length > 0 && (
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
                <History className="h-3 w-3" />
                Histórico de Resoluções
              </div>
              <div
                className="flex flex-col gap-1.5 max-h-40 overflow-y-auto"
                data-testid="semantic-resolution-history"
              >
                {resolutionHistory.slice(0, 10).map((entry, i) => (
                  <ResolutionRow key={`${entry.id}-${i}`} entry={entry} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ============================================================
// Sub-componentes
// ============================================================

function CurrentInference({ entry }: { entry: SemanticInferenceEntry }) {
  const hasError = entry.error.length > 0;
  const hasCandidates = entry.candidates.length > 0;

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3"
      data-testid="semantic-current-inference"
    >
      {/* Contexto */}
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
          <Sparkles className="h-3 w-3" />
          Contexto Enviado
        </div>
        <p className="text-xs text-text font-mono break-words">
          {entry.contextText || "(vazio)"}
        </p>
      </div>

      {/* Metadados */}
      <div className="flex flex-wrap gap-3 text-[10px] text-text-muted">
        <span className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {entry.inferenceMs}ms
        </span>
        <span className="flex items-center gap-1">
          <Database className="h-3 w-3" />
          {entry.provider}
        </span>
        <span className="flex items-center gap-1">
          <Brain className="h-3 w-3" />
          {entry.model}
        </span>
        {entry.cached && (
          <span className="flex items-center gap-1 text-emerald-400">
            <Zap className="h-3 w-3" />
            cache hit
          </span>
        )}
        {hasError && (
          <span className="flex items-center gap-1 text-red-400">
            <AlertCircle className="h-3 w-3" />
            erro
          </span>
        )}
      </div>

      {/* Erro */}
      {hasError && (
        <p className="text-[11px] text-red-400 font-mono break-words">
          {entry.error}
        </p>
      )}

      {/* Candidatos */}
      {hasCandidates && (
        <div className="flex flex-col gap-1.5">
          <div className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
            Candidatos ({entry.candidates.length})
          </div>
          {entry.candidates.map((c, i) => (
            <CandidateRow key={i} candidate={c} />
          ))}
        </div>
      )}

      {/* Intent */}
      <div className="text-[10px] text-text-muted">
        intent: <span className="text-text font-mono">{entry.intent || "—"}</span>
      </div>
    </div>
  );
}

function CandidateRow({ candidate }: { candidate: SemanticCandidateEntry }) {
  const ref = candidate.verse > 0
    ? `${candidate.book} ${candidate.chapter}:${candidate.verse}`
    : `${candidate.book} ${candidate.chapter}`;
  const pct = Math.round(candidate.confidence * 100);

  return (
    <div
      className="flex flex-col gap-1 rounded border border-border bg-surface p-2"
      data-testid="semantic-candidate"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-mono text-text">{ref}</span>
        <span className="text-[10px] text-text-muted">{pct}%</span>
      </div>
      {/* Barra de confiança */}
      <div className="h-1.5 w-full rounded-full bg-border overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            pct >= 80 ? "bg-emerald-500" : pct >= 60 ? "bg-yellow-500" : "bg-red-500",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
      {candidate.reason && (
        <p className="text-[10px] text-text-muted italic break-words">
          {candidate.reason}
        </p>
      )}
    </div>
  );
}

function CurrentResolution({ entry }: { entry: SemanticResolutionEntry }) {
  const resolved = entry.resolved;
  const chosenRef = entry.chosenBook
    ? entry.chosenVerse > 0
      ? `${entry.chosenBook} ${entry.chosenChapter}:${entry.chosenVerse}`
      : `${entry.chosenBook} ${entry.chosenChapter}`
    : "";

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-md border p-3",
        resolved
          ? "border-emerald-600/40 bg-emerald-900/10"
          : "border-border bg-surface-2",
      )}
      data-testid="semantic-current-resolution"
    >
      <div className="flex items-center gap-2">
        {resolved ? (
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
        ) : (
          <XCircle className="h-4 w-4 text-text-muted" />
        )}
        <span className="text-xs font-semibold text-text">
          {resolved ? "Resolvido" : "Não resolvido"}
        </span>
        {entry.skippedDueToParser && (
          <span className="text-[10px] text-yellow-400 ml-auto">
            parser venceu
          </span>
        )}
      </div>

      {resolved && chosenRef && (
        <div className="flex flex-col gap-1">
          <span className="text-[10px] text-text-muted uppercase tracking-wide">
            Candidato escolhido
          </span>
          <span className="text-sm font-mono text-emerald-400">
            {chosenRef}
          </span>
          <span className="text-[10px] text-text-muted">
            confiança: {(entry.chosenConfidence * 100).toFixed(0)}%
          </span>
        </div>
      )}

      <div className="flex flex-wrap gap-3 text-[10px] text-text-muted">
        <span>
          recebidos: <span className="text-text font-mono">{entry.numCandidatesIn}</span>
        </span>
        <span>
          válidos: <span className="text-text font-mono">{entry.numCandidatesValid}</span>
        </span>
        <span>
          motivo: <span className="text-text font-mono">{entry.reason}</span>
        </span>
      </div>
    </div>
  );
}

function InferenceRow({ entry }: { entry: SemanticInferenceEntry }) {
  const hasError = entry.error.length > 0;
  return (
    <div className="flex items-center gap-2 text-[10px] text-text-muted">
      {hasError ? (
        <XCircle className="h-3 w-3 text-red-400 shrink-0" />
      ) : entry.candidates.length > 0 ? (
        <Sparkles className="h-3 w-3 text-purple-400 shrink-0" />
      ) : (
        <XCircle className="h-3 w-3 text-text-muted shrink-0" />
      )}
      <span className="font-mono truncate flex-1">
        {entry.contextText.slice(0, 50) || "(vazio)"}
      </span>
      <span className="shrink-0">{entry.inferenceMs}ms</span>
      {entry.cached && <Zap className="h-3 w-3 text-emerald-400 shrink-0" />}
    </div>
  );
}

function ResolutionRow({ entry }: { entry: SemanticResolutionEntry }) {
  const chosenRef = entry.chosenBook
    ? entry.chosenVerse > 0
      ? `${entry.chosenBook} ${entry.chosenChapter}:${entry.chosenVerse}`
      : `${entry.chosenBook} ${entry.chosenChapter}`
    : "";
  return (
    <div className="flex items-center gap-2 text-[10px] text-text-muted">
      {entry.resolved ? (
        <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
      ) : (
        <XCircle className="h-3 w-3 text-text-muted shrink-0" />
      )}
      <span className="font-mono truncate flex-1">
        {entry.resolved ? chosenRef : entry.reason}
      </span>
      {entry.skippedDueToParser && (
        <span className="text-yellow-400 shrink-0">parser</span>
      )}
    </div>
  );
}
