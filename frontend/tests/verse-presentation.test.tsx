/**
 * Testes do VersePresentationPanel e handlers (Sprint 18).
 *
 * Cobre:
 * - Renderização do painel no estado inicial.
 * - Handler despacha VerseResolving → status="presenting".
 * - Handler despacha VerseResolved → versículo preenchido.
 * - Handler despacha VersePresented → status="presented".
 * - Handler despacha VersePresentationFailed → status="failed".
 * - Correlation_id preservado entre eventos do mesmo fluxo.
 * - Histórico acumula entradas.
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  ThemeProvider,
  ApplicationProvider,
  InfraProvider,
  ConnectionProvider,
  NotificationsProvider,
  OperationProvider,
} from "@/contexts";
import { VersePresentationPanel } from "@/components/operational";
import { dispatchDomainHandlers } from "@/stream/handlers";
import { createStoreRegistry, type StoreRegistry } from "@/stores";
import type { EventDTO } from "@/types";
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

function makeEvent(
  eventType: string,
  payload: Record<string, unknown>,
  correlationId = "corr-1",
): EventDTO {
  return {
    event_type: eventType,
    category: "operational",
    meta: {
      event_id: `evt-${eventType}`,
      correlation_id: correlationId,
      causation_id: "ref-evt-id",
      session_id: "test-session",
      timestamp: 1000.0,
      origin: "VersePresentationService",
      metadata: [],
    },
    payload,
  };
}

describe("VersePresentationPanel", () => {
  beforeEach(() => cleanup());
  afterEach(() => cleanup());

  it("renderiza o título Apresentação Automática", () => {
    renderWithProviders(<VersePresentationPanel />);
    expect(screen.getByText("Apresentação Automática")).toBeTruthy();
  });

  it("tem o panel com data-testid correto", () => {
    renderWithProviders(<VersePresentationPanel />);
    expect(screen.getByTestId("verse-presentation-panel")).toBeTruthy();
  });

  it("mostra mensagem de nenhuma apresentação no estado inicial", () => {
    renderWithProviders(<VersePresentationPanel />);
    const placeholder = screen.queryByText(/apresentação iniciada ainda/i);
    const loading = screen.queryByText(/Carregando/i);
    expect(placeholder !== null || loading !== null).toBeTruthy();
  });
});

describe("handleVersePresentationEvent", () => {
  let stores: StoreRegistry;

  beforeEach(() => {
    stores = createStoreRegistry();
  });

  afterEach(() => cleanup());

  it("VerseResolving atualiza status para presenting", () => {
    const dto = makeEvent("VerseResolving", {
      book: "João",
      book_id: 43,
      chapter: 3,
      verse_start: 16,
      verse_end: 16,
      normalized_text: "joao 3:16",
    });

    act(() => {
      dispatchDomainHandlers(dto, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.current).not.toBeNull();
    expect(state?.current?.status).toBe("presenting");
    expect(state?.current?.book).toBe("João");
    expect(state?.current?.chapter).toBe(3);
    expect(state?.current?.verse).toBe(16);
    expect(state?.current?.reference).toBe("joao 3:16");
  });

  it("VerseResolved preenche o texto do versículo", () => {
    const resolving = makeEvent("VerseResolving", {
      book: "João",
      book_id: 43,
      chapter: 3,
      verse_start: 16,
      verse_end: 16,
      normalized_text: "joao 3:16",
    });
    const resolved = makeEvent("VerseResolved", {
      book: "João",
      book_id: 43,
      chapter: 3,
      verse: 16,
      version: "ACF",
      verse_text: "Porque Deus amou o mundo...",
      reference: "João 3:16",
      search_ms: 5,
    });

    act(() => {
      dispatchDomainHandlers(resolving, stores);
      dispatchDomainHandlers(resolved, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.current?.verseText).toContain("Porque Deus amou");
    expect(state?.current?.reference).toBe("João 3:16");
    expect(state?.current?.version).toBe("ACF");
    // Ainda presenting — só VersePresented muda para presented.
    expect(state?.current?.status).toBe("presenting");
  });

  it("VersePresented atualiza status para presented", () => {
    const resolving = makeEvent("VerseResolving", {
      book: "João", book_id: 43, chapter: 3, verse_start: 16, verse_end: 16,
      normalized_text: "joao 3:16",
    });
    const resolved = makeEvent("VerseResolved", {
      book: "João", book_id: 43, chapter: 3, verse: 16, version: "ACF",
      verse_text: "Porque Deus amou o mundo...",
      reference: "João 3:16", search_ms: 5,
    });
    const presented = makeEvent("VersePresented", {
      book: "João", book_id: 43, chapter: 3, verse: 16, version: "ACF",
      reference: "João 3:16",
      quick_presentation: false,
      holyrics_status: "ok",
      holyrics_latency_ms: 120,
      total_latency_ms: 250,
    });

    act(() => {
      dispatchDomainHandlers(resolving, stores);
      dispatchDomainHandlers(resolved, stores);
      dispatchDomainHandlers(presented, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.current?.status).toBe("presented");
    expect(state?.current?.holyricsStatus).toBe("ok");
    expect(state?.current?.holyricsLatencyMs).toBe(120);
    expect(state?.current?.totalLatencyMs).toBe(250);
    expect(state?.current?.quickPresentation).toBe(false);
  });

  it("VersePresentationFailed atualiza status para failed", () => {
    const resolving = makeEvent("VerseResolving", {
      book: "Klingon", book_id: 0, chapter: 3, verse_start: 16, verse_end: 16,
      normalized_text: "klingon 3:16",
    });
    const failed = makeEvent("VersePresentationFailed", {
      book: "Klingon", book_id: 0, chapter: 3, verse: 16,
      reference: "klingon 3:16",
      failure_stage: "search",
      error_type: "book_not_found",
      error_message: "unknown book: Klingon",
      latency_ms: 2,
    });

    act(() => {
      dispatchDomainHandlers(resolving, stores);
      dispatchDomainHandlers(failed, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.current?.status).toBe("failed");
    expect(state?.current?.failureStage).toBe("search");
    expect(state?.current?.errorType).toBe("book_not_found");
    expect(state?.current?.errorMessage).toContain("unknown book");
  });

  it("preserva correlation_id entre eventos do mesmo fluxo", () => {
    const corrId = "my-flux-123";
    const resolving = makeEvent("VerseResolving", {
      book: "João", book_id: 43, chapter: 3, verse_start: 16, verse_end: 16,
      normalized_text: "joao 3:16",
    }, corrId);
    const presented = makeEvent("VersePresented", {
      book: "João", book_id: 43, chapter: 3, verse: 16, version: "ACF",
      reference: "João 3:16", quick_presentation: false,
      holyrics_status: "ok", holyrics_latency_ms: 100, total_latency_ms: 200,
    }, corrId);

    act(() => {
      dispatchDomainHandlers(resolving, stores);
      dispatchDomainHandlers(presented, stores);
    });

    const state = stores.versePresentation.current?.data;
    // Mesma entrada (não duas) — correlation_id preservado.
    expect(state?.entries.length).toBe(1);
    expect(state?.entries[0].id).toBe(corrId);
  });

  it("acumula entradas no histórico para fluxos diferentes", () => {
    const ref1 = makeEvent("VerseResolving", {
      book: "João", book_id: 43, chapter: 3, verse_start: 16, verse_end: 16,
      normalized_text: "joao 3:16",
    }, "flux-1");
    const ref2 = makeEvent("VerseResolving", {
      book: "Salmos", book_id: 19, chapter: 23, verse_start: 1, verse_end: 1,
      normalized_text: "salmos 23:1",
    }, "flux-2");

    act(() => {
      dispatchDomainHandlers(ref1, stores);
      dispatchDomainHandlers(ref2, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.entries.length).toBe(2);
    // Mais recente primeiro.
    expect(state?.entries[0].id).toBe("flux-2");
    expect(state?.entries[1].id).toBe("flux-1");
  });

  it("quick_presentation=True é registrado no estado", () => {
    const resolving = makeEvent("VerseResolving", {
      book: "João", book_id: 43, chapter: 3, verse_start: 16, verse_end: 16,
      normalized_text: "joao 3:16",
    });
    const presented = makeEvent("VersePresented", {
      book: "João", book_id: 43, chapter: 3, verse: 16, version: "ACF",
      reference: "João 3:16", quick_presentation: true,
      holyrics_status: "ok", holyrics_latency_ms: 80, total_latency_ms: 150,
    });

    act(() => {
      dispatchDomainHandlers(resolving, stores);
      dispatchDomainHandlers(presented, stores);
    });

    const state = stores.versePresentation.current?.data;
    expect(state?.current?.quickPresentation).toBe(true);
  });
});
