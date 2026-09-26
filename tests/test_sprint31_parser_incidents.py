"""Sprint 31 — regressões de incidentes reais de culto (parser de fala).

Cada incidente (a–e) tem teste nomeado. Todas as frases são enviadas
em chunks de vários tamanhos: o resultado NÃO pode depender das
fronteiras de commit do LocalAgreement-2.
"""

from __future__ import annotations

import random
import threading
from pathlib import Path

import pytest

from parser.books import load_parser_books
from parser.canon import load_canon_bounds
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    PipelineStopped,
    ReferenceAntecipada,
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
)
from pipeline.incremental_parser import IncrementalBiblicalParser
from pipeline.metadata import EventMetadata

BOOKS = load_parser_books("config/books.json")
BOUNDS = load_canon_bounds()


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Harness:
    def __init__(self, **kw) -> None:
        self.bus = PipelineEventBus()
        self.clock = Clock()
        self.parser = IncrementalBiblicalParser(
            books=BOOKS, bus=self.bus, session_id="t", clock=self.clock, **kw)
        self.parser.start()
        self.detected: list[ReferenceDetected] = []
        self.anticipated: list[ReferenceAntecipada] = []
        self.candidates: list[ReferenceCandidate] = []
        self.bus.subscribe(ReferenceDetected, self.detected.append)
        self.bus.subscribe(ReferenceAntecipada, self.anticipated.append)
        self.bus.subscribe(ReferenceCandidate, self.candidates.append)
        self._n = 0

    def say(self, text: str, chunk: int = 3, pause: bool = True) -> None:
        """Uma utterance (mesmo correlation_id); pause=True fecha o segmento."""
        self._n += 1
        corr = f"utt-{self._n}"
        words, full = text.split(), ""
        for i in range(0, len(words), chunk):
            part = " ".join(words[i:i + chunk])
            full = (full + " " + part).strip()
            self.bus.publish(SpeechCommittedWords(
                meta=EventMetadata.for_initial(
                    session_id="t", origin="test", correlation_id=corr),
                committed_text=part, full_committed_text=full,
                confidence=0.4,
            ))
        if pause:
            self.bus.publish(SpeechTranscribed(
                meta=EventMetadata.for_initial(
                    session_id="t", origin="test", correlation_id=corr),
                text=text,
            ))

    def refs(self) -> list[str]:
        return [
            f"{e.book} {e.chapter}:{e.verse_start}"
            + (f"-{e.verse_end}" if e.verse_end != e.verse_start else "")
            for e in self.detected
        ]


def detect(text: str, chunk: int = 3, **kw) -> list[str]:
    h = Harness(**kw)
    h.say(text, chunk=chunk)
    return h.refs()


CHUNKS = (1, 2, 3, 5, 100)


# ---------------------------------------------------------------------------
# Critérios de aceite — detecção
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chunk", CHUNKS)
@pytest.mark.parametrize("text,expected", [
    ("João 3:16", "João 3:16"),
    ("joão três dezesseis", "João 3:16"),
    ("joão capítulo três versículo dezesseis", "João 3:16"),
    ("vamos em gênesis capítulo um versículo um", "Gênesis 1:1"),
    ("judas versículo nove", "Judas 1:9"),
    ("abre em judas nove", "Judas 1:9"),
    ("primeira de joão capítulo um versículo nove", "1 João 1:9"),
    ("primeira carta aos coríntios treze quatro", "1 Coríntios 13:4"),
    ("segunda timóteo três dezesseis", "2 Timóteo 3:16"),
    ("II Reis dois onze", "2 Reis 2:11"),
    ("salmo vinte e três versículo um", "Salmos 23:1"),
    ("romanos oito vinte e oito", "Romanos 8:28"),
    ("apocalipse vinte e um quatro", "Apocalipse 21:4"),
    ("salmos cento e dezenove versículo cento e cinco", "Salmos 119:105"),
    ("lá no evangelho segundo joão três dezesseis", "João 3:16"),
    ("jó capítulo um versículo vinte e um", "Jó 1:21"),
    ("cântico dos cânticos dois quatro", "Cânticos 2:4"),
    ("hebreus capítulo doze a partir do versículo um", "Hebreus 12:1"),
])
def test_explicit_references_detected(text, expected, chunk):
    assert detect(text, chunk) == [expected]


def test_range_detected_when_committed_together():
    assert detect("atos dois do quarenta ao quarenta e sete", chunk=100) == ["Atos 2:40-47"]


@pytest.mark.parametrize("chunk", CHUNKS)
def test_range_start_never_lost_across_chunks(chunk):
    """Intervalo dividido entre commits: o início é sempre correto."""
    refs = detect("atos dois do quarenta ao quarenta e sete", chunk)
    assert len(refs) == 1 and refs[0].startswith("Atos 2:40")


