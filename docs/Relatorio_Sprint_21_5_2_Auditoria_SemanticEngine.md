# Sprint 21.5.2 — Relatório de Auditoria da Política de Disparo do SemanticEngine

## Data: 2026-07-22
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão principal:** A política de disparo do SemanticEngine **não está bloqueando** as inferências semânticas. Todos os 5 testes com frases de referência implícita chegaram ao LLM com sucesso em ambiente controlado. A causa raiz do problema observado em produção está **antes** do SemanticEngine — os eventos `SpeechPartial`/`SpeechPartialUpdated` provavelmente **nunca chegam** ao SemanticEngine porque são descartados pelo `StreamingSTTService` (filtros de RMS/confiança) ou porque o `EventBus` não entrega eventos a handlers subsequentes quando um handler anterior lança exceção.

---

## 2. Fluxo Completo de uma Referência Implícita

```
Áudio (6s janela)
    ↓
StreamingSTTService.on_window()
    ├─ Filtro 1: duração < 1s? → SKIP
    ├─ Filtro 2: RMS < 0.005? → SKIP (silêncio)
    ├─ Whisper.transcribe()
    ├─ Filtro 3: texto vazio? → SKIP
    ├─ Filtro 4: confidence < 0.30? → SKIP (alucinação)
    ├─ Filtro 5: diff < 3 chars? → SKIP (só para Updated)
    ↓
EventBus.publish(SpeechPartial | SpeechPartialUpdated)
    ↓
[Handler 1] IncrementalParser._on_partial()
    ├─ _detected_published? → return early (não lança exceção)
    ├─ Normaliza texto, tenta match book/chapter/verse
    └─ Se não match → return (não lança exceção)
    ↓
[Handler 2] SermonMemoryEngine._on_partial()
    ├─ len(text) < 3? → return early
    ├─ Extrai entidades/topics, atualiza contexto
    └─ Publica SermonContextUpdated (pode lançar exceção!)
    ↓
[Handler 3] SemanticEngine._on_partial()  ← PODE NUNCA CHEGAR AQUI
    ├─ enabled? → False? → return
    ├─ len(text) < 8? → return (min_text_length)
    ├─ _should_fire_on_growth():
    │   ├─ elapsed_ms < 1000? → False (rate limit)
    │   ├─ growth_chars < 20? → False (crescimento insuficiente)
    │   └─ append_words < 3? → False (filler)
    ├─ Se growth dispara → _fire_inference() imediatamente
    └─ Se não → agenda debounce 800ms (cancelado pelo próximo evento)
    ↓
_fire_inference()
    ├─ ContextEngine.build() → contexto + hash
    ├─ Cache.get(hash)? → cache hit → publica telemetria, return
    ├─ Provider.is_available()? → False → publica erro, return
    ├─ Provider.infer() → chama LLM
    └─ Publica SemanticInferenceCompleted + IntentCandidate
```

---

## 3. Critérios Avaliados pelo SemanticEngine

| Critério | Default | config.yaml | Valor Real em Runtime |
|----------|---------|-------------|----------------------|
| `_MIN_TEXT_LENGTH` | 8 | 8 (não override) | 8 |
| `min_growth_chars` | 20 | (não setado) | 20 |
| `min_append_words` | 3 | (não setado) | 3 |
| `min_interval_ms` | 1000 | (não setado) | 1000 |
| `debounce_ms` | 400 | **800** | **800** ⚠️ |
| `timeout_ms` | 5000 | 5000 | 5000 |
| `enabled` | True | true | True (hardcoded) |

**⚠️ Discrepância:** `debounce_ms` no config.yaml é 800ms (valor da Sprint 20), não 400ms (valor da Sprint 21.5). Durante fala contínua, o debounce é sempre cancelado pelo próximo evento (400ms < 800ms), então esse valor não afeta o resultado — o gatilho de crescimento é o único que dispara durante fala contínua.

---

## 4. Valor Calculado de Cada Critério (por frase)

### Teste 1: Cenário simples (frase completa num único SpeechPartial)

