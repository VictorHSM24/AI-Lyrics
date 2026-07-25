"""Sprint 21.7 — Validação Estatística da Inferência Bíblica.

Executa o corpus de 100 frases em dois experimentos:
  A — Baseline (prompt atual com recent_text)
  B — Sem recent_text

Mais teste separado de 5 frases dependentes de contexto.

Uso:
    python _diag_sprint21_7.py
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from _diag_sprint21_7_corpus import CORPUS, CORPUS_CONTEXTUAL

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_7_output.txt"
_SUMMARY_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_7_summary.txt"
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

from semantic.local_provider import _SYSTEM_PROMPT
from semantic.backend_factory import create_backend, normalize_base_url_for_backend
from semantic.types import SemanticContext
from semantic.thinking_sanitizer import ThinkingSanitizer


# ---------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------
def build_user_prompt_baseline(ctx: SemanticContext) -> str:
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


# ---------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------
def parse_response(content: str) -> tuple[dict | None, str | None]:
    sanitizer = ThinkingSanitizer()
    sanitize_result = sanitizer.sanitize(content)
    cleaned = sanitize_result.content
    text = cleaned.strip()
    try:
        data = json.loads(text)
        return _validate(data), None
    except json.JSONDecodeError:
        pass
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.rfind("```")
        if end > start:
            try:
                data = json.loads(text[start:end].strip())
                return _validate(data), None
            except json.JSONDecodeError as e:
                return None, f"JSON decode error em bloco markdown: {e}"
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
    intent = data.get("intent", "none")
    if intent not in ("show_reference", "none"):
        intent = "none"
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
# Inferência
# ---------------------------------------------------------------------
def call_ollama(backend, system_prompt, user_prompt, model, temperature,
                top_p, max_tokens, disable_thinking, timeout_s):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature, "top_p": top_p, "num_predict": max_tokens},
    }
    if disable_thinking:
        payload["think"] = False
    t0 = time.monotonic()
    resp = backend.send_request(payload, timeout_s)
    http_ms = (time.monotonic() - t0) * 1000.0
    return resp.content, http_ms


# ---------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------
def is_correct(cand: dict, gt_book: str, gt_ch: int, gt_v: int) -> bool:
    if cand["book"] != gt_book:
        return False
    if cand["chapter"] != gt_ch:
        return False
    if gt_v == 0 or cand["verse"] == 0:
        return True  # capítulo inteiro ou verso não especificado
    return cand["verse"] == gt_v


def evaluate_one(intent, candidates, gt_book, gt_ch, gt_v):
    intent_ok = intent == "show_reference"
    primary_ok = False
    any_ok = False
    conf = 0.0
    if candidates:
        conf = candidates[0]["confidence"]
        primary_ok = is_correct(candidates[0], gt_book, gt_ch, gt_v)
        for c in candidates:
            if is_correct(c, gt_book, gt_ch, gt_v):
                any_ok = True
                break
    return intent_ok, primary_ok, any_ok, conf


# ---------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------
def run_experiment(name, system_prompt, user_prompt_fn, backend, model,
                   corpus, with_recent=True, log_details=True):
    results = []
    logger.info("")
    logger.info("█" * 70)
    logger.info("█ EXPERIMENTO: %s", name)
    logger.info("█ Casos: %d", len(corpus))
    logger.info("█" * 70)

    for i, entry in enumerate(corpus):
        if len(entry) == 7:
            cat, diff, frase, gt_book, gt_ch, gt_v, recent_override = entry
        else:
            cat, diff, frase, gt_book, gt_ch, gt_v = entry
            recent_override = None

        # Definir recent_text
        if recent_override is not None:
            recent_text = recent_override
        elif with_recent and i > 0:
            # Usar a frase anterior como recent_text (simula streaming)
            prev_entry = corpus[i - 1]
            recent_text = prev_entry[2] if len(prev_entry) >= 3 else ""
        else:
            recent_text = ""

        ctx = SemanticContext(current_text=frase, recent_text=recent_text, session_id="diag")
        user_prompt = user_prompt_fn(ctx)

        if log_details and i < 3:  # Log detalhado só dos 3 primeiros
            logger.info("")
            logger.info("Caso %d: %r (cat=%s, diff=%s)", i + 1, frase[:60], cat, diff)
            logger.info("  recent_text: %r", recent_text[:60] if recent_text else "")
            logger.info("  user_prompt:")
            for line in user_prompt.splitlines():
                logger.info("    %s", line)
        elif i % 10 == 0:
            logger.info("  Caso %d/%d...", i + 1, len(corpus))

        try:
            raw, http_ms = call_ollama(
                backend, system_prompt, user_prompt, model,
                0.1, 0.9, 300, True, 120.0,
            )
        except Exception as e:
            logger.info("  ✗ Caso %d ERRO: %s", i + 1, e)
            results.append({
                "idx": i, "cat": cat, "diff": diff, "frase": frase,
                "gt": (gt_book, gt_ch, gt_v), "recent": recent_text,
                "intent": "none", "candidates": [], "primary_ok": False,
                "any_ok": False, "intent_ok": False, "conf": 0.0,
                "ms": 0, "error": str(e),
            })
            continue

        parsed, _ = parse_response(raw)
        if parsed is None:
            intent, candidates = "none", []
        else:
            intent, candidates = parsed["intent"], parsed["candidates"]

        intent_ok, primary_ok, any_ok, conf = evaluate_one(
            intent, candidates, gt_book, gt_ch, gt_v)

        if log_details and i < 3:
            logger.info("  Resposta RAW: %s", raw[:200] if isinstance(raw, str) else str(raw)[:200])
            logger.info("  intent=%s candidates=%d primary_ok=%s any_ok=%s",
                        intent, len(candidates), primary_ok, any_ok)

        results.append({
            "idx": i, "cat": cat, "diff": diff, "frase": frase,
            "gt": (gt_book, gt_ch, gt_v), "recent": recent_text,
            "intent": intent, "candidates": candidates,
            "primary_ok": primary_ok, "any_ok": any_ok, "intent_ok": intent_ok,
            "conf": conf, "ms": int(http_ms), "error": None,
        })

    return results


# ---------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------
def compute_metrics(results):
    n = len(results)
    if n == 0:
        return {}
    intent_ok = sum(1 for r in results if r["intent_ok"])
    primary_ok = sum(1 for r in results if r["primary_ok"])
    any_ok = sum(1 for r in results if r["any_ok"])
    confs = [r["conf"] for r in results if r["candidates"]]
    times = [r["ms"] for r in results if r["ms"] > 0]
    return {
        "n": n,
        "intent": intent_ok,
        "intent_rate": intent_ok / n,
        "primary": primary_ok,
        "primary_rate": primary_ok / n,
        "any": any_ok,
        "any_rate": any_ok / n,
        "avg_conf": sum(confs) / len(confs) if confs else 0,
        "avg_time": sum(times) / len(times) if times else 0,
    }


def by_category(results):
    cats = {}
    for r in results:
        c = r["cat"]
        if c not in cats:
            cats[c] = []
        cats[c].append(r)
    return {c: compute_metrics(rs) for c, rs in cats.items()}


def by_difficulty(results):
    diffs = {}
    for r in results:
        d = r["diff"]
        if d not in diffs:
            diffs[d] = []
        diffs[d].append(r)
    return {d: compute_metrics(rs) for d, rs in diffs.items()}


def find_regressions(results_a, results_b):
    """Casos onde A acertou e B errou."""
    regressions = []
    improvements = []
    for a, b in zip(results_a, results_b):
        if a["primary_ok"] and not b["primary_ok"]:
            regressions.append((a, b))
        elif not a["primary_ok"] and b["primary_ok"]:
            improvements.append((a, b))
    return regressions, improvements


def main():
    logger.info("=" * 70)
    logger.info("Sprint 21.7 — Validação Estatística da Inferência Bíblica")
    logger.info("=" * 70)
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Modelo: qwen3:8b-q4_K_M")
    logger.info("Corpus: %d frases + %d contextuais", len(CORPUS), len(CORPUS_CONTEXTUAL))

    base_url_native = normalize_base_url_for_backend("ollama", "http://localhost:11434/v1")
    backend = create_backend(
        provider="ollama", base_url=base_url_native,
        model="qwen3:8b-q4_K_M", api_key="ollama",
    )

    # Warmup
    logger.info(">> Warmup...")
    try:
        warm_payload = {
            "model": "qwen3:8b-q4_K_M",
            "messages": [
                {"role": "system", "content": "Responda apenas com JSON."},
                {"role": "user", "content": "Diga {\"ok\":true}"},
            ],
            "stream": False, "options": {"temperature": 0.1, "num_predict": 50},
            "think": False,
        }
        t0 = time.monotonic()
        backend.send_request(warm_payload, 120.0)
        logger.info("   Warmup OK em %.1fs", time.monotonic() - t0)
    except Exception as e:
        logger.info("   Warmup falhou: %s", e)

    # Experimento A — Baseline
    results_a = run_experiment(
        "A — Baseline (com recent_text)",
        _SYSTEM_PROMPT, build_user_prompt_baseline,
        backend, "qwen3:8b-q4_K_M", CORPUS, with_recent=True,
    )

    # Experimento B — Sem recent_text
    results_b = run_experiment(
        "B — Sem recent_text",
        _SYSTEM_PROMPT, build_user_prompt_no_recent,
        backend, "qwen3:8b-q4_K_M", CORPUS, with_recent=False,
    )

    # Teste contextual (separado)
    logger.info("")
    logger.info("█" * 70)
    logger.info("█ TESTE CONTEXTUAL (frases dependentes de contexto)")
    logger.info("█" * 70)
    # Para contextuais, o recent_text é ESSENCIAL para desambiguar.
    # Executar ambos os experimentos com o recent_text definido.
    corpus_ctx_a = [(f, r, b, c, v) for (f, r, b, c, v) in CORPUS_CONTEXTUAL]
    # Transformar em formato (cat, diff, frase, gt_book, gt_ch, gt_v, recent_override)
    corpus_ctx_full = []
    for frase, recent, gt_book, gt_ch, gt_v in CORPUS_CONTEXTUAL:
        corpus_ctx_full.append(("Contextual", "contexto", frase, gt_book, gt_ch, gt_v, recent))

    # A: com recent_text (baseline)
    results_ctx_a = run_experiment(
        "Contextual A — Baseline (com recent_text)",
        _SYSTEM_PROMPT, build_user_prompt_baseline,
        backend, "qwen3:8b-q4_K_M", corpus_ctx_full, with_recent=True, log_details=True,
    )
    # B: sem recent_text
    results_ctx_b = run_experiment(
        "Contextual B — Sem recent_text",
        _SYSTEM_PROMPT, build_user_prompt_no_recent,
        backend, "qwen3:8b-q4_K_M", corpus_ctx_full, with_recent=False, log_details=True,
    )

    # -----------------------------------------------------------------
    # Relatório
    # -----------------------------------------------------------------
    m_a = compute_metrics(results_a)
    m_b = compute_metrics(results_b)
    cat_a = by_category(results_a)
    cat_b = by_category(results_b)
    diff_a = by_difficulty(results_a)
    diff_b = by_difficulty(results_b)
    regressions, improvements = find_regressions(results_a, results_b)
    m_ctx_a = compute_metrics(results_ctx_a)
    m_ctx_b = compute_metrics(results_ctx_b)

    # Escrever relatório resumido em arquivo separado
    summary = []
    def w(s=""):
        summary.append(s)
        logger.info(s)

    w("")
    w("=" * 70)
    w("RELATÓRIO FINAL — Sprint 21.7")
    w("=" * 70)

    w("")
    w("1. MÉTRICAS GLOBAIS (100 frases)")
    w("-" * 70)
    w("Métrica                | Baseline (A)  | Sem recent (B) | Delta")
    w("-----------------------|---------------|----------------|------")
    w("Intent correto         | %d/%d (%.1f%%)   | %d/%d (%.1f%%)    | %+.1fpp" % (
        m_a["intent"], m_a["n"], m_a["intent_rate"] * 100,
        m_b["intent"], m_b["n"], m_b["intent_rate"] * 100,
        (m_b["intent_rate"] - m_a["intent_rate"]) * 100))
    w("Candidato primário     | %d/%d (%.1f%%)   | %d/%d (%.1f%%)    | %+.1fpp" % (
        m_a["primary"], m_a["n"], m_a["primary_rate"] * 100,
        m_b["primary"], m_b["n"], m_b["primary_rate"] * 100,
        (m_b["primary_rate"] - m_a["primary_rate"]) * 100))
    w("Candidato em qualquer  | %d/%d (%.1f%%)   | %d/%d (%.1f%%)    | %+.1fpp" % (
        m_a["any"], m_a["n"], m_a["any_rate"] * 100,
        m_b["any"], m_b["n"], m_b["any_rate"] * 100,
        (m_b["any_rate"] - m_a["any_rate"]) * 100))
    w("Confiança média        | %.2f           | %.2f            | %+.2f" % (
        m_a["avg_conf"], m_b["avg_conf"], m_b["avg_conf"] - m_a["avg_conf"]))
    w("Tempo médio (ms)       | %.0f            | %.0f             | %+.0f" % (
        m_a["avg_time"], m_b["avg_time"], m_b["avg_time"] - m_a["avg_time"]))

    w("")
    w("2. POR CATEGORIA")
    w("-" * 70)
    w("Categoria      | A primário | B primário | A qualquer | B qualquer | Δ primário")
    w("---------------|------------|------------|------------|------------|-----------")
    all_cats = sorted(set(list(cat_a.keys()) + list(cat_b.keys())))
    for c in all_cats:
        ca = cat_a.get(c, {})
        cb = cat_b.get(c, {})
        ca_p = ca.get("primary_rate", 0) * 100
        cb_p = cb.get("primary_rate", 0) * 100
        ca_a = ca.get("any_rate", 0) * 100
        cb_a = cb.get("any_rate", 0) * 100
        ca_n = ca.get("n", 0)
        cb_n = cb.get("n", 0)
        w("%-14s | %d/%d (%.0f%%)  | %d/%d (%.0f%%)   | %.0f%%        | %.0f%%        | %+.0fpp" % (
            c, ca.get("primary", 0), ca_n, ca_p,
            cb.get("primary", 0), cb_n, cb_p,
            ca_a, cb_a, cb_p - ca_p))

    w("")
    w("3. POR DIFICULDADE")
    w("-" * 70)
    w("Dificuldade | A primário | B primário | A qualquer | B qualquer | Δ primário")
    w("------------|------------|------------|------------|------------|-----------")
    for d in ["facil", "media", "dificil"]:
        da = diff_a.get(d, {})
        db = diff_b.get(d, {})
        da_p = da.get("primary_rate", 0) * 100
        db_p = db.get("primary_rate", 0) * 100
        da_a = da.get("any_rate", 0) * 100
        db_a = db.get("any_rate", 0) * 100
        da_n = da.get("n", 0)
        db_n = db.get("n", 0)
        w("%-11s | %d/%d (%.0f%%)  | %d/%d (%.0f%%)   | %.0f%%        | %.0f%%        | %+.0fpp" % (
            d, da.get("primary", 0), da_n, da_p,
            db.get("primary", 0), db_n, db_p,
            da_a, db_a, db_p - da_p))

    w("")
    w("4. REGRESSÕES (A acertou, B errou) — %d casos" % len(regressions))
    w("-" * 70)
    for a, b in regressions:
        gt = a["gt"]
        gt_str = f"{gt[0]} {gt[1]}:{gt[2]}" if gt[2] else f"{gt[0]} {gt[1]}"
        b_prim = b["candidates"][0] if b["candidates"] else None
        b_str = f"{b_prim['book']} {b_prim['chapter']}:{b_prim['verse']}" if b_prim else "none"
        w("  %r (cat=%s, esperado=%s)" % (a["frase"][:50], a["cat"], gt_str))
        w("    A acertou primário | B retornou: %s (intent=%s)" % (b_str, b["intent"]))

    w("")
    w("5. MELHORIAS (A errou, B acertou) — %d casos" % len(improvements))
    w("-" * 70)
    for a, b in improvements:
        gt = a["gt"]
        gt_str = f"{gt[0]} {gt[1]}:{gt[2]}" if gt[2] else f"{gt[0]} {gt[1]}"
        a_prim = a["candidates"][0] if a["candidates"] else None
        a_str = f"{a_prim['book']} {a_prim['chapter']}:{a_prim['verse']}" if a_prim else "none"
        w("  %r (cat=%s, esperado=%s)" % (a["frase"][:50], a["cat"], gt_str))
        w("    A retornou: %s | B acertou primário" % a_str)

    w("")
    w("6. TESTE CONTEXTUAL (5 frases dependentes de contexto)")
    w("-" * 70)
    w("Métrica                | Com recent (A) | Sem recent (B) | Delta")
    w("-----------------------|----------------|----------------|------")
    w("Intent correto         | %d/%d (%.1f%%)     | %d/%d (%.1f%%)     | %+.1fpp" % (
        m_ctx_a["intent"], m_ctx_a["n"], m_ctx_a["intent_rate"] * 100,
        m_ctx_b["intent"], m_ctx_b["n"], m_ctx_b["intent_rate"] * 100,
        (m_ctx_b["intent_rate"] - m_ctx_a["intent_rate"]) * 100))
    w("Candidato primário     | %d/%d (%.1f%%)     | %d/%d (%.1f%%)     | %+.1fpp" % (
        m_ctx_a["primary"], m_ctx_a["n"], m_ctx_a["primary_rate"] * 100,
        m_ctx_b["primary"], m_ctx_b["n"], m_ctx_b["primary_rate"] * 100,
        (m_ctx_b["primary_rate"] - m_ctx_a["primary_rate"]) * 100))
    w("Candidato em qualquer  | %d/%d (%.1f%%)     | %d/%d (%.1f%%)     | %+.1fpp" % (
        m_ctx_a["any"], m_ctx_a["n"], m_ctx_a["any_rate"] * 100,
        m_ctx_b["any"], m_ctx_b["n"], m_ctx_b["any_rate"] * 100,
        (m_ctx_b["any_rate"] - m_ctx_a["any_rate"]) * 100))

    w("")
    w("Detalhes contextuais:")
    for a, b in zip(results_ctx_a, results_ctx_b):
        gt = a["gt"]
        gt_str = f"{gt[0]} {gt[1]}:{gt[2]}" if gt[2] else f"{gt[0]} {gt[1]}"
        a_prim = a["candidates"][0] if a["candidates"] else None
        b_prim = b["candidates"][0] if b["candidates"] else None
        a_str = f"{a_prim['book']} {a_prim['chapter']}:{a_prim['verse']}" if a_prim else "none"
        b_str = f"{b_prim['book']} {b_prim['chapter']}:{b_prim['verse']}" if b_prim else "none"
        w("  Frase: %r" % a["frase"])
        w("    recent_text: %r" % a["recent"][:50])
        w("    esperado: %s" % gt_str)
        w("    A (com recent): %s (intent=%s, ok=%s)" % (a_str, a["intent"], a["primary_ok"]))
        w("    B (sem recent):  %s (intent=%s, ok=%s)" % (b_str, b["intent"], b["primary_ok"]))

    w("")
    w("7. CONCLUSÃO")
    w("-" * 70)
    delta_primary = (m_b["primary_rate"] - m_a["primary_rate"]) * 100
    if delta_primary > 10:
        w("A remoção do recent_text melhora significativamente a acurácia (%+.1fpp no candidato primário)." % delta_primary)
    elif delta_primary > 0:
        w("A remoção do recent_text melhora marginalmente a acurácia (%+.1fpp)." % delta_primary)
    elif delta_primary < -10:
        w("A remoção do recent_text PIORA significativamente a acurácia (%+.1fpp)." % delta_primary)
    else:
        w("A remoção do recent_text não tem efeito significativo (%+.1fpp)." % delta_primary)

    if len(regressions) == 0:
        w("Nenhuma regressão detectada — nenhum caso que o Baseline acertou e o novo prompt errou.")
    else:
        w("Regressões detectadas: %d caso(s) — ver seção 4." % len(regressions))

    w("")
    if delta_primary > 10 and len(regressions) <= 2:
        w("Recomendação: REMOVER recent_text como comportamento padrão.")
    elif delta_primary > 0 and len(regressions) <= 5:
        w("Recomendação: REMOVER recent_text, com monitoramento de regressões.")
    elif delta_primary > 0 and len(regressions) > 5:
        w("Recomendação: AVALIAR caso a caso — ganho marginal com muitas regressões.")
    else:
        w("Recomendação: MANTER recent_text — remoção não traz benefício claro.")

    # Escrever sumário em arquivo separado
    with open(_SUMMARY_FILE, "w", encoding="utf-8") as sf:
        sf.write("\n".join(summary))

    _fh.flush()
    _fh.close()
    print(f"Concluído. Logs em: {_LOG_FILE}")
    print(f"Resumo em: {_SUMMARY_FILE}")


if __name__ == "__main__":
    main()
