# Sprint 21.5.3 — Validação da Integridade do EventBus

## Data: 2026-07-25
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão definitiva:** O EventBus **POSSUI** o mecanismo de interrupção (sem `try/except` no loop de handlers), e esse mecanismo **REALMENTE impede** que subscribers subsequentes recebam um evento quando um handler anterior lança exceção. **ENTRETANTO**, com os 3 componentes reais (IncrementalParser, SermonMemoryEngine, SemanticEngine) e as 5 frases de teste, **NENHUMA exceção foi lançada** e **TODOS os 5 eventos chegaram ao SemanticEngine**.

A hipótese do EventBus interromper a propagação é **REFUTADA** para os componentes e frases testados. A causa da ausência de inferências em produção está em **outro ponto do pipeline**.

---

## 2. Instrumentação Aplicada

### 2.1 EventBus.publish() — Monkey-patch

O método `publish()` do `PipelineEventBus` foi envolvido com instrumentação que registra:

```
==================================================
EVENTO: SpeechPartial
  ID: <event_id>
  Correlation: <correlation_id>
  Texto: <texto>
  Subscribers registrados: N
    1. IncrementalParser
    2. SermonMemoryEngine
    3. SemanticEngine
==================================================

→ Executando subscriber: IncrementalParser
← IncrementalParser concluído (tempo=0.20ms)

→ Executando subscriber: SermonMemoryEngine
← SermonMemoryEngine concluído (tempo=0.18ms)

→ Executando subscriber: SemanticEngine
← SemanticEngine concluído (tempo=0.25ms)

PUBLISH FINALIZADO
  Subscribers executados: [IncrementalParser, SermonMemoryEngine, SemanticEngine]
  Todos os subscribers executaram com sucesso.
```

### 2.2 Handlers dos Subscribers — Wrap na primeira linha

Cada handler `_on_partial` foi envolvido para logar **antes de qualquer filtro interno**:

```
[SemanticEngine] SemanticEngine RECEBIDO
  correlation: <corr_id>
  texto: <texto>
  thread: MainThread
  timestamp: 1784984991.636
  [SemanticEngine] Processando...
  [SemanticEngine] concluído (tempo=1.08ms)
```

### 2.3 StreamingSTTService — Log de publicação

```
######################################################################
# STREAMING STT PUBLICANDO
# SpeechPartial publicado
#   texto: 'O Senhor é meu pastor.'
#   timestamp: 1784984991.635
######################################################################
```

---

## 3. Ordem Real de Execução dos Subscribers

Confirmada via `bus._subscriptions.get(SpeechPartial, [])`:

| Ordem | Subscriber | Origem (composition.py) |
|-------|-----------|------------------------|
| 1 | IncrementalParser | `incremental_parser.start()` — linha 617 |
| 2 | SermonMemoryEngine | `sermon_memory_engine.start()` — linha 813 |
| 3 | SemanticEngine | `semantic_engine.start()` — linha 841 |

---

## 4. Tempo Gasto por Cada Subscriber

### Teste principal (5 frases, 3 subscribers reais + proxy)

| Frase | IncrementalParser | SermonMemoryEngine | SemanticEngine |
|-------|------------------|--------------------|-----------------|
| "Provérbios 15:14" | 0.15ms | 0.32ms | 1.11ms |
| "O Senhor é meu pastor." | 0.15ms | 0.29ms | 1.24ms |
| "Porque Deus amou o mundo." | 0.17ms | 0.29ms | 0.57ms |
| "Ainda que eu ande pelo vale da sombra da morte." | 0.22ms | 0.27ms | 0.27ms |
| "Tudo posso naquele que me fortalece." | 0.21ms | 0.37ms | 0.36ms |

### Teste complementar B (IncrementalParser REAL)

| Frase | IncrementalParser | SermonMemoryEngine | SemanticEngine |
|-------|------------------|--------------------|-----------------|
| "Provérbios 15:14" | 0.20ms | 0.10ms | 0.79ms |
| "O Senhor é meu pastor." | 0.17ms | 0.18ms | 0.25ms |
| "Porque Deus amou o mundo." | 0.15ms | 0.19ms | 0.17ms |
| "Ainda que eu ande pelo vale da sombra da morte." | 0.17ms | 0.17ms | 0.17ms |
| "Tudo posso naquele que me fortalece." | 0.11ms | 0.19ms | 0.19ms |

**Nenhum subscriber demora mais que 1.24ms.** Não há lentidão que possa causar timeout ou bloqueio.

---

## 5. Eventos Efetivamente Recebidos por Cada Componente

### Teste principal (proxy IncrementalParser + SermonMemory real + SemanticEngine real)

| Frase | StreamingSTT publicou? | IncrementalParser recebeu? | SermonMemory recebeu? | SermonMemory terminou? | SemanticEngine recebeu? | SemanticEngine chamou LLM? |
|-------|----------------------|---------------------------|----------------------|----------------------|------------------------|---------------------------|
| "Provérbios 15:14" | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM (via debounce) |
| "O Senhor é meu pastor." | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM (via growth) |
| "Porque Deus amou o mundo." | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM (via growth) |
| "Ainda que eu ande..." | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM (via growth) |
| "Tudo posso naquele..." | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM | ✅ SIM (via growth) |

