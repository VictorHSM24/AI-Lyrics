"""Testes do Sprint 17.2 — Event Stream Optimization.

Valida a separação entre OperationalEvent e TelemetryEvent:
  - OperationalEvents são armazenados no EventStore.
  - TelemetryEvents NÃO são armazenados no EventStore.
  - Ambos são dispatchados aos handlers.
  - EventDTO carrega o campo `category`.
  - EventMapper.to_dto() propaga category corretamente.
  - AudioEventPublisher marca audio.level como telemetry.
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from pipeline.events import (
    PipelineEvent,
    OperationalEvent,
    TelemetryEvent,
    PipelineStarted,
    PipelineStopped,
    ReferenceDetected,
    SpeechTranscribed,
    is_operational_event,
    is_telemetry_event,
)
from pipeline.metadata import EventMetadata
from pipeline.bus import PipelineEventBus
from pipeline.event_store import MemoryEventStore
from presentation.dtos import EventDTO, EventMetadataDTO
from presentation.mappers import EventMapper


def _make_meta(origin: str = "test") -> EventMetadata:
    return EventMetadata.for_initial(origin=origin, session_id="test-session")


# ---------------------------------------------------------------------------
# Eventos de telemetria para teste
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AudioLevel(TelemetryEvent):
    """Evento de telemetria para teste — nível de áudio."""

    rms: float = 0.0
    peak: float = 0.0


@dataclass(frozen=True)
class CpuUsage(TelemetryEvent):
    """Evento de telemetria para teste — uso de CPU."""

    usage_percent: float = 0.0


class TestEventHierarchy(unittest.TestCase):
    """Testa a hierarquia OperationalEvent vs TelemetryEvent."""

    def test_all_existing_events_are_operational(self):
        """Todos os eventos existentes herdam de OperationalEvent."""
        events = [
            PipelineStarted(meta=_make_meta()),
            PipelineStopped(meta=_make_meta()),
            SpeechTranscribed(meta=_make_meta()),
        ]
        for e in events:
            self.assertIsInstance(e, OperationalEvent, f"{type(e).__name__} should be OperationalEvent")
            self.assertEqual(e.category, "operational")

    def test_telemetry_events_have_telemetry_category(self):
        """TelemetryEvents têm category='telemetry'."""
        e = AudioLevel(meta=_make_meta(), rms=0.5)
        self.assertEqual(e.category, "telemetry")
        self.assertTrue(is_telemetry_event(e))
        self.assertFalse(is_operational_event(e))

    def test_operational_events_have_operational_category(self):
        """OperationalEvents têm category='operational'."""
        e = PipelineStarted(meta=_make_meta())
        self.assertEqual(e.category, "operational")
        self.assertTrue(is_operational_event(e))
        self.assertFalse(is_telemetry_event(e))

    def test_all_events_are_pipeline_events(self):
        """Tanto Operational quanto Telemetry são PipelineEvents."""
        op = PipelineStarted(meta=_make_meta())
        tel = AudioLevel(meta=_make_meta())
        self.assertIsInstance(op, PipelineEvent)
        self.assertIsInstance(tel, PipelineEvent)


class TestEventBusTelemetryFiltering(unittest.TestCase):
    """Testa que o EventBus não armazena TelemetryEvents no EventStore."""

    def setUp(self):
        self.store = MemoryEventStore()
        self.bus = PipelineEventBus(store=self.store)

    def test_operational_events_are_stored(self):
        """OperationalEvents são armazenados no EventStore."""
        e = PipelineStarted(meta=_make_meta())
        self.bus.publish(e)
        self.assertEqual(self.store.count(), 1)
        stored = self.store.all()
        self.assertEqual(stored[0].event_type, "PipelineStarted")

    def test_telemetry_events_are_not_stored(self):
        """TelemetryEvents NÃO são armazenados no EventStore."""
        e = AudioLevel(meta=_make_meta(), rms=0.5)
        self.bus.publish(e)
        self.assertEqual(self.store.count(), 0)

    def test_telemetry_events_still_dispatch_to_handlers(self):
        """TelemetryEvents ainda são dispatchados aos handlers inscritos."""
        received = []
        self.bus.subscribe(AudioLevel, received.append)
        e = AudioLevel(meta=_make_meta(), rms=0.5)
        self.bus.publish(e)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].rms, 0.5)

    def test_mixed_events_only_operational_stored(self):
        """Mix de eventos — apenas OperationalEvents são persistidos."""
        self.bus.publish(PipelineStarted(meta=_make_meta()))
        self.bus.publish(AudioLevel(meta=_make_meta(), rms=0.1))
        self.bus.publish(AudioLevel(meta=_make_meta(), rms=0.2))
        self.bus.publish(SpeechTranscribed(meta=_make_meta(), text="hello"))
        self.bus.publish(AudioLevel(meta=_make_meta(), rms=0.3))
        # Apenas 2 OperationalEvents (PipelineStarted + SpeechTranscribed).
        self.assertEqual(self.store.count(), 2)
        types = [e.event_type for e in self.store.all()]
        self.assertIn("PipelineStarted", types)
        self.assertIn("SpeechTranscribed", types)
        self.assertNotIn("AudioLevel", types)

    def test_telemetry_does_not_appear_in_history(self):
        """TelemetryEvents não aparecem no history()."""
        self.bus.publish(PipelineStarted(meta=_make_meta()))
        self.bus.publish(AudioLevel(meta=_make_meta(), rms=0.1))
        self.bus.publish(PipelineStopped(meta=_make_meta()))
        history = self.bus.history()
        self.assertEqual(len(history), 2)
        for e in history:
            self.assertTrue(is_operational_event(e))


class TestEventDTOCategory(unittest.TestCase):
    """Testa que EventDTO carrega o campo category."""

    def test_operational_dto_has_operational_category(self):
        """EventMapper.to_dto() propaga category='operational'."""
        e = PipelineStarted(meta=_make_meta())
        dto = EventMapper.to_dto(e)
        self.assertEqual(dto.category, "operational")
        self.assertTrue(dto.is_operational)
        self.assertFalse(dto.is_telemetry)

    def test_telemetry_dto_has_telemetry_category(self):
        """EventMapper.to_dto() propaga category='telemetry'."""
        e = AudioLevel(meta=_make_meta(), rms=0.5)
        dto = EventMapper.to_dto(e)
        self.assertEqual(dto.category, "telemetry")
        self.assertTrue(dto.is_telemetry)
        self.assertFalse(dto.is_operational)

    def test_dto_to_dict_includes_category(self):
        """to_dict() inclui o campo category."""
        e = PipelineStarted(meta=_make_meta())
        dto = EventMapper.to_dto(e)
        d = dto.to_dict()
        self.assertIn("category", d)
        self.assertEqual(d["category"], "operational")

    def test_dto_default_category_is_operational(self):
        """EventDTO sem category explicito default='operational'."""
        dto = EventDTO(
            event_type="TestEvent",
            meta=EventMetadataDTO(
                event_id="e1", correlation_id="c1", causation_id=None,
                session_id="s1", timestamp=0, origin="test", metadata=(),
            ),
        )
        self.assertEqual(dto.category, "operational")


class TestAudioEventPublisherTelemetry(unittest.TestCase):
    """Testa que AudioEventPublisher marca audio.level como telemetry."""

    def test_audio_level_event_is_telemetry(self):
        """audio.level EventDTO tem category='telemetry'."""
        from api.websocket.audio_events import _make_audio_event
        dto = _make_audio_event(
            "audio.level",
            {"rms": 0.5, "peak": 0.8, "timestamp": 1.0},
            category="telemetry",
        )
        self.assertEqual(dto.category, "telemetry")
        self.assertTrue(dto.is_telemetry)

    def test_audio_started_event_is_operational(self):
        """audio.started EventDTO tem category='operational' (default)."""
        from api.websocket.audio_events import _make_audio_event
        dto = _make_audio_event(
            "audio.started",
            {"device_index": 0, "sample_rate": 16000, "channels": 1},
        )
        self.assertEqual(dto.category, "operational")
        self.assertTrue(dto.is_operational)

    def test_audio_stopped_event_is_operational(self):
        """audio.stopped EventDTO tem category='operational' (default)."""
        from api.websocket.audio_events import _make_audio_event
        dto = _make_audio_event("audio.stopped", {})
        self.assertEqual(dto.category, "operational")


class TestFutureTelemetryEvents(unittest.TestCase):
    """Testa que futuros eventos de telemetria (CPU, GPU, RAM) funcionam."""

    def test_cpu_usage_is_telemetry(self):
        """CpuUsage (futuro) é corretamente identificado como telemetry."""
        e = CpuUsage(meta=_make_meta(), usage_percent=45.0)
        self.assertTrue(is_telemetry_event(e))
        self.assertEqual(e.category, "telemetry")
        # Não seria armazenado no EventStore.
        store = MemoryEventStore()
        bus = PipelineEventBus(store=store)
        bus.publish(e)
        self.assertEqual(store.count(), 0)

    def test_cpu_usage_dto_is_telemetry(self):
        """CpuUsage DTO tem category='telemetry'."""
        e = CpuUsage(meta=_make_meta(), usage_percent=45.0)
        dto = EventMapper.to_dto(e)
        self.assertEqual(dto.category, "telemetry")


class TestWebSocketContract(unittest.TestCase):
    """Valida que o JSON transmitido via WebSocket inclui `category`.

    Sprint 17.2 — O bug original era que EventModel.from_dto() descartava
    o campo `category` do EventDTO. O frontend nunca recebia category="telemetry"
    e portanto não conseguia filtrar audio.level da Timeline.

    Estes testes garantem que o contrato WebSocket inclui category.
    """

    def test_audio_level_ws_json_has_telemetry_category(self):
        """WebSocket JSON para audio.level tem category='telemetry'."""
        import json
        from api.schemas.models import EventModel, WsEventModel
        from api.websocket.audio_events import _make_audio_event

        dto = _make_audio_event(
            "audio.level",
            {"rms": 0.5, "peak": 0.8, "timestamp": 1.0},
            category="telemetry",
        )
        model = EventModel.from_dto(dto)
        ws_msg = json.loads(WsEventModel(event=model).model_dump_json())
        self.assertIn("category", ws_msg["event"])
        self.assertEqual(ws_msg["event"]["category"], "telemetry")

    def test_operational_event_ws_json_has_operational_category(self):
        """WebSocket JSON para PipelineStarted tem category='operational'."""
        import json
        from api.schemas.models import EventModel, WsEventModel

        e = PipelineStarted(meta=_make_meta())
        dto = EventMapper.to_dto(e)
        model = EventModel.from_dto(dto)
        ws_msg = json.loads(WsEventModel(event=model).model_dump_json())
        self.assertIn("category", ws_msg["event"])
        self.assertEqual(ws_msg["event"]["category"], "operational")

    def test_reference_detected_ws_json_has_operational_and_confidence(self):
        """WebSocket JSON para ReferenceDetected tem category e confidence no payload."""
        import json
        from api.schemas.models import EventModel, WsEventModel

        meta = _make_meta()
        e = ReferenceDetected(
            meta=meta,
            intent="OPEN_REFERENCE",
            book="João",
            book_id=43,
            chapter=15,
            verse_start=2,
            verse_end=2,
            confidence=0.95,
            raw_text="joão capítulo quinze versículo dois",
            normalized_text="joao 15:2",
        )
        dto = EventMapper.to_dto(e)
        model = EventModel.from_dto(dto)
        ws_msg = json.loads(WsEventModel(event=model).model_dump_json())
        event = ws_msg["event"]
        self.assertEqual(event["category"], "operational")
        self.assertEqual(event["payload"]["confidence"], 0.95)
        self.assertEqual(event["payload"]["book"], "João")
        self.assertEqual(event["payload"]["chapter"], 15)
        self.assertEqual(event["payload"]["verse_start"], 2)

    def test_speech_transcribed_ws_json_has_confidence(self):
        """WebSocket JSON para SpeechTranscribed tem confidence no payload."""
        import json
        from api.schemas.models import EventModel, WsEventModel

        meta = _make_meta()
        e = SpeechTranscribed(
            meta=meta,
            text="joão capítulo quinze versículo dois",
            language="pt",
            confidence=0.87,
            latency_ms=120,
            duration_ms=2000,
        )
        dto = EventMapper.to_dto(e)
        model = EventModel.from_dto(dto)
        ws_msg = json.loads(WsEventModel(event=model).model_dump_json())
        event = ws_msg["event"]
        self.assertEqual(event["category"], "operational")
        self.assertEqual(event["payload"]["confidence"], 0.87)
        self.assertEqual(event["payload"]["latency_ms"], 120)
        self.assertEqual(event["payload"]["duration_ms"], 2000)

    def test_event_model_from_dto_preserves_category(self):
        """EventModel.from_dto() preserva category do EventDTO."""
        from api.schemas.models import EventModel

        # Telemetry
        dto_tel = _make_audio_event_dto("telemetry")
        model_tel = EventModel.from_dto(dto_tel)
        self.assertEqual(model_tel.category, "telemetry")

        # Operational
        dto_op = EventMapper.to_dto(PipelineStarted(meta=_make_meta()))
        model_op = EventModel.from_dto(dto_op)
        self.assertEqual(model_op.category, "operational")

    def test_legacy_dto_without_category_defaults_operational(self):
        """EventDTO sem category → EventModel default='operational'."""
        from api.schemas.models import EventModel

        dto = EventDTO(
            event_type="LegacyEvent",
            meta=EventMetadataDTO(
                event_id="e1", correlation_id="c1", causation_id=None,
                session_id="s1", timestamp=0, origin="test", metadata=(),
            ),
            payload={},
            # category não definido — default deve ser "operational"
        )
        model = EventModel.from_dto(dto)
        self.assertEqual(model.category, "operational")


def _make_audio_event_dto(category: str) -> EventDTO:
    """Cria um EventDTO de audio.level com a categoria especificada."""
    from api.websocket.audio_events import _make_audio_event
    return _make_audio_event(
        "audio.level",
        {"rms": 0.5, "peak": 0.8, "timestamp": 1.0},
        category=category,
    )


if __name__ == "__main__":
    unittest.main()
