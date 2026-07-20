/**
 * API layer — preparação para futura comunicação HTTP/WebSocket.
 *
 * Nenhum cliente HTTP é implementado aqui. Apenas a estrutura
 * para futuras implementações (fetch, axios, WebSocket, SSE).
 *
 * Quando o backend FastAPI existir, substituir as implementações
 * stub por chamadas reais.
 */

import type { PresentationApi } from "@/services";

/**
 * Stub de PresentationApi — todas as chamadas lançam "not implemented".
 *
 * Futuro: substituir por implementação real que faz fetch() para
 * os endpoints REST do backend.
 */
export function createPresentationApi(): PresentationApi {
  const notImplemented = (): never => {
    throw new Error(
      "API não implementada — backend ainda não disponível. " +
        "Esta é uma infraestrutura preparatória.",
    );
  };

  return {
    pipeline: {
      getStatus: notImplemented,
      getSession: notImplemented,
      getMetrics: notImplemented,
      getSnapshot: notImplemented,
      startPipeline: notImplemented,
      stopPipeline: notImplemented,
    },
    session: {
      getCurrentSession: notImplemented,
    },
    metrics: {
      getMetrics: notImplemented,
    },
    configuration: {
      getConfiguration: notImplemented,
      updateConfiguration: notImplemented,
    },
    health: {
      getHealth: notImplemented,
      testHolyrics: notImplemented,
    },
    diagnostics: {
      getDiagnostics: notImplemented,
    },
    events: {
      getAllEvents: notImplemented,
      getEventsByCorrelation: notImplemented,
      getEventsBySession: notImplemented,
      getEventSnapshot: notImplemented,
    },
    replay: {
      getReplayEvents: notImplemented,
      getReplaySessions: notImplemented,
      getReplayCorrelations: notImplemented,
    },
    audio: {
      getDevices: notImplemented,
      getCurrentDevice: notImplemented,
      getLevels: notImplemented,
      startCapture: notImplemented,
      stopCapture: notImplemented,
      selectDevice: notImplemented,
    },
    system: {
      getSystemInfo: notImplemented,
    },
    info: {
      getInfo: notImplemented,
    },
  };
}
