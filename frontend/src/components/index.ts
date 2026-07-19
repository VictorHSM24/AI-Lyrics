/**
 * Components barrel — ponto único de entrada do Design System.
 *
 * Componentes estão organizados em categorias:
 *   common/     — genéricos (Divider, PageContainer, Section, Card, Panel, PropertyGrid)
 *   layout/     — layout (PageContainer, Section, Panel)
 *   feedback/   — feedback (Loading, EmptyState, ErrorState, Toast, Modal, ConfirmationDialog)
 *   navigation/ — navegação (Toolbar, SearchBox)
 *   status/     — status (StatusBadge)
 *   metrics/    — métricas (MetricCard)
 *   tables/     — tabelas (Table)
 *   timeline/   — timeline (Timeline)
 *   forms/      — formulários (preparado, vazio)
 *
 * Este barrel re-exporta tudo para compatibilidade com imports
 * existentes: `import { Card } from "@/components"`.
 */

// Common
export { Divider } from "./Divider";
export { PageContainer } from "./PageContainer";
export { Section } from "./Section";
export { Card } from "./Card";
export { Panel } from "./Panel";
export { PropertyGrid } from "./PropertyGrid";

// Feedback
export { Loading } from "./Loading";
export { EmptyState } from "./EmptyState";
export { ErrorState } from "./ErrorState";
export { ToastContainer } from "./Toast";
export { ConfirmationDialog } from "./ConfirmationDialog";
export { Modal } from "./Modal";
export { ConnectionIndicator } from "./feedback/ConnectionIndicator";

// Navigation
export { Toolbar } from "./Toolbar";
export { SearchBox } from "./SearchBox";

// Status
export { StatusBadge } from "./StatusBadge";

// Metrics
export { MetricCard } from "./MetricCard";

// Tables
export { Table } from "./Table";

// Timeline
export { Timeline } from "./Timeline";
