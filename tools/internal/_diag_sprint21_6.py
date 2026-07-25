"""Sprint 21.6 — Validação Final da Inferência Semântica e Engenharia de Prompt.

Executa 4 experimentos com a mesma cadeia de inferência (Ollama real),
variando apenas o prompt conforme cada experimento:

  Exp 1 — Baseline: implementação atual (sem alterações)
  Exp 2 — Sem recent_text: remover "Fala recente" do user prompt
  Exp 3 — recent_text como contexto secundário: adicionar instrução ao system prompt
  Exp 4 — Ordem invertida: Texto atual antes de Fala recente

Para cada experimento, executa as 6 frases:
  1. O Senhor é meu pastor.
  2. Porque Deus amou o mundo.
  3. Ainda que eu ande pelo vale da sombra da morte.
  4. Tudo posso naquele que me fortalece.
  5. A armadura de Deus.
  6. Provérbios 15:14

Referências esperadas (ground truth):
  1. Salmos 23:1
  2. João 3:16
  3. Salmos 23:4
  4. Filipenses 4:13
  5. Efésios 6:10-18 (capítulo 6)
  6. Provérbios 15:14

Uso:
    python _diag_sprint21_6.py
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_6_output.txt"
_fh = open(_LOG_FILE, "w", encoding="utf-8")
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=_fh,
)
logger = logging.getLogger("diag")
logger.setLevel(logging.INFO)
_fh_handler = logging.StreamHandler(_fh)
_fh_handler.setLevel(logging.INFO)
_fh_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_fh_handler)
logger.propagate = False

from semantic.local_provider import LocalLLMProvider, _SYSTEM_PROMPT
from semantic.backend_factory import create_backend, normalize_base_url_for_backend
from semantic.types import SemanticContext, SemanticResult
from semantic.thinking_sanitizer import ThinkingSanitizer


# ---------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------
GROUND_TRUTH = {
    "O Senhor é meu pastor.": ("Salmos", 23, 1),
    "Porque Deus amou o mundo.": ("João", 3, 16),
    "Ainda que eu ande pelo vale da sombra da morte.": ("Salmos", 23, 4),
    "Tudo posso naquele que me fortalece.": ("Filipenses", 4, 13),
    "A armadura de Deus.": ("Efésios", 6, 0),  # capítulo inteiro
    "Provérbios 15:14": ("Provérbios", 15, 14),
}

FRASES = list(GROUND_TRUTH.keys())


# ---------------------------------------------------------------------
# Variações de prompt
# ---------------------------------------------------------------------
SYSTEM_PROMPT_SECUNDARIO = _SYSTEM_PROMPT + """