| Frase | len | growth_chars | append_words | elapsed_ms | growth_ok | append_ok | rate_ok | DECISÃO | LLM chamado? |
|-------|-----|-------------|-------------|-----------|-----------|-----------|--------|---------|--------------|
| "O Senhor é meu pastor." | 22 | 22 | 5 | ∞ | ✅ | ✅ | ✅ | GROWTH DISPARA | ✅ SIM |
| "Porque Deus amou o mundo." | 25 | 25 | 5 | ∞ | ✅ | ✅ | ✅ | GROWTH DISPARA | ✅ SIM |
| "Tudo posso naquele que me fortalece." | 36 | 36 | 6 | ∞ | ✅ | ✅ | ✅ | GROWTH DISPARA | ✅ SIM |
| "Ainda que eu ande pelo vale da sombra da morte." | 47 | 47 | 10 | ∞ | ✅ | ✅ | ✅ | GROWTH DISPARA | ✅ SIM |
| "A armadura de Deus." | 19 | 19 | 4 | ∞ | ❌ (19<20) | ✅ | ✅ | DEBOUNCE (800ms) | ✅ SIM (após 800ms) |

### Teste 2: Cenário realista (streaming incremental, 2-3 palavras por incremento)

| Frase | Incrementos | Disparos growth | Disparos debounce | Total LLM | Texto enviado ao LLM |
|-------|-------------|----------------|-------------------|-----------|---------------------|
| "O Senhor é meu pastor." | 3 | 1 | 0 | 1 | "O Senhor é meu pastor." |
| "Porque Deus amou o mundo." | 3 | 1 | 0 | 1 | "Porque Deus amou o mundo." |
| "Tudo posso naquele que me fortalece." | 3 | 1 | 1 | 2 | "Tudo posso naquele que" + "Tudo posso...me fortalece." |
| "Ainda que eu ande pelo vale da sombra da morte." | 4 | 1 | 1 | 2 | "Ainda que eu ande pelo" + "Ainda que...da morte." |
| "A armadura de Deus." | 2 | 0 | 1 | 1 | "A armadura de Deus." |

### Teste 3: Cenário extremo (1 palavra por incremento, 400ms intervalo)

| Frase | Palavras | Disparos growth | Disparos debounce | Total LLM |
|-------|---------|----------------|-------------------|-----------|
| "O Senhor é meu pastor e nada me faltará" | 9 | 1 | 1 | 2 |
| "Irmãos hoje queremos meditar..." (24 palavras) | 24 | 4 | 1 | 5 |
| "Porque Deus amou o mundo..." (2 palavras/incr) | 7 | 2 | 1 | 3 |

### Teste 4: Pipeline completo com 3 subscribers reais

| Frase | IncrementalParser | SermonMemoryEngine | SemanticEngine | LLM chamado? | Exceção no bus? |
|-------|------------------|-------------------|---------------|--------------|----------------|
| "O Senhor é meu pastor." | ✅ recebeu | ✅ processou | ✅ growth disparou | ✅ SIM | NÃO |
| "Porque Deus amou o mundo." | ✅ recebeu | ✅ processou | ✅ growth disparou | ✅ SIM | NÃO |
| "Tudo posso naquele que me fortalece." | ✅ recebeu | ✅ processou | ✅ growth disparou | ✅ SIM | NÃO |
| "Ainda que eu ande pelo vale da sombra da morte." | ✅ recebeu | ✅ processou | ✅ growth disparou | ✅ SIM | NÃO |
| "A armadura de Deus." | ✅ recebeu | ✅ processou | ✅ debounce disparou | ✅ SIM | NÃO |

---

## 5. Qual Critério Impediu a Chamada ao LLM?

**NENHUM.** Em todos os 4 cenários de teste (simples, realista, extremo, pipeline completo), **todas as 5 frases chegaram ao LLM**. A política de disparo do SemanticEngine **não bloqueou nenhuma inferência**.

---

## 6. Evidências (Logs)

### Evidência 1: Teste simples — "O Senhor é meu pastor."
```
SpeechPartial recebido: text='O Senhor é meu pastor.' (len=22)
[_should_fire_on_growth] text='O Senhor é meu pastor.'
    growth_chars=22 (min=20) -> OK
    append_words=5 (min=3) -> OK
    elapsed_ms=infinito (primeira) (min_interval=1000ms) -> OK
    DECISÃO: DISPARA
>>> LLM CHAMADO com texto='O Senhor é meu pastor.'
[TELEMETRIA] intent=none, candidates=0, cached=False, error=''
```

