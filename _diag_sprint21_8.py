"""Sprint 21.8 — Classificação de Dependência de Contexto.

Implementa 4 estratégias de classificação (A: heurística simples,
B: heurística linguística, C: LLM, D: híbrida) e avalia em 200 frases.

Uso:
    python _diag_sprint21_8.py
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from _diag_sprint21_8_corpus import CORPUS, AMBIGUOUS

_LOG_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_8_output.txt"
_SUMMARY_FILE = r"C:\Users\USER\Documents\AI Lyrics\_diag_sprint21_8_summary.txt"
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

from semantic.backend_factory import create_backend, normalize_base_url_for_backend
from semantic.thinking_sanitizer import ThinkingSanitizer


# ---------------------------------------------------------------------
# Estratégia A — Heurística simples
# ---------------------------------------------------------------------
# Palavras que indicam dependência de contexto
_CONTEXT_WORDS = {
    "anterior", "anteriores", "anteriormente", "antes", "posterior", "posteriormente",
    "mesmo", "mesma", "mesmos", "mesmas",
    "esse", "essa", "esses", "essas", "aquele", "aquela", "aqueles", "aquelas",
    "isso", "aquilo", "ali", "lá", "aqui",
    "capítulo", "versículo", "passagem", "texto", "salmo", "livro",
    "novamente", "outra", "outro", "de novo", "mais uma vez",
    "como vimos", "como lemos", "como falamos", "como dissemos",
    "como estudamos", "como mencionamos", "como acabamos",
    "voltando", "retornando",
}

# Palavras que indicam referência completa
_COMPLETE_WORDS = {
    "senhor", "deus", "jesus", "cristo", "paulo", "pedro", "joão", "davi",
    "moisés", "isaías", "pastor", "armadura", "graça", "fé", "amor",
    "luz", "salvação", "esperança", "paz", "verdade", "vida",
    "criou", "amou", "fortalece", "guarda", "confia",
}


def strategy_a_simple(text: str) -> tuple[str, float]:
    """Heurística simples baseada em palavras-chave e tamanho."""
    text_lower = text.lower().strip()
    words = text_lower.split()
    n_words = len(words)

    # Verificar palavras contextuais
    context_hits = 0
    for w in _CONTEXT_WORDS:
        if w in text_lower:
            context_hits += 1

    # Verificar palavras de referência completa
    complete_hits = 0
    for w in _COMPLETE_WORDS:
        if w in text_lower:
            complete_hits += 1

    # Regras:
    # 1. Frases muito curtas (< 3 palavras) sem palavras completas → CONTEXT_DEPENDENT
    # 2. Presença de palavras contextuais > palavras completas → CONTEXT_DEPENDENT
    # 3. Caso contrário → COMPLETE_REFERENCE
    if n_words <= 2 and complete_hits == 0:
        return "CONTEXT_DEPENDENT", 0.8
    if context_hits > 0 and context_hits >= complete_hits:
        return "CONTEXT_DEPENDENT", 0.7
    if complete_hits > 0 and complete_hits > context_hits:
        return "COMPLETE_REFERENCE", 0.7
    if n_words >= 5:
        return "COMPLETE_REFERENCE", 0.6
    return "CONTEXT_DEPENDENT", 0.5


# ---------------------------------------------------------------------
# Estratégia B — Heurística linguística
# ---------------------------------------------------------------------
# Pronomes demonstrativos: este, esse, aquele, isto, isso, aquilo
_DEMONSTRATIVE_RE = re.compile(
    r"\b(este|esta|estes|estas|esse|essa|esses|essas|aquele|aquela|aqueles|aquelas|isto|isso|aquilo)\b",
    re.IGNORECASE,
)
# Artigos definidos + substantivos abstratos sem contexto
_ARTICLE_ONLY_RE = re.compile(r"^(o|a|os|as)\s+\w{2,}$", re.IGNORECASE)
# Elipses: frase começa com "como", "voltando", "retornando"
_ELLIPSIS_RE = re.compile(
    r"^(como|voltando|retornando|conforme|segundo|igualmente|também|outro|outra|novamente)\b",
    re.IGNORECASE,
)
# Referência anafórica: "aquele versículo", "esse texto", "a mesma passagem"
_ANAPHORA_RE = re.compile(
    r"\b(esse|essa|aquele|aquela|o|a)\s+(mesmo|mesma|versículo|capítulo|passagem|texto|salmo|livro|parte|ponto)\b",
    re.IGNORECASE,
)
# Expressões temporais contextuais
_TEMPORAL_RE = re.compile(
    r"\b(anterior|anteriormente|antes|posterior|início|final|começo|fim|meio|frente|adiante)\b",
    re.IGNORECASE,
)
# Verbos de referência retrospectiva
_RETROSPECTIVE_RE = re.compile(
    r"\b(vimos|lemos|falamos|dissemos|estudamos|mencionamos|acabamos|explicamos|vimos)\b",
    re.IGNORECASE,
)
# Nomes próprios e termos bíblicos que indicam completude
_BIBLICAL_TERMS_RE = re.compile(
    r"\b(senhor|deus|jesus|cristo|paulo|pedro|joão|davi|moisés|isaías|abraão|jacob|espirito|graça|fé|amor|paz|salvação|esperança|verdade|vida|luz|pastor|armadura|cruz|sangue|perdão|reino|céu|terra|criou|amou|fortalece|guarda|confia|entrega|revesti|buscai|vinde|ama|honra|temerás)\b",
    re.IGNORECASE,
)
# Referências explícitas (livro capítulo:versículo)
_EXPLICIT_REF_RE = re.compile(
    r"\b(gênesis|êxodo|levítico|números|deuteronômio|josué|juízes|rute|samuel|reis|crônicas|esdras|neemias|ester|jó|salmos|salmo|provérbios|eclesiastes|cantares|isaías|jeremias|lamentações|ezequiel|daniel|oséias|joel|amós|obadias|jonas|miquéias|naum|habacuque|sofonias|ageu|zacarias|malaquias|mateus|marcos|lucas|joão|atos|romanos|coríntios|gálatas|efésios|filipenses|colossenses|tessalonicenses|timóteo|tito|filemom|hebreus|tiago|pedro|joão|judas|apocalipse)\s+\d+",
    re.IGNORECASE,
)


def strategy_b_linguistic(text: str) -> tuple[str, float]:
    """Heurística linguística baseada em pronomes, elipses e anáforas."""
    text_lower = text.lower().strip()
    words = text_lower.split()
    n_words = len(words)

    # Pontuação: cada feature contribui com um score
    context_score = 0.0
    complete_score = 0.0

    # Demonstrativos → contexto
    if _DEMONSTRATIVE_RE.search(text_lower):
        context_score += 2.0
    # Anáfora → contexto
    if _ANAPHORA_RE.search(text_lower):
        context_score += 3.0
    # Elipse → contexto
    if _ELLIPSIS_RE.search(text_lower):
        context_score += 2.0
    # Temporal → contexto
    if _TEMPORAL_RE.search(text_lower):
        context_score += 2.0
    # Retrospectivo → contexto
    if _RETROSPECTIVE_RE.search(text_lower):
        context_score += 3.0
    # Frase muito curta → contexto
    if n_words <= 2:
        context_score += 1.5
    elif n_words <= 4:
        context_score += 0.5

    # Referência explícita → completo
    if _EXPLICIT_REF_RE.search(text_lower):
        complete_score += 5.0
    # Termos bíblicos → completo
    biblical_matches = _BIBLICAL_TERMS_RE.findall(text_lower)
    complete_score += len(biblical_matches) * 1.0
    # Frase longa → completo
    if n_words >= 6:
        complete_score += 1.0
    # Verbo de ação imperativa → completo
    if re.search(r"\b(buscai|vinde|guarda|confia|entrega|revesti|ama|honra|sede|não)\b", text_lower):
        complete_score += 1.0

    # Decisão
    if context_score > complete_score:
        return "CONTEXT_DEPENDENT", min(0.95, 0.5 + (context_score - complete_score) * 0.1)
    elif complete_score > context_score:
        return "COMPLETE_REFERENCE", min(0.95, 0.5 + (complete_score - context_score) * 0.1)
    else:
        # Empate: se tem palavras bíblicas, completo; senão, contexto
        if biblical_matches:
            return "COMPLETE_REFERENCE", 0.55
        return "CONTEXT_DEPENDENT", 0.55


# ---------------------------------------------------------------------
# Estratégia C — LLM
# ---------------------------------------------------------------------
_LLM_SYSTEM_PROMPT = """Você é um classificador de dependência de contexto.

