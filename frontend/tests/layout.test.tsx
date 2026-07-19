import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Header } from "@/app/layout/Header";
import { Sidebar } from "@/app/layout/Sidebar";
import { Footer } from "@/app/layout/Footer";
import { AppLayout } from "@/app/layout/AppLayout";
import { PageLayout } from "@/app/layout/PageLayout";
import {
  ThemeProvider,
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
} from "@/contexts";

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

describe("Header", () => {
  it("renderiza logo e nome da aplicação", () => {
    render(wrapProviders(<Header />));
    expect(screen.getByText("AI Lyrics")).toBeInTheDocument();
  });

  it("renderiza versão", () => {
    render(wrapProviders(<Header />));
    expect(screen.getByText(/v0\.1\.0/)).toBeInTheDocument();
  });

  it("renderiza status da conexão", () => {
    render(wrapProviders(<Header />));
    expect(screen.getByText("Sem backend")).toBeInTheDocument();
  });

  it("renderiza botões de tema", () => {
    render(wrapProviders(<Header />));
    expect(screen.getByLabelText("Tema Claro")).toBeInTheDocument();
    expect(screen.getByLabelText("Tema Escuro")).toBeInTheDocument();
    expect(screen.getByLabelText("Tema Sistema")).toBeInTheDocument();
  });

  it("renderiza indicador do pipeline", () => {
    render(wrapProviders(<Header />));
    expect(screen.getByText(/Pipeline/)).toBeInTheDocument();
  });
});

describe("Sidebar", () => {
  it("renderiza todos os itens de navegação", () => {
    render(
      wrapProviders(
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>,
      ),
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Console")).toBeInTheDocument();
    expect(screen.getByText("Sessões")).toBeInTheDocument();
    expect(screen.getByText("Replay")).toBeInTheDocument();
    expect(screen.getByText("Logs")).toBeInTheDocument();
    expect(screen.getByText("Configurações")).toBeInTheDocument();
    expect(screen.getByText("Diagnóstico")).toBeInTheDocument();
    expect(screen.getByText("Sobre")).toBeInTheDocument();
  });

  it("renderiza links com hrefs corretos", () => {
    render(
      wrapProviders(
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>,
      ),
    );
    expect(screen.getByText("Dashboard").closest("a")).toHaveAttribute("href", "/");
    expect(screen.getByText("Console").closest("a")).toHaveAttribute("href", "/console");
    expect(screen.getByText("Replay").closest("a")).toHaveAttribute("href", "/replay");
  });
});

describe("Footer", () => {
  it("renderiza nome e versão", () => {
    render(wrapProviders(<Footer />));
    expect(screen.getByText(/AI Lyrics/)).toBeInTheDocument();
    expect(screen.getByText(/v0\.1\.0/)).toBeInTheDocument();
  });
});

describe("AppLayout", () => {
  it("renderiza header, sidebar e main content", () => {
    render(
      wrapProviders(
        <MemoryRouter>
          <AppLayout>
            <div>conteúdo principal</div>
          </AppLayout>
        </MemoryRouter>,
      ),
    );
    expect(screen.getByTestId("header")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("main-content")).toBeInTheDocument();
    expect(screen.getByText("conteúdo principal")).toBeInTheDocument();
  });

  it("renderiza footer", () => {
    render(
      wrapProviders(
        <MemoryRouter>
          <AppLayout>
            <div>c</div>
          </AppLayout>
        </MemoryRouter>,
      ),
    );
    expect(screen.getByTestId("footer")).toBeInTheDocument();
  });
});

describe("PageLayout", () => {
  it("renderiza título e descrição", () => {
    render(
      <PageLayout title="Minha Página" description="Descrição da página">
        <div>conteúdo</div>
      </PageLayout>,
    );
    expect(screen.getByText("Minha Página")).toBeInTheDocument();
    expect(screen.getByText("Descrição da página")).toBeInTheDocument();
    expect(screen.getByText("conteúdo")).toBeInTheDocument();
  });

  it("renderiza toolbar quando fornecida", () => {
    render(
      <PageLayout title="T" toolbar={<button>Ação</button>}>
        <div>c</div>
      </PageLayout>,
    );
    expect(screen.getByText("Ação")).toBeInTheDocument();
    expect(screen.getByTestId("toolbar")).toBeInTheDocument();
  });

  it("renderiza sem toolbar", () => {
    render(<PageLayout title="T"><div>c</div></PageLayout>);
    expect(screen.queryByTestId("toolbar")).not.toBeInTheDocument();
  });
});