### Teste complementar B (IncrementalParser REAL + SermonMemory REAL + SemanticEngine REAL)

| Frase | IncrementalParser | SermonMemory | SemanticEngine | LLM? | Exceção? |
|-------|------------------|--------------|----------------|------|----------|
| "Provérbios 15:14" | ✅ 0.20ms | ✅ 0.10ms | ✅ 0.79ms | ✅ SIM | NÃO |
| "O Senhor é meu pastor." | ✅ 0.17ms | ✅ 0.18ms | ✅ 0.25ms | ✅ SIM | NÃO |
| "Porque Deus amou o mundo." | ✅ 0.15ms | ✅ 0.19ms | ✅ 0.17ms | ✅ SIM | NÃO |
| "Ainda que eu ande..." | ✅ 0.17ms | ✅ 0.17ms | ✅ 0.17ms | ✅ SIM | NÃO |
| "Tudo posso naquele..." | ✅ 0.11ms | ✅ 0.19ms | ✅ 0.19ms | ✅ SIM | NÃO |

**Resultado: 5/5 eventos recebidos pelo SemanticEngine, 5/5 chamadas ao LLM, 0 exceções.**

---

## 6. Exceções Encontradas

### Teste principal e complementar B (componentes reais)

**NENHUMA exceção encontrada.** Total: 0 exceções em 10 publicações (5 + 5).

### Teste complementar A (exceção injetada)

**3 exceções injetadas proposicionalmente** no SermonMemoryEngine para provar o mecanismo:

```
✗ SermonMemoryEngine(FAILING) EXCEÇÃO (0.02ms): RuntimeError: EXCEÇÃO INJETADA para provar interrupção do EventBus
    Traceback (most recent call last):
      File "_diag_sprint21_5_3_complementar.py", line 102, in patched_publish
        h(event)
      File "_diag_sprint21_5_3_complementar.py", line 156, in failing_proxy
        raise RuntimeError("EXCEÇÃO INJETADA para provar interrupção do EventBus")
    RuntimeError: EXCEÇÃO INJETADA para provar interrupção do EventBus
  ⚠️ LOOP INTERROMPIDO — restantes NÃO executarão: ['SemanticEngine']
```

---

## 7. Evidência de Interrupção (ou Ausência Dela)

### Teste A — Prova do mecanismo (exceção injetada)

| Métrica | Valor |
|---------|-------|
| IncrementalParser recebeu | 3/3 eventos |
| SermonMemoryEngine recebeu (antes de falhar) | 3/3 eventos |
| **SemanticEngine recebeu** | **0/3 eventos** |
| **LLM chamado** | **0 vezes** |
| Publicações interrompidas | 3/3 |

**Evidência:** Quando o SermonMemoryEngine lança exceção, o loop `for handler in handlers` é interrompido e o SemanticEngine **NUNCA recebe o evento**. O mecanismo de interrupção está **CONFIRMADO**.

### Teste B — Componentes reais (sem exceção injetada)

| Métrica | Valor |
|---------|-------|
| IncrementalParser recebeu | 5/5 eventos |
| SermonMemoryEngine recebeu | 5/5 eventos |
| **SemanticEngine recebeu** | **5/5 eventos** |
| **LLM chamado** | **5 vezes** |
| Publicações interrompidas | 0/5 |

**Evidência:** Com os componentes reais, **NENHUMA interrupção** ocorreu. Todos os subscribers receberam todos os eventos.

---

## 8. Validação da Hipótese

### Caso 1: Todos os subscribers receberam?

**SIM.** No Teste B (componentes reais), todos os 3 subscribers receberam todos os 5 eventos.

### Caso 2: Algum subscriber lançou exceção?

**NÃO.** Com os componentes reais (IncrementalParser, SermonMemoryEngine, SemanticEngine) e as 5 frases de teste, **nenhuma exceção foi lançada**.

A única exceção observada foi a **injetada proposicionalmente** no Teste A (RuntimeError) para provar o mecanismo.

### Caso 3: O EventBus interrompeu o loop?

**SIM no Teste A (exceção injetada), NÃO no Teste B (componentes reais).**

O mecanismo de interrupção **existe e funciona** — mas não é **triggerado** pelos componentes reais com as frases testadas.

### Caso 4: SemanticEngine deixou de receber algum evento?

**NÃO** com os componentes reais. O SemanticEngine recebeu todos os 5/5 eventos.

**SIM** no Teste A (exceção injetada) — o SemanticEngine recebeu 0/3 eventos, provando que o mecanismo pode bloquear a entrega.

---

## 9. Confirmação ou Refutação Definitiva da Hipótese

