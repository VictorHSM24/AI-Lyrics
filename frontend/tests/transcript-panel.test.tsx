/**
 * Testes do TranscriptPanel (Sprint 16).
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  ThemeProvider,
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
  OperationProvider,
} from "@/contexts";
import { TranscriptPanel } from "@/components/operational";
import type { ReactNode } from "react";

function renderWithProviders(ui: ReactNode) {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <ApplicationProvider>
          <InfraProvider>
            <ConnectionProvider>
              <NotificationsProvider>
                <OperationProvider>
                  {ui}
                </OperationProvider>
              </NotificationsProvider>
            </ConnectionProvider>
          </InfraProvider>
        </ApplicationProvider>
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe("TranscriptPanel", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    cleanup();
  });

  it("renderiza o título Transcrição", () => {
    renderWithProviders(<TranscriptPanel />);
    expect(screen.getByText("Transcrição")).toBeTruthy();
  });

  it("mostra mensagem de carregando ou aguardando fala no estado inicial", () => {
    renderWithProviders(<TranscriptPanel />);
    // Estado inicial: pode mostrar "Carregando..." ou "Aguardando fala..."
    // dependendo de se o store já tem snapshot.
    const loading = screen.queryByText("Carregando...");
    const waiting = screen.queryByText("Aguardando fala...");
    expect(loading !== null || waiting !== null).toBeTruthy();
  });

  it("mostra mensagem de nenhuma transcrição ainda", () => {
    renderWithProviders(<TranscriptPanel />);
    expect(screen.getByText("Nenhuma transcrição ainda.")).toBeTruthy();
  });

  it("mostra badge Inativo no estado inicial", () => {
    renderWithProviders(<TranscriptPanel />);
    expect(screen.getByText("Inativo")).toBeTruthy();
  });

  it("tem o panel com data-testid correto", () => {
    renderWithProviders(<TranscriptPanel />);
    expect(screen.getByTestId("transcript-panel")).toBeTruthy();
    expect(screen.getByTestId("transcript-history")).toBeTruthy();
  });
});
