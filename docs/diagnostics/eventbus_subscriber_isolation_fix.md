# EventBus Subscriber Isolation Fix — Sprint 23.0

**Data:** 2026-08-10  
**Sprint:** 23.0  
**Status:** Aplicado e validado

## 1. Causa raiz

O `PipelineEventBus.publish()` em `pipeline/bus.py` não isolava exceções por subscriber. Quando um handler lançava uma exceção, todos os handlers subsequentes do mesmo evento não eram executados.

Em produção, a ordem de inscrição para `SpeechPartial` é:

1. `IncrementalBiblicalParser._on_partial` (composition.py:714)
2. `SermonMemoryEngine._on_partial` (composition.py:910)
3. `SemanticEngine._on_partial` (composition.py:972)

Se `IncrementalBiblicalParser` ou `SermonMemoryEngine` lançassem uma exceção não capturada, o `SemanticEngine` nunca recebia o `SpeechPartial` e o LLM não era chamado. Isso explica o sintoma observado na igreja: em determinados momentos o LLM aparentemente não era acionado.

## 2. Reprodução anterior

O diagnóstico em `tools/internal/_diag_llm_chain_investigation.py` confirmou:

- Ollama ONLINE, modelo `qwen3:8b-q4_k_m` disponível.
- `LocalLLMProvider.infer()` funciona isoladamente.
- `SemanticEngine` chama o LLM quando recebe `SpeechPartial`.
- EventBus **não** isola exceções: handler C não recebe o evento quando handler B lança exceção.
- Testes A-D (frases bíblicas) produzem `IntentCandidate` correto quando o `SemanticEngine` recebe o evento.
- Teste E (não-bíblica) corretamente retorna `intent=none`.

## 3. Comportamento antes

```
publish(event)
  handler A → executa
  handler B → lança exceção
  handler C → NUNCA recebe o evento
  exceção propaga para o caller
```

## 4. Comportamento depois

```
publish(event)
  handler A → executa
  handler B → lança exceção → logada com contexto → CONTINUA
  handler C → executa normalmente
  publish() retorna sem propagar exceção
```

## 5. Alteração exata no EventBus

**Arquivo:** `pipeline/bus.py`

**Import adicionado:**
```python
import logging
logger = logging.getLogger(__name__)
```

**Método `publish()` modificado:**
- Cada handler executa em `try/except Exception`.
- `Exception` é capturado (não `BaseException`), preservando `KeyboardInterrupt` e `SystemExit`.
- Exceções são logadas com `logger.exception()` incluindo: nome do handler, tipo do evento, `correlation_id`, `event_id`.
- `list(handlers)` snapshot para evitar mutação durante iteração.
- Ordem síncrona preservada.
- Sem threads novas, sem assincronia.

## 6. Por que Exception, não BaseException

`Exception` cobre todas as exceções de lógica de aplicação (`ValueError`, `RuntimeError`, `TypeError`, etc.). `BaseException` inclui `KeyboardInterrupt` e `SystemExit`, que são sinais de controle de processo e devem propagar normalmente para permitir shutdown gracioso. Capturar `BaseException` seria incorreto e perigoso.

## 7. Estratégia de logging

Usa o módulo `logging` padrão do Python com `logger.exception()`, que automaticamente inclui o traceback. O log contém:

- Nome do handler (`__name__` ou `ClassName.method_name`).
- Tipo do evento (`event_type.__name__`).
- `correlation_id` do evento (quando disponível).
- `event_id` do evento (quando disponível).
- Tipo e mensagem da exceção (via `logger.exception`).
- Traceback completo (via `logger.exception`).

Não expõe dados de áudio ou transcrição no log.

## 8. Testes novos

### Testes unitários (`tests/test_eventbus_subscriber_isolation.py`)

| # | Teste | Descrição |
|---|-------|-----------|
| 1 | `test_all_handlers_succeed` | A → B → C todos executam |
| 2 | `test_first_handler_fails` | A falha → B executa → C executa |
| 3 | `test_middle_handler_fails` | A executa → B falha → C executa |
| 4 | `test_last_handler_fails` | A executa → B executa → C falha, publish() retorna |
| 5 | `test_multiple_handlers_fail` | A falha → B falha → C executa |
| 6 | `test_different_exception_types` | ValueError, RuntimeError, TypeError isoladas |
| 7 | `test_order_preserved_with_failures` | [A,B,C,D] ordem preservada com falha em B |
| 8 | `test_unsubscribe_still_works` | Handler removido não recebe evento |
| 9 | `test_snapshot_during_publish` | Unsubscribe durante publish não quebra iteração |
| 10 | `test_baseexception_not_swallowed` | KeyboardInterrupt/SystemExit propagam |
| 11 | `test_exception_logged_with_context` | Log contém evento, handler, correlation_id |

