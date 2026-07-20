/**
 * Testes do ReferencePanel (Sprint 17).
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
import { ReferencePanel } from "@/components/operational";
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

describe("ReferencePanel", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    cleanup();
  });

  it("renderiza o título Referência Bíblica", () => {
    renderWithProviders(<ReferencePanel />);
    expect(screen.getByText("Referência Bíblica")).toBeTruthy();
  });

  it("mostra mensagem de nenhuma referência no estado inicial", () => {
    renderWithProviders(<ReferencePanel />);
    // Usa queryByText com substring para evitar problemas de encoding.
    const placeholder = screen.queryByText(/detectada ainda/i);
    const loading = screen.queryByText(/Carregando/i);
    expect(placeholder !== null || loading !== null).toBeTruthy();
  });

  it("tem o panel com data-testid correto", () => {
    renderWithProviders(<ReferencePanel />);
    expect(screen.getByTestId("reference-panel")).toBeTruthy();
  });
});