CONTEXTO SECUNDÁRIO:
A seção "Fala recente" serve apenas para desambiguar referências incompletas.
Identifique a referência exclusivamente do "Texto atual".
Nunca escolha um candidato apenas por causa da fala recente."""


def build_user_prompt_baseline(ctx: SemanticContext) -> str:
    """Implementação atual — replicada de local_provider._build_user_prompt."""
    lines = []
    if ctx.sermon_book:
        ref = ctx.sermon_book
        if ctx.sermon_chapter > 0:
            ref += f" {ctx.sermon_chapter}"
        lines.append(f"Contexto do sermão: pregando em {ref}.")
        if ctx.sermon_theme:
            lines.append(f"Tema atual: {ctx.sermon_theme}.")
        if ctx.sermon_entities:
            lines.append(f"Entidades mencionadas: {', '.join(ctx.sermon_entities[:5])}.")
        if ctx.sermon_confidence > 0:
            lines.append(f"Confiança da memória: {ctx.sermon_confidence:.0%}.")
    elif ctx.last_book:
        lines.append(f"Contexto: o sermão está em {ctx.last_reference or ctx.last_book}.")
    if ctx.recent_text and ctx.recent_text != ctx.current_text:
        lines.append(f"Fala recente: {ctx.recent_text}")
    lines.append(f"Texto atual: {ctx.current_text}")
    lines.append("")
    lines.append("Responda apenas com JSON:")
    return "\n".join(lines)


def build_user_prompt_no_recent(ctx: SemanticContext) -> str:
    """Exp 2 — remover Fala recente."""
    lines = []
    if ctx.sermon_book:
        ref = ctx.sermon_book
        if ctx.sermon_chapter > 0:
            ref += f" {ctx.sermon_chapter}"
        lines.append(f"Contexto do sermão: pregando em {ref}.")
        if ctx.sermon_theme:
            lines.append(f"Tema atual: {ctx.sermon_theme}.")
        if ctx.sermon_entities:
            lines.append(f"Entidades mencionadas: {', '.join(ctx.sermon_entities[:5])}.")
        if ctx.sermon_confidence > 0:
            lines.append(f"Confiança da memória: {ctx.sermon_confidence:.0%}.")
    elif ctx.last_book:
        lines.append(f"Contexto: o sermão está em {ctx.last_reference or ctx.last_book}.")
    # NÃO incluir recent_text
    lines.append(f"Texto atual: {ctx.current_text}")
    lines.append("")
    lines.append("Responda apenas com JSON:")
    return "\n".join(lines)


def build_user_prompt_inverted(ctx: SemanticContext) -> str:
    """Exp 4 — ordem invertida: Texto atual antes de Fala recente."""
    lines = []
    if ctx.sermon_book:
        ref = ctx.sermon_book
        if ctx.sermon_chapter > 0:
            ref += f" {ctx.sermon_chapter}"
        lines.append(f"Contexto do sermão: pregando em {ref}.")
        if ctx.sermon_theme:
            lines.append(f"Tema atual: {ctx.sermon_theme}.")
        if ctx.sermon_entities:
            lines.append(f"Entidades mencionadas: {', '.join(ctx.sermon_entities[:5])}.")
        if ctx.sermon_confidence > 0:
            lines.append(f"Confiança da memória: {ctx.sermon_confidence:.0%}.")
    elif ctx.last_book:
        lines.append(f"Contexto: o sermão está em {ctx.last_reference or ctx.last_book}.")
    # ORDEM INVERTIDA
    lines.append(f"Texto atual: {ctx.current_text}")
    if ctx.recent_text and ctx.recent_text != ctx.current_text:
        lines.append(f"Fala recente: {ctx.recent_text}")
    lines.append("")
    lines.append("Responda apenas com JSON:")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Inferência direta (sem EventBus, sem SemanticEngine)
# ---------------------------------------------------------------------
@dataclass
class InferenceResult:
    frase: str
    user_prompt: str
    system_prompt: str
    payload: dict
    raw_response: str
    parsed: dict | None
    parse_error: str | None
    intent: str
    candidates: list[dict]
    inference_ms: int
    http_ms: float


def call_ollama_directly(
    backend,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    disable_thinking: bool,
    timeout_s: float,
) -> tuple[str, float]:
    """Envia requisição direta ao Ollama e retorna (raw_content, http_ms)."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "num_predict": max_tokens,
        },
    }
    if disable_thinking:
        payload["think"] = False

    t0 = time.monotonic()
    resp = backend.send_request(payload, timeout_s)
    http_ms = (time.monotonic() - t0) * 1000.0
    return resp.content, http_ms


def parse_response(content: str) -> tuple[dict | None, str | None]:
    """Replica o parser do LocalLLMProvider._parse_and_validate (simplificado)."""
    # Sanitizar thinking
    sanitizer = ThinkingSanitizer()
    sanitize_result = sanitizer.sanitize(content)
    cleaned = sanitize_result.content

    # Extrair JSON (pode estar dentro de ```json ... ``` ou solto)
    text = cleaned.strip()
    # Tentar json.loads direto
    try:
        data = json.loads(text)
        return _validate(data), None
    except json.JSONDecodeError:
        pass

    # Tentar encontrar JSON dentro de ```json ... ```
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.rfind("```")
        if end > start:
            try:
                data = json.loads(text[start:end].strip())
                return _validate(data), None
            except json.JSONDecodeError as e:
                return None, f"JSON decode error em bloco markdown: {e}"

    # Tentar encontrar primeiro { e último }
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            data = json.loads(text[first:last + 1])
            return _validate(data), None
        except json.JSONDecodeError as e:
            return None, f"JSON decode error: {e}"

    return None, f"Não foi possível encontrar JSON válido em: {text[:200]}"


def _validate(data: dict) -> dict:
    """Valida e normaliza o schema do candidato."""
    intent = data.get("intent", "none")
    if intent not in ("show_reference", "none"):
        intent = "none" if intent != "show_reference" else intent

    cands_raw = data.get("candidates", [])
    if not isinstance(cands_raw, list):
        cands_raw = []

    candidates = []
    for c in cands_raw:
        if not isinstance(c, dict):
            continue
        book = str(c.get("book", "")).strip()[:40]
        chapter = int(c.get("chapter", 0) or 0)
        verse = int(c.get("verse", 0) or 0)
        confidence = float(c.get("confidence", 0.0) or 0.0)
        confidence = max(0.0, min(1.0, confidence))
        reason = str(c.get("reason", ""))[:80]
        if book:
            candidates.append({
                "book": book, "chapter": chapter, "verse": verse,
                "confidence": confidence, "reason": reason,
            })

    return {"intent": intent, "candidates": candidates}


