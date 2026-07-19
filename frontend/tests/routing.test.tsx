import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import {
  ThemeProvider,
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
} from "@/contexts";
import { AppLayout } from "@/app/layout";
import {
  DashboardPage,
  ConsolePage,
  SessionsPage,
  ReplayPage,
  LogsPage,
  ConfigurationPage,
  DiagnosticPage,
  AboutPage,
  NotFoundPage,
} from "@/pages";

function wrapProviders(children: React.ReactNode) {
  return (
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
    </ThemeProvider>
  );
}

const pageElements: Record<string, React.ReactNode> = {
  "/": <DashboardPage />,
  "/console": <ConsolePage />,
  "/sessoes": <SessionsPage />,
  "/replay": <ReplayPage />,
  "/logs": <LogsPage />,
  "/configuracoes": <ConfigurationPage />,
  "/diagnostico": <DiagnosticPage />,
  "/sobre": <AboutPage />,
};

function renderRoute(path: string) {
  const routes = Object.entries(pageElements).map(([route, element]) => ({
    path: route,
    element: wrapProviders(<AppLayout>{element}</AppLayout>),
  }));
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("Roteamento — páginas", () => {
  it("Dashboard renderiza", () => {
    renderRoute("/");
    expect(screen.getAllByText("Dashboard").length).toBeGreaterThan(0);
    expect(screen.getByText("Em desenvolvimento")).toBeInTheDocument();
  });

  it("Console renderiza", () => {
    renderRoute("/console");
    expect(screen.getAllByText("Console").length).toBeGreaterThan(0);
  });

  it("Sessões renderiza", () => {
    renderRoute("/sessoes");
    expect(screen.getAllByText("Sessões").length).toBeGreaterThan(0);
  });

  it("Replay renderiza", () => {
    renderRoute("/replay");
    expect(screen.getAllByText("Replay").length).toBeGreaterThan(0);
  });

  it("Logs renderiza", () => {
    renderRoute("/logs");
    expect(screen.getAllByText("Logs").length).toBeGreaterThan(0);
  });

  it("Configurações renderiza", () => {
    renderRoute("/configuracoes");
    expect(screen.getAllByText("Configurações").length).toBeGreaterThan(0);
  });

  it("Diagnóstico renderiza", () => {
    renderRoute("/diagnostico");
    expect(screen.getAllByText("Diagnóstico").length).toBeGreaterThan(0);
  });

  it("Sobre renderiza com informações", () => {
    renderRoute("/sobre");
    expect(screen.getAllByText("Sobre").length).toBeGreaterThan(0);
    // "AI Lyrics" aparece no Header e na página Sobre
    expect(screen.getAllByText("AI Lyrics").length).toBeGreaterThan(0);
  });

  it("NotFound renderiza 404", () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>
      </ThemeProvider>,
    );
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByText("Página não encontrada")).toBeInTheDocument();
  });

  it("NotFound renderiza link para Dashboard", () => {
    render(
      <ThemeProvider>
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>
      </ThemeProvider>,
    );
    expect(screen.getByText("Voltar ao Dashboard")).toBeInTheDocument();
  });
});

describe("Padrão visual das páginas", () => {
  // Páginas que ainda estão em desenvolvimento (DevelopmentPage).
  const devPages = [
    { route: "/", title: "Dashboard" },
    { route: "/sessoes", title: "Sessões" },
    { route: "/replay", title: "Replay" },
    { route: "/logs", title: "Logs" },
    { route: "/configuracoes", title: "Configurações" },
    { route: "/diagnostico", title: "Diagnóstico" },
  ];

  for (const page of devPages) {
    it(`${page.title} segue padrão visual (título + descrição + conteúdo)`, () => {
      const { unmount } = renderRoute(page.route);
      // Título da página (h1)
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(page.title);
      // Estado de desenvolvimento
      expect(screen.getByText("Em desenvolvimento")).toBeInTheDocument();
      // Estrutura comum
      expect(screen.getByTestId("page-container")).toBeInTheDocument();
      expect(screen.getByTestId("page-header")).toBeInTheDocument();
      expect(screen.getByTestId("page-content")).toBeInTheDocument();
      unmount();
    });
  }

  it("Console segue padrão visual (título + descrição + conteúdo funcional)", () => {
    const { unmount } = renderRoute("/console");
    // Título da página (h1) contém "Console"
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Console");
    // Console é funcional — não tem "Em desenvolvimento"
    expect(screen.queryByText("Em desenvolvimento")).not.toBeInTheDocument();
    // Estrutura comum
    expect(screen.getByTestId("page-container")).toBeInTheDocument();
    expect(screen.getByTestId("page-header")).toBeInTheDocument();
    expect(screen.getByTestId("page-content")).toBeInTheDocument();
    // Componentes do Console
    expect(screen.getByTestId("console-header")).toBeInTheDocument();
    expect(screen.getByTestId("timeline-panel")).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-panel")).toBeInTheDocument();
    unmount();
  });
});

// Import necessário para MemoryRouter no teste do NotFound
import { MemoryRouter } from "react-router-dom";
