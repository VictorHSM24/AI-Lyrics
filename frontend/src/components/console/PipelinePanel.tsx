/**
 * PipelinePanel — painel do pipeline mostrando as etapas.
 *
 * Mostra o fluxo:
 *   Microfone → Captura → VAD → Speech Segment → Whisper →
 *   Intenção → Busca Bíblica → Holyrics → Concluído
 *
 * Cada etapa muda visualmente conforme o estado:
 * Idle, Running, Success, Warning, Error.
 *
 * O estado é inferido a partir do último evento recebido.
 */

import { useEvents, usePipeline } from "@/hooks";
import { Panel } from "@/components";
import { PipelineStage, type StageState } from "./PipelineStage";

// Definição das etapas do pipeline.
const STAGE_NAMES = [
  "Microfone",
  "Captura",
  "VAD",
  "Speech Segment",
  "Whisper",
  "Intenção",
  "Busca Bíblica",
  "Holyrics",
  "Concluído",
] as const;

// Mapeamento de tipos de evento → etapa → estado.
const EVENT_TO_STAGE: Record<string, { stage: string; state: StageState }> = {
  AudioCaptured: { stage: "Captura", state: "success" },
  SpeechStarted: { stage: "VAD", state: "running" },
  SpeechEnded: { stage: "VAD", state: "success" },
  SpeechSegmentReceived: { stage: "Speech Segment", state: "success" },
  SpeechRecognized: { stage: "Whisper", state: "success" },
  IntentDetected: { stage: "Intenção", state: "success" },
  SearchRequested: { stage: "Busca Bíblica", state: "running" },
  SearchCompleted: { stage: "Busca Bíblica", state: "success" },
  CandidateGenerated: { stage: "Busca Bíblica", state: "running" },
  RecommendationChosen: { stage: "Busca Bíblica", state: "success" },
  VerseFound: { stage: "Busca Bíblica", state: "success" },
  HolyricsRequest: { stage: "Holyrics", state: "running" },
  HolyricsSuccess: { stage: "Holyrics", state: "success" },
  HolyricsFailure: { stage: "Holyrics", state: "error" },
  PresentationCompleted: { stage: "Concluído", state: "success" },
  PipelineError: { stage: "Concluído", state: "error" },
};

export function PipelinePanel() {
  const { events } = useEvents();
  const { status } = usePipeline();

  // Constrói mapa de estágio → estado a partir dos eventos.
  const stageStates: Record<string, StageState> = {};
  const stageLatencies: Record<string, number> = {};

  for (const event of events) {
    const mapping = EVENT_TO_STAGE[event.event_type];
    if (!mapping) continue;
    // Só atualiza se for mais recente ou se for erro (prioridade).
    const current = stageStates[mapping.stage];
    if (current === "error" && mapping.state !== "error") continue;
    stageStates[mapping.stage] = mapping.state;

    const latency = event.payload["latency_ms"] as number | undefined;
    if (latency != null && latency > 0) {
      stageLatencies[mapping.stage] = latency;
    }
  }

  // Se o pipeline está parado, todas as etapas estão idle.
  if (!status?.running && !status?.paused) {
    for (const name of STAGE_NAMES) {
      if (!(name in stageStates)) stageStates[name] = "idle";
    }
  } else if (status?.is_processing) {
    // Se está processando, "Microfone" está ativo.
    if (!stageStates["Microfone"]) stageStates["Microfone"] = "running";
  } else {
    // Se está rodando mas ocioso, "Microfone" está ativo (ouvindo).
    if (!stageStates["Microfone"]) stageStates["Microfone"] = "running";
  }

  return (
    <div data-testid="pipeline-panel">
    <Panel title="Pipeline">
      <div className="flex flex-col gap-2">
        {STAGE_NAMES.map((name, i) => (
          <div key={name} className="flex flex-col gap-1">
            <PipelineStage
              name={name}
              state={stageStates[name] ?? "idle"}
              latencyMs={stageLatencies[name]}
            />
            {i < STAGE_NAMES.length - 1 && (
              <div className="ml-4 h-2 w-px bg-border" aria-hidden="true" />
            )}
          </div>
        ))}
      </div>
    </Panel>
    </div>
  );
}
