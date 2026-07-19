import { createBrowserRouter, type RouteObject } from "react-router-dom";
import { AppLayout } from "@/app/layout";
import { ErrorBoundary } from "@/app/ErrorBoundary";
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

const routes: RouteObject[] = [
  {
    path: "/",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <DashboardPage />
        </AppLayout>
      </ErrorBoundary>
    ),
    errorElement: <NotFoundPage />,
  },
  {
    path: "/console",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <ConsolePage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/sessoes",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <SessionsPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/replay",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <ReplayPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/logs",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <LogsPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/configuracoes",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <ConfigurationPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/diagnostico",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <DiagnosticPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "/sobre",
    element: (
      <ErrorBoundary>
        <AppLayout>
          <AboutPage />
        </AppLayout>
      </ErrorBoundary>
    ),
  },
  {
    path: "*",
    element: <NotFoundPage />,
  },
];

export const router = createBrowserRouter(routes);