# ---------------------------------------------------------------------
# Executor de experimento
# ---------------------------------------------------------------------
def run_experiment(
    name: str,
    system_prompt: str,
    user_prompt_fn,
    backend,
    model: str,
    temperature: float = 0.1,
    top_p: float = 0.9,
    max_tokens: int = 300,
    disable_thinking: bool = True,
    timeout_s: float = 120.0,
) -> list[InferenceResult]:
    """Executa as 6 frases com a configuração dada."""
    results: list[InferenceResult] = []

    logger.info("")
    logger.info("█" * 70)
    logger.info("█ EXPERIMENTO: %s", name)
    logger.info("█" * 70)

    # Contexto simulado: cada frase recebe a frase anterior como recent_text.
    for i, frase in enumerate(FRASES):
        recent_text = FRASES[i - 1] if i > 0 else ""
        ctx = SemanticContext(
            current_text=frase,
            recent_text=recent_text,
            session_id="diag",
        )

        user_prompt = user_prompt_fn(ctx)

        logger.info("")
        logger.info("─" * 60)
        logger.info("Frase %d: %r", i + 1, frase)
        logger.info("recent_text: %r", recent_text)
        logger.info("")
        logger.info("  ── USER PROMPT ──")
        for line in user_prompt.splitlines():
            logger.info("    %s", line)
        logger.info("")
        logger.info("  ── SYSTEM PROMPT (primeiras 5 e últimas 5 linhas) ──")
        sys_lines = system_prompt.splitlines()
        for line in sys_lines[:5]:
            logger.info("    %s", line)
        logger.info("    [...]")
        for line in sys_lines[-5:]:
            logger.info("    %s", line)

        # Payload
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": temperature, "top_p": top_p, "num_predict": max_tokens},
            "think": False if disable_thinking else None,
        }
        if "think" in payload and payload["think"] is None:
            del payload["think"]

        logger.info("")
        logger.info("  ── PAYLOAD ──")
        payload_display = json.loads(json.dumps(payload))
        for m in payload_display["messages"]:
            if m["role"] == "system":
                m["content"] = f"[SYSTEM PROMPT — {len(system_prompt)} chars]"
        for line in json.dumps(payload_display, indent=2, ensure_ascii=False).splitlines():
            logger.info("    %s", line)

        # Chamada
        try:
            raw_content, http_ms = call_ollama_directly(
                backend, system_prompt, user_prompt, model,
                temperature, top_p, max_tokens, disable_thinking, timeout_s,
            )
        except Exception as e:
            logger.info("  ✗ ERRO HTTP: %s: %s", type(e).__name__, e)
            results.append(InferenceResult(
                frase=frase, user_prompt=user_prompt, system_prompt=system_prompt,
                payload=payload, raw_response=str(e), parsed=None,
                parse_error=str(e), intent="none", candidates=[],
                inference_ms=0, http_ms=0,
            ))
            continue

        logger.info("")
        logger.info("  ── RESPOSTA RAW (http_ms=%.0f) ──", http_ms)
        for line in raw_content.splitlines() if isinstance(raw_content, str) else [str(raw_content)]:
            logger.info("    %s", line)

        # Parse
        parsed, parse_err = parse_response(raw_content)
        if parse_err:
            logger.info("  ✗ PARSER ERRO: %s", parse_err)
            intent = "none"
            candidates = []
        else:
            intent = parsed["intent"]
            candidates = parsed["candidates"]
            logger.info("")
            logger.info("  ── PARSER OK ──")
            logger.info("    intent: %s", intent)
            logger.info("    candidates: %d", len(candidates))
            for j, c in enumerate(candidates):
                logger.info("      [%d] %s %d:%d conf=%.2f reason=%r",
                            j, c["book"], c["chapter"], c["verse"], c["confidence"], c["reason"])

        results.append(InferenceResult(
            frase=frase, user_prompt=user_prompt, system_prompt=system_prompt,
            payload=payload, raw_response=raw_content, parsed=parsed,
            parse_error=parse_err, intent=intent, candidates=candidates,
            inference_ms=int(http_ms), http_ms=http_ms,
        ))

    return results