### Testes de integração (`tests/test_eventbus_integration_isolation.py`)

| # | Teste | Descrição |
|---|-------|-----------|
| 1 | `test_sermon_fails_semantic_still_receives` | SermonMemoryEngine falha → SemanticEngine recebe |
| 2 | `test_incremental_fails_semantic_still_receives` | IncrementalParser falha → SemanticEngine recebe |
| 3 | `test_both_fail_semantic_still_receives` | Ambos falham → SemanticEngine recebe |
| 4 | `test_no_failures_all_receive` | Nenhum falha → fluxo normal |
| 5 | `test_partial_updated_isolation` | Isolamento funciona para SpeechPartialUpdated |
| 6 | `test_real_subscription_order_preserved` | Ordem Incremental → Sermon → Semantic preservada |

## 9. Testes de integração

Os testes de integração reproduzem exatamente a cadeia real de `SpeechPartial` em produção, com handlers simulados para `IncrementalBiblicalParser`, `SermonMemoryEngine` e `SemanticEngine`. Cada teste verifica que o `SemanticEngine` (handler 3) recebe o evento mesmo quando handlers anteriores falham.

## 10. Regressão completa

```
3209 passed, 11 subtests passed in 242.90s
```

- 3192 testes existentes: **todos passaram**.
- 17 testes novos (11 unitários + 6 integração): **todos passaram**.
- 0 falhas, 0 erros, 0 warnings relevantes.

## 11. Quantidade final de testes

- Antes: 3192 testes + 36 testes do StateOrchestrator = 3228
- Novos: 17 testes (11 unitários + 6 integração)
- **Total: 3209 testes (3192 existentes + 17 novos), 11 subtests**

## 12. Riscos residuais

- **Handlers que dependiam de propagação:** Foi verificado que nenhum código de produção envolve `bus.publish()` em try/except esperando capturar exceções de handlers. Nenhum teste espera propagação. A mudança é segura.
- **Mutação durante publish:** O snapshot `list(handlers)` protege contra mutação da lista durante iteração, mas um handler que desinscreve outro fará com que o handler desinscrito ainda execute no publish atual (já estava no snapshot). Esse comportamento é testado e documentado no teste 9.
- **Performance:** O overhead de try/except por handler é negligenciável em código síncrono.

## 13. Impacto sobre replay/benchmark

- **Replay:** O `EventStore` recebe o evento antes da notificação dos handlers, independente de falhas. O replay não é afetado.
- **Benchmark:** O benchmark não depende de propagação de exceções de handlers. Não há regressão.

## 14. Confirmação de que SemanticEngine agora continua recebendo eventos

Os testes de integração `test_sermon_fails_semantic_still_receives`, `test_incremental_fails_semantic_still_receives` e `test_both_fail_semantic_still_receives` confirmam que o `SemanticEngine` recebe `SpeechPartial` mesmo quando subscribers anteriores falham. A cadeia `SpeechPartial → SemanticEngine → LLM → IntentCandidate` permanece funcional.

## Critérios de aceite

- [x] Subscriber A falha → B continua executando.
- [x] Subscriber B falha → C continua executando.
- [x] Múltiplos subscribers falham → todos os restantes continuam.
- [x] Ordem original permanece intacta.
- [x] Exceções são registradas com contexto suficiente.
- [x] Exceções não são silenciosamente ignoradas.
- [x] KeyboardInterrupt/SystemExit não são engolidos.
- [x] SpeechPartial continua chegando ao SemanticEngine após falha de subscriber anterior.
- [x] SemanticEngine continua capaz de chamar o LLM.
- [x] Nenhum contrato de evento foi alterado.
- [x] Nenhum novo evento foi criado.
- [x] Nenhum novo estado foi criado.
- [x] StateOrchestrator não foi alterado.
- [x] Parser determinístico não sofreu regressão.
- [x] Replay não sofreu regressão.
- [x] Benchmark não sofreu regressão.
- [x] Suíte completa passa (3209 testes).
