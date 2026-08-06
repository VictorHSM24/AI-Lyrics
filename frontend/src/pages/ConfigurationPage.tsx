/**
 * ConfigurationPage — tela de Configurações funcional.
 *
 * Dividida em abas: Geral, Áudio, IA, Holyrics, Sistema, Avançado.
 * Toda alteração é persistida automaticamente via OperationContext.
 */

import { useState } from "react";
import { Settings, Mic, Brain, Church, Server, Wrench } from "lucide-react";
import { PageLayout } from "@/app/layout";
import { OperationStatusBadge } from "@/components/operational";
import { useOperationState } from "@/contexts/OperationContext";
import { TabNav, type TabDef, SaveRestartBar } from "@/components/settings";
import { GeneralTab } from "@/components/settings/GeneralTab";
import { AudioTab } from "@/components/settings/AudioTab";
import { AITab } from "@/components/settings/AITab";
import { HolyricsTab } from "@/components/settings/HolyricsTab";
import { SystemTab } from "@/components/settings/SystemTab";
import { AdvancedTab } from "@/components/settings/AdvancedTab";

type TabId = "general" | "audio" | "ai" | "holyrics" | "system" | "advanced";

export function ConfigurationPage() {
  const [activeTab, setActiveTab] = useState<TabId>("general");
  const { operation } = useOperationState();
  const opState = operation?.data.state ?? "stopped";
  const opMessage = operation?.data.message ?? "";

  const tabs: TabDef[] = [
    {
      id: "general",
      label: "Geral",
      icon: <Settings className="h-4 w-4" />,
      content: <GeneralTab />,
    },
    {
      id: "audio",
      label: "Áudio",
      icon: <Mic className="h-4 w-4" />,
      content: <AudioTab />,
    },
    {
      id: "ai",
      label: "IA",
      icon: <Brain className="h-4 w-4" />,
      content: <AITab />,
    },
    {
      id: "holyrics",
      label: "Holyrics",
      icon: <Church className="h-4 w-4" />,
      content: <HolyricsTab />,
    },
    {
      id: "system",
      label: "Sistema",
      icon: <Server className="h-4 w-4" />,
      content: <SystemTab />,
    },
    {
      id: "advanced",
      label: "Avançado",
      icon: <Wrench className="h-4 w-4" />,
      content: <AdvancedTab />,
    },
  ];

  return (
    <PageLayout
      title="Configurações"
      description="Configure o AI Lyrics. As alterações são salvas automaticamente."
      toolbar={
        <OperationStatusBadge state={opState} message={opMessage} />
      }
    >
      <TabNav
        tabs={tabs}
        activeTab={activeTab}
        onChange={(id) => setActiveTab(id as TabId)}
      />

      {/* Sprint 27 — Barra global "Salvar e Reiniciar Backend".
          Fica no rodapé, FORA das abas, para que o usuário entenda
          que TODAS as configurações de TODAS as abas serão salvas
          de uma só vez antes de reiniciar o backend. */}
      <SaveRestartBar />
    </PageLayout>
  );
}
