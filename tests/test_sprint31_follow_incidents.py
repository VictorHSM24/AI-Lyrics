"""Sprint 31 — regressões de incidentes reais (acompanhamento de leitura).

Harness de integração com os componentes reais no MESMO bus e na mesma
ordem de inscrição da composição de produção:
VersePresentationService → ReadingFollowService → VersionCommandDetector
→ IncrementalBiblicalParser. Searcher e Holyrics são dublês.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from parser.books import load_parser_books
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    PipelineStopped,
    ReadingFollowAdvanced,
    ReadingFollowEnded,
    SpeechCommittedWords,
    SpeechTranscribed,
    VersePresented,
)
from pipeline.incremental_parser import IncrementalBiblicalParser
from pipeline.metadata import EventMetadata
from presentation.reading_follow_service import ReadingFollowService
from presentation.verse_presentation_service import VersePresentationService
from presentation.version_command_detector import VersionCommandDetector

BOOK_IDS = {"João": 43, "Romanos": 45, "Hebreus": 58}
TEXTS = {
    ("Hebreus", 12, 1): "PORTANTO nós também, pois que estamos rodeados de uma tão grande "
                        "nuvem de testemunhas, deixemos todo o embaraço, e o pecado que tão "
                        "de perto nos rodeia, e corramos com paciência a carreira que nos "
                        "está proposta,",
    ("Hebreus", 12, 2): "Olhando para Jesus, autor e consumador da fé, o qual, pelo gozo que "
                        "lhe estava proposto, suportou a cruz, desprezando a afronta, e "
                        "assentou-se à destra do trono de Deus.",
    ("Hebreus", 12, 3): "Considerai, pois, aquele que suportou tais contradições dos "
                        "pecadores contra si mesmo, para que não enfraqueçais, desfalecendo "
                        "em vossos ânimos.",
    ("Hebreus", 11, 40): "Provendo Deus alguma coisa melhor a nosso respeito, para que eles "
                         "sem nós não fossem aperfeiçoados.",
    ("João", 11, 35): "Jesus chorou.",
    ("João", 11, 36): "Disseram, pois, os judeus: Vede como o amava.",
    ("João", 3, 16): "Porque Deus amou o mundo de tal maneira que deu o seu Filho unigênito, "
                     "para que todo aquele que nele crê não pereça, mas tenha a vida eterna.",
    ("João", 3, 17): "Porque Deus enviou o seu Filho ao mundo, não para que condenasse o "
                     "mundo, mas para que o mundo fosse salvo por ele.",
    ("João", 3, 18): "Quem crê nele não é condenado; mas quem não crê já está condenado.",
    ("Romanos", 8, 28): "E sabemos que todas as coisas contribuem juntamente para o bem "
                        "daqueles que amam a Deus.",
}
CHAPTER_END = {("Hebreus", 12): 29, ("Hebreus", 11): 40, ("João", 11): 57,
               ("João", 3): 36, ("Romanos", 8): 39}

# ~4 minutos de pregação SOBRE Hebreus 12:1, usando vocabulário do
# versículo e muitas palavras funcionais da cauda ("a", "que", "nos",
# "está") — sem ler o versículo.
PREACHING = (
    "irmãos a vida cristã é uma carreira e não uma corrida de cem metros "
    "o autor aos hebreus quer que nós entendamos que existe uma nuvem de "
    "testemunhas olhando para nós a fé deles está registrada no capítulo "
    "onze e agora a palavra nos chama para deixar o embaraço o pecado que "
    "nos rodeia não é pequeno meus irmãos quantos aqui já sentiram o peso "
    "de uma carreira difícil a paciência que Deus nos dá está disponível "
    "hoje a igreja precisa correr com perseverança e não desistir amém "
    "aquele que começou a boa obra nos chama e está conosco até o fim "
)


def _search(book_name=None, chapter=None, verse=None, *args, version=None, **kw):
    if book_name is None and args:
        book_name = args[0]
    text = TEXTS.get((book_name, chapter, verse))
    if text is None:
        return None
    return SimpleNamespace(
        text=text, book=book_name, book_id=BOOK_IDS[book_name], chapter=chapter,
        verse=verse, reference=f"{book_name} {chapter}:{verse}", version="ACF",
    )


def _search_chapter(book_name, chapter, *, version=None):
    end = CHAPTER_END.get((book_name, chapter), 0)
    return [SimpleNamespace(verse=v) for v in range(1, end + 1)]


class Rig:
    def __init__(self) -> None:
        self.bus = PipelineEventBus()
        self.searcher = MagicMock()
        self.searcher.search_by_reference.side_effect = _search
        self.searcher.search_chapter.side_effect = _search_chapter
        self.holyrics = MagicMock()
        self.holyrics.show_verse.return_value = SimpleNamespace(status="ok")
        self.holyrics.show_verse_references.return_value = {"status": "ok"}
        self.vps = VersePresentationService(
            searcher=self.searcher, holyrics=self.holyrics, bus=self.bus,
            session_id="s")
        self.vps.start()
        self.follow = ReadingFollowService(
            searcher=self.searcher, holyrics=self.holyrics, bus=self.bus,
            session_id="s", version="ACF")
        self.follow.start()
        self.vcd = VersionCommandDetector(bus=self.bus, session_id="s")
        self.vcd.start()
        self.parser = IncrementalBiblicalParser(
            books=load_parser_books("config/books.json"), bus=self.bus,
            session_id="s")
        self.parser.start()
        self.presented: list[VersePresented] = []
        self.advanced: list[ReadingFollowAdvanced] = []
        self.ended: list[ReadingFollowEnded] = []
        self.bus.subscribe(VersePresented, self.presented.append)
        self.bus.subscribe(ReadingFollowAdvanced, self.advanced.append)
        self.bus.subscribe(ReadingFollowEnded, self.ended.append)
        self._n = 0

    def say(self, text: str, chunk: int = 3, pause: bool = True) -> None:
        self._n += 1
        corr, full = f"u{self._n}", ""
        words = text.split()
        for i in range(0, len(words), chunk):
            part = " ".join(words[i:i + chunk])
            full = (full + " " + part).strip()
            self.bus.publish(SpeechCommittedWords(
                meta=EventMetadata.for_initial(session_id="s", origin="t", correlation_id=corr),
                committed_text=part, full_committed_text=full))
        if pause:
            self.bus.publish(SpeechTranscribed(
                meta=EventMetadata.for_initial(session_id="s", origin="t", correlation_id=corr),
                text=text))

    def operator_present(self, book: str, chapter: int, verse: int) -> None:
        """Equivalente ao POST /operator/present (show_verse + VersePresented)."""
        self.holyrics.show_verse(book_id=BOOK_IDS[book], chapter=chapter, verse=verse)
        self.bus.publish(VersePresented(
            meta=EventMetadata.for_initial(session_id="s", origin="OperatorPanel"),
            book=book, book_id=BOOK_IDS[book], chapter=chapter, verse=verse,
            version="ACF", reference=f"{book} {chapter}:{verse}", holyrics_status="ok"))

    def state(self) -> dict:
        return self.follow.get_state()

    def screen(self) -> str:
        p = self.presented[-1]
        return f"{p.book} {p.chapter}:{p.verse}"


def read(key: tuple) -> str:
    return TEXTS[key]


# ---------------------------------------------------------------------------
# Incidente (d) — avanço espúrio por pregação sem leitura
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("chunk", (1, 2, 3, 7))
def test_incident_d_preaching_never_advances(chunk):
    rig = Rig()
    rig.say("hebreus doze versículo um")
    assert rig.screen() == "Hebreus 12:1" and rig.state()["active"]
    for _ in range(12):  # ~ 1100 palavras de pregação
        rig.say(PREACHING, chunk)
    assert rig.state()["current_verse"] == 1
    assert rig.advanced == []
    assert rig.screen() == "Hebreus 12:1"


def test_incident_d_function_word_tail_does_not_complete():
    """Cauda "a carreira que nos está proposta": 4 funcionais em ordem sem
    as palavras de conteúdo não completam (a regra 4-de-6 completava)."""
    rig = Rig()
    rig.say("hebreus doze versículo um")
    rig.say(read(("Hebreus", 12, 1)).split("a carreira")[0])  # corpo lido
    rig.say("e a vida que nos está sendo dada hoje")
    assert rig.state()["current_verse"] == 1


def test_incident_d_real_reading_advances_and_follows_chapter():
    rig = Rig()
    rig.say("hebreus doze versículo um")
    rig.say(read(("Hebreus", 12, 1)) + " " + read(("Hebreus", 12, 2)), chunk=3)
    assert rig.state()["current_verse"] == 3
    assert rig.screen() == "Hebreus 12:3"


def test_incident_d_pause_midverse_then_resume():
    rig = Rig()
    rig.say("hebreus doze versículo um")
    text = read(("Hebreus", 12, 1)).split()
    rig.say(" ".join(text[:18]))           # metade do versículo
    for _ in range(4):
        rig.say(PREACHING)                 # comentário longo
    rig.say(" ".join(text[18:]))           # retoma de onde parou
    assert rig.state()["current_verse"] == 2


def test_incident_d_reread_partial_then_finish():
    rig = Rig()
    rig.say("hebreus doze versículo um")
    text = read(("Hebreus", 12, 1)).split()
    rig.say(" ".join(text[:12]))
    rig.say(" ".join(text[:12]))           # relê o início
    rig.say(" ".join(text[12:]))
    assert rig.state()["current_verse"] == 2


def test_incident_d_short_verse():
    rig = Rig()
    rig.operator_present("João", 11, 35)
    rig.say("jesus é o nosso amigo irmãos")
    assert rig.state()["current_verse"] == 35
    rig.say("jesus chorou")
    assert rig.state()["current_verse"] == 36


# ---------------------------------------------------------------------------
# Incidente (e) — capítulo sem versículo não apresenta
# ---------------------------------------------------------------------------

def test_incident_e_chapter_instruction_does_not_present_or_anchor():
    rig = Rig()
    rig.operator_present("Hebreus", 11, 40)
    rig.say("abra a sua bíblia em hebreus capítulo doze")
    assert rig.screen() == "Hebreus 11:40"
    rig.say("versículo um")                 # completa pela pausa
    assert rig.screen() == "Hebreus 12:1"


# ---------------------------------------------------------------------------
# Incidente (f) — follow x navegação manual / nova referência
# ---------------------------------------------------------------------------

def test_incident_f_operator_present_reanchors_without_double_show():
    rig = Rig()
    rig.say("joão três dezesseis")
    assert rig.state()["current_verse"] == 16
    calls = rig.holyrics.show_verse.call_count
    rig.operator_present("João", 3, 18)
    assert rig.holyrics.show_verse.call_count == calls + 1  # só a do operador
    assert rig.state()["current_verse"] == 18 and rig.state()["verse_start"] == 18


def test_incident_f_follow_advance_keeps_vps_in_sync():
    rig = Rig()
    rig.say("joão três dezesseis")
    rig.say(read(("João", 3, 16)))
    assert rig.screen() == "João 3:17"
    assert rig.vps._last_presented_key == (43, 3, 17)
    rig.say("joão três dezessete")          # já na tela → sem reapresentar
    assert rig.screen() == "João 3:17" and rig.state()["current_verse"] == 17


def test_incident_f_navigation_single_owner():
    rig = Rig()
    rig.say("joão três dezesseis")
    n = len(rig.presented)
    rig.say("próximo")
    assert rig.state()["current_verse"] == 17
    assert len(rig.presented) == n + 1 and rig.screen() == "João 3:17"
    rig.say("voltar um")
    assert rig.state()["current_verse"] == 16 and rig.screen() == "João 3:16"
    rig.say("voltar versículo")             # já no início do intervalo
    assert rig.screen() == "João 3:16"


def test_incident_f_navigation_word_mid_sentence_ignored():
    rig = Rig()
    rig.say("joão três dezesseis")
    rig.say("e o próximo versículo vai dizer algo lindo irmãos")
    rig.say("vamos voltar a velhas práticas")
    assert rig.state()["current_verse"] == 16


def test_incident_f_new_reference_during_follow_not_hijacked_by_goto():
    rig = Rig()
    rig.say("joão três dezesseis")
    rig.say("agora vamos para romanos capítulo oito")
    rig.say("versículo vinte e oito")
    assert rig.screen() == "Romanos 8:28"
    assert rig.state()["book"] == "Romanos" and rig.state()["current_verse"] == 28
    assert all(not (p.book == "João" and p.verse == 28) for p in rig.presented)


def test_incident_f_stop_really_stops():
    rig = Rig()
    rig.say("joão três dezesseis")
    rig.follow.deactivate()
    assert not rig.state()["active"] and rig.state()["auto_follow_paused"]
    rig.say("romanos oito vinte e oito")    # voz apresenta, follow NÃO ancora
    assert rig.screen() == "Romanos 8:28" and not rig.state()["active"]
    rig.operator_present("João", 3, 16)     # operador reativa
    assert rig.state()["active"] and not rig.state()["auto_follow_paused"]


# ---------------------------------------------------------------------------
# Incidente (g) — pipeline parado não deixa follow fantasma
# ---------------------------------------------------------------------------

def test_incident_g_pipeline_stop_deactivates_follow():
    rig = Rig()
    rig.say("hebreus doze versículo um")
    assert rig.state()["active"]
    rig.bus.publish(PipelineStopped(meta=EventMetadata.for_initial(
        session_id="s", origin="PipelinePresentationService"), reason="manual_stop"))
    assert not rig.state()["active"]
    assert rig.ended[-1].reason == "pipeline_stopped"
    rig.say(read(("Hebreus", 12, 1)))
    assert rig.advanced == [] and rig.screen() == "Hebreus 12:1"


def test_incident_g_audio_stop_publishes_pipeline_stopped():
    from api.routers.audio import _publish_pipeline_stopped
    rig = Rig()
    rig.say("hebreus doze versículo um")
    root = SimpleNamespace(bus=rig.bus, pipeline_service=None,
                           session=SimpleNamespace(session_id="s"))
    _publish_pipeline_stopped(root, reason="audio_stopped")
    assert not rig.state()["active"]


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------

def test_follow_concurrent_handlers():
    rig = Rig()
    rig.operator_present("João", 3, 16)
    errors: list[BaseException] = []

    def reader():
        try:
            for _ in range(30):
                rig.say(read(("João", 3, 16)), chunk=2)
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    def operator():
        try:
            for v in (16, 17, 18) * 10:
                rig.operator_present("João", 3, v)
                rig.follow.get_state()
        except BaseException as e:  # pragma: no cover
            errors.append(e)

    ts = [threading.Thread(target=reader), threading.Thread(target=operator)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert errors == []
    st = rig.state()
    assert not st["active"] or 16 <= st["current_verse"] <= 36
