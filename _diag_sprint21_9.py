"""Sprint 21.9 — Diagnóstico de integração da telemetria.

Valida que, ao simular um fluxo do pipeline (SpeechPartial → Parser →
SermonMemory → SemanticEngine → Resolver → Holyrics), os arquivos .jsonl
são gerados corretamente com os eventos esperados.

Não testa o pipeline real; apenas valida que a instrumentação está
conectada e produzindo arquivos nas categorias corretas.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Garantir que o diretório do projeto está no path.
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))


def main() -> int:
    from telemetry import configure_recorder, record, shutdown_recorder, get_recorder
    from telemetry import hooks as telemetry_hooks

    # Configurar recorder em diretório temporário.
    tmp_dir = tempfile.mkdtemp(prefix="sprint21_9_diag_")
    r = configure_recorder(output_dir=tmp_dir, enabled=True)

    # Coletar saída para escrever em arquivo (contornar truncamento do PS).
    output_lines = []
    def log(msg: str = "") -> None:
        print(msg)
        output_lines.append(msg)

    log(f"Session dir: {r.session_dir}")

    # Simular fluxo do pipeline chamando os hooks diretamente.
    corr_id = "diag-corr-001"

    # 1. STT — janela de áudio transcrita.
    telemetry_hooks.stt_window(
        correlation_id=corr_id,
        audio_duration_ms=6000,
        rms=0.0234,
        transcribed=True,
        text="irmãos vamos abrir no evangelho de João capítulo 3 versículo 16",
        confidence=0.78,
        latency_ms=950,
        language="pt",
    )

    # 2. Streaming — SpeechPartial publicado.
    telemetry_hooks.stt_partial_published(
        correlation_id=corr_id,
        text="irmãos vamos abrir no evangelho de João capítulo 3 versículo 16",
        confidence=0.78,
        latency_ms=950,
        audio_duration_ms=6000,
        language="pt",
        is_update=False,
    )

    # 3. Parser — book detectado.
    telemetry_hooks.parser_event(
        correlation_id=corr_id,
        text_processed="joão",
        expecting="chapter",
        completeness="book",
        book="João",
        chapter=0,
        verse=0,
        confidence=0.85,
        decision="publish_candidate",
        published_event="ReferenceCandidate",
        latency_ms=2,
    )

    # 4. Parser — chapter detectado.
    telemetry_hooks.parser_event(
        correlation_id=corr_id,
        text_processed="joão capítulo 3",
        expecting="verse",
        completeness="chapter",
        book="João",
        chapter=3,
        verse=0,
        confidence=0.90,
        decision="publish_detected",
        published_event="ReferenceDetected",
        latency_ms=3,
    )

    # 5. SermonMemory — mudança por referência detectada.
    telemetry_hooks.sermon_state_change(
        correlation_id=corr_id,
        reason="reference_detected+book_changed",
        previous_book="",
        previous_chapter=0,
        new_book="João",
        new_chapter=3,
        probable_theme="salvação",
        num_entities=3,
        num_topics=2,
        num_references=1,
        confidence=0.75,
        source="parser",
        reference_active="João 3:0",
        total_updates=1,
    )

    # 6. SemanticEngine — input recebido.
    telemetry_hooks.semantic_input(
        correlation_id=corr_id,
        text="Porque Deus amou o mundo de tal maneira",
        recent_text="irmãos vamos abrir no evangelho de João capítulo 3",
        trigger="growth",
        growth_chars=35,
        append_words=6,
        cached=False,
        context_hash="abc123",
    )

    # 7. LocalLLMProvider — prompt enviado.
    telemetry_hooks.semantic_prompt(
        correlation_id=corr_id,
        system_prompt="You are a biblical reference detector...",
        user_prompt="Texto: Porque Deus amou o mundo...\nFala recente: irmãos vamos abrir...",
        context={
            "current_text": "Porque Deus amou o mundo de tal maneira",
            "recent_text": "irmãos vamos abrir no evangelho de João capítulo 3",
            "last_book": "João",
            "last_chapter": 3,
            "sermon_book": "João",
            "sermon_chapter": 3,
        },
        model="qwen3:8b-q4_K_M",
        temperature=0.0,
    )

    # 8. LocalLLMProvider — resposta RAW do LLM.
    telemetry_hooks.semantic_llm_response(
        correlation_id=corr_id,
        raw_content='{"intent":"show_reference","candidates":[{"book":"João","chapter":3,"verse":16,"confidence":0.92}]}',
        cleaned_content='{"intent":"show_reference","candidates":[{"book":"João","chapter":3,"verse":16,"confidence":0.92}]}',
        had_thinking=False,
        http_ms=2300,
        attempt=0,
    )

    # 9. SemanticEngine — resultado final.
    telemetry_hooks.semantic_result(
        correlation_id=corr_id,
        intent="show_reference",
        candidates=[{"book": "João", "chapter": 3, "verse": 16, "confidence": 0.92}],
        inference_ms=2300,
        cached=False,
        context_hash="abc123",
    )

    # 10. ReferenceResolver — decisão.
    telemetry_hooks.resolver_decision(
        correlation_id=corr_id,
        candidates_in=[{"book": "João", "chapter": 3, "verse": 16, "confidence": 0.92}],
        candidates_valid=[{"book": "João", "chapter": 3, "verse": 16, "confidence": 0.92}],
        chosen={"book": "João", "chapter": 3, "verse": 16, "confidence": 0.92},
        reason="highest_confidence",
        min_confidence=0.5,
        latency_ms=15,
    )

    # 11. Holyrics — apresentação.
    telemetry_hooks.holyrics_presentation(
        correlation_id=corr_id,
        book="João",
        chapter=3,
        verse=16,
        version="ACF",
        quick_presentation=False,
        success=True,
        latency_ms=420,
    )

    # Aguardar a thread consumidora processar tudo.
    time.sleep(0.5)
    shutdown_recorder()

    # Verificar arquivos gerados.
    sd = r.session_dir
    files = sorted(os.listdir(sd))
    log(f"\nArquivos gerados ({len(files)}):")
    for f in files:
        file_path = os.path.join(sd, f)
        lines = open(file_path, encoding="utf-8").readlines()
        log(f"  {f}: {len(lines)} evento(s)")

    # Validar categorias esperadas.
    expected_categories = {
        "stt", "streaming", "parser", "sermon_memory",
        "semantic_engine", "semantic_prompt", "semantic_llm_response",
        "semantic_result", "resolver", "holyrics",
    }
    found_categories = {f.replace(".jsonl", "") for f in files}
    missing = expected_categories - found_categories
    if missing:
        log(f"\nERRO: categorias faltando: {missing}")
        return 1

    log(f"\nTodas as {len(expected_categories)} categorias esperadas estão presentes.")

    # Validar conteúdo de alguns arquivos.
    log("\nAmostra de eventos:")

    stt_lines = open(os.path.join(sd, "stt.jsonl"), encoding="utf-8").readlines()
    stt_event = json.loads(stt_lines[0])
    log(f"  stt: text={stt_event['text'][:50]!r}, confidence={stt_event['confidence']}")

    prompt_lines = open(os.path.join(sd, "semantic_prompt.jsonl"), encoding="utf-8").readlines()
    prompt_event = json.loads(prompt_lines[0])
    log(f"  semantic_prompt: model={prompt_event['model']}, user_prompt len={len(prompt_event['user_prompt'])}")

    result_lines = open(os.path.join(sd, "semantic_result.jsonl"), encoding="utf-8").readlines()
    result_event = json.loads(result_lines[0])
    log(f"  semantic_result: intent={result_event['intent']}, candidates={len(result_event['candidates'])}")

    resolver_lines = open(os.path.join(sd, "resolver.jsonl"), encoding="utf-8").readlines()
    resolver_event = json.loads(resolver_lines[0])
    log(f"  resolver: reason={resolver_event['reason']}, chosen={resolver_event['chosen']['book']} {resolver_event['chosen']['chapter']}:{resolver_event['chosen']['verse']}")

    holyrics_lines = open(os.path.join(sd, "holyrics.jsonl"), encoding="utf-8").readlines()
    holyrics_event = json.loads(holyrics_lines[0])
    log(f"  holyrics: success={holyrics_event['success']}, latency={holyrics_event['latency_ms']}ms")

    log("\nDiagnóstico concluído com sucesso.")
    log(f"Arquivos em: {sd}")

    # Escrever saída em arquivo para contornar truncamento do PowerShell.
    output_path = project_root / "_diag_sprint21_9_output.txt"
    output_path.write_text("\n".join(output_lines), encoding="utf-8")
    log(f"Saída escrita em: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

