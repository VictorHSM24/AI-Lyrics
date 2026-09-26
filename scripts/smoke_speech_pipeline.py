"""Smoke test ponta a ponta com a composição REAL do backend.

Monta o CompositionRoot de produção (config.yaml, base FTS5 local,
HolyricsClient, ordem real de inscrição no EventBus) e injeta falas
simuladas como SpeechCommittedWords — sem microfone/Whisper. Imprime a
linha do tempo de eventos relevantes para cada cenário.

Holyrics offline → VersePresentationFailed(stage=holyrics) é esperado; o
que importa é QUAL referência chegou à etapa de apresentação.

Uso: python scripts/smoke_speech_pipeline.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.events import (  # noqa: E402
    PipelineStopped,
    ReadingFollowAdvanced,
    ReadingFollowEnded,
    ReadingFollowStarted,
    ReferenceAntecipada,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
    VersePresentationFailed,
    VersePresented,
)
from pipeline.metadata import EventMetadata  # noqa: E402

WATCH = (ReferenceDetected, ReferenceAntecipada, VersePresented,
         VersePresentationFailed, ReadingFollowStarted, ReadingFollowAdvanced,
         ReadingFollowEnded)

SCENARIOS = [
    ("(a) Judéia + 'um testemunho'", [
        "e sereis minhas testemunhas tanto em jerusalém como em toda a judéia e samaria",
        "para dar um testemunho a todas as nações",
    ]),
    ("(b) vocabulário de pregação", [
        "uma revelação diferente eu amo você o mal não prevalecerá",
        "andou sobre o mar quarenta dias e quarenta noites o justo juiz",
    ]),
    ("(c) Amós 19:99", ["amós dezenove noventa e nove"]),
    ("(e) instrução de capítulo", ["abra a sua bíblia em hebreus capítulo doze"]),
    ("(e') ... e o versículo após a pausa", ["versículo um"]),
    ("(d) pregação sem leitura (follow em Hb 12:1)", [
        "irmãos a vida cristã é uma carreira a paciência que Deus nos dá está "
        "disponível hoje a nuvem de testemunhas olha para nós e o pecado que nos "
        "rodeia precisa ser deixado amém",
    ] * 6),
    ("(d') leitura real de Hb 12:1", [
        "portanto nós também pois que estamos rodeados de uma tão grande nuvem de "
        "testemunhas deixemos todo o embaraço e o pecado que tão de perto nos "
        "rodeia e corramos com paciência a carreira que nos está proposta",
    ]),
    ("comando 'voltar um'", ["voltar um"]),
    ("(g) pipeline parado", ["__STOP__", "olhando para jesus autor e consumador da fé"]),
    ("salmo vinte e três (chunks de 1)", ["salmo vinte e três versículo um"]),
]


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    from api.startup.composition import create_composition_root

    root = create_composition_root()
    bus = root.bus
    timeline: list[str] = []

    def watch(ev) -> None:
        name = type(ev).__name__
        if isinstance(ev, (ReferenceDetected, ReferenceAntecipada)):
            timeline.append(f"{name} {ev.book} {ev.chapter}:{ev.verse_start} ({ev.confidence})")
        elif isinstance(ev, VersePresented):
            timeline.append(f"{name} {ev.reference} [origin={ev.origin}]")
        elif isinstance(ev, VersePresentationFailed):
            timeline.append(f"{name} {ev.reference} stage={ev.failure_stage} ({ev.error_type})")
        elif isinstance(ev, ReadingFollowAdvanced):
            timeline.append(f"{name} {ev.previous_verse}->{ev.current_verse} ({ev.reason})")
        elif isinstance(ev, ReadingFollowEnded):
            timeline.append(f"{name} reason={ev.reason}")
        else:
            timeline.append(f"{name} {getattr(ev, 'book', '')} "
                            f"{getattr(ev, 'chapter', '')}:{getattr(ev, 'current_verse', '')}")

    for et in WATCH:
        bus.subscribe(et, watch)

    follow = root.reading_follow_service
    n = 0
    for title, utterances in SCENARIOS:
        timeline.clear()
        chunk = 1 if "chunks de 1" in title else 3
        for text in utterances:
            if text == "__STOP__":
                bus.publish(PipelineStopped(meta=EventMetadata.for_session_event(
                    session_id="smoke", origin="smoke"), reason="manual_stop"))
                continue
            n += 1
            corr, full, words = f"smoke-{n}", "", text.split()
            for i in range(0, len(words), chunk):
                part = " ".join(words[i:i + chunk])
                full = (full + " " + part).strip()
                bus.publish(SpeechCommittedWords(
                    meta=EventMetadata.for_initial(
                        session_id="smoke", origin="StreamingSTTService", correlation_id=corr),
                    committed_text=part, full_committed_text=full, confidence=0.4))
            bus.publish(SpeechTranscribed(
                meta=EventMetadata.for_initial(
                    session_id="smoke", origin="SpeechWorker", correlation_id=corr),
                text=text))
        state = follow.get_state() if follow else {}
        print(f"\n== {title}")
        for line in timeline or ["(nenhum evento de apresentação)"]:
            print("   ", line)
        if follow:
            print(f"    follow: active={state.get('active')} "
                  f"{state.get('book')} {state.get('chapter')}:{state.get('current_verse')}")


if __name__ == "__main__":
    main()
