import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

export type NotificationType = "info" | "success" | "warning" | "error";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  timestamp: number;
}

export interface NotificationsContextValue {
  notifications: Notification[];
  notify: (type: NotificationType, title: string, message?: string) => void;
  dismiss: (id: string) => void;
  clear: () => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

let _notifIdCounter = 0;

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const notify = useCallback(
    (type: NotificationType, title: string, message = "") => {
      _notifIdCounter += 1;
      const notif: Notification = {
        id: `notif-${_notifIdCounter}`,
        type,
        title,
        message,
        timestamp: Date.now() / 1000,
      };
      setNotifications((prev) => [...prev, notif]);
    },
    [],
  );

  const clear = useCallback(() => {
    setNotifications([]);
  }, []);

  const value: NotificationsContextValue = {
    notifications,
    notify,
    dismiss,
    clear,
  };

  return (
    <NotificationsContext.Provider value={value}>
      {children}
    </NotificationsContext.Provider>
  );
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext);
  if (!ctx) {
    throw new Error(
      "useNotifications deve ser usado dentro de NotificationsProvider",
    );
  }
  return ctx;
}
