# Sprint 22.1 — Auditoria Arquitetural do Pipeline Semântico

**Data:** 2026-07-25
**Status:** Concluído (diagnóstico apenas, sem correções)
**Sprint anterior:** 22.0 (BibleRetriever + RAG Local)

---

## 1. Resumo Executivo

A auditoria identificou **três causas-raiz** para os comportamentos observados, todas distintas das hipóteses iniciais do enunciado. O SemanticEngine **não** depende de palavras-comando: o pipeline dispara inferência para qualquer fala com 8+ caracteres. O problema está no **prompt do modo atual**, que pergunta ao LLM "se ele está pedindo para mostrar uma referência", levando o modelo a interpretar frases narrativas bíblicas como não sendo pedidos. O BibleRetriever funciona corretamente para todos os cinco casos de teste sem comando, mas não está sendo chamado porque `knowledge.enabled=false` no config real. A persistência indevida de "Números 6" nas inferências seguintes nasce no SermonMemory, que **nunca expira** `current_book`/`current_chapter` — esses campos só mudam quando uma nova `ReferenceDetected` chega.

O modo RAG resolve os problemas #1 e #2, mas introduz um risco novo: a regra 7 do `_SYSTEM_PROMPT_RAG` ("considere o contexto do sermão") pode induzir o LLM a ancorar no livro antigo mesmo quando o candidato top aponta para outro livro.

---

## 2. Diagrama do Pipeline Executado

```
SpeechPartial / SpeechPartialUpdated (Whisper streaming)
       │
       ├──► IncrementalBiblicalParser (regex)
       │         └──► ReferenceDetected (se regex match)
       │
       ├──► SermonMemoryEngine
       │         ├── _process_text → entidades/temas (decaem)
       │         └── _on_reference_detected → current_book/chapter (NÃO decaem)
       │
       └──► SemanticEngine
                 ├── _schedule_inference (política crescimento/debounce)
                 │     └── filtro: len(text) >= 8
                 ├── _run_inference
                 │     ├── ContextEngine.build (inclui sermon_context)
                 │     ├── [RAG] BibleRetriever.retrieve (se knowledge.enabled)
                 │     ├── context_hash
                 │     ├── cache check
                 │     └── provider.infer (LLM ou Stub)
                 │           └──► IntentCandidate
                 │
                 └── (downstream) ReferenceResolver
                           ├── desserializa candidatos
                           ├── valida via Searcher
                           ├── escolhe max(confidence)
                           └──► ReferenceDetected (se houver confident)
                                       │
                                       └──► SermonMemory._on_reference_detected
                                                 └── atualiza current_book/chapter
```

**Ordem de subscrição no composition root** (determina ordem de execução síncrona por correlation_id):

1. `BiblicalNLUService` — assina `SpeechTranscribed` (não `SpeechPartial`)
2. `IncrementalBiblicalParser` — assina `SpeechPartial/Updated`
3. `SermonMemoryEngine` — assina `SpeechPartial/Updated` + `ReferenceDetected`
4. `SemanticEngine` — assina `SpeechPartial/Updated`
5. `ReferenceResolver` — assina `IntentCandidate`
6. `VersePresentationService` — assina `ReferenceDetected`

**Conclusão:** três componentes (IncrementalParser, SermonMemory, SemanticEngine) processam cada `SpeechPartial` em paralelo, sem filtro entre eles.

---

## 3. Verificação A — Acionamento do SemanticEngine

**Pergunta:** O SemanticEngine é executado para toda SpeechPartial ou somente quando existe um Intent específico?

**Resposta:** Para toda SpeechPartial com `len(text) >= 8`, independentemente de Intent.

**Evidência:**

