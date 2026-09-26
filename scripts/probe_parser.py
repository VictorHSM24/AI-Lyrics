"""Sonda o IncrementalBiblicalParser com frases faladas (diagnóstico).

Uso: python scripts/probe_parser.py ["frase 1" "frase 2" ...]
Sem argumentos, roda um corpus embutido de citações e falsos positivos.
Cada frase é enviada em chunks de 3 palavras (simula committed words).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser.books import load_parser_books  # noqa: E402
from pipeline.bus import PipelineEventBus  # noqa: E402
from pipeline.events import (  # noqa: E402
    ReferenceAntecipada,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
)
from pipeline.incremental_parser import IncrementalBiblicalParser  # noqa: E402
from pipeline.metadata import EventMetadata  # noqa: E402

CORPUS = [
    # Citações (devem detectar)
    "João 3:16",
    "joão três dezesseis",
    "joão capítulo três versículo dezesseis",
    "vamos em gênesis capítulo um versículo um",
    "judas versículo nove",
    "atos dois do quarenta ao quarenta e sete",
    "primeira de joão capítulo um versículo nove",
    "primeira coríntios treze quatro",
    "segunda timóteo três dezesseis",
    "primeiro reis dezoito trinta e oito",
    "salmo vinte e três",
    "salmos noventa e um versículo um",
    "romanos oito vinte e oito",
    "hebreus onze versículo um",
    "apocalipse vinte e um quatro",
    # Narrativas (NÃO devem apresentar)
    "como em toda a judéia e samaria",
    "uma revelação diferente",
    "eu amo você",
    "o mal não prevalecerá",
    "ele foi um dos doze",
    "judas traiu jesus por trinta moedas",
    "jonas ficou três dias e três noites no ventre do peixe",
    "daniel orava três vezes por dia",
    "os nossos atos dois mil anos",
    "andou sobre o mar quarenta dias e quarenta noites",
    "deus é o justo juiz dez vezes",
    "eu vi o senhor",
    "eu li a palavra",
    "salmos eu vi três coisas",
    "os números vinte e sete",
    "cântico novo cinco vezes",
    "o provérbio diz duas coisas",
    "êxodo de dez mil pessoas",
    "lucas foi médico doze anos",
    "pedro negou três vezes",
    "amós dezenove noventa e nove",
    "judas um testemunho",
    "abra hebreus capítulo doze",
]


def probe(phrase: str, books, chunk: int = 3) -> list[str]:
    bus = PipelineEventBus()
    p = IncrementalBiblicalParser(books=books, bus=bus, session_id="probe")
    p.start()
    out: list[str] = []
    bus.subscribe(ReferenceDetected, lambda e: out.append(
        f"DETECTED {e.book} {e.chapter}:{e.verse_start}"
        + (f"-{e.verse_end}" if e.verse_end != e.verse_start else "")
        + f" conf={e.confidence:.2f}"))
    bus.subscribe(ReferenceAntecipada, lambda e: out.append(
        f"ANTECIPADA {e.book} {e.chapter}:{e.verse_start} ({e.completeness})"))
    words = phrase.split()
    full = ""
    for i in range(0, len(words), chunk):
        part = " ".join(words[i:i + chunk])
        full = (full + " " + part).strip()
        bus.publish(SpeechCommittedWords(
            meta=EventMetadata.for_initial(
                session_id="probe", origin="probe", correlation_id="c1"),
            committed_text=part, full_committed_text=full,
        ))
    bus.publish(SpeechTranscribed(
        meta=EventMetadata.for_initial(session_id="probe", origin="probe",
                                       correlation_id="c1"),
        text=phrase,
    ))
    return out


def main() -> None:
    books = load_parser_books("config/books.json")
    phrases = sys.argv[1:] or CORPUS
    for ph in phrases:
        results = {c: "; ".join(probe(ph, books, c)) or "-" for c in (1, 2, 3, 50)}
        same = len(set(results.values())) == 1
        shown = results[3] if same else " | ".join(f"c{c}: {v}" for c, v in results.items())
        print(f"{ph!r:62} -> {shown}")


if __name__ == "__main__":
    main()
