import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  InfraProvider,
  useInfrastructure,
  useClient,
  useEventStream,
  useStores,
  useServices,
  createInfrastructure,
} from "@/contexts/InfraContext";
import {
  createServices,
  createStubServices,
} from "@/services";
import { createClient } from "@/sdk";
import { createEventStream } from "@/stream";
import { createStoreRegistry } from "@/stores";

describe("InfraContext", () => {
  function renderWithInfra(children: React.ReactNode) {
    return render(<InfraProvider>{children}</InfraProvider>);
  }

  it("fornece client, stream, stores, services", () => {
    function Test() {
      const infra = useInfrastructure();
      return (
        <div>
          <span data-testid="has-client">{String(!!infra.client)}</span>
          <span data-testid="has-stream">{String(!!infra.stream)}</span>
          <span data-testid="has-stores">{String(!!infra.stores)}</span>
          <span data-testid="has-services">{String(!!infra.services)}</span>
        </div>
      );
    }
    renderWithInfra(<Test />);
    expect(screen.getByTestId("has-client")).toHaveTextContent("true");
    expect(screen.getByTestId("has-stream")).toHaveTextContent("true");
    expect(screen.getByTestId("has-stores")).toHaveTextContent("true");
    expect(screen.getByTestId("has-services")).toHaveTextContent("true");
  });

  it("useClient retorna client", () => {
    function Test() {
      const client = useClient();
      return <span data-testid="client">{String(!!client)}</span>;
    }
    renderWithInfra(<Test />);
    expect(screen.getByTestId("client")).toHaveTextContent("true");
  });

  it("useEventStream retorna stream", () => {
    function Test() {
      const stream = useEventStream();
      return <span data-testid="stream">{String(!!stream)}</span>;
    }
    renderWithInfra(<Test />);
    expect(screen.getByTestId("stream")).toHaveTextContent("true");
  });

  it("useStores retorna registry", () => {
    function Test() {
      const stores = useStores();
      return <span data-testid="stores">{String(!!stores.pipeline)}</span>;
    }
    renderWithInfra(<Test />);
    expect(screen.getByTestId("stores")).toHaveTextContent("true");
  });

  it("useServices retorna services", () => {
    function Test() {
      const services = useServices();
      return <span data-testid="services">{String(!!services.pipeline)}</span>;
    }
    renderWithInfra(<Test />);
    expect(screen.getByTestId("services")).toHaveTextContent("true");
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Test() {
      useInfrastructure();
      return null;
    }
    expect(() => render(<Test />)).toThrow();
    spy.mockRestore();
  });

  it("aceita overrides (client customizado)", () => {
    const customClient = createClient();
    function Test() {
      const client = useClient();
      return <span data-testid="same">{String(client === customClient)}</span>;
    }
    render(
      <InfraProvider client={customClient}>
        <Test />
      </InfraProvider>,
    );
    expect(screen.getByTestId("same")).toHaveTextContent("true");
  });

  it("createInfrastructure cria bundle isolado", () => {
    const infra = createInfrastructure();
    expect(infra.client).toBeDefined();
    expect(infra.stream).toBeDefined();
    expect(infra.stores).toBeDefined();
    expect(infra.services).toBeDefined();
  });
});

describe("Services", () => {
  it("createServices retorna PresentationServices", () => {
    const client = createClient();
    const services = createServices(client);
    expect(services.pipeline).toBeDefined();
    expect(services.session).toBeDefined();
    expect(services.metrics).toBeDefined();
    expect(services.configuration).toBeDefined();
    expect(services.health).toBeDefined();
    expect(services.diagnostics).toBeDefined();
    expect(services.events).toBeDefined();
    expect(services.replay).toBeDefined();
  });

  it("createStubServices retorna PresentationServices", () => {
    const services = createStubServices();
    expect(services.pipeline).toBeDefined();
    expect(services.session).toBeDefined();
    expect(services.metrics).toBeDefined();
  });

  it("stub services rejeitam com notConfigured", async () => {
    const services = createStubServices();
    await expect(services.pipeline.getStatus()).rejects.toThrow();
    await expect(services.pipeline.getSession()).rejects.toThrow();
    await expect(services.pipeline.getMetrics()).rejects.toThrow();
    await expect(services.pipeline.getSnapshot()).rejects.toThrow();
    await expect(services.session.getCurrentSession()).rejects.toThrow();
    await expect(services.metrics.getMetrics()).rejects.toThrow();
    await expect(services.configuration.getConfiguration()).rejects.toThrow();
    await expect(services.health.getHealth()).rejects.toThrow();
    await expect(services.diagnostics.getDiagnostics()).rejects.toThrow();
    await expect(services.events.getAllEvents()).rejects.toThrow();
    await expect(services.events.getEventsByCorrelation("c1")).rejects.toThrow();
    await expect(services.events.getEventsBySession("s1")).rejects.toThrow();
    await expect(services.events.getEventSnapshot()).rejects.toThrow();
    await expect(services.replay.getReplayEvents("c1")).rejects.toThrow();
    await expect(services.replay.getReplaySessions()).rejects.toThrow();
    await expect(services.replay.getReplayCorrelations("s1")).rejects.toThrow();
  });

  it("createServices com stub client rejeita (sem backend)", async () => {
    const client = createClient();
    const services = createServices(client);
    await expect(services.pipeline.getStatus()).rejects.toThrow();
  });

  it("deprecated aliases ainda funcionam", () => {
    // PipelineApi = PipelineService (deprecated)
    const services = createStubServices();
    // Apenas verifica que o tipo é compatível
    expect(typeof services.pipeline.getStatus).toBe("function");
  });
});

describe("Integração — Stores + EventStream", () => {
  it("Store pode ser atualizado por evento do stream", () => {
    const stream = createEventStream();
    const stores = createStoreRegistry();
    // Simula: evento chega via stream → atualiza store
    stream.subscribe((event) => {
      if (event.type === "MetricsUpdated") {
        stores.metrics.set({
          segments_received: 1,
          segments_processed: 1,
          segments_dropped: 0,
          queries_processed: 0,
          presentations_executed: 0,
          presentations_failed: 0,
          errors_total: 0,
          errors_recoverable: 0,
          errors_fatal: 0,
          total_latency_ms: 0,
          avg_latency_ms: 0,
          avg_recognition_latency_ms: 0,
          avg_search_latency_ms: 0,
          avg_ranking_latency_ms: 0,
          avg_intelligence_latency_ms: 0,
          avg_presentation_latency_ms: 0,
          throughput_segments_per_min: 0,
          throughput_queries_per_min: 0,
          error_rate: 0,
          drop_rate: 0,
          presentation_success_rate: 0,
          processing_success_rate: 0,
          duration_s: 0,
          correlation_count: 0,
        });
      }
    });
    stream.publish({
      id: "e1",
      type: "MetricsUpdated",
      timestamp: 100,
      correlationId: null,
      payload: {},
    });
    expect(stores.metrics.hasSnapshot).toBe(true);
    expect(stores.metrics.current!.data.segments_received).toBe(1);
  });
});
