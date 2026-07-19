/**
 * RecognitionPanel — painel de reconhecimento de fala.
 *
 * Wrapper simples que inclui RecognitionCard dentro de um Panel.
 * Dados vêm do EventStore via useEvents().
 */

import { RecognitionCard } from "./RecognitionCard";

export function RecognitionPanel() {
  return (
    <div data-testid="recognition-panel">
      <RecognitionCard />
    </div>
  );
}
