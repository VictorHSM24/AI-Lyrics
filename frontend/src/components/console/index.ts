/**
 * Console components barrel.
 */

export { ConsoleHeader } from "./ConsoleHeader";
export { TimelinePanel } from "./TimelinePanel";
export { PipelinePanel } from "./PipelinePanel";
export { RecognitionPanel } from "./RecognitionPanel";
export { ResultPanel } from "./ResultPanel";

export { ConnectionBadge } from "./ConnectionBadge";
export { LatencyBadge } from "./LatencyBadge";
export { SeverityBadge } from "./SeverityBadge";
export { EventCard } from "./EventCard";
export { PipelineStage } from "./PipelineStage";
export type { StageState } from "./PipelineStage";
export { RecognitionCard } from "./RecognitionCard";
export { VerseCard } from "./VerseCard";

export {
  eventToCategory,
  eventToSeverity,
  categoryToConfig,
  severityToVisualStatus,
  ALL_CATEGORIES,
  ALL_SEVERITIES,
  CATEGORY_CONFIG,
  type EventCategory,
  type EventSeverity,
} from "./event-categories";
