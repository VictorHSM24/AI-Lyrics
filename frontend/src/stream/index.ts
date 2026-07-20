export {
  createEventStream,
  eventDtoToStreamEvent,
  EventStreamImpl,
  type EventStream,
  type StreamEvent,
  type StreamSnapshot,
  type StreamSubscription,
  type StreamListener,
} from "./EventStream";

export {
  createEventStreamBridge,
  EventStreamBridge,
} from "./bridge";

export {
  dispatchDomainHandlers,
  handlePipelineLifecycle,
  handleSessionEvent,
  handleMetricsEvent,
  handleDiagnosticEvent,
} from "./handlers";

export {
  bootstrapStores,
  type BootstrapResult,
  type DomainKey,
} from "./bootstrap";

// Sprint 17.5.1 — BootstrapCoordinator: orquestra bootstrap com retry
// exponencial e estado por recurso. Substitui o uso direto de
// bootstrapStores no useBootstrap.
export {
  createBootstrapCoordinator,
  BootstrapCoordinator,
  type ResourceState,
  type ResourceStatus,
  type BootstrapCoordinatorConfig,
} from "./BootstrapCoordinator";
