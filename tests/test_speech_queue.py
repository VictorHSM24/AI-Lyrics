"""Testes da SpeechQueue (Sprint 16).

Cobre:
  - put/get básico.
  - Bounded: descarta quando cheia.
  - Thread-safety (produtor/consumidor em threads).
  - Métricas.
  - clear().
"""

from __future__ import annotations

import threading
import time
import unittest

from microfone.capture import SpeechSegment
from microfone.speech_queue import SpeechQueue


def _make_segment(duration_ms: int = 500) -> SpeechSegment:
    """Cria um SpeechSegment fake para testes."""
    return SpeechSegment(
        audio=b"\x00" * 100,
        start_time=time.time(),
        end_time=time.time(),
        duration_ms=duration_ms,
        chunk_count=10,
    )


class TestSpeechQueue(unittest.TestCase):
    """Testes básicos da SpeechQueue."""

    def test_put_and_get(self):
        """put enfileira, get desenfileira na ordem FIFO."""
        q = SpeechQueue(maxsize=10)
        s1 = _make_segment(100)
        s2 = _make_segment(200)

        self.assertTrue(q.put(s1))
        self.assertTrue(q.put(s2))
        self.assertEqual(q.qsize(), 2)

        got1 = q.get(timeout=1.0)
        got2 = q.get(timeout=1.0)
        self.assertIs(got1, s1)
        self.assertIs(got2, s2)
        self.assertEqual(q.qsize(), 0)

    def test_get_timeout_returns_none(self):
        """get com timeout retorna None se vazia."""
        q = SpeechQueue(maxsize=10)
        result = q.get(timeout=0.1)
        self.assertIsNone(result)

    def test_get_nowait_empty(self):
        """get_nowait retorna None se vazia."""
        q = SpeechQueue(maxsize=10)
        self.assertIsNone(q.get_nowait())

    def test_bounded_drops_when_full(self):
        """put retorna False quando a fila está cheia."""
        q = SpeechQueue(maxsize=2)
        self.assertTrue(q.put(_make_segment()))
        self.assertTrue(q.put(_make_segment()))
        # Fila cheia — deve descartar.
        self.assertFalse(q.put(_make_segment()))
        # Métricas devem mostrar 1 descarte.
        m = q.metrics
        self.assertEqual(m.total_dropped, 1)

    def test_metrics(self):
        """Métricas refletem operações."""
        q = SpeechQueue(maxsize=10)
        q.put(_make_segment(100))
        q.put(_make_segment(200))
        q.get(timeout=1.0)

        m = q.metrics
        self.assertEqual(m.total_enqueued, 2)
        self.assertEqual(m.total_dequeued, 1)
        self.assertEqual(m.total_dropped, 0)
        self.assertEqual(m.current_size, 1)
        self.assertEqual(m.max_size_reached, 2)

    def test_clear(self):
        """clear remove todos os itens e retorna o count."""
        q = SpeechQueue(maxsize=10)
        q.put(_make_segment())
        q.put(_make_segment())
        q.put(_make_segment())
        self.assertEqual(q.qsize(), 3)

        removed = q.clear()
        self.assertEqual(removed, 3)
        self.assertEqual(q.qsize(), 0)
        self.assertTrue(q.empty())

    def test_empty_property(self):
        """empty() retorna True quando vazia."""
        q = SpeechQueue(maxsize=10)
        self.assertTrue(q.empty())
        q.put(_make_segment())
        self.assertFalse(q.empty())
        q.get_nowait()
        self.assertTrue(q.empty())

    def test_thread_safety(self):
        """Produtor e consumidor em threads separadas não corrompem."""
        q = SpeechQueue(maxsize=100)
        produced = []
        consumed = []
        stop = threading.Event()

        def producer():
            for i in range(50):
                seg = _make_segment(i * 10)
                q.put(seg)
                produced.append(seg)
            stop.set()

        def consumer():
            while not (stop.is_set() and q.empty()):
                seg = q.get(timeout=0.1)
                if seg is not None:
                    consumed.append(seg)

        t1 = threading.Thread(target=producer)
        t2 = threading.Thread(target=consumer)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        self.assertEqual(len(produced), 50)
        self.assertEqual(len(consumed), 50)


if __name__ == "__main__":
    unittest.main()
