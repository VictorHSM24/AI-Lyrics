/**
 * StartupPage — tela de inicialização.
 *
 * Renderiza o StartupScreen que mostra todas as etapas.
 * Quando completa, o operador clica em "Continuar" para ir ao Console.
 */

import { StartupScreen } from "@/components/operational";

export function StartupPage() {
  return <StartupScreen continueTo="/console" />;
}
