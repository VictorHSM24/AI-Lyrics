/**
 * ConsolePage — Console Operacional do AI Lyrics.
 *
 * Principal interface durante a operação do sistema.
 *
 * Layout (5 regiões):
 *   1. Cabeçalho       — ConsoleHeader
 *   2. Linha do Tempo  — TimelinePanel (central, principal)
 *   3. Pipeline        — PipelinePanel
 *   4. Reconhecimento  — RecognitionPanel
 *   5. Resultado       — ResultPanel
 *
 * Toda atualização ocorre via EventStream → Stores → Hooks.
 * Nenhum polling. Nenhum acesso direto a WebSocket/Transport.
 */

import { PageLayout } from "@/app/layout";
import {
  ConsoleHeader,
  TimelinePanel,
  PipelinePanel,
  PipelineControl,
  RecognitionPanel,
  ResultPanel,
} from "@/components/console";
import { TranscriptPanel, ReferencePanel, VersePresentationPanel, SemanticPanel, SermonMemoryPanel } from "@/components/operational";
import { useAutoStartPipeline } from "@/hooks";
import { useOperationState } from "@/contexts/OperationContext";

export function ConsolePage() {
  const { settings } = useOperationState();
  const autoStart = settings?.data.general.autoStart ?? false;
  useAutoStartPipeline(autoStart);

  return (
    <PageLayout
      title="Console Operacional"
      description="Monitoramento ao vivo do pipeline de reconhecimento."
    >
      {/* 1. Cabeçalho */}
      <ConsoleHeader />

      {/* Sprint 17.1 — Controle do Pipeline (Iniciar/Parar) */}
      <PipelineControl />

      {/* Grid: timeline (principal) + painéis laterais */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* 2. Linha do Tempo (principal, ocupa 2 colunas) */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          <TimelinePanel />
          {/* Sprint 16 — Transcrição em tempo real */}
          <TranscriptPanel />
          {/* Sprint 17 — Referência bíblica detectada */}
          <ReferencePanel />
          {/* Sprint 18 — Apresentação automática no Holyrics */}
          <VersePresentationPanel />
          {/* Sprint 20 — Semantic Engine */}
          <SemanticPanel />
          {/* Sprint 21 — Sermon Memory */}
          <SermonMemoryPanel />
        </div>

        {/* Coluna lateral: Pipeline + Reconhecimento + Resultado */}
        <div className="flex flex-col gap-4">
          {/* 3. Pipeline */}
          <PipelinePanel />

          {/* 4. Reconhecimento */}
          <RecognitionPanel />

          {/* 5. Resultado */}
          <ResultPanel />
        </div>
      </div>
    </PageLayout>
  );
}
