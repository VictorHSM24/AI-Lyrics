/**
 * Testes do PipelineControl (Sprint 17.1).
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import {
  ThemeProvider,
  ApplicationProvider,
  InfraProvider,
  ConnectionProvider,
  NotificationsProvider,
  OperationProvider,
} from "@/contexts";
import { PipelineControl } from "@/components/console";
import { createClient } from "@/sdk";
import { createEventStream, createEventStreamBridge } from "@/stream";
import { createStoreRegistry } from "@/stores";
import { createServices } from "@/services";
import type { ReactNode } from "react";

function makeInfra() {
  const client = createClient();
  const stream = createEventStream();
  const stores = createStoreRegistry();
  const services = createServices(client);
  const bridge = createEventStreamBridge(client, stream, stores);
  bridge.start();
  return { client, stream, stores, services, bridge };
}

function renderWithProviders(ui: ReactNode) {
  const infra = makeInfra();
  return {
    ...render(
      <ThemeProvider>
        <ApplicationProvider>
          <InfraProvider
            client={infra.client}
            stream={infra.stream}
            stores={infra.stores}
            services={infra.services}
          >
            <ConnectionProvider>
              <NotificationsProvider>
                <OperationProvider skipStartup>
                  {ui}
                </OperationProvider>
              </NotificationsProvider>
            </ConnectionProvider>
          </InfraProvider>
        </ApplicationProvider>
      </ThemeProvider>,
    ),
    infra,
  };
}

describe("PipelineControl", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    cleanup();
  });

  it("renderiza com data-testid correto", () => {
    renderWithProviders(<PipelineControl />);
    expect(screen.getByTestId("pipeline-control")).toBeTruthy();
  });

  it("mostra estado Parado no estado inicial", () => {
    renderWithProviders(<PipelineControl />);
    const phase = screen.getByTestId("pipeline-phase");
    expect(phase.textContent).toContain("Parado");
  });

  it("mostra botao Iniciar Pipeline quando parado", () => {
    renderWithProviders(<PipelineControl />);
    expect(screen.getByTestId("pipeline-start-btn")).toBeTruthy();
  });

  it("nao mostra botao Parar quando parado", () => {
    renderWithProviders(<PipelineControl />);
    expect(screen.queryByTestId("pipeline-stop-btn")).toBeNull();
  });
});