### Evidência 2: Teste realista — "A armadura de Deus." (debounce fallback)
```
>> SpeechPartial: 'A armadura'
[DECISÃO] NÃO dispara growth | growth(10<20), append(2<3) | debounce agendado 800ms
>> SpeechPartialUpdated: full='A armadura de Deus.' appended='de Deus.'
[DECISÃO] NÃO dispara growth | growth(19<20) | debounce reagendado 800ms
>> Fala terminou. Aguardando 1.5s...
>>> LLM CHAMADO: 'A armadura de Deus.' (via debounce)
```

### Evidência 3: Pipeline completo com SermonMemoryEngine real
```
Ordem de inscrição SpeechPartial: 3 handlers
[IncrementalParser] recebeu 'O Senhor é meu pastor.' (não faz nada)
[SermonMemoryEngine processou sem exceção]
SemanticEngine: growth trigger fired (text=22 chars, growth=22, append_words=5)
>>> LLM CHAMADO: 'O Senhor é meu pastor.'
bus.publish() concluído SEM exceção
```

### Evidência 4: Stats finais do pipeline completo
```
Chamadas ao LLM: 5
Telemetria: 5 eventos (todos intent=none, cached=False, error='')
Stats: growth=4 debounce=1 calls=5
```

---

## 7. Análise das 5 Hipóteses

### Hipótese 1: O gatilho de crescimento nunca dispara
**REFUTADA.** O gatilho de crescimento disparou em 4 das 5 frases no cenário simples. A única frase que não disparou via growth ("A armadura de Deus." com 19 chars) disparou via debounce. Nos cenários realista e extremo, o growth disparou após 2-5 incrementos (0.8-2.0 segundos de fala contínua).

### Hipótese 2: O Rate Limiter está descartando inferências
**REFUTADA.** O rate limit (`min_interval_ms = 1000ms`) apenas atrasa a inferência, não descarta. Quando `elapsed_ms < 1000ms`, o growth trigger não dispara, mas o debounce é agendado. Se o debounce expira (pessoa para de falar), a inferência é executada. Se o debounce é cancelado (pessoa continua falando), o growth eventualmente dispara quando `elapsed_ms >= 1000ms` E `growth >= 20`.

### Hipótese 3: O Cache considera o contexto repetido
**REFUTADA.** O cache key é `SHA256(current_text + recent_text + last_book + last_chapter + sermon_book + sermon_chapter + sermon_theme)`. Como `current_text` é diferente para cada frase, o cache key é diferente. **Zero cache hits** em todos os testes. O cache não está bloqueando.

### Hipótese 4: Existe algum filtro semântico
**REFUTADA.** Os únicos filtros no SemanticEngine são:
- `_MIN_TEXT_LENGTH = 8`: todas as 5 frases têm > 8 chars
- `min_growth_chars = 20`: 4 das 5 frases têm >= 20 chars no primeiro evento; a 5ª dispara via debounce
- `min_append_words = 3`: todas as 5 frases têm >= 3 palavras
- `min_interval_ms = 1000`: apenas atrasa, não descarta
- `enabled = True`: hardcoded em composition.py

Não há filtro de confidence, language, noise ou qualquer outro filtro semântico no SemanticEngine.

### Hipótese 5: O SemanticEngine recebe o evento mas decide não executar
**REFUTADA.** Em todos os testes, quando o SemanticEngine recebeu o evento, ele executou (via growth trigger ou debounce). A única situação em que o SemanticEngine não executa é se `enabled = False` (não é o caso) ou se `len(text) < 8` (não é o caso para nenhuma das 5 frases).

---

## 8. Causa Raiz

**A política de disparo do SemanticEngine NÃO é a causa raiz.** A evidência dos 4 cenários de teste é conclusiva: todas as 5 frases chegam ao LLM quando o SemanticEngine recebe os eventos.

A causa raiz está **antes** do SemanticEngine — os eventos `SpeechPartial`/`SpeechPartialUpdated` **não estão chegando** ao SemanticEngine em produção. Existem duas causas possíveis:

### Causa A (MAIS PROVÁVEL): EventBus sem tratamento de exceções

**Arquivo:** `pipeline/bus.py`, linhas 120-144

```python
def publish(self, event: Any) -> None:
    handlers = self._subscriptions.get(event_type, [])
    for handler in handlers:
        handler(event)  # ⚠️ SEM try/except
```

