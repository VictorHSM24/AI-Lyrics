import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  ThemeProvider,
  ApplicationProvider,
  ConnectionProvider,
  NotificationsProvider,
  InfraProvider,
  useTheme,
  useApplication,
  useConnection,
  useNotifications,
} from "@/contexts";
import {
  usePipeline,
  useMetrics,
  useHealth,
  useSession,
  useReplay,
  useConfiguration,
  useDiagnostics,
  useEvents,
  useConnectionStatus,
} from "@/hooks";

function renderWithProviders(children: React.ReactNode) {
  return render(
    <ThemeProvider>
      <ApplicationProvider>
        <InfraProvider>
          <ConnectionProvider>
            <NotificationsProvider>
              {children}
            </NotificationsProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>,
  );
}

describe("Hooks — valores padrão", () => {
  it("usePipeline retorna valores nulos por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { status, snapshot, loading, error } = usePipeline();
      return (
        <div>
          <span data-testid="status">{String(status)}</span>
          <span data-testid="snapshot">{String(snapshot)}</span>
          <span data-testid="loading">{String(loading)}</span>
          <span data-testid="error">{String(error)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("status")).toHaveTextContent("null");
    expect(screen.getByTestId("snapshot")).toHaveTextContent("null");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
    expect(screen.getByTestId("error")).toHaveTextContent("null");
  });

  it("useMetrics retorna valores nulos por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { metrics, loading, error } = useMetrics();
      return (
        <div>
          <span data-testid="metrics">{String(metrics)}</span>
          <span data-testid="loading">{String(loading)}</span>
          <span data-testid="error">{String(error)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("metrics")).toHaveTextContent("null");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useHealth retorna valores nulos por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { health, loading } = useHealth();
      return (
        <div>
          <span data-testid="health">{String(health)}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("health")).toHaveTextContent("null");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useSession retorna valores nulos por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { session, loading } = useSession();
      return (
        <div>
          <span data-testid="session">{String(session)}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("session")).toHaveTextContent("null");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useReplay retorna arrays vazios por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { events, sessionIds, loading } = useReplay();
      return (
        <div>
          <span data-testid="events-len">{events.length}</span>
          <span data-testid="sessions-len">{sessionIds.length}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("events-len")).toHaveTextContent("0");
    expect(screen.getByTestId("sessions-len")).toHaveTextContent("0");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useConfiguration retorna valores nulos por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { configuration, loading } = useConfiguration();
      return (
        <div>
          <span data-testid="config">{String(configuration)}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("config")).toHaveTextContent("null");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useDiagnostics retorna array vazio por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { diagnostics, loading } = useDiagnostics();
      return (
        <div>
          <span data-testid="diag-len">{diagnostics.length}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("diag-len")).toHaveTextContent("0");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useEvents retorna array vazio por padrão (loading=true sem snapshot)", () => {
    function Test() {
      const { events, loading } = useEvents();
      return (
        <div>
          <span data-testid="events-len">{events.length}</span>
          <span data-testid="loading">{String(loading)}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("events-len")).toHaveTextContent("0");
    expect(screen.getByTestId("loading")).toHaveTextContent("true");
  });

  it("useConnectionStatus retorna status do contexto", () => {
    function Test() {
      const { status, lastConnectedAt } = useConnectionStatus();
      return (
        <div>
          <span data-testid="status">{status}</span>
          <span data-testid="last-at">{lastConnectedAt}</span>
        </div>
      );
    }
    renderWithProviders(<Test />);
    expect(screen.getByTestId("status")).toHaveTextContent("unknown");
    expect(screen.getByTestId("last-at")).toHaveTextContent("0");
  });
});

describe("Hooks — erro fora do provider", () => {
  it("useTheme lança erro fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Test() {
      useTheme();
      return null;
    }
    expect(() => render(<Test />)).toThrow();
    spy.mockRestore();
  });

  it("useApplication lança erro fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Test() {
      useApplication();
      return null;
    }
    expect(() => render(<Test />)).toThrow();
    spy.mockRestore();
  });

  it("useConnection lança erro fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Test() {
      useConnection();
      return null;
    }
    expect(() => render(<Test />)).toThrow();
    spy.mockRestore();
  });

  it("useNotifications lança erro fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Test() {
      useNotifications();
      return null;
    }
    expect(() => render(<Test />)).toThrow();
    spy.mockRestore();
  });
});
