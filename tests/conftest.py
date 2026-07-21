"""conftest.py — configuração global para os testes do AI Lyrics.

Sprint 21.1: seta AI_LYRICS_TEST_MODE=1 para evitar que create_composition_root()
carregue componentes pesados (STT faster-whisper, embeddings, SemanticEngine,
SermonMemoryEngine, etc.) durante testes que apenas validam endpoints REST.

Testes que precisam de componentes reais devem usar mocks próprios ou
unsetar esta env var explicitamente.
"""

import os

# Setar antes de qualquer import do api.startup.
os.environ["AI_LYRICS_TEST_MODE"] = "1"
