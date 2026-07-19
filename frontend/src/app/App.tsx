import { RouterProvider } from "react-router-dom";
import { router } from "@/router";
import {
  ApplicationProvider,
  ConnectionProvider,
  InfraProvider,
  NotificationsProvider,
  ThemeProvider,
} from "@/contexts";
import { ToastContainer } from "@/components";

// Configuração do backend.
// Em desenvolvimento, aponta para o servidor FastAPI local.
// Em produção, seria configurado via variável de ambiente.
const BACKEND_REST_URL = "http://localhost:8000";
const BACKEND_WS_URL = "ws://localhost:8000/ws/events";

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
            <NotificationsProvider>
              <RouterProvider router={router} />
              <ToastContainer />
            </NotificationsProvider>
          </ConnectionProvider>
        </InfraProvider>
      </ApplicationProvider>
    </ThemeProvider>
  );
}
