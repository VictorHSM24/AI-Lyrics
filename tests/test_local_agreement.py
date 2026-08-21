"""Testes do LocalAgreement-2 no StreamingSTTService (Sprint 28).

Valida o algoritmo de LocalAgreement-2:
- 2 transcrições consecutivas concordam em palavras → COMMITTED
- Divergência no prefixo → palavras não committed
- Buffer de committed cresce incrementalmente
- SpeechCommittedWords é publicado corretamente
"""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from microfone.streaming_stt_service import StreamingSTTService
from pipeline.bus import PipelineEventBus
from pipeline.events import SpeechCommittedWords, SpeechPartial, SpeechPartialUpdated
from transcricao.stt import STTResult


def _make_result(
    text: str,
    words: tuple[tuple[str, float, float], ...] = (),
    confidence: float = 0.9,
) -> STTResult:
    """Cria um STTResult para teste."""
    return STTResult(
        text=text,
        language="pt",
        confidence=confidence,
        processing_ms=100,
        audio_duration_ms=6000,
        words=words,
    )


def _make_job_result(result: STTResult):
    """Cria um STTJobResult mock."""
    from microfone.stt_executor import STTJobResult
    return STTJobResult(result=result, queue_wait_ms=0, total_ms=100)


@pytest.fixture
def service():
    """Cria um StreamingSTTService com executor mock."""
    executor = MagicMock()
    bus = PipelineEventBus()
    svc = StreamingSTTService(
        executor=executor,
        bus=bus,
        session_id="test-session",
        sample_rate=16000,
    )
    svc.start()
    return svc, executor, bus