Sua tarefa: determinar se uma frase falada por um pregador possui informação suficiente para identificar uma referência bíblica SEM conhecer a conversa anterior.

Classes:
- COMPLETE_REFERENCE: a frase tem conteúdo suficiente para identificar uma referência bíblica. Contém palavras de conteúdo (nomes divinos, conceitos bíblicos, verbos, referências explícitas como "João 3:16").
- CONTEXT_DEPENDENT: a frase NÃO tem conteúdo suficiente. Depende da fala anterior. Contém pronomes demonstrativos ("esse", "aquele", "isso"), referências anafóricas ("o mesmo versículo", "como vimos"), elipses, ou é muito curta sem conteúdo bíblico.

REGRAS:
1. Responda APENAS com uma das duas classes: COMPLETE_REFERENCE ou CONTEXT_DEPENDENT.
2. Nenhum texto adicional. Nenhuma explicação. Apenas o nome da classe.
3. Frases como "O Senhor é meu pastor" → COMPLETE_REFERENCE (tem conteúdo bíblico).
4. Frases como "Como vimos anteriormente" → CONTEXT_DEPENDENT (depende do contexto).
5. Frases como "Esse versículo" → CONTEXT_DEPENDENT (pronome demonstrativo + "versículo").
6. Frases como "O bom pastor" → COMPLETE_REFERENCE (metáfora bíblica conhecida).
7. Referências explícitas como "João 3:16" → COMPLETE_REFERENCE."""


def call_llm_classifier(backend, model: str, text: str, timeout_s: float = 60.0) -> tuple[str, float, float]:
    """Chama o LLM para classificar a frase. Retorna (classe, confiança, ms)."""
    user_prompt = f"Frase: {text}\n\nClasse:"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "top_p": 0.9, "num_predict": 20},
        "think": False,
    }
    t0 = time.monotonic()
    try:
        resp = backend.send_request(payload, timeout_s)
        ms = (time.monotonic() - t0) * 1000.0
        content = resp.content.strip().upper()
        # Parse: aceitar variações
        if "COMPLETE" in content and "CONTEXT" not in content:
            return "COMPLETE_REFERENCE", 0.9, ms
        elif "CONTEXT" in content and "COMPLETE" not in content:
            return "CONTEXT_DEPENDENT", 0.9, ms
        elif "COMPLETE" in content:
            return "COMPLETE_REFERENCE", 0.7, ms
        elif "CONTEXT" in content:
            return "CONTEXT_DEPENDENT", 0.7, ms
        else:
            # Não conseguiu classificar
            return "UNKNOWN", 0.0, ms
    except Exception as e:
        ms = (time.monotonic() - t0) * 1000.0
        return "ERROR", 0.0, ms


# ---------------------------------------------------------------------
# Estratégia D — Híbrida
# ---------------------------------------------------------------------
def strategy_d_hybrid(text: str, backend=None, model: str = "", use_llm: bool = True) -> tuple[str, float, float]:
    """Combina heurística linguística (B) com LLM (C).

    Estratégia:
    1. Executa heurística B.
    2. Se confiança >= 0.8, usa o resultado de B.
    3. Caso contrário, consulta o LLM (C).
    4. Se LLM e B concordam, usa a classe com confiança combinada.
    5. Se discordam, usa o resultado do LLM (mais confiável para casos ambíguos).
    """
    b_class, b_conf = strategy_b_linguistic(text)

    # Se B está muito confiante, usar B
    if b_conf >= 0.8:
        return b_class, b_conf, 0.0

    # Caso contrário, consultar LLM
    if use_llm and backend is not None:
        c_class, c_conf, c_ms = call_llm_classifier(backend, model, text)
        if c_class in ("ERROR", "UNKNOWN"):
            # LLM falhou, usar B
            return b_class, b_conf, c_ms
        # Se concordam, confiança combinada
        if c_class == b_class:
            return c_class, min(0.98, (b_conf + c_conf) / 2 + 0.1), c_ms
        else:
            # Discordam: usar LLM
            return c_class, c_conf, c_ms
    else:
        return b_class, b_conf, 0.0


# ---------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------
def evaluate(predictions: list[tuple[str, str, float, float]], expected: list[str]) -> dict:
    """Calcula métricas de classificação.
    predictions: lista de (predicted_class, _, confidence, time_ms)
    expected: lista de classes esperadas
    """
    n = len(expected)
    tp = fp = fn = tn = 0  # positive = CONTEXT_DEPENDENT
    errors = []
    for i, (pred, _, conf, ms) in enumerate(predictions):
        exp = expected[i]
        if pred == "CONTEXT_DEPENDENT" and exp == "CONTEXT_DEPENDENT":
            tp += 1
        elif pred == "CONTEXT_DEPENDENT" and exp == "COMPLETE_REFERENCE":
            fp += 1
            errors.append(("FP", i, pred, exp, conf))
        elif pred == "COMPLETE_REFERENCE" and exp == "CONTEXT_DEPENDENT":
            fn += 1
            errors.append(("FN", i, pred, exp, conf))
        else:
            tn += 1

    accuracy = (tp + tn) / n if n else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0
    times = [p[3] for p in predictions if p[3] > 0]
    avg_time = sum(times) / len(times) if times else 0
    return {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": accuracy, "precision": precision, "recall": recall, "f1": f1,
        "avg_time_ms": avg_time,
        "errors": errors,
    }


# ---------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------
def main():
    logger.info("=" * 70)
    logger.info("Sprint 21.8 — Classificação de Dependência de Contexto")
    logger.info("=" * 70)
    logger.info("Data: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("Corpus: %d frases", len(CORPUS))

    # Backend
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
                {"role": "system", "content": "Responda apenas com uma palavra."},
                {"role": "user", "content": "Diga OK"},
            ],
            "stream": False, "options": {"temperature": 0.0, "num_predict": 10},
            "think": False,
        }
        t0 = time.monotonic()
        backend.send_request(warm_payload, 120.0)
        logger.info("   Warmup OK em %.1fs", time.monotonic() - t0)
    except Exception as e:
        logger.info("   Warmup falhou: %s", e)

    # Preparar dados
    texts = [t for (_, t) in CORPUS]
    expected = [c for (c, _) in CORPUS]

    # -----------------------------------------------------------------
    # Estratégia A — Heurística simples
    # -----------------------------------------------------------------
    logger.info("")
    logger.info("Executando Estratégia A — Heurística simples...")
    preds_a = []
    for i, text in enumerate(texts):
        cls, conf = strategy_a_simple(text)
        preds_a.append((cls, "", conf, 0.0))
    metrics_a = evaluate(preds_a, expected)
    logger.info("  A: accuracy=%.1f%% precision=%.1f%% recall=%.1f%% f1=%.1f%%",
                metrics_a["accuracy"] * 100, metrics_a["precision"] * 100,
                metrics_a["recall"] * 100, metrics_a["f1"] * 100)

    # -----------------------------------------------------------------
    # Estratégia B — Heurística linguística
    # -----------------------------------------------------------------
    logger.info("Executando Estratégia B — Heurística linguística...")
    preds_b = []
    for i, text in enumerate(texts):
        cls, conf = strategy_b_linguistic(text)
        preds_b.append((cls, "", conf, 0.0))
    metrics_b = evaluate(preds_b, expected)
    logger.info("  B: accuracy=%.1f%% precision=%.1f%% recall=%.1f%% f1=%.1f%%",
                metrics_b["accuracy"] * 100, metrics_b["precision"] * 100,
                metrics_b["recall"] * 100, metrics_b["f1"] * 100)

    # -----------------------------------------------------------------
    # Estratégia C — LLM
    # -----------------------------------------------------------------
    logger.info("Executando Estratégia C — LLM (200 chamadas, ~10min)...")
    preds_c = []
    for i, text in enumerate(texts):
        if i % 20 == 0:
            logger.info("  C: caso %d/%d...", i + 1, len(texts))
        cls, conf, ms = call_llm_classifier(backend, "qwen3:8b-q4_K_M", text)
        preds_c.append((cls, "", conf, ms))
    metrics_c = evaluate(preds_c, expected)
    logger.info("  C: accuracy=%.1f%% precision=%.1f%% recall=%.1f%% f1=%.1f%%",
                metrics_c["accuracy"] * 100, metrics_c["precision"] * 100,
                metrics_c["recall"] * 100, metrics_c["f1"] * 100)

    # -----------------------------------------------------------------
    # Estratégia D — Híbrida
    # -----------------------------------------------------------------
    logger.info("Executando Estratégia D — Híbrida (B + LLM para casos incertos)...")
    preds_d = []
    llm_calls_d = 0
    for i, text in enumerate(texts):
        if i % 20 == 0:
            logger.info("  D: caso %d/%d...", i + 1, len(texts))
        # Verificar se B está confiante
        b_class, b_conf = strategy_b_linguistic(text)
        if b_conf >= 0.8:
            preds_d.append((b_class, "", b_conf, 0.0))
        else:
            cls, conf, ms = call_llm_classifier(backend, "qwen3:8b-q4_K_M", text)
            preds_d.append((cls, "", conf, ms))
            llm_calls_d += 1
    metrics_d = evaluate(preds_d, expected)
    logger.info("  D: accuracy=%.1f%% precision=%.1f%% recall=%.1f%% f1=%.1f%% (LLM calls: %d/%d)",
                metrics_d["accuracy"] * 100, metrics_d["precision"] * 100,
                metrics_d["recall"] * 100, metrics_d["f1"] * 100, llm_calls_d, len(texts))

    # -----------------------------------------------------------------
    # Casos ambíguos
    # -----------------------------------------------------------------
    logger.info("")
    logger.info("Analisando casos ambíguos...")
    ambiguous_results = []
    for text in AMBIGUOUS:
        a_cls, a_conf = strategy_a_simple(text)
        b_cls, b_conf = strategy_b_linguistic(text)
        c_cls, c_conf, c_ms = call_llm_classifier(backend, "qwen3:8b-q4_K_M", text)
        d_cls, d_conf, _ = strategy_d_hybrid(text, backend, "qwen3:8b-q4_K_M")
        ambiguous_results.append({
            "text": text, "A": a_cls, "A_conf": a_conf,
            "B": b_cls, "B_conf": b_conf,
            "C": c_cls, "C_conf": c_conf,
            "D": d_cls, "D_conf": d_conf,
        })
        logger.info("  %r", text)
        logger.info("    A=%s(%.2f) B=%s(%.2f) C=%s(%.2f) D=%s(%.2f)",
                    a_cls, a_conf, b_cls, b_conf, c_cls, c_conf, d_cls, d_conf)

    # -----------------------------------------------------------------
    # Relatório
    # -----------------------------------------------------------------
    summary = []
    def w(s=""):
        summary.append(s)
        logger.info(s)

    w("")
    w("=" * 70)
    w("RELATÓRIO FINAL — Sprint 21.8")
    w("=" * 70)

    w("")
    w("1. DESEMPENHO DE CADA ESTRATÉGIA")
    w("-" * 70)
    w("Estratégia  | Accuracy | Precision | Recall | F1     | Tempo Médio | LLM Calls")
    w("------------|----------|-----------|--------|--------|-------------|----------")
    for name, m, llm_calls in [
        ("A (simples)", metrics_a, 0),
        ("B (linguíst.)", metrics_b, 0),
        ("C (LLM)", metrics_c, len(texts)),
        ("D (híbrida)", metrics_d, llm_calls_d),
    ]:
        w("%-11s | %.1f%%    | %.1f%%      | %.1f%%   | %.1f%%  | %.0fms       | %d/%d" % (
            name, m["accuracy"] * 100, m["precision"] * 100, m["recall"] * 100,
            m["f1"] * 100, m["avg_time_ms"], llm_calls, len(texts)))

    w("")
    w("2. MATRIZES DE CONFUSÃO (positivo = CONTEXT_DEPENDENT)")
    w("-" * 70)
    for name, m in [("A", metrics_a), ("B", metrics_b), ("C", metrics_c), ("D", metrics_d)]:
        w("")
        w("  Estratégia %s:" % name)
        w("                    Pred COMPLETE  Pred CONTEXT  Total")
        w("  Real COMPLETE        %3d (TN)      %3d (FP)     %d" % (m["tn"], m["fp"], m["tn"] + m["fp"]))
        w("  Real CONTEXT         %3d (FN)      %3d (TP)     %d" % (m["fn"], m["tp"], m["fn"] + m["tp"]))
        w("  Total                %d             %d            %d" % (m["tn"] + m["fn"], m["fp"] + m["tp"], m["n"]))

    w("")
    w("3. CASOS DE ERRO")
    w("-" * 70)
    for name, m, preds in [
        ("A", metrics_a, preds_a),
        ("B", metrics_b, preds_b),
        ("C", metrics_c, preds_c),
        ("D", metrics_d, preds_d),
    ]:
        w("")
        w("  Estratégia %s — %d erros:" % (name, len(m["errors"])))
        for err_type, idx, pred, exp, conf in m["errors"]:
            w("    [%s] %r → predito=%s esperado=%s (conf=%.2f)" % (
                err_type, texts[idx][:50], pred, exp, conf))

    w("")
    w("4. CASOS AMBÍGUOS")
    w("-" * 70)
    w("Texto                    | A            | B            | C            | D")
    w("-------------------------|--------------|--------------|--------------|------------")
    for r in ambiguous_results:
        w("%-24s | %-12s  | %-12s  | %-12s  | %s" % (
            r["text"][:22], r["A"], r["B"], r["C"], r["D"]))

    w("")
    w("5. SIMULAÇÃO DE PRODUÇÃO")
    w("-" * 70)
    # Usar a melhor estratégia (D) para simular
    best_metrics = metrics_d
    best_preds = preds_d
    n_complete = sum(1 for p in best_preds if p[0] == "COMPLETE_REFERENCE")
    n_context = sum(1 for p in best_preds if p[0] == "CONTEXT_DEPENDENT")
    error_rate = 1 - best_metrics["accuracy"]
    w("Estratégia recomendada: D (híbrida)")
    w("  Frases → COMPLETE_REFERENCE: %d/%d (%.1f%%)" % (
        n_complete, len(texts), n_complete / len(texts) * 100))
    w("  Frases → CONTEXT_DEPENDENT: %d/%d (%.1f%%)" % (
        n_context, len(texts), n_context / len(texts) * 100))
    w("  Taxa de erro do classificador: %.1f%%" % (error_rate * 100))
    w("  LLM calls necessárias: %d/%d (%.1f%%)" % (
        llm_calls_d, len(texts), llm_calls_d / len(texts) * 100))
    w("  Tempo médio: %.0fms (heurística pura) + LLM para %.1f%% dos casos" % (
        metrics_b["avg_time_ms"], llm_calls_d / len(texts) * 100))

    w("")
    w("6. RECOMENDAÇÃO ARQUITETURAL")
    w("-" * 70)
    # Determinar melhor estratégia
    strategies = [("A", metrics_a), ("B", metrics_b), ("C", metrics_c), ("D", metrics_d)]
    best = max(strategies, key=lambda x: x[1]["f1"])
    w("Melhor estratégia por F1: %s (F1=%.1f%%, accuracy=%.1f%%)" % (
        best[0], best[1]["f1"] * 100, best[1]["accuracy"] * 100))
    w("")
    if best[1]["f1"] >= 0.9:
        w("VIÁVEL: O classificador atinge F1 >= 90%%.")
        w("Recomendação: introduzir classificador antes da inferência bíblica.")
    elif best[1]["f1"] >= 0.8:
        w("VIÁVEL COM RESSALVAS: O classificador atinge F1 >= 80%%.")
        w("Recomendação: introduzir classificador com monitoramento de erros.")
    else:
        w("INVIÁVEL: O classificador não atinge F1 >= 80%%.")
        w("Recomendação: não introduzir classificador; buscar abordagem alternativa.")

    w("")
    w("Impacto esperado na inferência bíblica:")
    w("  Com a estratégia híbrida (D):")
    w("  - %.1f%% das frases irão para o pipeline sem recent_text (melhor acurácia)" % (
        n_complete / len(texts) * 100))
    w("  - %.1f%% das frases irão para o pipeline com contexto (necessário para desambiguação)" % (
        n_context / len(texts) * 100))
    w("  - Taxa de erro de classificação: %.1f%% (frases enviadas para o pipeline errado)" % (
        error_rate * 100))
    w("  - Custo adicional: %.1f%% das frases precisam de chamada ao LLM para classificação" % (
        llm_calls_d / len(texts) * 100))

    with open(_SUMMARY_FILE, "w", encoding="utf-8") as sf:
        sf.write("\n".join(summary))

    _fh.flush()
    _fh.close()
    print(f"Concluído. Logs em: {_LOG_FILE}")
    print(f"Resumo em: {_SUMMARY_FILE}")


if __name__ == "__main__":
    main()
