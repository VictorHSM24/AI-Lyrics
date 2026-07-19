import { useEffect } from "react";
import { CheckCircle, Info, AlertTriangle, XCircle, X } from "lucide-react";
import { cn } from "@/utils";
import { useNotifications, type NotificationType } from "@/contexts/NotificationsContext";

const ICONS = {
  info: Info,
  success: CheckCircle,
  warning: AlertTriangle,
  error: XCircle,
};

const COLORS: Record<NotificationType, string> = {
  info: "border-status-info/30 bg-status-info/10 text-status-info",
  success: "border-status-success/30 bg-status-success/10 text-status-success",
  warning: "border-status-warning/30 bg-status-warning/10 text-status-warning",
  error: "border-status-error/30 bg-status-error/10 text-status-error",
};

export function ToastContainer() {
  const { notifications, dismiss } = useNotifications();

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col gap-2"
      data-testid="toast-container"
      role="region"
      aria-label="Notificações"
    >
      {notifications.map((notif) => {
        const Icon = ICONS[notif.type];
        return (
          <ToastItem
            key={notif.id}
            id={notif.id}
            type={notif.type}
            title={notif.title}
            message={notif.message}
            Icon={Icon}
            onDismiss={() => dismiss(notif.id)}
          />
        );
      })}
    </div>
  );
}

interface ToastItemProps {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  Icon: typeof Info;
  onDismiss: () => void;
}

function ToastItem({ type, title, message, Icon, onDismiss }: ToastItemProps) {
  useEffect(() => {
    const timer = setTimeout(onDismiss, 5000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-lg border px-4 py-3 shadow-lg",
        "min-w-[300px] max-w-md",
        COLORS[type],
      )}
      data-testid="toast"
      data-type={type}
      role="alert"
    >
      <Icon className="mt-0.5 h-5 w-5 flex-shrink-0" />
      <div className="flex flex-1 flex-col gap-0.5">
        <span className="text-sm font-semibold">{title}</span>
        {message && <span className="text-xs opacity-90">{message}</span>}
      </div>
      <button
        onClick={onDismiss}
        className="rounded p-0.5 hover:bg-black/10"
        aria-label="Fechar notificação"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
