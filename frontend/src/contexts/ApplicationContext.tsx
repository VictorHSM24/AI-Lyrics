import { createContext, useContext, type ReactNode } from "react";

export interface ApplicationInfo {
  name: string;
  version: string;
  description: string;
}

export interface ApplicationContextValue {
  info: ApplicationInfo;
}

const ApplicationContext = createContext<ApplicationContextValue | null>(null);

export function ApplicationProvider({ children }: { children: ReactNode }) {
  const value: ApplicationContextValue = {
    info: {
      name: "AI Lyrics",
      version: "0.1.0",
      description: "Sistema de reconhecimento de fala para versículos bíblicos",
    },
  };

  return (
    <ApplicationContext.Provider value={value}>
      {children}
    </ApplicationContext.Provider>
  );
}

export function useApplication(): ApplicationContextValue {
  const ctx = useContext(ApplicationContext);
  if (!ctx) {
    throw new Error("useApplication deve ser usado dentro de ApplicationProvider");
  }
  return ctx;
}