# ---------------------------------------------------------------------------
# Incidente (a) — "Judéia" → Judas 1:1 espúrio
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chunk", CHUNKS)
def test_incident_a_judeia_never_resolves_judas(chunk):
    h = Harness()
    h.say("e sereis minhas testemunhas tanto em jerusalém como em toda a "
          "judéia e samaria e até os confins da terra", chunk)
    h.say("para dar um testemunho de primeiro amor", chunk)
    assert h.detected == [] and h.candidates == []


def test_incident_a_english_alias_jude_ignored():
    h = Harness()
    h.say("como em toda a jude", chunk=100, pause=False)
    assert h.parser._current_book is None


# ---------------------------------------------------------------------------
# Incidente (b) — vocabulário de pregação vira livro
# ---------------------------------------------------------------------------

NARRATIVE = [
    "uma revelação diferente de deus capítulo por capítulo",
    "eu amo você três vezes mais",
    "o mal não prevalecerá sete vezes",
    "ele foi um dos doze",
    "judas traiu jesus por trinta moedas",
    "jonas ficou três dias e três noites no ventre do peixe",
    "daniel orava três vezes por dia",
    "os nossos atos dois mil anos",
    "andou sobre o mar quarenta dias e quarenta noites",
    "deus é o justo juiz dez vezes",
    "eu vi o senhor três vezes",
    "salmos eu li três coisas",
    "os números vinte e sete",
    "o provérbio diz duas coisas",
    "êxodo de dez mil pessoas",
    "lucas foi médico doze anos",
    "pedro negou três vezes",
    "marcos tinha doze anos",
    "no versículo três joão diz",
    "a igreja de tessalônica sete vezes",
    "como diz lá em salmos assenta-te",
]


@pytest.mark.parametrize("chunk", (1, 3, 100))
@pytest.mark.parametrize("text", NARRATIVE)
def test_incident_b_narrative_mentions_never_present(text, chunk):
    h = Harness()
    h.say(text, chunk)
    assert h.detected == [] and h.anticipated == []


@pytest.mark.parametrize("chunk", CHUNKS)
def test_dezessete_is_seventeen(chunk):
    """"dezessete" (PT-BR) não era convertido — 17 falado nunca casava."""
    assert detect("joão três dezessete", chunk) == ["João 3:17"]
    assert detect("atos capítulo dezessete versículo onze", chunk) == ["Atos 17:11"]


def test_incident_b_roman_words_not_numbers():
    """"eu vi"/"eu li"/"mil" não viram 6/51/1049 na fala."""
    from parser.normalizer import Normalizer
    n = Normalizer(protect_function_words=True)
    assert n.normalize("eu vi e eu li mil vezes") == "eu vi e eu li mil vezes"
    assert n.normalize("II Reis") == "2 reis"


def test_incident_b_typed_abbreviations_not_speech_aliases():
    from pipeline.speech_reference_grammar import SpeechBookMatcher
    aliases = {a for a, _ in SpeechBookMatcher(BOOKS).eligible_aliases()}
    for bad in ("mar", "mat", "rom", "jud", "jude", "rev", "revelacao",
                "amo", "mal", "juiz", "1100", "150", "1001", "jo", "de", "na"):
        assert bad not in aliases, bad


def test_incident_b_canonical_names_still_work():
    assert detect("vamos ler amós nove treze") == ["Amós 9:13"]
    assert detect("malaquias três dez") == ["Malaquias 3:10"]
    assert detect("atos dois trinta e oito") == ["Atos 2:38"]
    assert detect("no livro de atos capítulo dois versículo um") == ["Atos 2:1"]


# ---------------------------------------------------------------------------
# Incidente (c) — referência canonicamente impossível
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "amós dezenove noventa e nove",
    "amós capítulo dezenove versículo um",
    "judas capítulo dois versículo um",
    "joão três quarenta",
    "salmos cento e cinquenta e um versículo um",
    "gênesis cinquenta versículo trinta",
])
def test_incident_c_out_of_canon_never_detected(text):
    h = Harness()
    h.say(text, chunk=2)
    assert h.detected == []


def test_incident_c_every_detection_is_canonical_fuzz():
    """Propriedade: fala aleatória com livros e números nunca gera
    ReferenceDetected fora do cânon."""
    rng = random.Random(31)
    names = ["joão", "amós", "judas", "salmos", "gênesis", "obadias",
             "atos", "romanos", "capítulo", "versículo", "e", "o", "de"]
    nums = ["um", "dois", "três", "nove", "dezenove", "noventa e nove",
            "cento e cinquenta", "40", "3", "16", "200", "vinte e"]
    h = Harness()
    for _ in range(300):
        words = [rng.choice(names + nums) for _ in range(rng.randint(2, 9))]
        h.say(" ".join(words), chunk=rng.randint(1, 4))
    assert h.detected, "fuzz deveria produzir alguma detecção válida"
    for e in h.detected:
        assert BOUNDS.valid_verse(e.book_id, e.chapter, e.verse_start), e
        assert BOUNDS.valid_verse(e.book_id, e.chapter, e.verse_end), e


