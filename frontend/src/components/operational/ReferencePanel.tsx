/**
 * ReferencePanel — painel de referências bíblicas detectadas (Sprint 17).
 *
 * Mostra:
 * - Última referência detectada (livro, capítulo, versículo, confiança)
 * - Badge de confiança (alta/média/baixa)
 * - Histórico de referências
 * - Última referência inválida (se houver)
 *
 * Atualização em tempo real via EventStream → ReferenceStore → useReference.
 */

import { BookOpen, AlertTriangle, History, CheckCircle2 } from "lucide-react";
import { useReference } from "@/hooks";
import { cn } from "@/utils";

interface ReferencePanelProps {
  className?: string;
}

export function ReferencePanel({ className }: ReferencePanelProps) {
  const { current, entries, invalid, loading } = useReference();

  return (
    <div
      className={cn("flex flex-col gap-3 rounded-lg border border-border bg-surface p-4", className)}
      data-testid="reference-panel"
    >
      {/* Header */}
      <div className="flex items-center gap-2">
        <BookOpen className="h-4 w-4 text-text" />
        <h3 className="text-sm font-semibold text-text">Referência Bíblica</h3>
      </div>

      {/* Referência atual */}
      {loading ? (
        <p className="text-xs text-text-muted">Carregando...</p>
      ) : current ? (
        <CurrentReference entry={current} />
      ) : (
        <p className="text-xs text-text-muted italic">
          Nenhuma referência detectada ainda.
        </p>
      )}

      {/* Referência inválida */}
      {invalid && (
        <div
          className="flex items-start gap-2 rounded-md border border-status-error/30 bg-status-error/10 px-3 py-2"
          data-testid="reference-invalid"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-status-error mt-0.5" />
          <div className="flex flex-col gap-0.5">
            <p className="text-xs font-medium text-status-error">
              Referência inválida: {invalid.book}
            </p>
            <p className="text-[10px] text-text-muted">
              {invalid.reason} — "{invalid.rawText.slice(0, 60)}"
            </p>
          </div>
        </div>
      )}

      {/* Histórico */}
      {entries.length > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-1.5 text-[10px] font-medium text-text-muted uppercase tracking-wide">
            <History className="h-3 w-3" />
            Histórico
          </div>
          <div
            className="flex flex-col gap-1.5 max-h-48 overflow-y-auto"
            data-testid="reference-history"
          >
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-2 rounded-md border border-border-subtle bg-surface-elevated px-2.5 py-1.5"
              >
                <CheckCircle2 className="h-3 w-3 shrink-0 text-status-healthy" />
                <span className="text-xs font-medium text-text flex-1">
                  {entry.normalizedText}
                </span>
                <span className="text-[10px] text-text-subtle">
                  {(entry.confidence * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CurrentReference({ entry }: { entry: NonNullable<ReturnType<typeof useReference>["current"]> }) {
  const confidenceLevel = getConfidenceLevel(entry.confidence);

  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border-subtle bg-surface-elevated px-3 py-3"
      data-testid="reference-current"
    >
      {/* Referência normalizada */}
      <div className="flex items-center gap-2">
        <BookOpen className="h-5 w-5 text-primary" />
        <span className="text-lg font-bold text-text">
          {entry.normalizedText}
        </span>
      </div>

      {/* Detalhes */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <DetailRow label="Livro" value={entry.book} />
        <DetailRow label="ID" value={String(entry.bookId)} />
        <DetailRow label="Capítulo" value={String(entry.chapter)} />
        <DetailRow
          label="Versículo"
          value={entry.verseStart === entry.verseEnd
            ? String(entry.verseStart)
            : `${entry.verseStart}-${entry.verseEnd}`}
        />
      </div>

      {/* Confiança */}
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-medium text-text-muted uppercase tracking-wide">
          Confiança
        </span>
        <div className="flex-1 h-1.5 rounded-full bg-surface overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-all", confidenceLevel.color)}
            style={{ width: `${entry.confidence * 100}%` }}
          />
        </div>
        <span className={cn("text-xs font-semibold", confidenceLevel.textColor)}>
          {(entry.confidence * 100).toFixed(0)}%
        </span>
      </div>

      {/* Texto original */}
      <div className="text-[10px] text-text-subtle italic border-t border-border-subtle pt-1.5">
        "{entry.rawText}"
      </div>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-text-muted">{label}:</span>
      <span className="font-medium text-text">{value}</span>
    </div>
  );
}

function getConfidenceLevel(confidence: number): { color: string; textColor: string; label: string } {
  if (confidence >= 0.9) {
    return { color: "bg-status-healthy", textColor: "text-status-healthy", label: "Alta" };
  }
  if (confidence >= 0.7) {
    return { color: "bg-status-warning", textColor: "text-status-warning", label: "Média" };
  }
  return { color: "bg-status-error", textColor: "text-status-error", label: "Baixa" };
}