- `semantic/engine.py` linhas 191-192: o `start()` assina `SpeechPartial` e `SpeechPartialUpdated` diretamente, sem qualquer filtro de Intent.
- Linhas 220-226: `_on_partial` e `_on_partial_updated` chamam `_schedule_inference(text, meta)` sem inspecionar Intent.
- Linhas 249-253: o único filtro em `_schedule_inference` é `if not self._enabled: return` e `if len(text) < _MIN_TEXT_LENGTH: return` (onde `_MIN_TEXT_LENGTH = 8`).
- **Não existe** no código qualquer condição `if intent != SHOW_REFERENCE: return` ou equivalente. Busca confirmatória por `subscribe.*IntentDetected` no SemanticEngine retornou zero matches.

**Instrumentação confirmatória:** simulei streaming de `SpeechPartialUpdated` e rastreei chamadas a `_run_inference`:

| Cenário | Gap entre chunks | `_run_inference` chamado |
|---|---|---|
| Sem comando ("Portanto, vão...") | 150ms | 2 vezes |
| Com comando ("Coloca o versículo, portanto...") | 150ms | 2 vezes |
| Sem comando, pausa 500ms | 500ms | 5 vezes |
| Com comando, pausa 500ms | 500ms | 5 vezes |

O SemanticEngine dispara igualmente com e sem comando. A hipótese do enunciado ("depende de palavras-comando") está **refutada** para o acionamento.

**Impacto arquitetural:** nenhum desvio. O acionamento está conforme projetado.

---

## 4. Verificação B — Acionamento do BibleRetriever

**Pergunta:** `retrieve()` foi chamado em cada inferência? Por que `retrieves=0, candidates=0` no encerramento?

**Resposta:** O contador está correto. `retrieves=0` significa que `retrieve()` nunca foi chamado na sessão. A causa mais provável é `knowledge.enabled=false` no config real, apesar do log de startup poder sugerir o contrário.

**Evidência:**

- O único caller de `retrieve()` em produção é `semantic/engine.py` linha 425, dentro de `_run_inference`.
- A guarda é `if self._bible_retriever is not None and self._bible_retriever.is_ready:` (linha 423). Se `_bible_retriever is None`, o bloco é pulado silenciosamente, sem telemetria.
- `composition.py` linha 609: o retriever só é inicializado se `knowledge_config is not None and knowledge_config.enabled`. Se `enabled=false`, `bible_retriever_instance` permanece `None` (declarado na linha 525).
- `config/config.yaml` linha 108: `enabled: false` (default preserva Modo Atual).
- `close()` em `bible_retriever.py` linha 748 loga `retrieves=%d` — só é chamado se `retriever is not None` (app.py linha 100).

**Hipóteses do enunciado avaliadas:**

| Hipótese | Veredito |
|---|---|
| BibleRetriever nunca foi chamado | Plausível se `enabled=false` |
| Chamado por outro caminho sem contabilização | Refutado: único caller é engine.py:425, e o contador `_total_retrieves += 1` (linha 492) está dentro de `retrieve()` |
| Contador com defeito | Refutado: contador é `+= 1` simples, inicializado apenas no `__init__` (linha 231), nunca resetado |
| Bypass para pipeline antigo | Refutado: não há outro caminho. Se `_bible_retriever is not None and is_ready`, retrieve é chamado antes do cache |

**Cenários que produzem `retrieves=0` mesmo com startup "RAG ativo":**

1. `knowledge.enabled=true` mas `book_table` falhou ao carregar (composition.py linha 547-552): `bible_retriever_instance = None`, e o warning "BibleRetriever disabled — book_table not available" pode passar despercebido.
2. `warmup_bible_retriever` lançou exceção (composition.py linha 632-637): `bible_retriever_instance = None`, warning "warmup failed" logado mas `semantic_engine` ainda recebe `bible_retriever=None`. O log "SemanticEngine started (mode=current)" deveria aparecer, mas se o usuário olhou apenas "BibleRetriever carregado" de um diagnóstico anterior, pode ter interpretado erroneamente.
3. `is_ready` retorna `False` após warmup (improvável, mas possível se `_mem_conn is None` por falha de FTS5).

