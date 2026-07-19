import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { createPresentationApi } from "@/api/client";
import { ToastContainer } from "@/components/Toast";
import { NotificationsProvider, useNotifications } from "@/contexts";
import { ErrorBoundary } from "@/app/ErrorBoundary";
import { ErrorPage } from "@/pages/ErrorPage";

describe("API stub", () => {
  it("createPresentationApi retorna objeto com todos os services", () => {
    const api = createPresentationApi();
    expect(api.pipeline).toBeDefined();
    expect(api.session).toBeDefined();
    expect(api.metrics).toBeDefined();
    expect(api.configuration).toBeDefined();
    expect(api.health).toBeDefined();
    expect(api.diagnostics).toBeDefined();
    expect(api.events).toBeDefined();
    expect(api.replay).toBeDefined();
  });

  it("todos os métodos lançam 'not implemented'", () => {
    const api = createPresentationApi();
    expect(() => api.pipeline.getStatus()).toThrow("não implementada");
    expect(() => api.pipeline.getSession()).toThrow("não implementada");
    expect(() => api.pipeline.getMetrics()).toThrow("não implementada");
    expect(() => api.pipeline.getSnapshot()).toThrow("não implementada");
    expect(() => api.session.getCurrentSession()).toThrow("não implementada");
    expect(() => api.metrics.getMetrics()).toThrow("não implementada");
    expect(() => api.configuration.getConfiguration()).toThrow("não implementada");
    expect(() => api.health.getHealth()).toThrow("não implementada");
    expect(() => api.diagnostics.getDiagnostics()).toThrow("não implementada");
    expect(() => api.events.getAllEvents()).toThrow("não implementada");
    expect(() => api.events.getEventsByCorrelation("c1")).toThrow("não implementada");
    expect(() => api.events.getEventsBySession("s1")).toThrow("não implementada");
    expect(() => api.events.getEventSnapshot()).toThrow("não implementada");
    expect(() => api.replay.getReplayEvents("c1")).toThrow("não implementada");
    expect(() => api.replay.getReplaySessions()).toThrow("não implementada");
    expect(() => api.replay.getReplayCorrelations("s1")).toThrow("não implementada");
  });
});

describe("Toast", () => {
  it("não renderiza nada sem notificações", () => {
    render(
      <NotificationsProvider>
        <ToastContainer />
      </NotificationsProvider>,
    );
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  it("renderiza toast quando notificado", () => {
    function Trigger() {
      const { notify } = useNotifications();
      return <button onClick={() => notify("success", "Sucesso!", "Operação concluída")}>notify</button>;
    }
    render(
      <NotificationsProvider>
        <Trigger />
        <ToastContainer />
      </NotificationsProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("notify"));
    });
    expect(screen.getByTestId("toast")).toBeInTheDocument();
    expect(screen.getByText("Sucesso!")).toBeInTheDocument();
    expect(screen.getByText("Operação concluída")).toBeInTheDocument();
  });

  it("renderiza container com role region", () => {
    render(
      <NotificationsProvider>
        <ToastContainer />
      </NotificationsProvider>,
    );
    expect(screen.getByTestId("toast-container")).toHaveAttribute("aria-label", "Notificações");
  });
});

describe("ErrorBoundary", () => {
  it("renderiza children quando não há erro", () => {
    render(
      <ErrorBoundary>
        <div>ok</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("renderiza ErrorPage quando há erro", () => {
    function Boom(): React.ReactNode {
      throw new Error("Kaboom");
    }
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByTestId("error-page")).toBeInTheDocument();
    expect(screen.getByText("Algo deu errado")).toBeInTheDocument();
    spy.mockRestore();
  });
});

describe("ErrorPage", () => {
  it("renderiza com erro", () => {
    render(<ErrorPage error={new Error("Falha de teste")} />);
    expect(screen.getByText("Falha de teste")).toBeInTheDocument();
  });

  it("renderiza com mensagem padrão", () => {
    render(<ErrorPage />);
    expect(screen.getByText("Ocorreu um erro inesperado.")).toBeInTheDocument();
  });

  it("renderiza botão de reset quando fornecido", () => {
    render(<ErrorPage reset={() => {}} />);
    expect(screen.getByText("Tentar novamente")).toBeInTheDocument();
  });
});
