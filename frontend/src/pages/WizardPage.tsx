/**
 * WizardPage — Assistente de configuração de primeira execução (Sprint 23.0).
 *
 * 5 etapas: Áudio → Holyrics → Ollama → Bíblia → Teste → Concluído.
 *
 * Acessada em /wizard na primeira execução (main.py abre o browser aqui
 * quando o flag .wizard_completed não existe). Após concluir, chama
 * POST /wizard/complete que cria o flag e redireciona para o Dashboard.
 *
 * Cada etapa é um componente em frontend/src/components/wizard/. Este
 * arquivo contém apenas o shell, o stepper e a orquestração das etapas.
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Cpu,
  Database,
  Mic,
  PlayCircle,
} from "lucide-react";

import {
  AudioStep,
  BibleStep,
  HolyricsStep,
  OllamaStep,
  TestStep,
  STEPS,
  apiGet,
  apiPost,
  type Step,
  type WizardStatus,
} from "@/components/wizard";

// ============================================================
// Componente principal
// ============================================================

export function WizardPage() {
  const navigate = useNavigate();
  const [stepIdx, setStepIdx] = useState(0);
  const [status, setStatus] = useState<WizardStatus | null>(null);
  // Sprint 23.1: estado que bloqueia navegação durante operações.
  // Cada Step reporta se está busy (loading, testing, pulling) via
  // onBusyChange. O WizardPage desabilita Voltar/Próxima enquanto busy.
  const [busy, setBusy] = useState(false);

  const loadStatus = useCallback(async () => {
    try {
      const s = await apiGet<WizardStatus>("/status");
      setStatus(s);
    } catch (e) {
      console.error("wizard status error", e);
    }
  }, []);

  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const goNext = () => {
    if (busy) return;
    if (stepIdx < STEPS.length - 1) {
      setStepIdx(stepIdx + 1);
    } else {
      setStepIdx(STEPS.length);
    }
  };

  const goPrev = () => {
    if (busy) return;
    if (stepIdx > 0) setStepIdx(stepIdx - 1);
  };

  const completeWizard = async () => {
    try {
      await apiPost("/complete");
      navigate("/");
    } catch (e) {
      console.error("complete wizard error", e);
    }
  };

  if (status?.completed && stepIdx === 0) {
    return (
      <WizardShell>
        <div className="text-center py-12">
          <CheckCircle2 className="h-16 w-16 text-green-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold mb-2">Configuração já concluída</h2>
          <p className="text-sm text-text-muted mb-6">
            O wizard de primeira execução já foi concluído neste computador.
          </p>
          <button
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-white rounded hover:opacity-90"
          >
            Ir para o Dashboard <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      </WizardShell>
    );
  }

  const currentStep: Step | undefined = STEPS[stepIdx];

  return (
    <WizardShell>
      <Stepper currentIdx={stepIdx} />
      <div className="mt-8">
        {currentStep === "audio" && <AudioStep onBusyChange={setBusy} />}
        {currentStep === "holyrics" && <HolyricsStep onBusyChange={setBusy} />}
        {currentStep === "ollama" && <OllamaStep onBusyChange={setBusy} />}
        {currentStep === "bible" && <BibleStep onBusyChange={setBusy} />}
        {currentStep === "test" && <TestStep onBusyChange={setBusy} />}
        {stepIdx >= STEPS.length && <DoneStep onComplete={completeWizard} />}
      </div>
      {stepIdx < STEPS.length && (
        <div className="mt-8 flex justify-between">
          <button
            onClick={goPrev}
            disabled={stepIdx === 0 || busy}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm text-text-muted disabled:opacity-30"
          >
            <ArrowLeft className="h-4 w-4" /> Voltar
          </button>
          <button
            onClick={goNext}
            disabled={busy}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-accent text-white rounded hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Aguarde..." : "Próxima etapa"} <ArrowRight className="h-4 w-4" />
          </button>
        </div>
      )}
    </WizardShell>
  );
}

// ============================================================
// Shell + Stepper
// ============================================================

function WizardShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background text-text">
      <div className="max-w-3xl mx-auto px-6 py-12">
        <h1 className="text-2xl font-semibold mb-2">AI Lyrics — Configuração inicial</h1>
        <p className="text-sm text-text-muted mb-8">
          Vamos configurar o sistema em 5 etapas rápidas.
        </p>
        {children}
      </div>
    </div>
  );
}

function Stepper({ currentIdx }: { currentIdx: number }) {
  const items: { label: string; icon: React.ReactNode }[] = [
    { label: "Áudio", icon: <Mic className="h-5 w-5" /> },
    { label: "Holyrics", icon: <BookOpen className="h-5 w-5" /> },
    { label: "Ollama", icon: <Cpu className="h-5 w-5" /> },
    { label: "Bíblia", icon: <Database className="h-5 w-5" /> },
    { label: "Teste", icon: <PlayCircle className="h-5 w-5" /> },
  ];
  return (
    <div className="flex items-center gap-2 overflow-x-auto">
      {items.map((it, i) => {
        const done = i < currentIdx;
        const current = i === currentIdx;
        return (
          <div key={it.label} className="flex items-center gap-2 flex-shrink-0">
            <div
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs ${
                done
                  ? "bg-green-100 text-green-700"
                  : current
                    ? "bg-accent text-white"
                    : "bg-surface text-text-muted"
              }`}
            >
              {done ? <CheckCircle2 className="h-4 w-4" /> : it.icon}
              {it.label}
            </div>
            {i < items.length - 1 && <ArrowRight className="h-4 w-4 text-text-muted" />}
          </div>
        );
      })}
    </div>
  );
}

// ============================================================
// Etapa final: Done
// ============================================================

function DoneStep({ onComplete }: { onComplete: () => void }) {
  return (
    <div className="text-center py-12">
      <CheckCircle2 className="h-16 w-16 text-green-500 mx-auto mb-4" />
      <h2 className="text-xl font-semibold mb-2">Configuração concluída!</h2>
      <p className="text-sm text-text-muted mb-6">
        O AI Lyrics está pronto para uso. Você será redirecionado para o
        Dashboard, onde pode iniciar o pipeline.
      </p>
      <button
        onClick={onComplete}
        className="inline-flex items-center gap-2 px-6 py-3 bg-accent text-white rounded hover:opacity-90"
      >
        Concluir e ir para o Dashboard <ArrowRight className="h-4 w-4" />
      </button>
    </div>
  );
}
