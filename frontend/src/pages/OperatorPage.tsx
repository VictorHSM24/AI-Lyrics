/**
 * OperatorPage — Painel do Operador (Sprint 25 Fase B).
 *
 * Interface dedicada para o operador de cultos apresentar versículos
 * no Holyrics manualmente, sem precisar abrir o Holyrics diretamente.
 *
 * Sprint 25 Fase B: usa OperatorWorkspace (navegação rápida ◀ ▶,
 * atalhos de teclado, separação visual Selecionado/Apresentado,
 * sincronização automática após apresentação).
 *
 * Layout:
 *   1. Cabeçalho (PageLayout)
 *   2. OperatorWorkspace (QuickNavigator + PresentationCards + histórico)
 *
 * Atualização do histórico é em tempo real via EventStream →
 * VersePresentationStore → useVersePresentation.
 */

import { PageLayout } from "@/app/layout";
import { ConnectionIndicator } from "@/components";
import { OperatorWorkspace } from "@/components/operator";

export function OperatorPage() {
  return (
    <PageLayout
      title="Painel do Operador"
      description="Navegação bíblica e apresentação manual no Holyrics."
    >
      <div className="mb-2">
        <ConnectionIndicator />
      </div>
      <OperatorWorkspace />
    </PageLayout>
  );
}