**Ordem de inscrição no EventBus** (composition.py):
1. Linha 617: `IncrementalParser.start()` → handler 1
2. Linha 813: `SermonMemoryEngine.start()` → handler 2
3. Linha 841: `SemanticEngine.start()` → handler 3

Se o `SermonMemoryEngine._on_partial()` lançar **qualquer exceção**, o loop `for handler in handlers` é interrompido e o `SemanticEngine._on_partial()` **nunca é chamado**.

O `SermonMemoryEngine._process_text()` chama `_publish_update()` que publica `SermonContextUpdated` no EventBus. Se **qualquer handler** de `SermonContextUpdated` lançar exceção, ela propaga de volta através de:
```
handler(SermonContextUpdated) → exceção
  ↓ propaga
bus.publish(SermonContextUpdated) → exceção
  ↓ propaga
SermonMemoryEngine._publish_update() → exceção
  ↓ propaga
SermonMemoryEngine._process_text() → exceção
  ↓ propaga
SermonMemoryEngine._on_partial() → exceção
  ↓ propaga
bus.publish(SpeechPartial) → LOOP INTERROMPIDO
  ↓
SemanticEngine._on_partial() NUNCA É CHAMADO
```

**Por que referências explícitas funcionam?** Porque após o IncrementalParser detectar uma referência explícita, ele seta `_detected_published = True` e para de processar. O texto da referência explícita é tipicamente curto ("Provérbios 15") e pode não triggerar uma exceção no SermonMemoryEngine. Já textos mais longos de referências implícitas ("O Senhor é meu pastor", "Ainda que eu ande pelo vale da sombra da morte") podem triggerar exceções no processamento de entidades/topics do SermonMemoryEngine.

### Causa B (MENOS PROVÁVEL): Filtros do StreamingSTTService

**Arquivo:** `microfone/streaming_stt_service.py`, linhas 177-226

O `StreamingSTTService` tem 5 filtros antes de publicar eventos:
1. Duração do áudio < 1s → SKIP
2. RMS < 0.005 → SKIP (silêncio)
3. Texto vazio → SKIP
4. Confidence < 0.30 → SKIP (alucinação)
5. Diff < 3 chars → SKIP (só para Updated)

Se o áudio das referências implícitas tiver RMS baixo ou confidence baixa, os eventos nunca são publicados. Mas isso não explicaria por que referências explícitas funcionam (a menos que o áudio seja diferente).

### Causa C (MENOS PROVÁVEL): `reset_flow()` nunca chamado em produção

**Arquivo:** `microfone/streaming_stt_service.py`, linhas 396-406

O método `reset_flow()` **nunca é chamado em produção** — não há wiring no `composition.py`. O `SpeechEnded` é publicado pelo `SpeechPipelineService` mas **nenhum componente assina** esse evento para chamar `reset_flow()`.

Sem `reset_flow()`, o `_current_text` do StreamingSTTService cresce indefinidamente. Após uma referência explícita, o texto acumulado pode interferir com a detecção de diffs para a próxima frase. Mas o `_compute_diff` trata o caso de "Whisper reescreveu" retornando o texto inteiro, então isso não deveria bloquear a publicação.

---

## 9. Correção Recomendada (sem implementar)

### Correção 1 (CRÍTICA): Adicionar try/except no EventBus

**Arquivo:** `pipeline/bus.py`, método `publish()`

```python
def publish(self, event: Any) -> None:
    from pipeline.events import TelemetryEvent
    if not isinstance(event, TelemetryEvent):
        self._store.append(event)
    event_type = type(event)
    handlers = self._subscriptions.get(event_type, [])
    for handler in handlers:
        try:
            handler(event)
        except Exception as e:
            logger.exception(
                "EventBus: handler %s raised exception for %s: %s",
                handler.__qualname__, event_type.__name__, e
            )
            # Continua para o próximo handler — NÃO interrompe o loop
```

**Impacto:** Garante que todos os subscribers recebam eventos mesmo se um handler lançar exceção. Isso é a correção mais importante — sem ela, qualquer exceção em qualquer handler bloqueia todos os handlers subsequentes.

### Correção 2 (ALTA PRIORIDADE): Instrumentação de diagnóstico

