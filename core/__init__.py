"""Core do projeto: tipos canônicos, exceções, hardware e orquestração.

Nota: Pipeline e ApplicationContext são importados diretamente de
core.pipeline para evitar import circular com config.
"""

from core.decision import DecisionEngine, DecisionMetrics
from core.confirmation import (
    Candidate,
    CandidateList,
    CandidateSelector,
    ConfirmationPolicy,
    ProcessResult,
    SelectionResult,
)
from core.exceptions import (
    AILyricsError,
    ConfigError,
    DecisionError,
    PipelineError,
    STTError,
    StateError,
)
from core.hardware import (
    CpuInfo,
    EmbeddingRecommendation,
    GpuInfo,
    HardwareDetector,
    HardwareProfile,
    HardwareRecommender,
    LLMRecommendation,
    Recommendations,
    STTRecommendation,
)
from core.types import Confidence, Decision, Intent, LogEntry, Utterance, VerseRef

__all__ = [
    "AILyricsError",
    "ConfigError",
    "DecisionError",
    "PipelineError",
    "StateError",
    "STTError",
    "CpuInfo",
    "EmbeddingRecommendation",
    "GpuInfo",
    "HardwareDetector",
    "HardwareProfile",
    "HardwareRecommender",
    "LLMRecommendation",
    "Recommendations",
    "STTRecommendation",
    "Confidence",
    "Decision",
    "Intent",
    "LogEntry",
    "Utterance",
    "VerseRef",
    "DecisionEngine",
    "DecisionMetrics",
    "Candidate",
    "CandidateList",
    "CandidateSelector",
    "ConfirmationPolicy",
    "ProcessResult",
    "SelectionResult",
]
