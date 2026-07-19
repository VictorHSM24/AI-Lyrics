/**
 * SDK barrel — ponto único de entrada para o Client SDK.
 *
 * Camadas superiores (Services, Hooks) importam apenas deste barrel.
 * Nunca importam diretamente de transport.ts, errors.ts, etc.
 */

// Errors
export {
  PresentationError,
  canceled,
  timeout,
  notConfigured,
  ok,
  err,
  isOk,
  isErr,
  ERROR_SEVERITIES,
  type ErrorCode,
  type ErrorSeverity,
  type PresentationErrorLike,
  type Result,
} from "./errors";

// Cancel
export {
  createCancelSource,
  canceledToken,
  raceCancel,
  NEVER_CANCEL,
  type CancelToken,
  type CancelSource,
} from "./cancel";

// Versioning
export {
  CURRENT_API_VERSION,
  apiVersionToString,
  parseApiVersion,
  compareApiVersion,
  versioned,
  isCompatible,
  type ApiVersion,
  type Versioned,
} from "./versioning";

// Transport
export {
  createStubTransport,
  type Transport,
  type TransportConfig,
  type TransportFactory,
  type TransportStatus,
  type TransportEvent,
  type TransportListener,
  type TransportRequest,
  type TransportResponse,
  type TransportErrorResponse,
  type TransportResult,
} from "./transport";

// Client
export {
  createClient,
  getDefaultClient,
  setDefaultClient,
  ClientImpl,
  type Client,
  type ClientConfig,
  type ClientEvent,
  type ClientEventListener,
  type CallOptions,
} from "./client";

// Real Client (REST + WebSocket)
export {
  createRealClient,
  RealClient,
  asClient,
  type RealClientConfig,
} from "./real-client";

// Transports (implementações reais)
export {
  createRestTransport,
  RestTransport,
  type RestTransportOptions,
  createWebSocketTransport,
  WebSocketTransport,
  type WebSocketTransportOptions,
} from "./transports";
