"""Sprint 32 — continuação ancorada: "capítulo X, versículo Y" ou
"versículo Y" sem nome do livro continuam da última referência.

Cenário do usuário: o pregador diz "João capítulo 3 versículo 16",
prega um pouco e depois pede isoladamente "capítulo 5, versículo 10"
— o sistema mantém o livro e resolve João 5:10. Exige marcador
explícito ("capítulo"/"versículo") — número solto nunca continua.
"""

from __future__ import annotations

from parser.books import load_parser_books
from pipeline.bus import PipelineEventBus
from pipeline.events import (
    ReferenceCandidate,
    ReferenceDetected,
    SpeechCommittedWords,
    SpeechTranscribed,
)
from pipeline.incremental_parser import IncrementalBiblicalParser
from pipeline.metadata import EventMetadata


class Rig:
    def __init__(self, anchor_seconds: float = 600.0, clock=lambda: 0.0) -> None:
        self.bus = PipelineEventBus()
        self.parser = IncrementalBiblicalParser(
            books=load_parser_books("config/books.json"), bus=self.bus,
            session_id="s", anchor_seconds=anchor_seconds, clock=clock)
        self.parser.start()
        self.detected: list[ReferenceDetected] = []
        self.candidates: list[ReferenceCandidate] = []
        self.bus.subscribe(ReferenceDetected, self.detected.append)
        self.bus.subscribe(ReferenceCandidate, self.candidates.append)
        self._n = 0

    def say(self, text: str, chunk: int = 4, pause: bool = True) -> None:
        self._n += 1
        corr = f"u{self._n}"
        words, full = text.split(), ""
        for i in range(0, len(words), chunk):
            part = " ".join(words[i:i + chunk])
            full = (full + " " + part).strip()
            self.bus.publish(SpeechCommittedWords(
                meta=EventMetadata.for_initial(
                    session_id="s", origin="t", correlation_id=corr),
                committed_text=part, full_committed_text=full))
        if pause:
            self.bus.publish(SpeechTranscribed(
                meta=EventMetadata.for_initial(
                    session_id="s", origin="t", correlation_id=corr),
                text=text))

    def last(self) -> str:
        d = self.detected[-1]
        return f"{d.book} {d.chapter}:{d.verse_start}"


def test_capitulo_versiculo_sem_livro_continua_da_ancora():
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    assert rig.last() == "João 3:16"
    rig.say("capítulo cinco versículo dez")
    assert rig.last() == "João 5:10"


def test_versiculo_isolado_mantem_livro_e_capitulo():
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    rig.say("versículo vinte")
    assert rig.last() == "João 3:20"


def test_ancora_atualiza_em_nova_referencia_completa():
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    rig.say("salmos capítulo vinte e três versículo um")
    assert rig.last() == "Salmos 23:1"
    rig.say("versículo quatro")          # continua de Salmos, não João
    assert rig.last() == "Salmos 23:4"


def test_numero_solto_nunca_continua():
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    n = len(rig.detected)
    rig.say("ele falou sobre os vinte e oito anos de ministério")
    assert len(rig.detected) == n        # sem marcador → sem continuação


def test_ancora_expira_apos_ttl():
    clock = [0.0]
    rig = Rig(anchor_seconds=60.0, clock=lambda: clock[0])
    rig.say("joão capítulo três versículo dezesseis")
    clock[0] = 100.0                     # 100s depois (> 60s TTL)
    rig.say("capítulo cinco versículo dez")
    assert len(rig.detected) == 1        # âncora expirada → nada


def test_par_compacto_sem_marcador_nao_continua():
    """"14 10" solto no meio da fala NÃO resolve pela âncora — exige
    marcador explícito "capítulo"/"versículo" (condição do usuário)."""
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    n = len(rig.detected)
    rig.say("quando ele falou isso 14 10")
    assert len(rig.detected) == n


def test_livro_explicito_no_inicio_nao_usa_ancora():
    rig = Rig()
    rig.say("joão capítulo três versículo dezesseis")
    rig.say("romanos capítulo oito versículo vinte e oito")
    assert rig.last() == "Romanos 8:28"  # livro explícito sempre vence
