/**
 * ResultPanel — painel de resultado (versículo + Holyrics).
 *
 * Wrapper simples que inclui VerseCard dentro de um Panel.
 * Dados vêm do EventStore via useEvents().
 */

import { VerseCard } from "./VerseCard";

export function ResultPanel() {
  return (
    <div data-testid="result-panel">
      <VerseCard />
    </div>
  );
}