**Ponto cego de telemetria:** quando `_bible_retriever is None`, não há registro explícito de "modo atual usado porque retriever desabilitado". O único sinal é o log de startup "BibleRetriever disabled (knowledge.enabled=False)". Recomenda-se adicionar um hook `semantic_rag_mode` no `_run_inference` registrando `rag_active=False, reason="retriever_none"` ou `reason="retriever_not_ready"`.

---

## 5. Verificação C — Pipeline RAG vs LLM Direta

**Pergunta:** Em cada inferência, o pipeline é Speech→Retriever→Top-K→Prompt→LLM ou Speech→LLM direta?

**Resposta:** Depende de `knowledge.enabled` e do estado do retriever, decidido em `_run_inference` linha 423.

**Evidência:**

- Se `_bible_retriever is not None and is_ready`: pipeline RAG. `retrieve()` é chamado antes do cache, candidatos injetados no contexto via `dataclasses.replace`, prompt usa `_SYSTEM_PROMPT_RAG`, `_build_user_prompt` inclui lista de candidatos.
- Se `_bible_retriever is None` ou `is_ready=False`: pipeline LLM direta. Bloco RAG pulado, contexto sem `rag_candidates`, prompt usa `_SYSTEM_PROMPT`, `_build_user_prompt` sem lista de candidatos.
- A decisão é por chamada, não por sessão. Se o retriever falhar midway, inferências seguintes caem para LLM direta (mas o retriever não recupera sozinho).

**Confirmação por simulação:** rodei o `_run_inference` completo com StubProvider e retriever real. Para os quatro casos sem comando, o fluxo RAG produziu `IntentCandidate` com `intent=show_reference` e o top candidato do retriever:

| Texto | Top candidato | Score |
|---|---|---|
| "Porque Deus amou o mundo..." | João 3:16 | 0.993 |
| "Portanto vão e façam discípulos..." | Mateus 28:19 | 1.000 |
| "O Senhor te abençoe e te guarde" | Números 6:24 | 1.000 |
| "Se Deus é por nós..." | Romanos 8:31 | 1.000 |

---

## 6. Verificação D — Construção do Prompt

**Pergunta:** O prompt favorece excessivamente o último livro utilizado?

**Resposta:** Sim, em ambos os modos, mas por mecanismos diferentes.

### Modo Atual (`_SYSTEM_PROMPT`)

O system prompt diz: "Sua tarefa: dado o texto falado por um pregador, **identificar se ele está pedindo para mostrar** uma referência bíblica". O exemplo da linha 74 diz: "como vimos anteriormente → depende do contexto (usar last_book/last_chapter se disponível)".

O user prompt inclui "Contexto do sermão: pregando em {sermon_book} {sermon_chapter}" sempre que `sermon_book` é truthy (`local_provider.py` linha 680-684).

