import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import {
  ThemeProvider,
  useTheme,
  ApplicationProvider,
  useApplication,
  ConnectionProvider,
  useConnection,
  InfraProvider,
  NotificationsProvider,
  useNotifications,
} from "@/contexts";

// Helpers para testar contexts
function ThemeConsumer() {
  const { mode, resolved, toggle } = useTheme();
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="resolved">{resolved}</span>
      <button onClick={toggle}>toggle</button>
    </div>
  );
}

function ApplicationConsumer() {
  const { info } = useApplication();
  return <span data-testid="app-name">{info.name}</span>;
}

function ConnectionConsumer() {
  const { status, backendUrl } = useConnection();
  return (
    <div>
      <span data-testid="conn-status">{status}</span>
      <span data-testid="backend-url">{backendUrl}</span>
    </div>
  );
}

function NotificationsConsumer() {
  const { notifications, notify, dismiss, clear } = useNotifications();
  return (
    <div>
      <span data-testid="notif-count">{notifications.length}</span>
      <button onClick={() => notify("info", "Test", "msg")}>notify</button>
      <button onClick={() => notifications[0] && dismiss(notifications[0].id)}>dismiss</button>
      <button onClick={clear}>clear</button>
    </div>
  );
}

describe("ThemeProvider", () => {
  it("fornece mode e resolved", () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    expect(screen.getByTestId("mode")).toBeInTheDocument();
    expect(screen.getByTestId("resolved")).toBeInTheDocument();
  });

  it("toggle alterna tema", () => {
    render(
      <ThemeProvider>
        <ThemeConsumer />
      </ThemeProvider>,
    );
    const toggleBtn = screen.getByText("toggle");
    const resolvedBefore = screen.getByTestId("resolved").textContent;
    fireEvent.click(toggleBtn);
    const resolvedAfter = screen.getByTestId("resolved").textContent;
    expect(resolvedAfter).not.toBe(resolvedBefore);
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ThemeConsumer />)).toThrow();
    spy.mockRestore();
  });
});

describe("ApplicationProvider", () => {
  it("fornece info da aplicação", () => {
    render(
      <ApplicationProvider>
        <ApplicationConsumer />
      </ApplicationProvider>,
    );
    expect(screen.getByTestId("app-name")).toHaveTextContent("AI Lyrics");
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ApplicationConsumer />)).toThrow();
    spy.mockRestore();
  });
});

describe("ConnectionProvider", () => {
  it("fornece status desconhecido por padrão", () => {
    render(
      <InfraProvider>
        <ConnectionProvider>
          <ConnectionConsumer />
        </ConnectionProvider>
      </InfraProvider>,
    );
    expect(screen.getByTestId("conn-status")).toHaveTextContent("unknown");
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ConnectionConsumer />)).toThrow();
    spy.mockRestore();
  });
});

describe("NotificationsProvider", () => {
  it("inicia sem notificações", () => {
    render(
      <NotificationsProvider>
        <NotificationsConsumer />
      </NotificationsProvider>,
    );
    expect(screen.getByTestId("notif-count")).toHaveTextContent("0");
  });

  it("adiciona notificação ao chamar notify", () => {
    render(
      <NotificationsProvider>
        <NotificationsConsumer />
      </NotificationsProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("notify"));
    });
    expect(screen.getByTestId("notif-count")).toHaveTextContent("1");
  });

  it("remove notificação ao chamar dismiss", () => {
    render(
      <NotificationsProvider>
        <NotificationsConsumer />
      </NotificationsProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("notify"));
    });
    expect(screen.getByTestId("notif-count")).toHaveTextContent("1");
    act(() => {
      fireEvent.click(screen.getByText("dismiss"));
    });
    expect(screen.getByTestId("notif-count")).toHaveTextContent("0");
  });

  it("limpa todas as notificações ao chamar clear", () => {
    render(
      <NotificationsProvider>
        <NotificationsConsumer />
      </NotificationsProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("notify"));
    });
    act(() => {
      fireEvent.click(screen.getByText("notify"));
    });
    expect(screen.getByTestId("notif-count")).toHaveTextContent("2");
    act(() => {
      fireEvent.click(screen.getByText("clear"));
    });
    expect(screen.getByTestId("notif-count")).toHaveTextContent("0");
  });

  it("lança erro se usado fora do provider", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<NotificationsConsumer />)).toThrow();
    spy.mockRestore();
  });
});