Adicionar logs temporários no `StreamingSTTService.on_window()` e no `EventBus.publish()` para registrar:
- Quando um evento é publicado (StreamingSTTService)
- Quando um handler é chamado (EventBus)
- Quando um handler lança exceção (EventBus)
- Quando o SemanticEngine recebe ou não recebe um evento

### Correção 3 (MÉDIA PRIORIDADE): Wiring do reset_flow

Conectar `SpeechEnded` ao `reset_flow()` do StreamingSTTService e ao `reset()` do IncrementalParser:

```python
# Em composition.py, após criar ambos:
def _on_speech_ended(event):
    streaming_stt.reset_flow()
    incremental_parser.reset()
bus.subscribe(SpeechEnded, _on_speech_ended)
```

### Correção 4 (BAIXA PRIORIDADE): Sincronizar debounce_ms

O `config.yaml` tem `debounce_ms: 800` (valor da Sprint 20), mas a Sprint 21.5 reduziu para 400ms. Atualizar o config.yaml para 400ms ou remover a linha para usar o default.

---

## 10. Avaliação de Impacto

| Correção | Impacto | Risco | Prioridade |
|----------|---------|-------|-----------|
| 1. try/except no EventBus | ALTO — garante entrega de eventos a todos os subscribers | BAIXO — apenas loga exceções em vez de propagar | CRÍTICA |
| 2. Instrumentação | ALTO — identifica a causa exata em produção | BAIXO — logs temporários | ALTA |
| 3. Wiring reset_flow | MÉDIO — reseta estado entre frases | BAIXO — já funciona sem reset, mas pode melhorar precisão | MÉDIA |
| 4. Sincronizar debounce | BAIXO — debounce é sempre cancelado durante fala contínua | BAIXO | BAIXA |

---

## 11. Resposta ao Critério de Aceite

**Pergunta:** Por que frases semanticamente relevantes como "O Senhor é meu pastor", "Ainda que eu ande pelo vale da sombra da morte" e "Porque Deus amou o mundo" não chegam ao LocalLLMProvider, enquanto frases contendo referências explícitas chegam normalmente ao SemanticEngine e produzem intent:none?

**Resposta:** A política de disparo do SemanticEngine **não é a causa**. Em 4 cenários de teste (simples, realista, extremo, pipeline completo com SermonMemoryEngine real), todas as 5 frases chegaram ao LLM com sucesso. A causa raiz está **antes** do SemanticEngine:

1. **Causa mais provável:** O `EventBus` (`pipeline/bus.py`) não tem `try/except` no loop de handlers. Se o `SermonMemoryEngine` (handler 2 de 3) lançar uma exceção ao processar `SpeechPartial`, o `SemanticEngine` (handler 3) **nunca recebe o evento**. Isso explicaria por que "não aparecem logs do SemanticEngine" e "não aparecem chamadas ao LocalLLMProvider".

2. **Causa alternativa:** Os filtros de RMS/confiança do `StreamingSTTService` estão descartando os eventos antes da publicação.

3. **A diferença entre referências explícitas e implícitas** pode ser explicada pelo fato de que textos de referências implícitas (mais longos, com mais entidades bíblicas como "Senhor", "Deus", "pastor", "armadura") podem triggerar exceções no `SermonMemoryEngine._extract_entities()` ou `_extract_topics()` que textos de referências explícitas ("Provérbios 15") não triggeram.

**Para confirmar a causa raiz**, é necessário:
1. Adicionar `try/except` no `EventBus.publish()` (Correção 1)
2. Adicionar logs de diagnóstico no `EventBus` e `StreamingSTTService` (Correção 2)
3. Executar os 5 testes em produção e verificar quais eventos são descartados

---

## 12. Arquivos de Evidência

- `_diag_sprint21_5_2.py` — Teste simples (frase completa num SpeechPartial)
- `_diag_sprint21_5_2_output.txt` — Saída do teste simples
- `_diag_sprint21_5_2_realistic.py` — Teste realista (streaming incremental)
- `_diag_sprint21_5_2_realistic_output.txt` — Saída do teste realista
- `_diag_sprint21_5_2_extreme.py` — Teste extremo (1 palavra por incremento)
- `_diag_sprint21_5_2_extreme_output.txt` — Saída do teste extremo
- `_diag_sprint21_5_2_fullpipe.py` — Pipeline completo com 3 subscribers reais
- `_diag_sprint21_5_2_fullpipe_output.txt` — Saída do pipeline completo
