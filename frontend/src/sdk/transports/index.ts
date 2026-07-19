/**
 * Transports barrel — implementações reais de Transport.
 *
 * O Client SDK consome estas implementações. Hooks, Services e
 * Componentes NUNCA importam deste barrel — apenas o Client SDK.
 */

export {
  createRestTransport,
  RestTransport,
  type RestTransportOptions,
} from "./rest";

export {
  createWebSocketTransport,
  WebSocketTransport,
  type WebSocketTransportOptions,
} from "./websocket";