**Efeito observado (Problema #1):** o LLM interpreta "Portanto, vão e façam discípulos" como NÃO sendo um pedido (é uma frase narrativa), retorna `intent="none"`. Com "Coloca o versículo, ...", o LLM entende que é um pedido explícito e tenta identificar. A dependência de "palavras-comando" nasce da **framing do prompt**, não do pipeline.

### Modo RAG (`_SYSTEM_PROMPT_RAG`)

A regra 7 diz: "Considere o contexto do sermão (livro/capítulo atual) se fornecido." O user prompt ainda inclui "Contexto do sermão: pregando em {sermon_book} {sermon_chapter}".

**Efeito de ancoragem (Problema #3):** quando o SermonMemory está preso em "Números 6" e o texto atual é "O Senhor é meu pastor" (Salmos 23:1), o prompt enviado ao LLM é:

```
Contexto do sermão: pregando em Números 6.
Confiança da memória: 80%.
Texto atual: O Senhor é meu pastor nada me faltará

Candidatos recuperados da Bíblia local:
1. Salmos 23:1 (score=1.00) ...

Escolha apenas UM candidato da lista acima.
```

A regra 7 autoriza o LLM a "considerar o contexto". Um LLM fraco pode:
- escolher Salmos 23:1 (correto, segue o candidato top)
- retornar `none` porque "não há candidato de Números"
- inventar "Números X:Y" (violação da regra 2, mas acontece com modelos pequenos)

**Reprodução confirmatória:** gerei o prompt real para "Portanto vão e façam discípulos" com `sermon_book="Números", sermon_chapter=6`. O candidato top é Mateus 28:19 (score 1.000), mas o prompt ainda diz "pregando em Números 6". A contradição está no prompt, não no retriever.

---

## 7. Verificação E — SermonMemory

**Pergunta:** Quando atualiza, limpa, expira, influencia nova inferência?

**Respostas:**

| Ação | Quando | Onde |
|---|---|---|
| Atualiza entidades/temas | A cada `SpeechPartial/Updated` | `_process_text` (linha 264), com decaimento |
| Atualiza current_book/chapter | A cada `ReferenceDetected` | `_apply_reference` (linha 645), **sem decaimento** |
| Aplica decaimento | A cada `_process_text` | `_apply_decay` (linha 492) |
| Expira entidades | Após meia-vida 120s, peso < min | Linhas 498-510 |
| Expira temas | Após meia-vida 300s, peso < min | Linhas 514-526 |
| Expira referências | Fora da janela `ref_window_s` | Linhas 528-535 |
| Expira current_book/chapter | **NUNCA** | Linhas 542-543: preservados em todos os caminhos |
| Reseta completamente | Apenas via `reset()` explícito | Linha 225 (não chamado automaticamente) |

**Causa-raiz da persistência (Problema #3):** `_apply_decay` (linha 541-552) reconstrói o `SermonContext` preservando `current_book` e `current_chapter` sem qualquer decaimento. Eles só mudam em `_apply_reference` (linha 674: `new_book = event.book`). Não há timeout, não há decaimento por desuso, não há reset automático quando o assunto muda.

**Fluxo da contaminação:**

1. Pregador diz "Números 6" → IncrementalParser (regex) publica `ReferenceDetected(book="Números", chapter=6)`.
2. SermonMemory recebe → `current_book="Números", current_chapter=6`.
3. Pregador muda de assunto: "O Senhor é meu pastor" (Salmos 23).
4. SermonMemory recebe `SpeechPartialUpdated` → `_process_text` → `_apply_decay`. Entidades/temas decaem, **mas current_book="Números" permanece**.
5. SemanticEngine dispara → `ContextEngine.build` consulta `sermon_memory.get_context` → retorna `sermon_book="Números"`.
6. Prompt: "Contexto do sermão: pregando em Números 6. Texto atual: O Senhor é meu pastor".
7. LLM ancora em "Números 6" e pode propor Números X:Y ou retornar none.

**Confiança decai, mas contexto não:** `_recompute_confidence` (linha 593-595) aplica decaimento à confiança, mas `current_book`/`current_chapter` são preservados (linhas 598-599). Mesmo com `confidence=0`, o prompt ainda inclui "pregando em Números 6" (a linha de confiança `if context.sermon_confidence > 0` é omitida, mas a linha de contexto já foi adicionada).

---

## 8. Verificação F — ReferenceResolver

**Pergunta:** Existe fallback para último livro quando não há candidato?

**Resposta:** Não. O ReferenceResolver é stateless e não mantém `_last_book`, `_current`, `_previous`, `_chosen` ou cache entre chamadas.

**Evidência:**

- `semantic/resolver.py` linhas 104-201: `_on_intent_candidate` não referencia qualquer estado persistente entre chamadas. Busca por `self._last|self._current|self._previous|self._chosen|self._cache|_last_book|_last_chapter` retornou zero matches.
- Se `not candidates`: publica `resolved=False, reason="no_candidates"` e retorna (linhas 111-125). Não há "manter último livro".
- Se `not confident_candidates`: publica `resolved=False, reason="low_confidence"` e retorna (linhas 158-178). Não há "usar última referência".
- O único caminho para publicar `ReferenceDetected` é via `_publish_reference_detected(event, chosen)` (linha 184), onde `chosen = max(confident_candidates, key=lambda c: c.confidence)` (linha 181). Sem chosen, sem publicação.

**Conclusão:** a persistência de "Números" nas inferências seguintes **não** nasce no ReferenceResolver. Nasce no SermonMemory (verificação E) e no prompt (verificação D).

---

## 9. Verificação G — BibleRetriever

**Pergunta:** Confirma que utiliza todas as 7 versões com SQL/score/agregação corretos?

**Resposta:** Sim. Todos os 5 casos de teste retornaram o candidato correto como top 1, sem comando, com agregação de múltiplas versões.

**Evidência (experimentos obrigatórios):**

| Caso | Texto (sem comando) | Top 1 | Score | Versões agregadas |
|---|---|---|---|---|
| 1 | "Porque Deus amou o mundo de tal maneira..." | João 3:16 | 0.993 | 5 |
| 2 | "Coloca o versículo, porque Deus amou..." | João 3:16 | 0.993 | 5 |
| 3 | "Portanto, vão e façam discípulos..." | Mateus 28:19 | 1.000 | 6 |
| 3b | "Portanto vão e façam discípulos... batizando-as..." | Mateus 28:19 | 1.000 | 7 |
| 4 | "O Senhor te abençoe e te guarde" | Números 6:24 | 1.000 | 7 |
| 5 | "Se Deus é por nós quem será contra nós" | Romanos 8:31 | 1.000 | 6 |

**Versões confirmadas:** ACF, ARA, ARC, JFAA, NAA, NTLH, NVT (7 bases descobertas automaticamente, 217.725 versículos indexados).

**Performance:** todos os retrieves em 16-65ms (objetivo <100ms atendido).

**Conclusão:** o BibleRetriever funciona corretamente e encontra todas as referências sem comando. O problema #1 não é do retriever, é do prompt do modo atual. O problema #2 (`retrieves=0`) é de configuração/acionamento, não de implementação.

---

## 10. Verificação H — Telemetria

**Hooks existentes** (`telemetry/hooks.py`):

| Hook | Categoria | Quando |
|---|---|---|
| `stt_window` | stt | janela do sliding window |
| `stt_partial_published` | stt | SpeechPartial publicado |
| `parser_event` | parser | IncrementalParser publicou |
| `sermon_state_change` | sermon | SermonMemory mudou estado |
| `semantic_input` | semantic | _run_inference recebeu texto |
| `semantic_prompt` | semantic | prompt enviado ao LLM |
| `semantic_llm_response` | semantic | resposta RAW do LLM |
| `semantic_result` | semantic | IntentCandidate publicado |
| `resolver_decision` | resolver | ReferenceResolver decidiu |
| `holyrics_presentation` | holyrics | apresentação executada |
| `bible_retriever_warmup` | bible_retriever | warmup concluído |
| `bible_retriever_query` | bible_retriever | retrieve executado |
| `bible_retriever_decision` | bible_retriever | decisão pós-retrieve |

**Pontos cegos identificados:**

1. **`_schedule_inference` decide não disparar:** se `len(text) < 8` ou `enabled=False`, retorna silenciosamente sem telemetria. Não há registro de "texto recebido mas ignorado por tamanho". Recomenda-se hook `semantic_skipped` com `reason="text_too_short"` ou `reason="disabled"`.

2. **Política de crescimento/debounce:** quando o gatilho de crescimento falha (`growth_chars < min_growth` ou `append_words < min_append` ou `elapsed < min_interval`), o debounce é reagendado, mas não há telemetria de "crescimento não atingiu threshold". Recomenda-se hook `semantic_trigger_eval` com `growth_chars, append_words, elapsed_ms, fired=bool`.

3. **Modo RAG desabilitado:** quando `_bible_retriever is None`, o bloco RAG é pulado sem telemetria. Não há registro de "modo atual usado porque retriever desabilitado". Recomenda-se adicionar ao `semantic_input` os campos `rag_active: bool, rag_reason: str` (e.g. "retriever_none", "retriever_not_ready", "enabled_false", "ok").

4. **`retrieve()` levanta exceção:** o `except` na linha 428 loga warning mas não chama telemetria. Recomenda-se hook `bible_retriever_error` com `error=str(e)`.

5. **SermonMemory expira `current_book`:** não existe, mas se fosse implementado, precisaria de telemetria. Hoje não há hook para "current_book expirou por desuso".

6. **`is_ready=False` no momento da inferência:** se o retriever foi warmupado mas `_mem_conn` foi fechado por outro caminho, `is_ready` retorna False e o bloco RAG é pulado. Sem telemetria.

---

## 11. Desvios entre Arquitetura Planejada e Executada

| # | Desvio | Severidade | Arquivo |
|---|---|---|---|
| 1 | `_SYSTEM_PROMPT` (modo atual) pergunta "se está pedindo para mostrar", induzindo LLM a ignorar frases narrativas bíblicas | Alta | `local_provider.py:68` |
| 2 | `_SYSTEM_PROMPT_RAG` regra 7 "considere o contexto do sermão" autoriza ancoragem no livro antigo | Alta | `local_provider.py:129` |
| 3 | SermonMemory nunca expira `current_book`/`current_chapter`, contaminando prompt indefinidamente | Alta | `sermon/engine.py:542-543` |
| 4 | `_build_user_prompt` sempre inclui "Contexto do sermão: pregando em {book} {chapter}" quando `sermon_book` é truthy, mesmo em modo RAG onde o candidato top deveria prevalecer | Alta | `local_provider.py:680-684` |
| 5 | `knowledge.enabled=false` no config default, fazendo o sistema rodar em modo LLM direta | Média | `config/config.yaml:108` |
| 6 | Ausência de telemetria quando retriever está desabilitado, impedindo diagnóstico de "retrieves=0" | Média | `semantic/engine.py:420-422` |
| 7 | Ausência de telemetria quando `_schedule_inference` decide não disparar | Baixa | `semantic/engine.py:249-253` |
| 8 | `ContextEngine.build` aceita `correlation_id` mas não o repassa ao `SemanticContext` (compensado por `dataclasses.replace` no `_run_inference`) | Baixa | `context_engine.py:72, 131-144` |

---

## 12. Respostas Diretas às Perguntas do Enunciado

**Quem decide quando a LLM é chamada?**
O `_schedule_inference` no SemanticEngine, baseado na política híbrida de gatilho de crescimento (`growth_chars >= 20 AND append_words >= 3 AND elapsed_ms >= 1000`) ou debounce (400ms após pausa). Não há filtro por Intent.

**Quem decide quando o BibleRetriever é chamado?**
O `_run_inference` linha 423, baseado em `self._bible_retriever is not None and self._bible_retriever.is_ready`. Se `_bible_retriever is None` (knowledge.enabled=false ou warmup falhou), o retriever não é chamado.

**Existe dependência de palavras-comando?**
Não no acionamento do SemanticEngine. Sim no comportamento do LLM em modo atual: o prompt pergunta "se está pedindo para mostrar", levando o LLM a exigir comando explícito. O modo RAG elimina essa dependência.

**Existe contaminação do SermonMemory?**
Sim. `current_book`/`current_chapter` nunca expiram, contaminando o prompt indefinidamente após a primeira referência detectada.

**Existe ancoragem causada pelo prompt?**
Sim. O `_SYSTEM_PROMPT_RAG` regra 7 e o `_build_user_prompt` linha 680-684 injetam "pregando em {book}" no prompt, autorizando o LLM a priorizar o contexto sobre o candidato top.

**Existe fallback indevido para referências anteriores?**
Não no ReferenceResolver (stateless, sem `_last_book`). Sim no SermonMemory (current_book persiste) e no prompt (sempre inclui sermon_book).

**O contador do BibleRetriever está correto?**
Sim. `_total_retrieves += 1` em `retrieve()`, inicializado apenas no `__init__`, nunca resetado. `retrieves=0` indica que `retrieve()` nunca foi chamado.

---

## 13. Correções Recomendadas (para a Sprint seguinte)

Em ordem de prioridade, **sem implementar nesta Sprint**:

### P0 — Ativar modo RAG e eliminar ancoragem do prompt

1. **`config/config.yaml:108`**: alterar `enabled: false` para `enabled: true`. Ativa o pipeline RAG, onde o Problema #1 é resolvido pela framing "escolha o melhor candidato" em vez de "identificar se é um pedido".

2. **`semantic/local_provider.py:129`**: remover ou reformular a regra 7 do `_SYSTEM_PROMPT_RAG`. Em modo RAG, o LLM deve escolher **apenas** pelo match entre texto e candidato, ignorando o contexto do sermão. Sugestão: "Ignore o contexto do sermão se ele conflitar com o candidato de maior score. O contexto é apenas um auxílio para desambiguação entre candidatos de score similar."

3. **`semantic/local_provider.py:680-697`**: em modo RAG, **não incluir** "Contexto do sermão: pregando em {book}" no user prompt, ou incluir apenas quando há 2+ candidatos com score >= 0.95 (desambiguação real). Quando há um top 1 claro, o contexto só prejudica.

### P1 — Expirar current_book no SermonMemory

4. **`sermon/engine.py:492-552`**: adicionar decaimento temporal para `current_book`/`current_chapter`. Após N segundos sem nova `ReferenceDetected` para o mesmo livro, zerar `current_book` (ou marcar `confidence=0` e omitir do prompt). Sugestão: meia-vida de 300s (igual aos temas), expirando completamente após ~600s sem nova referência.

5. **`sermon/engine.py:590-596`**: quando `confidence` cai abaixo de 0.3, zerar `current_book`/`current_chapter` (assunto provavelmente mudou).

### P2 — Telemetria de pontos cegos

6. **`semantic/engine.py:249-253`**: adicionar hook `semantic_skipped` quando `_schedule_inference` retorna por `len(text) < 8` ou `enabled=False`.

7. **`semantic/engine.py:420-422`**: adicionar ao `semantic_input` os campos `rag_active: bool, rag_reason: str` registrando se o retriever foi consultado e por quê não.

8. **`semantic/engine.py:428-433`**: adicionar hook `bible_retriever_error` quando `retrieve()` levanta exceção.

### P3 — Limpeza de redundância

9. **`semantic/context_engine.py:72, 131-144`**: ou passar `correlation_id` ao `SemanticContext` no `build`, ou remover o parâmetro (hoje é aceito mas ignorado, compensado por `dataclasses.replace` no `_run_inference`).

---

## 14. Conclusão

A auditoria refutou duas das três hipóteses iniciais e identificou causas-raiz distintas das suspeitadas. O SemanticEngine não depende de palavras-comando; o BibleRetriever não tem bug de contagem; o ReferenceResolver não tem fallback para último livro. Os três problemas observados têm origem em três lugares diferentes:

- **Problema #1** (dependência de comando): origem no `_SYSTEM_PROMPT` modo atual, que pergunta "se está pedindo para mostrar". Resolvido pelo modo RAG, que reformula para "escolha o melhor candidato".
- **Problema #2** (`retrieves=0`): origem em `knowledge.enabled=false` no config real. O pipeline RAG está implementado corretamente, mas não está ativo.
- **Problema #3** (persistência de Números): origem no SermonMemory, que nunca expira `current_book`/`current_chapter`, e no prompt que sempre injeta "pregando em {book}".

A Sprint 22.0 entregou a infraestrutura RAG correta e funcional. O que falta para colher o benefício é: (a) ativar `knowledge.enabled=true`, (b) eliminar a ancoragem do prompt RAG no contexto do sermão, e (c) expirar `current_book` no SermonMemory. Estas três correções, na Sprint 22.2, devem resolver os três problemas observados.
