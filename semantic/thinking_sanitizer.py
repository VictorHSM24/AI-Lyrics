"""semantic/thinking_sanitizer.py — Sanitização de blocos de thinking (Sprint 21.1.1).

Responsabilidade única:
  - Detectar blocos de raciocínio explícito (thinking) em respostas de LLMs.
  - Removê-los preservando o conteúdo útil (geralmente JSON).
  - Devolver apenas a resposta final.

Motivação:
  Modelos diferentes utilizam formatos diferentes para raciocínio explícito.
  Exemplos reais:
    <think>...</think>
    <thinking>...</thinking>
    <|thinking|>...<|/thinking|>
    [thinking]...[/thinking]

  O sanitizador é genérico e extensível — não depende de nomes de modelos.

Sprint 21.1.1 — Hardening do LocalLLMProvider.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = ["ThinkingSanitizer", "SanitizationResult"]


# ---------------------------------------------------------------------------
# Padrões regex de blocos de thinking.
# Cada entrada é (regex_compilada, descrição).
# Adicionar novos padrões aqui — não espalhar verificações pelo código.
# ---------------------------------------------------------------------------

# Padrões suportados (case-insensitive, multiline/DOTALL para capturar
# blocos que cruzam linhas).
_THINKING_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # <think>...</think> (qwen3, deepseek-r1)
    (re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL),
     "<think>...</think>"),
    # <thinking>...</thinking> (variantes)
    (re.compile(r"<thinking\b[^>]*>.*?</thinking\s*>",
                re.IGNORECASE | re.DOTALL),
     "<thinking>...</thinking>"),
    # <|thinking|>...<|/thinking|> (token-style)
    (re.compile(r"<\|thinking\|>.*?<\|/thinking\|>",
                re.IGNORECASE | re.DOTALL),
     "<|thinking|>...<|/thinking|>"),
    # [thinking]...[/thinking] (bracket-style)
    (re.compile(r"\[thinking\].*?\[/thinking\]",
                re.IGNORECASE | re.DOTALL),
     "[thinking]...[/thinking]"),
    # Blocos abertos sem fechamento — remover do início até o primeiro
    # JSON ou final. Caso raro mas real em respostas truncadas.
    (re.compile(r"<think\b[^>]*>.*", re.IGNORECASE | re.DOTALL),
     "<think>... (unterminated)"),
    (re.compile(r"<thinking\b[^>]*>.*", re.IGNORECASE | re.DOTALL),
     "<thinking>... (unterminated)"),
]


@dataclass(frozen=True)
class SanitizationResult:
    """Resultado da sanitização de uma resposta de LLM.

    Campos:
        content: conteúdo limpo (sem blocos de thinking).
        had_thinking: True se blocos de thinking foram detectados e removidos.
        patterns_matched: lista de descrições dos padrões que matched.
        original_length: tamanho do conteúdo original em caracteres.
        cleaned_length: tamanho do conteúdo limpo em caracteres.
    """
    content: str
    had_thinking: bool
    patterns_matched: tuple[str, ...] = ()
    original_length: int = 0
    cleaned_length: int = 0


class ThinkingSanitizer:
    """Sanitizador genérico de blocos de thinking em respostas de LLM.

    Uso:
        sanitizer = ThinkingSanitizer()
        result = sanitizer.sanitize(raw_content)
        if result.had_thinking:
            logger.debug("Thinking block removed")
        json_text = result.content

    Thread-safe (stateless). Pode ser compartilhado entre threads.
    """

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None) -> None:
        """Inicializa o sanitizador.

        Args:
            extra_patterns: padrões adicionais no formato (regex_str, descrição).
                Compilados com IGNORECASE | DOTALL. Útil para estender sem
                modificar este módulo.
        """
        self._patterns: list[tuple[re.Pattern[str], str]] = list(_THINKING_PATTERNS)
        if extra_patterns:
            for regex_str, desc in extra_patterns:
                self._patterns.append((
                    re.compile(regex_str, re.IGNORECASE | re.DOTALL),
                    desc,
                ))

    def sanitize(self, content: str) -> SanitizationResult:
        """Remove blocos de thinking do conteúdo.

        Args:
            content: resposta bruta do LLM.

        Returns:
            SanitizationResult com o conteúdo limpo e metadados.
        """
        if not content:
            return SanitizationResult(
                content="", had_thinking=False,
                original_length=0, cleaned_length=0,
            )

        original = content
        original_len = len(content)
        matched: list[str] = []
        cleaned = content

        for pattern, desc in self._patterns:
            new_cleaned, n = pattern.subn("", cleaned)
            if n > 0:
                matched.append(desc)
                cleaned = new_cleaned

        # Limpar espaços/quebras de linha remanescentes no início.
        # Após remover o bloco de thinking, o JSON geralmente começa
        # após algumas quebras de linha.
        cleaned = cleaned.lstrip("\r\n\t ")

        had_thinking = len(matched) > 0

        if had_thinking:
            logger.debug(
                "ThinkingSanitizer: removed %d pattern(s): %s",
                len(matched), ", ".join(matched),
            )

        return SanitizationResult(
            content=cleaned,
            had_thinking=had_thinking,
            patterns_matched=tuple(matched),
            original_length=original_len,
            cleaned_length=len(cleaned),
        )

    def has_thinking(self, content: str) -> bool:
        """Verifica rapidamente se o conteúdo contém blocos de thinking.

        Mais eficiente que sanitize() quando só interessa a detecção.
        """
        if not content:
            return False
        for pattern, _ in self._patterns:
            if pattern.search(content):
                return True
        return False
