/**
 * GeneralTab — Configurações > Geral.
 *
 * Mostra: nome, versão, idioma, tema, auto start, auto connect.
 * Salva automaticamente via OperationContext.updateSettings.
 */

import { Globe, Palette, Play, Plug } from "lucide-react";
import { useOperationState } from "@/contexts/OperationContext";
import { useApplication } from "@/contexts/ApplicationContext";
import { useTheme } from "@/contexts/ThemeContext";
import { Card, PropertyGrid } from "@/components";
import { SelectField, Toggle } from "./FormControls";

const LANGUAGE_OPTIONS = [
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "en-US", label: "English (US)" },
  { value: "es-ES", label: "Español (España)" },
];

export function GeneralTab() {
  const { info } = useApplication();
  const { settings, updateSettings } = useOperationState();
  const { mode, setMode } = useTheme();

  const general = settings?.data.general;

  if (!general) {
    return (
      <Card title="Geral">
        <p className="text-sm text-text-muted">Carregando configurações…</p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="general-tab">
      <Card title="Aplicação" description="Informações básicas do sistema.">
        <PropertyGrid
          properties={[
            { label: "Nome", value: info.name },
            { label: "Versão", value: info.version },
            { label: "Descrição", value: info.description },
          ]}
        />
      </Card>

      <Card title="Preferências" description="Configurações gerais salvas automaticamente.">
        <div className="flex flex-col gap-4">
          <SelectField
            label="Idioma"
            description="Idioma da interface do operador."
            tooltip="Afeta apenas a UI. O reconhecimento de fala tem seu próprio idioma."
            value={general.language}
            options={LANGUAGE_OPTIONS}
            onChange={(value) =>
              updateSettings((prev) => ({
                ...prev,
                general: { ...prev.general, language: value },
              }))
            }
          />

          <SelectField
            label="Tema"
            description="Aparência da interface (claro, escuro, sistema)."
            tooltip="Preparado para futura implementação de temas personalizados."
            value={mode}
            options={[
              { value: "light", label: "Claro" },
              { value: "dark", label: "Escuro" },
              { value: "system", label: "Sistema" },
            ]}
            onChange={(value) => {
              setMode(value as "light" | "dark" | "system");
              updateSettings((prev) => ({
                ...prev,
                general: { ...prev.general, theme: value as "light" | "dark" | "system" },
              }));
            }}
          />

          <Toggle
            label="Auto Start"
            description="Iniciar o pipeline automaticamente ao abrir a aplicação."
            tooltip="Preparado para futura implementação."
            checked={general.autoStart}
            onChange={(checked) =>
              updateSettings((prev) => ({
                ...prev,
                general: { ...prev.general, autoStart: checked },
              }))
            }
          />

          <Toggle
            label="Auto Connect"
            description="Conectar ao backend automaticamente ao iniciar."
            tooltip="Tenta reconectar ao backend assim que a aplicação abre."
            checked={general.autoConnect}
            onChange={(checked) =>
              updateSettings((prev) => ({
                ...prev,
                general: { ...prev.general, autoConnect: checked },
              }))
            }
          />
        </div>
      </Card>

      <Card title="Resumo">
        <div className="flex flex-wrap gap-3 text-xs text-text-muted">
          <span className="inline-flex items-center gap-1">
            <Globe className="h-3.5 w-3.5" /> {general.language}
          </span>
          <span className="inline-flex items-center gap-1">
            <Palette className="h-3.5 w-3.5" /> {general.theme}
          </span>
          <span className="inline-flex items-center gap-1">
            <Play className="h-3.5 w-3.5" /> Auto Start: {general.autoStart ? "Sim" : "Não"}
          </span>
          <span className="inline-flex items-center gap-1">
            <Plug className="h-3.5 w-3.5" /> Auto Connect: {general.autoConnect ? "Sim" : "Não"}
          </span>
        </div>
      </Card>
    </div>
  );
}