# ---------------------------------------------------------------------------
# Incidente (e) — "Abra Hebreus capítulo 12" apresentava 12:1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chunk", CHUNKS)
def test_incident_e_chapter_instruction_does_not_present(chunk):
    h = Harness()
    h.say("abra a sua bíblia em hebreus capítulo doze", chunk)
    assert h.detected == [] and h.anticipated == []
    assert any(c.completeness == "chapter" and c.chapter == 12 for c in h.candidates)


def test_incident_e_chapter_then_verse_after_pause_presents():
    h = Harness()
    h.say("abra a sua bíblia em hebreus capítulo doze")
    h.clock.t += 4
    h.say("versículo um")
    assert h.refs() == ["Hebreus 12:1"]


# ---------------------------------------------------------------------------
# Janela de proximidade / continuação após pausa
# ---------------------------------------------------------------------------

def test_pending_book_expires_and_late_number_does_not_complete():
    h = Harness()
    h.say("li o livro de jonas e depois de muito tempo falando sobre outras "
          "coisas capítulo três versículo dois", chunk=2)
    assert h.detected == []


@pytest.mark.parametrize("chunk", CHUNKS)
def test_carry_across_pause_marked_chapter(chunk):
    h = Harness()
    h.say("abra comigo a sua bíblia no livro de primeiro coríntios", chunk)
    h.clock.t += 3
    h.say("e no capítulo quatorze versículo dez", chunk)
    assert h.refs() == ["1 Coríntios 14:10"]


@pytest.mark.parametrize("chunk", CHUNKS)
def test_carry_across_pause_compact_pair(chunk):
    h = Harness()
    h.say("lá no evangelho de joão", chunk)
    h.clock.t += 2
    h.say("10:27", chunk)
    assert h.refs() == ["João 10:27"]


def test_carry_expires():
    h = Harness(carry_seconds=10.0)
    h.say("abra no livro de primeiro coríntios")
    h.clock.t += 11
    h.say("capítulo quatorze versículo dez")
    assert h.detected == []


def test_carry_requires_marker_at_start():
    h = Harness()
    h.say("abra no livro de primeiro coríntios")
    h.say("eram três pessoas dez anos atrás")
    h.say("quando ele falou isso 14 10")
    assert h.detected == []


def test_carry_cleared_by_pipeline_stop():
    h = Harness()
    h.say("abra no livro de primeiro coríntios")
    h.bus.publish(PipelineStopped(meta=EventMetadata.for_initial(
        session_id="t", origin="test")))
    h.say("capítulo quatorze versículo dez")
    assert h.detected == []


def test_verse_correction_same_utterance():
    h = Harness()
    h.say("joão três dezesseis porque deus amou o mundo e no versículo dezessete",
          pause=False)
    assert h.refs() == ["João 3:16", "João 3:17"]


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------

def test_concurrent_publishers_do_not_corrupt_state():
    h = Harness()
    errors: list[BaseException] = []

    def worker(tag: int) -> None:
        try:
            for i in range(60):
                h.bus.publish(SpeechCommittedWords(
                    meta=EventMetadata.for_initial(
                        session_id="t", origin="test", correlation_id=f"c{tag}-{i}"),
                    committed_text="romanos oito vinte e oito",
                ))
                h.bus.publish(SpeechTranscribed(
                    meta=EventMetadata.for_initial(session_id="t", origin="test"),
                    text="x",
                ))
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert h.detected and all(r == "Romanos 8:28" for r in h.refs())


# ---------------------------------------------------------------------------
# Benchmark oficial (morning-prayer-27-07-2026) — replay
# ---------------------------------------------------------------------------

BENCH = Path("datasets/benchmarks/morning-prayer-27-07-2026/benchmark.yaml")


@pytest.mark.skipif(not BENCH.exists(), reason="benchmark ausente")
def test_benchmark_morning_prayer_replay():
    import yaml
    events = yaml.safe_load(BENCH.read_text(encoding="utf-8"))
    h = Harness()
    presented: dict[int, list[str]] = {}
    for ev in events:
        before = len(h.detected)
        h.clock.t += 3
        h.say(" ".join(str(ev["speech"]).replace('"', " ").split()), chunk=3)
        presented[ev["id"]] = h.refs()[before:]
    # Apresentações esperadas (evento 5 é "repeat" — já está na tela).
    assert presented[2] == ["1 Coríntios 14:10"]
    assert presented[10] == ["João 10:27"]
    # Falsos positivos críticos: nada apresentado.
    for eid in (1, 3, 4, 6, 7, 8, 9, 11):
        assert presented[eid] == [], (eid, presented[eid])
    assert presented[5] in ([], ["1 Coríntios 14:10"])
    assert h.anticipated == []
