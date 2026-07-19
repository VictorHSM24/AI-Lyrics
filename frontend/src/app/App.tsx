import { RouterProvider } from "react-router-dom";
import { router } from "@/router";
import {
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
  OperationProvider,
  ThemeProvider,
} from "@/contexts";
import { useBootstrap, useHealthPolling } from "@/hooks";
import { ToastContainer } from "@/components";

// Configuração do backend.
// Em desenvolvimento, aponta para o servidor FastAPI local.
// Em produção, seria configurado via variável de ambiente.
const BACKEND_REST_URL = "http://localhost:8000";
const BACKEND_WS_URL = "ws://localhost:8000/ws/events";

/**
 * BootstrapOrchestrator — dispara o bootstrap quando a conexão
 * é estabelecida. Deve estar dentro de ConnectionProvider.
 */
function BootstrapOrchestrator() {
  useBootstrap();
  useHealthPolling(10000); // Poll health every 10s for real-time status.
  return null;
}

export function App() {
  return (
    <ThemeProvider>
      <ApplicationProvider>
        <InfraProvider
          config={{
            restUrl: BACKEND_REST_URL,
            wsUrl: BACKEND_WS_URL,
            autoConnect: true,
          }}
        >
          <ConnectionProvider>
            <BootstrapOrchestrator />
            <OperationProvider>
              <NotificationsProvider>
                <RouterProvider router={router} />
                <ToastContainer />
              </NotificationsProvider>
            </OperationProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>
  );
}