class TestLocalAgreement:
    """Testes do algoritmo LocalAgreement-2."""

    def test_two_consecutive_agree_commits_words(self, service):
        """2 transcrições que concordam em prefixo → palavras committed."""
        svc, executor, bus = service

        # Transcrição T1: 5 palavras
        t1_words = (("irmãos", 0.0, 0.5), ("vamos", 0.5, 0.8), ("abrir", 0.8, 1.2),
                     ("no", 1.2, 1.4), ("evangelho", 1.4, 2.0))
        # Transcrição T2: 7 palavras (5 primeiras iguais + 2 novas)
        t2_words = (("irmãos", 0.0, 0.5), ("vamos", 0.5, 0.8), ("abrir", 0.8, 1.2),
                     ("no", 1.2, 1.4), ("evangelho", 1.4, 2.0), ("de", 2.0, 2.2),
                     ("joão", 2.2, 2.6))

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1  # 6s de áudio

        # T1: primeira transcrição
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos vamos abrir no evangelho", t1_words)
        )
        svc.on_window(audio, 0.0)

        # T1 não tem prev_words, então nada committed ainda.
        assert svc.total_committed_published == 0
        assert svc.committed_text == ""

        # T2: segunda transcrição (5 palavras iguais + 2 novas)
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos vamos abrir no evangelho de joão", t2_words)
        )
        svc.on_window(audio, 0.4)

        # T2 concorda com T1 em 5 palavras → 5 committed.
        assert svc.total_committed_published == 1
        assert svc.total_committed_words == 5
        assert "irmãos vamos abrir no evangelho" in svc.committed_text

    def test_divergence_no_commit(self, service):
        """Transcrições que divergem no início → nada committed."""
        svc, executor, bus = service

        t1_words = (("irmãos", 0.0, 0.5), ("vamos", 0.5, 0.8))
        t2_words = (("meus", 0.0, 0.5), ("amigos", 0.5, 0.8))

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos vamos", t1_words)
        )
        svc.on_window(audio, 0.0)

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("meus amigos", t2_words)
        )
        svc.on_window(audio, 0.4)

        # Divergência no início → 0 committed.
        assert svc.total_committed_published == 0
        assert svc.committed_text == ""

    def test_incremental_commit(self, service):
        """Commits crescem incrementalmente ao longo de 3 transcrições."""
        svc, executor, bus = service

        t1_words = (("joão", 0.0, 0.5), ("capítulo", 0.5, 1.0))
        t2_words = (("joão", 0.0, 0.5), ("capítulo", 0.5, 1.0), ("três", 1.0, 1.5))
        t3_words = (("joão", 0.0, 0.5), ("capítulo", 0.5, 1.0), ("três", 1.0, 1.5),
                     ("versículo", 1.5, 2.0), ("dezesseis", 2.0, 2.5))

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        # T1: primeira transcrição, nada committed.
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("joão capítulo", t1_words)
        )
        svc.on_window(audio, 0.0)
        assert svc.total_committed_published == 0

        # T2: concorda com T1 em 2 palavras → 2 committed.
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("joão capítulo três", t2_words)
        )
        svc.on_window(audio, 0.4)
        assert svc.total_committed_published == 1
        assert svc.total_committed_words == 2
        assert "joão capítulo" in svc.committed_text

        # T3: concorda com T2 em 3 palavras → 1 nova committed ("três").
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("joão capítulo três versículo dezesseis", t3_words)
        )
        svc.on_window(audio, 0.8)
        assert svc.total_committed_published == 2
        assert svc.total_committed_words == 3
        assert "joão capítulo três" in svc.committed_text

    def test_reset_flow_clears_committed(self, service):
        """reset_flow() limpa estado de committed."""
        svc, executor, bus = service

        t1_words = (("irmãos", 0.0, 0.5), ("vamos", 0.5, 0.8))
        t2_words = (("irmãos", 0.0, 0.5), ("vamos", 0.5, 0.8), ("abrir", 0.8, 1.2))

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos vamos", t1_words)
        )
        svc.on_window(audio, 0.0)

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos vamos abrir", t2_words)
        )
        svc.on_window(audio, 0.4)
        assert svc.total_committed_words == 2

        # Reset
        svc.reset_flow()
        assert svc.committed_text == ""
        assert svc.total_committed_words == 2  # métrica acumulada não reset
        assert svc._committed_word_count == 0

    def test_speech_committed_words_event_published(self, service):
        """SpeechCommittedWords é publicado no EventBus."""
        svc, executor, bus = service

        events_received = []
        bus.subscribe(SpeechCommittedWords, lambda e: events_received.append(e))

        t1_words = (("deus", 0.0, 0.5), ("amou", 0.5, 1.0))
        t2_words = (("deus", 0.0, 0.5), ("amou", 0.5, 1.0), ("o", 1.0, 1.2))

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("deus amou", t1_words)
        )
        svc.on_window(audio, 0.0)

        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("deus amou o", t2_words)
        )
        svc.on_window(audio, 0.4)

        assert len(events_received) == 1
        event = events_received[0]
        assert event.committed_text == "deus amou"
        assert event.full_committed_text == "deus amou"
        assert len(event.words) == 2
        assert event.words[0][0] == "deus"
        assert event.words[1][0] == "amou"

    def test_silence_resets_prev_words(self, service):
        """Silêncio (RMS baixo) reseta prev_words (buffer trimming implícito)."""
        svc, executor, bus = service

        # Primeiro, áudio normal com fala
        t1_words = (("irmãos", 0.0, 0.5),)
        audio_loud = np.ones(16000 * 6, dtype=np.float32) * 0.1
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("irmãos", t1_words)
        )
        svc.on_window(audio_loud, 0.0)
        assert len(svc._prev_words) == 1

        # Depois, silêncio (RMS < min_rms)
        audio_silent = np.zeros(16000 * 6, dtype=np.float32) * 0.001
        svc.on_window(audio_silent, 0.4)

        # prev_words deve ser resetado.
        assert len(svc._prev_words) == 0

    def test_fallback_without_word_timestamps(self, service):
        """Sem word_timestamps, faz fallback splitting do texto."""
        svc, executor, bus = service

        # STTResult sem words (vazio) — fallback para split do texto.
        t1 = _make_result("irmãos vamos", words=())
        t2 = _make_result("irmãos vamos abrir", words=())

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        executor.transcribe_audio.return_value = _make_job_result(t1)
        svc.on_window(audio, 0.0)

        executor.transcribe_audio.return_value = _make_job_result(t2)
        svc.on_window(audio, 0.4)

        # Fallback: split do texto → 2 palavras committed.
        assert svc.total_committed_published == 1
        assert svc.total_committed_words == 2

    def test_sliding_window_words_fall_off_left(self, service):
        """SlidingWindow: palavras caem da esquerda, mas LocalAgreement-2
        ainda commita via alinhamento de sufixo/prefixo."""
        svc, executor, bus = service

        audio = np.ones(16000 * 6, dtype=np.float32) * 0.1

        # T1: 7 palavras na janela de 6s.
        t1_words = (("em", 0.0, 0.3), ("nome", 0.3, 0.6), ("de", 0.6, 0.9),
                     ("jesus", 0.9, 1.3), ("amém", 1.3, 1.6), ("meus", 1.6, 1.9),
                     ("queridos", 1.9, 2.3))
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("em nome de jesus amém meus queridos", t1_words)
        )
        svc.on_window(audio, 0.0)
        # T1: primeira transcrição, nada committed.
        assert svc.total_committed_published == 0

        # T2: "em nome de" caiu da esquerda (janela deslizou 400ms).
        # O sufixo de T1 ("jesus amém meus queridos") casa com
        # o prefixo de T2.
        t2_words = (("jesus", 0.0, 0.4), ("amém", 0.4, 0.7), ("meus", 0.7, 1.0),
                     ("queridos", 1.0, 1.4), ("bom", 1.4, 1.7), ("dia", 1.7, 2.0))
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("jesus amém meus queridos bom dia", t2_words)
        )
        svc.on_window(audio, 0.4)

        # T2: 4 palavras casam (jesus, amém, meus, queridos) → 4 committed.
        assert svc.total_committed_published == 1
        assert svc.total_committed_words == 4
        assert "jesus amém meus queridos" in svc.committed_text

        # T3: "jesus" caiu da esquerda. Novamente, alinhamento.
        t3_words = (("amém", 0.0, 0.3), ("meus", 0.3, 0.6), ("queridos", 0.6, 0.9),
                     ("bom", 0.9, 1.2), ("dia", 1.2, 1.5), ("graça", 1.5, 1.8),
                     ("paz", 1.8, 2.1))
        executor.transcribe_audio.return_value = _make_job_result(
            _make_result("amém meus queridos bom dia graça paz", t3_words)
        )
        svc.on_window(audio, 0.8)

        # T3: 5 palavras casam (amém, meus, queridos, bom, dia).
        # Já committed: "jesus amém meus queridos" (4 palavras).
        # Das 5 estáveis, 3 já estão committed (amém, meus, queridos).
        # Novas committed: "bom", "dia" (2 palavras).
        assert svc.total_committed_published == 2
        assert svc.total_committed_words == 6
        assert "bom dia" in svc.committed_text

    def test_trim_margin_seconds_stored(self):
        """trim_margin_seconds é armazenado como parâmetro."""
        executor = MagicMock()
        bus = PipelineEventBus()
        svc = StreamingSTTService(
            executor=executor,
            bus=bus,
            session_id="test-session",
            trim_margin_seconds=0.5,
        )
        assert svc._trim_margin_seconds == 0.5