### Hipótese: "O EventBus interrompe a propagação de SpeechPartial quando um subscriber lança exceção"

**CONFIRMADA em princípio, REFUTADA na prática.**

- **O mecanismo existe** (Teste A provou): se um handler lança exceção, o loop é interrompido e os handlers subsequentes não recebem o evento.
- **Os componentes reais não triggeram o mecanismo** (Teste B provou): com IncrementalParser real, SermonMemoryEngine real e SemanticEngine real, nenhuma exceção foi lançada em nenhuma das 5 frases de teste.

### Resposta ao critério de aceite

> Uma exceção em um subscriber realmente impede que os demais subscribers recebam um SpeechPartial, ou a causa da ausência de inferências semânticas está em outro ponto do pipeline?

**Resposta:** O mecanismo de interrupção **existe e funciona** (provado no Teste A). **ENTRETANTO**, com os componentes reais e as 5 frases de teste, **nenhuma exceção foi lançada** e **todos os eventos chegaram ao SemanticEngine** (provado no Teste B). Portanto, a causa da ausência de inferências semânticas em produção **NÃO está no EventBus** com os componentes e frases testados — está em **outro ponto do pipeline**.

---

## 10. Recomendação Técnica Fundamentada

### Sobre a necessidade de alterar o EventBus

**RECOMENDAÇÃO: Adicionar `try/except` no EventBus.publish() — SIM, mas como defesa em profundidade, não como correção do bug atual.**

**Justificativa:**

1. **O mecanismo de interrupção é um risco latente.** Embora os componentes atuais não lancem exceções com as frases testadas, qualquer exceção futura (em qualquer handler, de qualquer tipo de evento) bloquearia todos os handlers subsequentes. Isso é uma armadilha silenciosa — o erro não aparece nos logs do SemanticEngine, apenas nos logs do handler que falhou (se houver).

2. **O risco é real em produção.** Condições que não reproduzimos no teste (áudio ruidoso, textos muito longos, race conditions, falhas de rede no Ollama, erros de serialização JSON no SermonMemoryEngine, etc.) podem triggerar exceções que não ocorrem em ambiente controlado.

3. **A correção é trivial e de baixo risco.** Adicionar `try/except` com `logger.exception()` no loop de handlers não altera a lógica — apenas garante que um handler falho não bloqueie os demais.

4. **MAS isso não resolve o bug atual.** Como o Teste B provou, os componentes reais não lançam exceções com as frases testadas. A causa da ausência de inferências em produção está em outro lugar.

### Sobre a causa real do bug

A causa deve ser investigada nos seguintes pontos (em ordem de probabilidade):

1. **StreamingSTTService — filtros de RMS/confiança** (`microfone/streaming_stt_service.py`, linhas 177-226): O áudio das referências implícitas pode ter RMS < 0.005 (silêncio) ou confidence < 0.30 (alucinação), fazendo com que o evento nunca seja publicado.

2. **Whisper/STTExecutor**: O Whisper pode não transcrever corretamente frases de referência implícita (sem "capítulo" ou "versículo"), retornando texto vazio ou confidence baixa.

3. **Condições de produção**: Áudio ambiente, microfone, ruído de fundo, posição do pregador, etc. podem afetar a qualidade da transcrição de forma diferente para frases implícitas vs explícitas.

4. `reset_flow()` nunca chamado em produção: O `_current_text` do StreamingSTTService cresce indefinidamente, o que pode afetar o cálculo de diff e a publicação de SpeechPartialUpdated.

---

## 11. Arquivos de Evidência

| Arquivo | Descrição |
|---------|-----------|
| `_diag_sprint21_5_3.py` | Teste principal: 3 subscribers (proxy + real + real) |
| `_diag_sprint21_5_3_output.txt` | Saída do teste principal (353 linhas) |
| `_diag_sprint21_5_3_complementar.py` | Teste A (exceção injetada) + Teste B (IncrementalParser real) |
| `_diag_sprint21_5_3_complementar_output.txt` | Saída do teste complementar (184 linhas) |

---

## 12. Conclusão

| Pergunta | Resposta |
|----------|----------|
| O EventBus tem o mecanismo de interrupção? | **SIM** — sem `try/except` no loop |
| O mecanismo funciona (bloqueia handlers subsequentes)? | **SIM** — Teste A provou com exceção injetada |
| Os componentes reais lançam exceção com as 5 frases? | **NÃO** — Teste B provou, 0 exceções |
| O SemanticEngine recebeu todos os eventos? | **SIM** — 5/5 no Teste B |
| O LLM foi chamado para todas as frases? | **SIM** — 5/5 no Teste B |
| A hipótese do EventBus é a causa do bug? | **NÃO** — refutada para os componentes e frases testados |
| Onde está a causa real? | **Provavelmente no StreamingSTTService** (filtros de RMS/confiança) ou no **Whisper** (qualidade da transcrição) |
| Recomendação para o EventBus? | **Adicionar `try/except` como defesa em profundidade**, mas não como correção do bug atual |