# ---------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------
def evaluate(results: list[InferenceResult]) -> dict:
    """Compara resultados com ground truth."""
    metrics = {
        "intent_correct": 0,
        "primary_correct": 0,
        "any_correct": 0,
        "confidences": [],
        "times_ms": [],
        "details": [],
    }
    for r in results:
        gt = GROUND_TRUTH[r.frase]
        gt_book, gt_ch, gt_v = gt
        intent_ok = r.intent == "show_reference"
        primary_ok = False
        any_ok = False
        conf = 0.0
        if r.candidates:
            conf = r.candidates[0]["confidence"]
            # Verificar candidato primário
            c0 = r.candidates[0]
            if c0["book"] == gt_book and c0["chapter"] == gt_ch:
                if gt_v == 0 or c0["verse"] == 0 or c0["verse"] == gt_v:
                    primary_ok = True
            # Verificar qualquer candidato
            for c in r.candidates:
                if c["book"] == gt_book and c["chapter"] == gt_ch:
                    if gt_v == 0 or c["verse"] == 0 or c["verse"] == gt_v:
                        any_ok = True
                        break
        if intent_ok:
            metrics["intent_correct"] += 1
        if primary_ok:
            metrics["primary_correct"] += 1
        if any_ok:
            metrics["any_correct"] += 1
        if r.candidates:
            metrics["confidences"].append(conf)
        metrics["times_ms"].append(r.inference_ms)
        metrics["details"].append({
            "frase": r.frase,
            "intent": r.intent,
            "intent_ok": intent_ok,
            "primary": r.candidates[0] if r.candidates else None,
            "primary_ok": primary_ok,
            "any_ok": any_ok,
            "expected": f"{gt_book} {gt_ch}:{gt_v}" if gt_v else f"{gt_book} {gt_ch}",
            "inference_ms": r.inference_ms,
        })
    n = len(results)
    metrics["n"] = n
    metrics["intent_rate"] = metrics["intent_correct"] / n if n else 0
    metrics["primary_rate"] = metrics["primary_correct"] / n if n else 0
    metrics["any_rate"] = metrics["any_correct"] / n if n else 0
    metrics["avg_confidence"] = sum(metrics["confidences"]) / len(metrics["confidences"]) if metrics["confidences"] else 0
    metrics["avg_time_ms"] = sum(metrics["times_ms"]) / len(metrics["times_ms"]) if metrics["times_ms"] else 0
    return metrics


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    logger.info("=" * 70)
    logger.info("Sprint 21.6 — Validação Final da Inferência Semântica")
    logger.info("Engenharia de Prompt")
    logger.info("=" * 70)
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Modelo: qwen3:8b-q4_K_M (Ollama local)")
    logger.info("Frases: %d", len(FRASES))
    logger.info("Experimentos: 4")
    logger.info("")

    # Backend
    base_url_native = normalize_base_url_for_backend("ollama", "http://localhost:11434/v1")
    backend = create_backend(
        provider="ollama",
        base_url=base_url_native,
        model="qwen3:8b-q4_K_M",
        api_key="ollama",
    )

    # Warmup
    logger.info(">> Warmup do modelo...")
    try:
        warm_payload = {
            "model": "qwen3:8b-q4_K_M",
            "messages": [
                {"role": "system", "content": "Responda apenas com JSON."},
                {"role": "user", "content": "Diga {\"ok\":true}"},
            ],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 50},
            "think": False,
        }
        t0 = time.monotonic()
        backend.send_request(warm_payload, 120.0)
        logger.info("   Warmup OK em %.1fs", time.monotonic() - t0)
    except Exception as e:
        logger.info("   Warmup falhou: %s", e)
    logger.info("")

    # Configuração comum
    common = dict(
        backend=backend,
        model="qwen3:8b-q4_K_M",
        temperature=0.1,
        top_p=0.9,
        max_tokens=300,
        disable_thinking=True,
        timeout_s=120.0,
    )

    # Experimento 1 — Baseline
    results1 = run_experiment(
        "1 — Baseline (implementação atual)",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_fn=build_user_prompt_baseline,
        **common,
    )

    # Experimento 2 — Sem recent_text
    results2 = run_experiment(
        "2 — Sem recent_text",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_fn=build_user_prompt_no_recent,
        **common,
    )

    # Experimento 3 — recent_text como contexto secundário
    results3 = run_experiment(
        "3 — recent_text como contexto secundário",
        system_prompt=SYSTEM_PROMPT_SECUNDARIO,
        user_prompt_fn=build_user_prompt_baseline,
        **common,
    )

    # Experimento 4 — Ordem invertida
    results4 = run_experiment(
        "4 — Ordem invertida (Texto atual antes de Fala recente)",
        system_prompt=_SYSTEM_PROMPT,
        user_prompt_fn=build_user_prompt_inverted,
        **common,
    )

    # -----------------------------------------------------------------
    # Avaliação
    # -----------------------------------------------------------------
    metrics1 = evaluate(results1)
    metrics2 = evaluate(results2)
    metrics3 = evaluate(results3)
    metrics4 = evaluate(results4)

    # -----------------------------------------------------------------
    # Relatório final
    # -----------------------------------------------------------------
    logger.info("")
    logger.info("")
    logger.info("=" * 70)
    logger.info("RELATÓRIO FINAL — Sprint 21.6")
    logger.info("=" * 70)

    logger.info("")
    logger.info("1. TABELA COMPARATIVA")
    logger.info("-" * 70)
    logger.info("Experimento                | Intent | Candidato Principal | Qualquer Candidato | Conf Média | Tempo Médio")
    logger.info("---------------------------|--------|---------------------|--------------------|----------- |------------")
    for name, m in [
        ("1. Baseline", metrics1),
        ("2. Sem recent_text", metrics2),
        ("3. recent_text secundário", metrics3),
        ("4. Ordem invertida", metrics4),
    ]:
        logger.info("%-26s | %d/%d (%.0f%%) | %d/%d (%.0f%%)           | %d/%d (%.0f%%)          | %.2f       | %.0fms",
                    name,
                    m["intent_correct"], m["n"], m["intent_rate"] * 100,
                    m["primary_correct"], m["n"], m["primary_rate"] * 100,
                    m["any_correct"], m["n"], m["any_rate"] * 100,
                    m["avg_confidence"], m["avg_time_ms"])

    logger.info("")
    logger.info("2. DETALHES POR FRASE E EXPERIMENTO")
    logger.info("-" * 70)
    for i, frase in enumerate(FRASES):
        gt = GROUND_TRUTH[frase]
        expected = f"{gt[0]} {gt[1]}:{gt[2]}" if gt[2] else f"{gt[0]} {gt[1]}"
        logger.info("")
        logger.info("Frase: %r (esperado: %s)", frase, expected)
        for exp_name, results in [
            ("Baseline", results1),
            ("Sem recent", results2),
            ("Secundário", results3),
            ("Invertido", results4),
        ]:
            r = results[i]
            c0 = r.candidates[0] if r.candidates else None
            c0_str = f"{c0['book']} {c0['chapter']}:{c0['verse']} ({c0['confidence']:.2f})" if c0 else "—"
            logger.info("  %-12s | intent=%s | primário=%s | %dms",
                        exp_name, r.intent, c0_str, r.inference_ms)

    logger.info("")
    logger.info("3. MÉTRICAS DETALHADAS")
    logger.info("-" * 70)
    for name, m in [
        ("1. Baseline", metrics1),
        ("2. Sem recent_text", metrics2),
        ("3. recent_text secundário", metrics3),
        ("4. Ordem invertida", metrics4),
    ]:
        logger.info("")
        logger.info("  %s:", name)
        logger.info("    Intent correto: %d/%d (%.1f%%)", m["intent_correct"], m["n"], m["intent_rate"] * 100)
        logger.info("    Candidato principal correto: %d/%d (%.1f%%)", m["primary_correct"], m["n"], m["primary_rate"] * 100)
        logger.info("    Candidato correto em qualquer posição: %d/%d (%.1f%%)", m["any_correct"], m["n"], m["any_rate"] * 100)
        logger.info("    Confiança média do candidato primário: %.2f", m["avg_confidence"])
        logger.info("    Tempo médio de inferência: %.0fms", m["avg_time_ms"])
        for d in m["details"]:
            prim = f"{d['primary']['book']} {d['primary']['chapter']}:{d['primary']['verse']}" if d["primary"] else "—"
            logger.info("      %r → intent=%s prim=%s ok_prim=%s ok_any=%s (esperado=%s) %dms",
                        d["frase"][:40], d["intent"], prim, d["primary_ok"], d["any_ok"],
                        d["expected"], d["inference_ms"])

    _fh.flush()
    _fh.close()
    print(f"Concluído. Saída em: {_LOG_FILE}")


if __name__ == "__main__":
    main()
