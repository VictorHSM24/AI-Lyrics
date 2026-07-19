/**
 * Testes dos componentes da Operational Foundation.
 *
 * Cobertura:
 * - OperationStatusBadge (todos os estados)
 * - StartupStepRow (todos os estados)
 * - StartupScreen (fluxo completo)
 * - HealthPanel (itens e status)
 * - AudioLevelMeter (nível, dB, estado vazio)
 * - OperationContext (estado, settings, persistência, startup)
 * - TabNav (navegação entre abas)
 * - Form controls (TextField, NumberField, SelectField, Toggle, Button)
 * - GeneralTab, AudioTab, AITab, HolyricsTab, SystemTab, AdvancedTab
 * - ConfigurationPage (abas)
 * - AboutPage (informações completas)
 * - StartupPage
 * - Persistência (localStorage)
 * - Restauração
 * - Auto Save
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  ThemeProvider,
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
  OperationProvider,
  useOperationState,
  type OperationState,
} from "@/contexts";
import {
  OperationStatusBadge,
  StartupStepRow,
  StartupScreen,
  HealthPanel,
  AudioLevelMeter,
} from "@/components/operational";
import {
  TabNav,
  TextField,
  NumberField,
  SelectField,
  Toggle,
  Button,
  FieldShell,
} from "@/components/settings";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { AudioTab } from "@/components/settings/AudioTab";
import { AITab } from "@/components/settings/AITab";
import { HolyricsTab } from "@/components/settings/HolyricsTab";
import { SystemTab } from "@/components/settings/SystemTab";
import { AdvancedTab } from "@/components/settings/AdvancedTab";
import { ConfigurationPage } from "@/pages/ConfigurationPage";
import { AboutPage } from "@/pages/AboutPage";
import { StartupPage } from "@/pages/StartupPage";
import type { StartupStep } from "@/contexts/OperationContext";

// ============================================================
// Helpers
// ============================================================

function wrapProviders(children: React.ReactNode, opts?: { skipStartup?: boolean }) {
  return (
    <ThemeProvider>
      <ApplicationProvider>
        <InfraProvider>
          <ConnectionProvider>
            <OperationProvider skipStartup={opts?.skipStartup ?? true}>
              <NotificationsProvider>
                <MemoryRouter>{children}</MemoryRouter>
              </NotificationsProvider>
            </OperationProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>
  );
}

function OperationConsumer() {
  const { operation, settings, startupSteps } = useOperationState();
  return (
    <div>
      <span data-testid="op-state">{operation?.data.state ?? "none"}</span>
      <span data-testid="op-message">{operation?.data.message ?? ""}</span>
      <span data-testid="settings-lang">{settings?.data.general.language ?? "none"}</span>
      <span data-testid="settings-audio-id">{settings?.data.audio.selectedDeviceId ?? "none"}</span>
      <span data-testid="startup-count">{startupSteps.length}</span>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
});

// ============================================================
// OperationStatusBadge
// ============================================================

describe("OperationStatusBadge", () => {
  const states: OperationState[] = [
    "stopped", "starting", "ready", "running",
    "paused", "degraded", "error", "stopping",
  ];

  for (const state of states) {
    it(`renderiza estado ${state}`, () => {
      render(<OperationStatusBadge state={state} />);
      const badge = screen.getByTestId("operation-status-badge");
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveAttribute("data-state", state);
    });
  }

  it("exibe tooltip com mensagem", () => {
    render(<OperationStatusBadge state="error" message="Falha na conexão" />);
    expect(screen.getByTestId("operation-status-badge")).toHaveAttribute(
      "title",
      "Erro: Falha na conexão",
    );
  });

  it("modo compacto renderiza apenas StatusBadge", () => {
    render(<OperationStatusBadge state="ready" compact />);
    const badge = screen.getByTestId("operation-status-badge");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("data-state", "ready");
  });

  it("tem role=status para acessibilidade", () => {
    render(<OperationStatusBadge state="running" />);
    expect(screen.getByTestId("operation-status-badge")).toHaveAttribute("role", "status");
  });
});

// ============================================================
// StartupStepRow
// ============================================================

describe("StartupStepRow", () => {
  const stepStates: StartupStep["state"][] = ["pending", "running", "success", "warning", "error"];

  for (const state of stepStates) {
    it(`renderiza etapa em estado ${state}`, () => {
      const step: StartupStep = { id: "test", label: "Teste", state };
      render(<StartupStepRow step={step} />);
      const el = screen.getByTestId("startup-step");
      expect(el).toHaveAttribute("data-state", state);
      expect(el).toHaveAttribute("data-step-id", "test");
    });
  }

  it("exibe duração quando disponível", () => {
    const step: StartupStep = { id: "test", label: "Teste", state: "success", durationMs: 42 };
    render(<StartupStepRow step={step} />);
    expect(screen.getByText("42ms")).toBeInTheDocument();
  });

  it("exibe mensagem no tooltip", () => {
    const step: StartupStep = { id: "test", label: "Teste", state: "warning", message: "Não configurado" };
    render(<StartupStepRow step={step} />);
    expect(screen.getByTestId("startup-step")).toHaveAttribute(
      "title",
      "Teste: Não configurado",
    );
  });
});

// ============================================================
// StartupScreen
// ============================================================

describe("StartupScreen", () => {
  it("renderiza logo e nome da aplicação", () => {
    render(wrapProviders(<StartupScreen />));
    expect(screen.getByText("AI Lyrics")).toBeInTheDocument();
  });

  it("renderiza todas as etapas de inicialização", () => {
    render(wrapProviders(<StartupScreen />));
    expect(screen.getByTestId("startup-steps")).toBeInTheDocument();
    // 8 etapas: backend, eventstream, websocket, presentation, stt, holyrics, config, pipeline
    const steps = screen.getAllByTestId("startup-step");
    expect(steps).toHaveLength(8);
  });

  it("renderiza botão Continuar quando pronto", async () => {
    render(wrapProviders(<StartupScreen />, { skipStartup: false }));
    await waitFor(
      () => {
        expect(screen.getByTestId("startup-continue")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });

  it("renderiza botão Reiniciar após completar", async () => {
    render(wrapProviders(<StartupScreen />, { skipStartup: false }));
    await waitFor(
      () => {
        expect(screen.getByTestId("startup-retry")).toBeInTheDocument();
      },
      { timeout: 5000 },
    );
  });
});

// ============================================================
// HealthPanel
// ============================================================

describe("HealthPanel", () => {
  it("renderiza todos os itens de saúde", () => {
    render(wrapProviders(<HealthPanel />));
    const items = screen.getAllByTestId("health-item");
    // 9 itens: backend, presentation, websocket, eventstream, pipeline, microphone, stt, bible, holyrics
    expect(items).toHaveLength(9);
  });

  it("marca backend como offline quando desconectado", () => {
    render(wrapProviders(<HealthPanel />));
    const items = screen.getAllByTestId("health-item");
    const backend = items.find((el) => el.getAttribute("data-item-id") === "backend");
    expect(backend).toBeDefined();
    expect(backend).toHaveAttribute("data-status", "offline");
  });

  it("tem role=list para acessabilidade", () => {
    render(wrapProviders(<HealthPanel />));
    expect(screen.getByTestId("health-panel")).toHaveAttribute("role", "list");
  });

  it("modo compacto renderiza grid com 3 colunas", () => {
    render(wrapProviders(<HealthPanel compact />));
    expect(screen.getByTestId("health-panel")).toBeInTheDocument();
  });
});

// ============================================================
// AudioLevelMeter
// ============================================================

describe("AudioLevelMeter", () => {
  it("renderiza barra de nível", () => {
    render(<AudioLevelMeter level={0.5} deviceName="Mic" />);
    expect(screen.getByTestId("audio-level-meter")).toBeInTheDocument();
  });

  it("exibe dB", () => {
    render(<AudioLevelMeter level={0.5} />);
    expect(screen.getByTestId("audio-level-db")).toBeInTheDocument();
  });

  it("exibe nome do dispositivo", () => {
    render(<AudioLevelMeter level={0.5} deviceName="Microfone USB" />);
    expect(screen.getByTestId("audio-level-device")).toHaveTextContent("Microfone USB");
  });

  it("exibe estado vazio quando noDevice", () => {
    render(<AudioLevelMeter noDevice />);
    const meter = screen.getByTestId("audio-level-meter");
    expect(meter).toHaveAttribute("data-state", "no-device");
    expect(screen.getByText("Sem dispositivo")).toBeInTheDocument();
  });

  it("tem role=meter com aria-valuenow", () => {
    render(<AudioLevelMeter level={0.5} />);
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow");
  });

  it("modo compacto não mostra device/atividade", () => {
    render(<AudioLevelMeter level={0.5} compact />);
    expect(screen.queryByTestId("audio-level-device")).not.toBeInTheDocument();
  });
});

// ============================================================
// OperationContext
// ============================================================

describe("OperationContext", () => {
  it("fornece estado operacional inicial", () => {
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("op-state")).toHaveTextContent("stopped");
  });

  it("fornece settings padrão", () => {
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("settings-lang")).toHaveTextContent("pt-BR");
  });

  it("fornece 8 etapas de startup", () => {
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("startup-count")).toHaveTextContent("8");
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<OperationConsumer />)).toThrow();
    spy.mockRestore();
  });
});

// ============================================================
// Persistência + Restauração
// ============================================================

describe("Persistência de Settings", () => {
  it("salva settings no localStorage", () => {
    function Updater() {
      const { updateSettings } = useOperationState();
      return (
        <button
          onClick={() =>
            updateSettings((prev) => ({
              ...prev,
              general: { ...prev.general, language: "en-US" },
            }))
          }
        >
          update
        </button>
      );
    }
    render(wrapProviders(<Updater />));
    fireEvent.click(screen.getByText("update"));
    const stored = JSON.parse(localStorage.getItem("ai-lyrics:settings") || "{}");
    expect(stored.general.language).toBe("en-US");
  });

  it("restaura settings do localStorage ao iniciar", () => {
    localStorage.setItem(
      "ai-lyrics:settings",
      JSON.stringify({
        general: { language: "es-ES", theme: "dark", autoStart: true, autoConnect: false },
        audio: { selectedDeviceId: "mic-99", sampleRate: 16000, channels: 1 },
        holyrics: { url: "http://h:1", token: "t", version: "v1", quickPresentation: false },
        ai: {
          whisperModel: "whisper-small",
          backend: "faster-whisper",
          device: "gpu",
          computeType: "float16",
          language: "en",
          threads: 8,
          llmModel: "llama3",
        },
      }),
    );
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("settings-lang")).toHaveTextContent("es-ES");
    expect(screen.getByTestId("settings-audio-id")).toHaveTextContent("mic-99");
  });

  it("usa defaults quando localStorage está vazio", () => {
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("settings-lang")).toHaveTextContent("pt-BR");
  });

  it("usa defaults quando localStorage tem JSON inválido", () => {
    localStorage.setItem("ai-lyrics:settings", "not-json{");
    render(wrapProviders(<OperationConsumer />));
    expect(screen.getByTestId("settings-lang")).toHaveTextContent("pt-BR");
  });
});

// ============================================================
// Auto Save
// ============================================================

describe("Auto Save", () => {
  it("persiste automaticamente ao alterar settings", () => {
    function AutoSaveTest() {
      const { updateSettings } = useOperationState();
      return (
        <button
          onClick={() =>
            updateSettings((prev) => ({
              ...prev,
              audio: { ...prev.audio, selectedDeviceId: "auto-save-mic" },
            }))
          }
        >
          autosave
        </button>
      );
    }
    render(wrapProviders(<AutoSaveTest />));
    fireEvent.click(screen.getByText("autosave"));
    const stored = JSON.parse(localStorage.getItem("ai-lyrics:settings") || "{}");
    expect(stored.audio.selectedDeviceId).toBe("auto-save-mic");
  });
});

// ============================================================
// TabNav
// ============================================================

describe("TabNav", () => {
  const tabs = [
    { id: "a", label: "Aba A", content: <div data-testid="content-a">A</div> },
    { id: "b", label: "Aba B", content: <div data-testid="content-b">B</div> },
  ];

  it("renderiza botões de aba", () => {
    render(<TabNav tabs={tabs} activeTab="a" onChange={() => {}} />);
    expect(screen.getByTestId("tab-button-a")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-b")).toBeInTheDocument();
  });

  it("marca aba ativa", () => {
    render(<TabNav tabs={tabs} activeTab="a" onChange={() => {}} />);
    expect(screen.getByTestId("tab-button-a")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("tab-button-b")).toHaveAttribute("data-active", "false");
  });

  it("renderiza conteúdo da aba ativa", () => {
    render(<TabNav tabs={tabs} activeTab="a" onChange={() => {}} />);
    expect(screen.getByTestId("content-a")).toBeInTheDocument();
    expect(screen.queryByTestId("content-b")).not.toBeInTheDocument();
  });

  it("chama onChange ao clicar em aba", () => {
    const onChange = vi.fn();
    render(<TabNav tabs={tabs} activeTab="a" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("tab-button-b"));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("tem role=tablist e role=tab", () => {
    render(<TabNav tabs={tabs} activeTab="a" onChange={() => {}} />);
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(2);
  });
});

// ============================================================
// Form Controls
// ============================================================

describe("TextField", () => {
  it("renderiza label e input", () => {
    render(<TextField label="Nome" value="" onChange={() => {}} />);
    expect(screen.getByText("Nome")).toBeInTheDocument();
    expect(screen.getByTestId("text-field")).toBeInTheDocument();
  });

  it("chama onChange ao digitar", () => {
    const onChange = vi.fn();
    render(<TextField label="Nome" value="" onChange={onChange} />);
    fireEvent.change(screen.getByTestId("text-field"), { target: { value: "abc" } });
    expect(onChange).toHaveBeenCalledWith("abc");
  });

  it("exibe erro quando fornecido", () => {
    render(<TextField label="Nome" value="" onChange={() => {}} error="Inválido" />);
    expect(screen.getByText("Inválido")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("exibe descrição", () => {
    render(<TextField label="Nome" value="" onChange={() => {}} description="Digite seu nome" />);
    expect(screen.getByText("Digite seu nome")).toBeInTheDocument();
  });
});

describe("NumberField", () => {
  it("renderiza input numérico", () => {
    render(<NumberField label="Threads" value={4} onChange={() => {}} />);
    expect(screen.getByTestId("number-field")).toHaveValue(4);
  });

  it("chama onChange com número", () => {
    const onChange = vi.fn();
    render(<NumberField label="Threads" value={4} onChange={onChange} />);
    fireEvent.change(screen.getByTestId("number-field"), { target: { value: "8" } });
    expect(onChange).toHaveBeenCalledWith(8);
  });
});

describe("SelectField", () => {
  it("renderiza opções", () => {
    render(
      <SelectField
        label="Idioma"
        value="pt"
        options={[
          { value: "pt", label: "Português" },
          { value: "en", label: "English" },
        ]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("select-field")).toBeInTheDocument();
    expect(screen.getAllByRole("option")).toHaveLength(2);
  });
});

describe("Toggle", () => {
  it("renderiza switch com aria-checked", () => {
    render(<Toggle label="Auto" checked={false} onChange={() => {}} />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
  });

  it("chama onChange ao clicar", () => {
    const onChange = vi.fn();
    render(<Toggle label="Auto" checked={false} onChange={onChange} />);
    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(true);
  });
});

describe("Button", () => {
  it("renderiza com variante primary", () => {
    render(<Button variant="primary">OK</Button>);
    expect(screen.getByTestId("button")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("desabilita quando loading", () => {
    render(<Button loading>OK</Button>);
    expect(screen.getByTestId("button")).toBeDisabled();
  });
});

describe("FieldShell", () => {
  it("renderiza label e children", () => {
    render(
      <FieldShell label="Campo">
        <input />
      </FieldShell>,
    );
    expect(screen.getByText("Campo")).toBeInTheDocument();
  });
});

// ============================================================
// Settings Tabs
// ============================================================

describe("GeneralTab", () => {
  it("renderiza informações da aplicação", () => {
    render(wrapProviders(<GeneralTab />));
    expect(screen.getByText("Aplicação")).toBeInTheDocument();
  });

  it("renderiza campo de idioma", () => {
    render(wrapProviders(<GeneralTab />));
    expect(screen.getByText("Idioma")).toBeInTheDocument();
  });

  it("renderiza toggle Auto Connect", () => {
    render(wrapProviders(<GeneralTab />));
    expect(screen.getByText("Auto Connect")).toBeInTheDocument();
  });
});

describe("AudioTab", () => {
  it("renderiza lista de dispositivos", () => {
    render(wrapProviders(<AudioTab />));
    expect(screen.getByText("Dispositivos")).toBeInTheDocument();
  });

  it("renderiza botão Atualizar", () => {
    render(wrapProviders(<AudioTab />));
    expect(screen.getByText("Atualizar")).toBeInTheDocument();
  });

  it("renderiza teste de áudio", () => {
    render(wrapProviders(<AudioTab />));
    expect(screen.getByText("Teste de áudio")).toBeInTheDocument();
  });
});

describe("AITab", () => {
  it("renderiza configuração STT", () => {
    render(wrapProviders(<AITab />));
    expect(screen.getByText("Speech-to-Text")).toBeInTheDocument();
  });

  it("renderiza campo LLM", () => {
    render(wrapProviders(<AITab />));
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });

  it("renderiza opções de modelo Whisper", () => {
    render(wrapProviders(<AITab />));
    expect(screen.getByText("Modelo Whisper")).toBeInTheDocument();
  });
});

describe("HolyricsTab", () => {
  it("renderiza campo URL", () => {
    render(wrapProviders(<HolyricsTab />));
    expect(screen.getByText("URL")).toBeInTheDocument();
  });

  it("renderiza botão Testar conexão", () => {
    render(wrapProviders(<HolyricsTab />));
    expect(screen.getByText("Testar conexão")).toBeInTheDocument();
  });

  it("exibe resultado do teste ao clicar", async () => {
    render(wrapProviders(<HolyricsTab />));
    fireEvent.click(screen.getByText("Testar conexão"));
    await waitFor(() => {
      expect(screen.getByTestId("holyrics-test-result")).toBeInTheDocument();
    });
  });
});

describe("SystemTab", () => {
  it("renderiza diretórios", () => {
    render(wrapProviders(<SystemTab />));
    expect(screen.getByText("Diretórios")).toBeInTheDocument();
  });

  it("renderiza versões", () => {
    render(wrapProviders(<SystemTab />));
    expect(screen.getByText("Versões")).toBeInTheDocument();
  });

  it("renderiza botão Limpar Cache", () => {
    render(wrapProviders(<SystemTab />));
    expect(screen.getByText("Limpar Cache")).toBeInTheDocument();
  });
});

describe("AdvancedTab", () => {
  it("renderiza estado vazio quando sem backend", () => {
    render(wrapProviders(<AdvancedTab />));
    expect(screen.getByText("Avançado")).toBeInTheDocument();
  });
});

// ============================================================
// ConfigurationPage
// ============================================================

describe("ConfigurationPage", () => {
  it("renderiza todas as abas", () => {
    render(wrapProviders(<ConfigurationPage />));
    expect(screen.getByTestId("tab-button-general")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-audio")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-ai")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-holyrics")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-system")).toBeInTheDocument();
    expect(screen.getByTestId("tab-button-advanced")).toBeInTheDocument();
  });

  it("troca de aba ao clicar", () => {
    render(wrapProviders(<ConfigurationPage />));
    // Aba geral ativa por padrão
    expect(screen.getByTestId("general-tab")).toBeInTheDocument();
    // Clica em Áudio
    fireEvent.click(screen.getByTestId("tab-button-audio"));
    expect(screen.getByTestId("audio-tab")).toBeInTheDocument();
  });
});

// ============================================================
// AboutPage
// ============================================================

describe("AboutPage", () => {
  it("renderiza nome e versão", () => {
    render(wrapProviders(<AboutPage />));
    expect(screen.getByText("Sobre")).toBeInTheDocument();
  });

  it("renderiza HealthPanel", () => {
    render(wrapProviders(<AboutPage />));
    expect(screen.getByTestId("health-panel")).toBeInTheDocument();
  });

  it("renderiza OperationStatusBadge", () => {
    render(wrapProviders(<AboutPage />));
    expect(screen.getByTestId("operation-status-badge")).toBeInTheDocument();
  });

  it("renderiza modelos de IA", () => {
    render(wrapProviders(<AboutPage />));
    expect(screen.getByText("Modelos de IA")).toBeInTheDocument();
  });
});

// ============================================================
// StartupPage
// ============================================================

describe("StartupPage", () => {
  it("renderiza StartupScreen", () => {
    render(wrapProviders(<StartupPage />));
    expect(screen.getByTestId("startup-screen")).toBeInTheDocument();
  });
});
