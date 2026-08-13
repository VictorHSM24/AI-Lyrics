# RFC Técnico — Capacidades Cognitivas AI Lyrics

Documento de especificação arquitetural para as 7 capacidades aprovadas no `capability_gap_analysis.md`.

Cada RFC é independente: um desenvolvedor pode implementar a capacidade apenas lendo sua seção.

> **Nota Sprint 28**: CAP-01 (`StateOrchestrator`) está implementado (Fase 5). O fluxo operacional primário agora é `SpeechCommittedWords` (LocalAgreement-2), não `SpeechTranscribed`. `BiblicalNLUService` está desativado por padrão (`enabled=False`); o parser incremental é o único caminho de parsing em produção. Ver ADR-011 e ADR-012.

---

## RFC CAP-01

id: CAP-01
title: Orquestração de máquina de estados (WAIT / PREPARE / PRESENT / IGNORE)
objective: >
  Criar um orquestrador de estados que mapeia a saída do parser incremental
  e do semantic_engine para os quatro estados do benchmark, publicando
  transições determinísticas no EventBus.

### current_behavior

O fluxo atual é linear e sem noção de estados:

1. `IncrementalBiblicalParser.process()` publica `ReferenceCandidate` (confidence 0.40/0.75) ou `ReferenceDetected` (confidence 0.98).
2. `BiblicalNLUService` consome `SpeechTranscribed`, chama `Parser.parse()`, e publica `ReferenceDetected` ou `IntentUnknown`.
3. `VersePresentationService` consome `ReferenceDetected` e apresenta no Holyrics.
4. `SemanticEngine` publica `IntentCandidate`, que `ReferenceResolver` pode converter em `ReferenceDetected`.

Não existe componente que decida "o sistema está aguardando" vs "preparando" vs "apresentando". O `VersePresentationService` reage a `ReferenceDetected` sem saber se o sistema já estava em PREPARE ou se pulou direto de WAIT. Não há conceito de IGNORE (segmentos descartados sem processamento semântico).

Por que não atende ao benchmark: todos os 11 eventos são definidos por transições de estado. Sem a máquina de estados, o sistema não consegue reproduzir nenhum evento.

### expected_behavior

Após cada segmento de fala processado, o sistema publica exatamente um evento `StateChanged` contendo o estado atual (WAIT, PREPARE, PRESENT ou IGNORE) e o motivo da transição. O estado só muda quando uma condição de transição é satisfeita. Segmentos sem referência não geram mudança de estado além de PRESENT → WAIT (reset automático pós-apresentação).

Comportamento observável:
- Quando o parser detecta um livro sem capítulo/versículo, o sistema transita para PREPARE.
- Quando o parser completa uma referência (livro + capítulo + versículo), o sistema transita para PRESENT.
- Após PRESENT, o próximo segmento sem referência faz o sistema transitar para WAIT.
- Segmentos que não contêm nenhuma pista bíblica (saudações, orações) resultam em IGNORE.
- Segmentos com menção de livro mas sem intenção de abertura resultam em WAIT (não PREPARE).

### state_transitions

```
WAIT
  ↓ [livro detectado + intenção de abertura]
PREPARE
  ↓ [capítulo + versículo detectados (completando referência)]
PRESENT
  ↓ [próximo segmento sem referência]
WAIT

WAIT
  ↓ [livro + capítulo detectados (sem versículo)]
PREPARE
  ↓ [versículo detectado]
PRESENT

PREPARE
  ↓ [expiração por mudança de assunto ou timeout]
WAIT

PRESENT
  ↓ [mesma referência detectada novamente]
PRESENT (repeat)

WAIT
  ↓ [segmento sem pista bíblica]
IGNORE

IGNORE
  ↓ [próximo segmento]
WAIT
```

### input_events

- `ReferenceCandidate` (do `IncrementalBiblicalParser`)
- `ReferenceDetected` (do `IncrementalBiblicalParser` ou `BiblicalNLUService`)
- `IntentCandidate` (do `SemanticEngine`)
- `IntentUnknown` (do `BiblicalNLUService`)
- `SpeechTranscribed` (do STT, para classificar IGNORE vs WAIT)

### output_events

- `StateChanged` (novo evento): contém `from_state`, `to_state`, `reason`, `correlation_id`, `context_snapshot`

Justificativa: nenhum evento existente carrega a noção de estado do sistema. `ReferenceDetected` indica detecção, não estado. `VersePresented` indica apresentação, não estado. O benchmark exige que cada mudança de estado seja um evento rastreável.

### required_context

- `current_state`: WAIT | PREPARE | PRESENT | IGNORE
- `active_book`: string | null
- `active_chapter`: int | null
- `pending_reference`: string | null (ex.: "1 Coríntios ?:?")
- `last_presented_reference`: string | null
- `segment_count_since_last_state_change`: int
- `has_biblical_content`: bool (para distinguir IGNORE de WAIT)

### algorithms

```
ALGORITMO: StateOrchestrator.on_event(event)

1. Se evento é SpeechTranscribed:
   a. Se current_state == PRESENT:
      - Se texto não contém referência: transitar para WAIT
      - Se texto contém mesma referência: permanecer PRESENT (repeat)
      - Se texto contém nova referência: processar como novo evento
   b. Se texto não contém nenhum nome de livro, número, nem gatilho bíblico:
      - transitar para IGNORE
   c. Caso contrário: permanecer no estado atual

2. Se evento é ReferenceCandidate:
   a. Se confidence >= 0.40 e < 0.75:
      - Se current_state != PREPARE: transitar para PREPARE
      - Atualizar active_book, pending_reference
   b. Se confidence >= 0.75 e < 0.98:
      - Se current_state != PREPARE: transitar para PREPARE
      - Atualizar active_book, active_chapter, pending_reference
   c. Se confidence >= 0.98:
      - Transitar para PRESENT
      - Atualizar last_presented_reference

3. Se evento é ReferenceDetected:
   a. Transitar para PRESENT
   b. Se (book_id, chapter, verse) == last_presented_reference: marcar repeat
   c. Atualizar last_presented_reference

4. Se evento é IntentUnknown:
   a. Se current_state == PRESENT: transitar para WAIT
   b. Caso contrário: permanecer

5. Se evento é IntentCandidate:
   a. Se foi aceito pelo resolver e gerou ReferenceDetected: tratar como passo 3
   b. Se foi rejeitado: permanecer no estado atual

6. Após cada transição, publicar StateChanged com from_state, to_state, reason
```

### edge_cases

- **Segmento vazio:** permanecer no estado atual. Não transitar.
- **Silêncio (sem SpeechTranscribed por N segundos):** se current_state == PREPARE, iniciar contagem de expiração. Se current_state == PRESENT, transitar para WAIT.
- **Livro detectado mas já em PREPARE para mesmo livro:** atualizar contexto, não publicar StateChanged (sem mudança de estado).
- **Livro detectado em PREPARE para livro diferente:** transitar PREPARE → PREPARE (novo livro). Publicar StateChanged com reason="book_changed".
- **ReferenceDetected sem PREPARE prévio (jump direto WAIT → PRESENT):** permitido. O parser pode detectar referência completa em um único segmento.
- **Dois ReferenceCandidate em sequência para mesma referência:** apenas o primeiro gera transição; o segundo é idempotente.
- **Número isolado em estado WAIT:** não deve gerar PREPARE. Números isolados só são processados se active_book != null.
- **Erro do STT (texto corrompido):** tratar como IntentUnknown, permanecer no estado atual.
- **Evento chega fora de ordem (ReferenceDetected antes de ReferenceCandidate):** processar normalmente; a máquina de estados deve ser robusta a ordem de eventos.

### failure_modes

1. **State drift:** o estado interno do orquestrador diverge do estado real do sistema. Detecção: comparar StateChanged com ReferenceDetected/VersePresented. Se ReferenceDetected é publicado mas o estado não é PRESENT, há drift.
2. **Stuck em PREPARE:** o sistema entra PREPARE e nunca sai. Detecção: métrica `prepare_duration` excede threshold configurável (ex.: 30 segundos).
3. **Stuck em PRESENT:** o sistema não reseta para WAIT após apresentação. Detecção: `present_duration` excede threshold.
4. **Falso IGNORE:** segmento com referência é classificado como IGNORE. Detecção: comparar IGNORE com presença de nomes de livros no texto.

### telemetry

- `state_transition_count`: total de transições por tipo (WAIT→PREPARE, PREPARE→PRESENT, etc.)
- `prepare_duration_ms`: tempo médio em PREPARE antes de transitar para PRESENT ou WAIT
- `present_duration_ms`: tempo médio em PRESENT antes de resetar para WAIT
- `ignore_ratio`: proporção de segmentos classificados como IGNORE
- `false_prepare_count`: vezes que PREPARE não resultou em PRESENT
- `state_orchestrator_latency_ms`: latência do orquestrador por evento

### unit_tests

1. "Estado inicial deve ser WAIT"
2. "ReferenceCandidate com confidence 0.40 deve transitar WAIT → PREPARE"
3. "ReferenceCandidate com confidence 0.75 deve transitar WAIT → PREPARE e manter active_chapter"
4. "ReferenceDetected com confidence 0.98 deve transitar PREPARE → PRESENT"
5. "ReferenceDetected sem PREPARE prévio deve transitar WAIT → PRESENT diretamente"
6. "IntentUnknown após PRESENT deve transitar PRESENT → WAIT"
7. "Segmento sem pista bíblica deve transitar WAIT → IGNORE"
8. "Segmento sem pista bíblica após IGNORE deve transitar IGNORE → WAIT"
9. "Segmento vazio não deve gerar transição"
10. "ReferenceCandidate para mesmo livro em PREPARE não deve gerar StateChanged"
11. "ReferenceCandidate para livro diferente em PREPARE deve gerar StateChanged com reason=book_changed"
12. "ReferenceDetected com mesma referência que last_presented_reference deve marcar repeat"
13. "Silêncio prolongado em PREPARE deve iniciar contagem de expiração"
14. "Silêncio prolongado em PRESENT deve transitar para WAIT"

### integration_tests

1. "Benchmark evento 1: WAIT → PREPARE ao detectar 'Primeiro Coríntios'"
2. "Benchmark evento 2: PREPARE → PRESENT ao detectar 'capítulo 14, versículo 10'"
3. "Benchmark evento 3: PRESENT → WAIT ao processar menções passivas de Gênesis e Salmos"
4. "Benchmark evento 6: PRESENT → WAIT ao processar alusão sem referência"
5. "Benchmark evento 9: WAIT → PREPARE ao detectar 'Evangelho de João'"
6. "Benchmark evento 11: PRESENT → WAIT ao processar citação não-atribuída"
7. "Replay completo do benchmark: 11 eventos, sequência de estados deve corresponder exatamente ao YAML"

### benchmark_mapping

[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
Não existe componente que centralize a decisão de estado. O `IncrementalBiblicalParser` mantém estado interno (`_current_book`, `_current_chapter`, `_current_verse`) mas não publica estados, apenas candidatos e detecções. O `BiblicalNLUService` é stateless. O `VersePresentationService` reage a `ReferenceDetected` sem contexto de estado prévio. O `SermonContextEngine` mantém `SermonContext` mas opera em fluxo paralelo não conectado ao pipeline principal.

**Módulo que deverá evoluir:**
Novo componente `StateOrchestrator` que assina eventos do `PipelineEventBus` e publica `StateChanged`. Este componente é o ponto único de decisão de estado.

**Por que este módulo foi escolhido:**
A máquina de estados é uma camada de orquestração que precisa observar múltiplas fontes (parser, semantic_engine, STT) e produzir uma saída unificada. Nenhum módulo existente tem esta responsabilidade. Estender o `IncrementalBiblicalParser` adicionaria responsabilidade de orquestração a um componente que deve ser focado em parsing. Estender o `VersePresentationService` misturaria decisão de estado com apresentação.

**Contratos que permanecem iguais:**
- `ReferenceCandidate`, `ReferenceDetected`, `IntentCandidate`, `IntentUnknown`, `SpeechTranscribed` não são modificados.
- `IncrementalBiblicalParser`, `BiblicalNLUService`, `SemanticEngine`, `ReferenceResolver` não mudam suas interfaces públicas.
- `VersePresentationService` continua consumindo `ReferenceDetected`.

**Contratos que precisarão mudar:**
- `VersePresentationService` deve assinar `StateChanged` (opcional) para saber se o sistema está em PRESENT (repeat) antes de re-apresentar.
- `PipelineEventBus` deve suportar o novo evento `StateChanged`.

### Invariantes

1. O estado atual é sempre exatamente um de: WAIT, PREPARE, PRESENT, IGNORE.
2. Toda mudança de estado gera um evento `StateChanged`.
3. `StateChanged` é publicado após o evento que causou a transição, nunca antes.
4. O orquestrador nunca publica `ReferenceDetected`; apenas reage a eles.
5. O estado PRESENT só é atingido quando uma referência completa (book + chapter + verse) foi detectada.

### Pré-condições

1. `IncrementalBiblicalParser` está ativo e publicando `ReferenceCandidate`/`ReferenceDetected`.
2. `PipelineEventBus` está operacional.
3. O orquestrador foi inicializado com estado = WAIT.

### Pós-condições

1. Após processar qualquer evento do pipeline, o orquestrador publicou zero ou um `StateChanged`.
2. Se `StateChanged` foi publicado, `from_state != to_state` (exceto repeat, onde `to_state == PRESENT` e `reason == "repeat"`).
3. O contexto interno (`active_book`, `active_chapter`, `pending_reference`, `last_presented_reference`) está consistente com o estado atual.

---

## RFC CAP-02

id: CAP-02
title: Propagação de contexto entre segmentos (active_book cross-segmentos)
objective: >
  Manter o livro ativo (active_book) entre segmentos de fala consecutivos
  para que capítulo e versículo chegando em segmentos separados sejam
  associados ao livro correto.

### current_behavior

O `IncrementalBiblicalParser` mantém `_current_book`, `_current_chapter`, `_current_verse` como estado interno entre chamadas de `process()`. Quando o pregador diz "Primeiro Coríntios" em um segmento e "capítulo 14, versículo 10" no segmento seguinte, o parser incremental pode completar a referência internamente.

No entanto, o `BiblicalNLUService` é explicitamente stateless: chama `Parser.parse(text)` sem passar estado do segmento anterior. O `Parser.parse()` recebe `BibleState | None`, mas este representa o estado da Bíblia no Holyrics (livro/capítulo atualmente aberto), não o estado do parser incremental.

O `SermonContextEngine` mantém `SermonContext.book/chapter` mas opera em um fluxo paralelo não conectado ao parser. Não há mecanismo que propague `active_book` do `IncrementalBiblicalParser` para o `BiblicalNLUService` ou para o orquestrador de estados.

Por que não atende ao benchmark: nos eventos 2, 5 e 10, o capítulo e versículo chegam em segmento separado do nome do livro. Sem propagação de contexto, o sistema não consegue completar a referência.

### expected_behavior

Quando o parser detecta um livro em um segmento e apenas capítulo/versículo no segmento seguinte, o sistema usa `active_book` do contexto para completar a referência. O formato compacto "10:27" é parseado como capítulo 10, versículo 27 quando há `active_book` ativo.

Comportamento observável:
- Após detectar "Primeiro Coríntios" (segmento A), o sistema mantém `active_book = "1 Coríntios"`.
- Ao receber "capítulo 14, versículo 10" (segmento B), o sistema associa a `active_book` e completa a referência.
- Ao receber "10:27" (segmento B) com `active_book = "João"`, o sistema interpreta como João 10:27.
- Números isolados em estado WAIT (sem `active_book`) não geram PREPARE.
- `active_book` expira após N segmentos sem menção ao livro (configurável).

### state_transitions

```
WAIT
  ↓ [livro detectado]
PREPARE (active_book = livro detectado)

PREPARE
  ↓ [capítulo detectado no segmento seguinte, usando active_book]
PREPARE (active_chapter = capítulo, pending_reference atualizada)

PREPARE
  ↓ [versículo detectado no segmento seguinte, usando active_book + active_chapter]
PRESENT

PREPARE
  ↓ [formato compacto "C:V" detectado, usando active_book]
PRESENT
```

### input_events

- `ReferenceCandidate` (do `IncrementalBiblicalParser`, carrega book/chapter/verse parciais)
- `SpeechTranscribed` (do STT, para detectar números isolados e formato compacto)
- `StateChanged` (do `StateOrchestrator`, para saber o estado atual)

### output_events

- `ReferenceCandidate` (enriquecido com `active_book` do contexto, se o segmento não continha nome de livro)
- `ReferenceDetected` (quando capítulo + versículo são completados usando contexto)

Justificativa: o `ReferenceCandidate` já existe. A novidade é que ele pode ser publicado com `book` preenchido pelo contexto mesmo quando o segmento atual não contém nome de livro. `ReferenceDetected` também já existe; a novidade é que pode ser publicado pelo orquestrador de contexto quando a referência é completada cross-segmento.

### required_context

- `active_book`: string | null (livro detectado no segmento mais recente)
- `active_book_id`: int | null
- `active_chapter`: int | null
- `pending_reference`: string | null (ex.: "1 Coríntios 14:?")
- `segments_since_book_mention`: int (contador para expiração)
- `current_state`: WAIT | PREPARE | PRESENT | IGNORE (do orquestrador)

### algorithms

```
ALGORITMO: ContextPropagator.on_segment(segment, current_state)

1. Se current_state == WAIT ou IGNORE:
   a. Não processar números isolados. Retornar sem ação.
   b. (Números em WAIT não são referência bíblica.)

2. Se current_state == PREPARE:
   a. Extrair números do segmento.
   b. Se há formato compacto "C:V" (ex.: "10:27"):
      - Se active_book != null:
        - chapter = C, verse = V
        - Publicar ReferenceDetected(book=active_book, chapter, verse)
        - Resetar segments_since_book_mention
      - Se active_book == null: ignorar (não há contexto)
   c. Se há marcadores explícitos ("capítulo N", "versículo N"):
      - Se "capítulo N" e active_book != null:
        - Atualizar active_chapter = N
        - Publicar ReferenceCandidate(book=active_book, chapter=N, confidence=0.75)
      - Se "versículo N" e active_book != null e active_chapter != null:
        - Publicar ReferenceDetected(book=active_book, chapter=active_chapter, verse=N)
   d. Se há apenas número isolado (sem marcador, sem "C:V"):
      - Se active_book != null e active_chapter == null:
        - Interpretar como capítulo: active_chapter = N
        - Publicar ReferenceCandidate(book=active_book, chapter=N, confidence=0.75)
      - Se active_book != null e active_chapter != null:
        - Interpretar como versículo
        - Publicar ReferenceDetected(book=active_book, chapter=active_chapter, verse=N)

3. Se current_state == PRESENT:
   a. Resetar contexto: active_book = null, active_chapter = null
   b. (O reset acontece porque PREPRESENT → WAIT no próximo segmento.)

4. Incrementar segments_since_book_mention a cada segmento.
   a. Se segments_since_book_mention > EXPIRY_THRESHOLD:
      - Limpar active_book, active_chapter, pending_reference
```

### edge_cases

- **Número isolado em WAIT:** não processar. Pode ser idade, tempo, contagem.
- **Número isolado em PREPARE sem active_book:** não processar. Não há contexto para associar.
- **Dois números isolados em sequência em PREPARE:** primeiro é capítulo, segundo é versículo.
- **Formato "C:V" em WAIT sem active_book:** ignorar. Pode ser hora (10:30) ou proporção.
- **Formato "C:V" em PREPARE com active_book:** processar como capítulo:versículo.
- **Nome de livro novo em PREPARE:** substituir active_book, resetar active_chapter.
- **Mesmo nome de livro em PREPARE:** idempotente, não gerar novo ReferenceCandidate.
- **Segmento com apenas "versículo 10" em PREPARE com active_book e active_chapter:** completar referência.
- **Segmento com apenas "versículo 10" em PREPARE com active_book mas sem active_chapter:** não completar; manter PREPARE.
- **STT reconhece "dez" em vez de "10":** o Normalizer converte extenso para dígito; deve funcionar.
- **STT reconhece "quatorze" em vez de "14":** idem.
- **Segmento com "capítulo 14 versículo 10" em um único segmento com active_book:** completar referência em um passo.

### failure_modes

1. **Contexto stale:** `active_book` expira mas não é limpo, causando associação errada. Detecção: `segments_since_book_mention` excede threshold sem reset.
2. **Falso capítulo:** número isolado interpretado como capítulo quando era outra coisa (ex.: "há 14 dias"). Detecção: `false_prepare_count` aumenta.
3. **Perda de contexto por segmento ruidoso:** um segmento com erro de STT entre o livro e o capítulo causa reset prematuro. Detecção: `context_misses` > `context_hits` em sessão.
4. **Ambiguidade capítulo vs versículo:** número isolado em PREPARE com active_book mas sem active_chapter pode ser capítulo ou versículo de capítulo anterior. Detecção: comparar com estrutura do livro (ex.: se número > maior capítulo do livro, é versículo).

### telemetry

- `context_hits`: vezes que active_book foi usado para completar referência
- `context_misses`: vezes que active_book estava null quando número isolado chegou em PREPARE
- `context_expiry_count`: vezes que active_book expirou por timeout
- `cross_segment_completion_count`: referências completadas usando contexto cross-segmento
- `false_prepare_from_context`: PREPARE gerado por número isolado que não resultou em PRESENT

### unit_tests

1. "active_book deve ser null no estado inicial"
2. "Detectar livro deve setar active_book e segments_since_book_mention = 0"
3. "Número isolado em WAIT não deve gerar ReferenceCandidate"
4. "Número isolado em PREPARE com active_book deve gerar ReferenceCandidate com chapter"
5. "Dois números isolados em sequência devem gerar ReferenceDetected"
6. "Formato '10:27' em PREPARE com active_book deve gerar ReferenceDetected"
7. "Formato '10:27' em WAIT sem active_book não deve gerar evento"
8. "Nome de livro novo em PREPARE deve substituir active_book"
9. "active_book deve expirar após EXPIRY_THRESHOLD segmentos"
10. "'versículo 10' em PREPARE com active_book e active_chapter deve completar referência"
11. "'versículo 10' em PREPARE com active_book mas sem active_chapter não deve completar"
12. "Reset de contexto após transição PRESENT → WAIT"

### integration_tests

1. "Benchmark evento 2: 'Primeiro Coríntios' (segmento A) + 'capítulo 14, versículo 10' (segmento B) deve resultar em ReferenceDetected para 1 Cor 14:10"
2. "Benchmark evento 5: 'aqui em Coríntios, capítulo 14, versículo 10' deve resultar em ReferenceDetected para 1 Cor 14:10 (repeat)"
3. "Benchmark evento 10: 'Evangelho de João' (segmento A) + '10:27' (segmento B) deve resultar em ReferenceDetected para João 10:27"
4. "Replay do benchmark: eventos 2, 5 e 10 devem produzir ReferenceDetected correto via contexto cross-segmento"

### benchmark_mapping

[2, 5, 10]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `IncrementalBiblicalParser` mantém estado interno mas não o expõe para outros componentes. O `BiblicalNLUService` é stateless por design. O `SermonContextEngine` mantém contexto mas não está conectado ao fluxo do parser. Não há ponte entre o estado interno do parser incremental e o contexto disponível ao orquestrador.

**Módulo que deverá evoluir:**
O `StateOrchestrator` (criado em CAP-01) deve ser estendido para manter `active_book`, `active_chapter` e `pending_reference` como parte de seu contexto interno. O `IncrementalBiblicalParser` já mantém este estado internamente; o orquestrador deve espelhar esse estado a partir dos eventos `ReferenceCandidate` que recebe.

**Por que este módulo foi escolhido:**
O orquestrador já é o ponto central de decisão de estado. Adicionar propagação de contexto a ele evita criar um novo componente. O `IncrementalBiblicalParser` não precisa mudar; ele já publica `ReferenceCandidate` com book/chapter parciais. O orquestrador apenas precisa acumular esses parciais.

**Contratos que permanecem iguais:**
- `ReferenceCandidate` e `ReferenceDetected` não mudam schema.
- `IncrementalBiblicalParser.process()` não muda.
- `BiblicalNLUService` não muda.

**Contratos que precisarão mudar:**
- O `StateOrchestrator` deve processar `SpeechTranscribed` (novo assinante) para detectar números isolados e formato compacto quando em PREPARE.
- O `StateOrchestrator` pode publicar `ReferenceCandidate` e `ReferenceDetected` derivados de contexto (nova responsabilidade).

### Invariantes

1. `active_book` é null quando `current_state` é WAIT ou IGNORE.
2. `active_book` é não-null quando `current_state` é PREPARE.
3. `segments_since_book_mention` é incrementado a cada segmento e resetado para 0 quando o livro é mencionado.
4. Números isolados nunca são processados quando `current_state` é WAIT.

### Pré-condições

1. `StateOrchestrator` (CAP-01) está operacional.
2. `active_book` está setado corretamente a partir de `ReferenceCandidate` anterior.
3. `current_state` é PREPARE.

### Pós-condições

1. Se um número isolado chega em PREPARE com `active_book` não-null, um `ReferenceCandidate` ou `ReferenceDetected` é publicado com `book = active_book`.
2. Se o formato "C:V" chega em PREPARE com `active_book` não-null, um `ReferenceDetected` é publicado.
3. Após transição PRESENT → WAIT, `active_book`, `active_chapter` e `pending_reference` são null.

---

## RFC CAP-03

id: CAP-03
title: Classificação de intenção do pregador (pedido de abertura vs. menção narrativa)
objective: >
  Distinguir pedidos de abertura bíblica ("Abra comigo em [livro]") de
  menções narrativas ("pregava ontem sobre [livro]", "Como diz lá em [livro]")
  para decidir se a menção de um livro deve disparar PREPARE ou manter WAIT.

### current_behavior

O `Parser` é puramente sintático: encontra nomes de livros via `ParserBookTable.resolve()` e números via `_parse_ref_suffix()`. Quando um livro é encontrado sem capítulo/versículo, retorna `action="uncertain"`. O `_has_trigger()` verifica verbos de comando (abre, mostrar, exibe) e pronomes demonstrativos, mas não classifica a intenção do pregador ao mencionar um livro.

O `IncrementalBiblicalParser` publica `ReferenceCandidate` com `confidence >= 0.40` sempre que detecta um nome de livro, independentemente do contexto linguístico. Não há filtro que diga "este livro foi mencionado narrativamente, não como pedido de abertura".

O `SemanticEngine` pode inferir intenção via LLM, mas não há um mecanismo que use essa inferência para suprimir PREPARE quando o parser já detectou o livro.

Por que não atende ao benchmark: o evento 3 contém "Gênesis" e "Salmos" como nomes detectáveis, mas o contexto é de menção passiva. O sistema deve manter WAIT. O evento 7 contém "Gênesis 3" que é uma referência ativa (não pedido formal de abertura, mas citação de local bíblico) e deve entrar PREPARE.

### expected_behavior

O sistema classifica a intenção do pregador ao mencionar um livro em três categorias:

1. **Pedido de abertura:** "Abra comigo em [livro]", "Vamos para [livro]", "[livro] capítulo N". Entra PREPARE.
2. **Citação ativa:** "Lá em [livro] [capítulo]", "aqui em [livro] capítulo N versículo V". Entra PREPARE.
3. **Menção narrativa:** "pregava ontem sobre [livro]", "Como diz lá em [livro]" (sem capítulo/versículo), "quando Jesus disse" (sem livro explícito). Mantém WAIT.

A classificação é determinística quando possível (padrões lexicais) e usa semantic_engine apenas como fallback para casos ambíguos.

Comportamento observável:
- "Abra comigo a sua Bíblia no livro de Primeiro Coríntios" → PREPARE
- "aqui em Coríntios, capítulo 14, versículo 10" → PREPARE
- "Lá em Gênesis 3" → PREPARE
- "pregava ontem sobre Gênesis" → WAIT
- "Como diz lá em Salmos" → WAIT (sem capítulo/versículo)

### state_transitions

```
WAIT
  ↓ [livro detectado + intenção = pedido de abertura]
PREPARE

WAIT
  ↓ [livro detectado + intenção = citação ativa (com capítulo)]
PREPARE

WAIT
  ↓ [livro detectado + intenção = menção narrativa]
WAIT (sem transição)

PREPARE
  ↓ [livro detectado + intenção = menção narrativa]
WAIT (expira PREPARE se a menção não é continuação)
```

### input_events

- `ReferenceCandidate` (do `IncrementalBiblicalParser`)
- `SpeechTranscribed` (do STT, para análise de intenção)
- `IntentCandidate` (do `SemanticEngine`, para casos ambíguos)

### output_events

- `IntentClassified` (novo evento): contém `intent_type` (OPEN_REQUEST | ACTIVE_CITATION | NARRATIVE_MENTION | AMBIGUOUS), `book`, `confidence`, `correlation_id`

Justificativa: nenhum evento existente carrega a classificação de intenção. O `ReferenceCandidate` indica detecção de livro, não intenção. O `IntentCandidate` é a saída do LLM, não a classificação final. O `StateOrchestrator` precisa de um evento que diga "esta menção é narrativa, não entre PREPARE".

### required_context

- `active_book`: string | null
- `current_state`: WAIT | PREPARE | PRESENT | IGNORE
- `recent_speech`: list[str] (últimos N segmentos para contexto linguístico)
- `speaker_intent`: OPEN_REQUEST | ACTIVE_CITATION | NARRATIVE_MENTION | AMBIGUOUS | null

### algorithms

```
ALGORITMO: IntentClassifier.classify(text, book_detected, current_state)

1. Se current_state == PREPARE e book_detected == active_book:
   a. Retornar ACTIVE_CITATION (continuação de referência em construção)

2. Se current_state == PREPARE e book_detected != active_book:
   a. Novo livro mencionado. Classificar independentemente.

3. Extrair padrões lexicais do texto:
   a. PADRÕES DE PEDIDO DE ABERTURA (determinístico):
      - "abra comigo" + livro → OPEN_REQUEST
      - "vamos para" + livro → OPEN_REQUEST
      - "abra em" + livro → OPEN_REQUEST
      - "vamos ler" + livro → OPEN_REQUEST
      - "acompanhe comigo" + livro → OPEN_REQUEST
   b. PADRÕES DE CITAÇÃO ATIVA (determinístico):
      - "lá em" + livro + número → ACTIVE_CITATION
      - "aqui em" + livro + número → ACTIVE_CITATION
      - livro + "capítulo" + número → ACTIVE_CITATION
      - livro + número (sem prefixo narrativo) → ACTIVE_CITATION
   c. PADRÕES DE MENÇÃO NARRATIVA (determinístico):
      - "pregava" / "pregou" + "sobre" + livro → NARRATIVE_MENTION
      - "sobre" + livro (sem número) → NARRATIVE_MENTION
      - "como diz" + livro (sem número) → NARRATIVE_MENTION
      - "ontem" + livro → NARRATIVE_MENTION
      - "outra vez" + livro (sem número) → NARRATIVE_MENTION

4. Se nenhum padrão determinístico casou:
   a. Se livro detectado sem número e sem padrão de abertura:
      - Retornar AMBIGUOUS
   b. Se livro detectado com número:
      - Retornar ACTIVE_CITATION (presunção: número indica citação)

5. Publicar IntentClassified com intent_type, book, confidence
```

### edge_cases

- **Livro detectado sem nenhum prefixo:** "Gênesis 3" sem "lá em" nem "abra em". Tem número, então ACTIVE_CITATION (presunção do passo 4b).
- **Livro detectado com "sobre" mas também com número:** "sobre Gênesis 3". O número indica citação ativa; "sobre" é ambíguo. Decisão: se há número, ACTIVE_CITATION prevalece.
- **"Como diz lá em Salmos" sem número:** NARRATIVE_MENTION (padrão "como diz" + livro sem número).
- **"Como diz lá em Salmos 91" com número:** ACTIVE_CITATION (número presente).
- **Livro mencionado em oração:** "Senhor, abra-nos em João 3:16". "abra" é verbo de comando, mas em contexto de oração. Decisão: OPEN_REQUEST (o padrão lexical prevalece; o sistema não interpreta contexto pragmático).
- **Livro mencionado em pergunta retórica:** "Vocês lembram de Gênesis 1?" Tem número, então ACTIVE_CITATION.
- **Livro mencionado duas vezes no mesmo segmento:** "Lá em Gênesis, no começo de tudo". Uma menção de livro, sem número. NARRATIVE_MENTION.
- **Verbos sinônimos não catalogados:** "veja em João 3". "veja" não está na lista de padrões de abertura. Fallback: se há número, ACTIVE_CITATION.
- **STT reconhece "abra" como "habra":** o Normalizer remove diacritics e pontuação; "habra" não casa com "abra". Fallback: se há livro + número, ACTIVE_CITATION.
- **Segmento com múltiplos livros:** "De Gênesis a Apocalipse". Sem números. NARRATIVE_MENTION para ambos.

### failure_modes

1. **Falso OPEN_REQUEST:** verbo de comando detectado em contexto narrativo. "E ele disse: abra em João". Detecção: comparar com aspas ou contexto de citação indireta. Mitigação: padrões lexicais são conservadores; apenas casam exatamente.
2. **Falso NARRATIVE_MENTION:** "pregava ontem sobre Gênesis 3:15" classificado como NARRATIVE_MENTION porque "pregava sobre" casou primeiro. Detecção: se há número após o livro, ACTIVE_CITATION deve prevalecer sobre NARRATIVE_MENTION. O algoritmo deve verificar número antes de classificar.
3. **AMBIGUOUS não resolvido:** livro sem número e sem padrão. Detecção: `ambiguous_count` na telemetria. Mitigação: default conservador é NARRATIVE_MENTION (mantém WAIT).
4. **Padrão lexical não catalogado:** novo verbo de abertura não reconhecido. Detecção: `unknown_intent_count`. Mitigação: o semantic_engine pode ser consultado como fallback.

### telemetry

- `intent_classification_count`: total de classificações por tipo
- `open_request_count`: pedidos de abertura detectados
- `narrative_mention_count`: menções narrativas detectadas
- `active_citation_count`: citações ativas detectadas
- `ambiguous_count`: casos não resolvidos deterministicamente
- `false_open_request`: pedidos classificados como OPEN_REQUEST que não resultaram em PRESENT
- `false_narrative_mention`: menções classificadas como NARRATIVE_MENTION mas que o pregador usou como abertura
- `intent_classifier_latency_ms`: latência da classificação

### unit_tests

1. "'Abra comigo em João' deve classificar como OPEN_REQUEST"
2. "'Vamos para Lucas 15' deve classificar como OPEN_REQUEST"
3. "'pregava ontem sobre Gênesis' deve classificar como NARRATIVE_MENTION"
4. "'Como diz lá em Salmos' deve classificar como NARRATIVE_MENTION"
5. "'Lá em Gênesis 3' deve classificar como ACTIVE_CITATION"
6. "'aqui em Coríntios capítulo 14' deve classificar como ACTIVE_CITATION"
7. "'Gênesis' sem número e sem prefixo deve classificar como AMBIGUOUS"
8. "'Gênesis 3' sem prefixo deve classificar como ACTIVE_CITATION (presunção por número)"
9. "'sobre Gênesis 3' deve classificar como ACTIVE_CITATION (número prevalece)"
10. "'Como diz lá em Salmos 91' deve classificar como ACTIVE_CITATION (número presente)"
11. "Em PREPARE com mesmo active_book, deve classificar como ACTIVE_CITATION (continuação)"
12. "Múltiplos livros sem número devem classificar como NARRATIVE_MENTION"

### integration_tests

1. "Benchmark evento 1: 'Abra comigo no livro de Primeiro Coríntios' deve classificar como OPEN_REQUEST e entrar PREPARE"
2. "Benchmark evento 3: 'pregava ontem sobre Gênesis' deve classificar como NARRATIVE_MENTION e manter WAIT"
3. "Benchmark evento 3: 'Como diz lá em Salmos' sem número deve classificar como NARRATIVE_MENTION e manter WAIT"
4. "Benchmark evento 7: 'Lá em Gênesis 3' deve classificar como ACTIVE_CITATION e entrar PREPARE"
5. "Benchmark evento 9: 'Evangelho de João' seguido de número deve classificar como ACTIVE_CITATION e entrar PREPARE"
6. "Replay do benchmark: eventos 3 e 7 devem produzir classificações corretas"

### benchmark_mapping

[3, 7]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `Parser` detecta livros mas não classifica intenção. O `_has_trigger()` verifica verbos de comando mas não os associa à detecção de livro. O `IncrementalBiblicalParser` publica `ReferenceCandidate` sempre que detecta um livro, sem filtrar por intenção. O `SemanticEngine` pode inferir intenção mas não há mecanismo que use essa inferência para suprimir `ReferenceCandidate`.

**Módulo que deverá evoluir:**
O `StateOrchestrator` (CAP-01) deve ser estendido para incluir um classificador de intenção que opera antes de decidir a transição de estado. O classificador pode ser um sub-componente interno do orquestrador, usando padrões lexicais determinísticos. O `Parser._has_trigger()` já cataloga verbos de comando; esta lógica pode ser reutilizada e estendida.

**Por que este módulo foi escolhido:**
O orquestrador já é o ponto de decisão de estado. A classificação de intenção é um input para essa decisão. Colocar o classificador dentro do orquestrador evita adicionar um novo componente no pipeline e mantém a lógica de decisão centralizada. O `Parser` não precisa mudar; ele continua detectando livros. O orquestrador filtra.

**Contratos que permanecem iguais:**
- `Parser.parse()` não muda.
- `IncrementalBiblicalParser.process()` não muda.
- `ReferenceCandidate` não muda schema.

**Contratos que precisarão mudar:**
- O `StateOrchestrator` deve assinar `SpeechTranscribed` (se já não assina via CAP-02) para classificar intenção antes de processar `ReferenceCandidate`.
- Novo evento `IntentClassified` no `PipelineEventBus`.

### Invariantes

1. Se `intent_type == NARRATIVE_MENTION`, o sistema não transita para PREPARE.
2. Se `intent_type == OPEN_REQUEST` ou `ACTIVE_CITATION` e há livro detectado, o sistema transita para PREPARE.
3. Se há número após o livro, `intent_type` nunca é `NARRATIVE_MENTION` (número indica citação ativa).
4. A classificação determinística tem precedência sobre o semantic_engine.

### Pré-condições

1. `StateOrchestrator` (CAP-01) está operacional.
2. `SpeechTranscribed` está disponível no EventBus.
3. O `Normalizer` está operacional para normalizar texto antes da classificação.

### Pós-condições

1. Após classificar, um `IntentClassified` é publicado com `intent_type` não-null.
2. Se `intent_type == NARRATIVE_MENTION` e `current_state == WAIT`, o estado permanece WAIT.
3. Se `intent_type == OPEN_REQUEST` ou `ACTIVE_CITATION`, o orquestrador processa a transição para PREPARE se aplicável.

---

## RFC CAP-04

id: CAP-04
title: Resolução anafórica de livro (nome sem ordinal)
objective: >
  Resolver nomes de livros bíblicos mencionados sem ordinal ("Coríntios")
  usando o contexto de referências recentes para determinar se se refere
  à primeira ou segunda epístola.

### current_behavior

O `ParserBookTable.resolve()` faz longest-match contra aliases normalizadas. As aliases de 1 Coríntios incluem "1 coríntios", "primeiro coríntios", "i coríntios", mas não "coríntios" isolado. Quando o pregador diz "aqui em Coríntios", o parser não encontra o livro e retorna `None`.

O `SermonContextEngine` mantém `recent_books` no `SermonContext`, mas o parser não consulta este contexto. O `BibleState` passado ao `Parser.parse()` representa o estado do Holyrics, não o histórico de livros mencionados.

Por que não atende ao benchmark: o evento 4 contém "aqui em Coríntios" que deve resolver para 1 Coríntios. Sem esta capacidade, o parser não detecta o livro e o evento 4 não dispara PREPARE.

### expected_behavior

Quando o pregador menciona "Coríntios" sem ordinal, o sistema consulta `recent_books` e `last_presented_reference` no contexto. Se 1 Coríntios está no histórico recente, resolve para 1 Coríntios. Se 2 Coríntios está no histórico, resolve para 2 Coríntios. Se ambos estão, prefere o mais recente. Se nenhum está no histórico, usa o default: 1 Coríntios (primeira epístola é o default para ordinal omitido).

Comportamento observável:
- Após apresentar 1 Cor 14:10, "aqui em Coríntios" resolve para 1 Coríntios.
- "em Coríntios" sem contexto prévio resolve para 1 Coríntios (default).
- "em Tessalonicenses" sem contexto prévio resolve para 1 Tessalonicenses (default).
- "em João" sempre resolve para João (não há ambiguidade de ordinal).

### state_transitions

```
PREPARE (active_book = 1 Coríntios)
  ↓ ["Coríntios" detectado + contexto resolve para 1 Coríntios]
PREPARE (mantém active_book, atualiza capítulo se presente)

WAIT
  ↓ ["Coríntios" detectado + sem contexto + default = 1 Coríntios]
PREPARE (active_book = 1 Coríntios)
```

### input_events

- `ReferenceCandidate` (do `IncrementalBiblicalParser`, pode conter book=null se o parser não resolveu)
- `SpeechTranscribed` (do STT, para detectar nome sem ordinal)
- `StateChanged` (do orquestrador, para consultar recent_books)

### output_events

- `ReferenceCandidate` (com `book` resolvido anafóricamente)

Justificativa: reutiliza o evento existente. A novidade é que o `book` pode ser preenchido pelo resolvedor anafórico quando o parser não encontrou o livro.

### required_context

- `recent_books`: list[str] (livros mencionados recentemente, do `SermonContext`)
- `last_presented_reference`: string | null (última referência apresentada)
- `active_book`: string | null

### algorithms

```
ALGORITMO: AnaphoricBookResolver.resolve(text, recent_books, last_presented_reference)

1. Extrair candidatos de nome de livro sem ordinal do texto:
   a. Lista de nomes base que têm ambiguidade de ordinal:
      - "coríntios" → {1 Coríntios, 2 Coríntios}
      - "tessalonicenses" → {1 Tessalonicenses, 2 Tessalonicenses}
      - "timóteo" → {1 Timóteo, 2 Timóteo}
      - "pedro" → {1 Pedro, 2 Pedro}
      - "joão" → {João, 1 João, 2 João, 3 João} (caso especial: João é único, 1/2/3 João são epístolas)
      - "reis" → {1 Reis, 2 Reis}
      - "crônicas" → {1 Crônicas, 2 Crônicas}
      - "samuel" → {1 Samuel, 2 Samuel}
   b. Para cada candidato, verificar se aparece no texto normalizado.

2. Para cada nome base encontrado:
   a. Consultar recent_books:
      - Se apenas um dos ordinais está em recent_books: resolver para esse.
      - Se ambos estão: resolver para o mais recente (topo de recent_books).
      - Se nenhum está:
        - Consultar last_presented_reference:
          - Se last_presented_reference contém o nome base: resolver para esse ordinal.
        - Se ainda não resolvido: usar default (ordinal 1).
   b. Para "joão":
      - "joão" sem qualificador resolve para João (evangelho), não 1 João.
      - "epístola de joão" ou "carta de joão" resolve para 1 João (default).
      - "1 joão" ou "primeiro joão" resolve via alias normal.

3. Retornar livro resolvido com confidence = 0.5 (anafórico, não explícito).
```

### edge_cases

- **"Coríntios" sem contexto e sem default:** não deve acontecer; default é sempre ordinal 1.
- **"Coríntios" com ambos no histórico:** preferir o mais recente. Se o mais recente é 2 Coríntios mas o pregador está re-referenciando 1 Coríntios (ex.: "aqui em Coríntios capítulo 14" após apresentar 1 Cor 14:10), o `last_presented_reference` deve ter precedência sobre `recent_books`.
- **"Tessalonicenses" sem contexto:** resolve para 1 Tessalonicenses (default).
- **"Samuel" sem contexto:** resolve para 1 Samuel (default).
- **"João" ambíguo:** "João" isolado resolve para o Evangelho de João (id=43), não para as epístolas. As epístolas exigem ordinal explícito ou "epístola/carta de João".
- **"Reis" sem contexto:** resolve para 1 Reis (default).
- **Nome base não está na lista de ambiguidade:** "Gênesis", "Salmos", "Provérbios" não têm ambiguidade de ordinal. O parser normal já resolve estes. O resolvedor anafórico não é acionado.
- **STT reconhece "corintios" sem acento:** o Normalizer remove diacritics; "corintios" casa com "coríntios" normalizado.
- **Nome base mencionado com ordinal em texto anterior mas sem ordinal no segmento atual:** o resolvedor deve usar o contexto do segmento anterior.
- **Múltiplos nomes base no mesmo segmento:** "De Coríntios a Tessalonicenses". Resolver cada um independentemente.

### failure_modes

1. **Default errado:** o pregador diz "Coríntios" referindo-se a 2 Coríntios, mas o default é 1. Detecção: se capítulo/versículo não existe em 1 Coríntios mas existe em 2 Coríntios, o `ReferenceResolver` pode detectar a inconsistência. Mitigação: se a referência é invalidada, tentar o outro ordinal.
2. **Contexto stale:** `recent_books` contém 1 Coríntios de 10 minutos atrás, mas o pregador mudou para 2 Coríntios. Detecção: `segments_since_book_mention` excede threshold. Mitigação: expirar `recent_books` junto com `active_book`.
3. **Falso positivo de nome base:** "coríntios" aparece como parte de outra palavra. Detecção: o `ParserBookTable._word_find()` já usa word boundaries; o resolvedor anafórico deve fazer o mesmo.
4. **Ambiguidade João vs epístolas:** "joão" resolve para Evangelho, mas o pregador queria 1 João. Detecção: se capítulo > 21 (último capítulo de João), tentar 1 João. Mitigação: o `ReferenceResolver` valida capítulo contra o livro.

### telemetry

- `anaphoric_resolution_count`: total de resoluções anafóricas
- `anaphoric_from_context`: resoluções que usaram recent_books ou last_presented_reference
- `anaphoric_from_default`: resoluções que usaram default (ordinal 1)
- `anaphoric_ambiguous_count`: casos onde ambos os ordinais estavam no contexto
- `anaphoric_failure_count`: resoluções que resultaram em referência inválida
- `anaphoric_latency_ms`: latência da resolução

### unit_tests

1. "'Coríntios' com recent_books=[1 Coríntios] deve resolver para 1 Coríntios"
2. "'Coríntios' com recent_books=[2 Coríntios] deve resolver para 2 Coríntios"
3. "'Coríntios' com recent_books=[2 Cor, 1 Cor] deve resolver para 2 Coríntios (mais recente)"
4. "'Coríntios' com last_presented_reference='1 Cor 14:10' deve resolver para 1 Coríntios"
5. "'Coríntios' sem contexto deve resolver para 1 Coríntios (default)"
6. "'Tessalonicenses' sem contexto deve resolver para 1 Tessalonicenses (default)"
7. "'João' deve resolver para Evangelho de João, não 1 João"
8. "'Samuel' sem contexto deve resolver para 1 Samuel (default)"
9. "'Reis' sem contexto deve resolver para 1 Reis (default)"
10. "'Coríntios' com recent_books=[] e last_presented_reference=null deve resolver para 1 Coríntios"
11. "Nome não ambíguo ('Gênesis') não deve acionar o resolvedor anafórico"
12. "Múltiplos nomes base no mesmo segmento devem resolver independentemente"

### integration_tests

1. "Benchmark evento 4: após evento 2 (1 Cor 14:10 apresentado), 'aqui em Coríntios' deve resolver para 1 Coríntios e entrar PREPARE"
2. "Benchmark evento 5: 'aqui em Coríntios, capítulo 14, versículo 10' deve resolver para 1 Cor 14:10 (repeat)"
3. "Replay do benchmark: evento 4 deve produzir ReferenceCandidate com book=1 Coríntios via resolução anafórica"

### benchmark_mapping

[4]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `ParserBookTable` resolve apenas contra aliases explicitamente cadastradas em `books.json`. "Coríntios" sem ordinal não está cadastrado como alias porque seria ambíguo entre 1 e 2 Coríntios. O parser não consulta contexto externo durante a resolução de livro.

**Módulo que deverá evoluir:**
O `StateOrchestrator` (CAP-01) deve ser estendido com um resolvedor anafórico que opera como fallback quando o `ParserBookTable.resolve()` retorna `None` mas o texto contém um nome base conhecido. O `config/books.json` pode ser estendido com uma lista de nomes base e seus ordinais possíveis, sem adicionar aliases ambíguas à tabela principal.

**Por que este módulo foi escolhido:**
O orquestrador já mantém `recent_books` e `last_presented_reference` no contexto. O resolvedor anafórico precisa deste contexto, que está disponível no orquestrador. Estender o `ParserBookTable` adicionaria dependência de contexto a um componente que é stateless por design.

**Contratos que permanecem iguais:**
- `ParserBookTable.resolve()` não muda.
- `books.json` não muda (novos nomes base podem ser adicionados em campo separado, não em aliases).
- `ReferenceCandidate` não muda schema.

**Contratos que precisarão mudar:**
- O `StateOrchestrator` deve interceptar `ReferenceCandidate` com `book=null` e tentar resolução anafórica antes de descartar.
- `config/books.json` pode ganhar um campo `base_names` para livros com ambiguidade de ordinal.

### Invariantes

1. O resolvedor anafórico só é acionado quando `ParserBookTable.resolve()` retorna `None`.
2. Nomes não ambíguos (ex.: "Gênesis", "Salmos") nunca acionam o resolvedor anafórico.
3. `confidence` de uma resolução anafórica é 0.5 (menor que resolução direta).
4. O default para ordinal omitido é sempre 1 (primeira epístola/livro).

### Pré-condições

1. `StateOrchestrator` (CAP-01) está operacional.
2. `recent_books` e `last_presented_reference` estão disponíveis no contexto.
3. O `ParserBookTable.resolve()` já foi tentado e retornou `None`.

### Pós-condições

1. Se o texto contém um nome base ambíguo, um `ReferenceCandidate` é publicado com `book` resolvido e `confidence = 0.5`.
2. Se o texto não contém nenhum nome base ambíguo, nenhum evento é publicado por esta capacidade.
3. O livro resolvido é consistente com `recent_books` ou `last_presented_reference` quando disponível.

---

## RFC CAP-05

id: CAP-05
title: Expiração de referência pendente por mudança de assunto
objective: >
  Expirar referências pendentes (PREPARE sem versículo) quando o pregador
  muda de assunto, abandonando a referência incompleta e transitando
  de PREPARE para WAIT.

### current_behavior

O `SermonContextEngine._apply_expiry()` expira `book` e `chapter` do `SermonContext` após N atualizações sem menção (`book_expiry=15`, `chapter_expiry=10`). Este mecanismo é baseado em contagem de atualizações, não em detecção de mudança de assunto.

O `IncrementalBiblicalParser` mantém `_current_book`/`_current_chapter` mas não tem mecanismo explícito de expiração. Ele publica `ReferenceCandidate` mas não publica um evento de "abandono" ou "expiração" quando o contexto muda.

O `StateOrchestrator` (CAP-01) mantém `pending_reference` mas não tem lógica para expirá-lo.

Por que não atende ao benchmark: o evento 8 testa exatamente isto. Gênesis 3 está em PREPARE (evento 7). Quando o pregador passa a falar sobre Tessalônica, o sistema deve abandonar Gênesis 3 e voltar para WAIT. Sem expiração, o sistema permanece em PREPARE e pode incorretamente associar "10:27" (evento 10) a Gênesis 3.

### expected_behavior

O sistema detecta mudança de assunto por dois sinais:

1. **Novo livro detectado:** quando um livro diferente de `active_book` é mencionado, a referência pendente do livro anterior é expirada.
2. **Timeout de segmentos:** quando N segmentos consecutivos chegam sem menção ao `active_book` e sem continuação numérica, a referência pendente expira.

Ao expirar, o sistema transita PREPARE → WAIT, limpa `active_book`, `active_chapter` e `pending_reference`, e publica `StateChanged` com `reason="prepare_expired"`.

Comportamento observável:
- Gênesis 3 em PREPARE; pregador menciona "igreja de Tessalônica" → PREPARE expira, transita para WAIT.
- Gênesis 3 em PREPARE; 5 segmentos depois sem menção a Gênesis → PREPARE expira, transita para WAIT.
- 1 Coríntios em PREPARE; próximo segmento contém "capítulo 14" → PREPARE mantido (continuação).

### state_transitions

```
PREPARE
  ↓ [novo livro detectado (diferente de active_book)]
WAIT (expiração por mudança de livro)

PREPARE
  ↓ [N segmentos sem menção ao livro e sem continuação numérica]
WAIT (expiração por timeout)

PREPARE
  ↓ [continuação numérica detectada (capítulo/versículo para active_book)]
PREPARE (mantém, atualiza contexto)

PREPARE
  ↓ [versículo detectado completando referência]
PRESENT
```

### input_events

- `ReferenceCandidate` (do `IncrementalBiblicalParser`, para detectar novo livro)
- `SpeechTranscribed` (do STT, para contar segmentos sem menção)
- `IntentClassified` (do `IntentClassifier`, para saber se menção é narrativa)
- `StateChanged` (do orquestrador, para saber estado atual)

### output_events

- `StateChanged` (com `reason="prepare_expired"`, `from_state=PREPARE`, `to_state=WAIT`)

Justificativa: reutiliza o evento `StateChanged` de CAP-01. A novidade é o `reason="prepare_expired"` que distingue expiração de outras transições PREPARE → WAIT.

### required_context

- `current_state`: WAIT | PREPARE | PRESENT | IGNORE
- `active_book`: string | null
- `active_chapter`: int | null
- `pending_reference`: string | null
- `segments_since_book_mention`: int
- `segments_since_chapter_mention`: int
- `expiry_threshold_segments`: int (configurável, default=5)
- `recent_books`: list[str]

### algorithms

```
ALGORITMO: PrepareExpiryManager.on_segment(segment, current_state, context)

1. Se current_state != PREPARE:
   a. Retornar sem ação. (Expiração só se aplica a PREPARE.)

2. Verificar se o segmento contém nome de livro:
   a. Se contém livro diferente de active_book:
      - Expirar referência pendente.
      - Publicar StateChanged(from=PREPARE, to=WAIT, reason="prepare_expired",
        detail="book_changed: {active_book} → {new_book}")
      - Limpar active_book, active_chapter, pending_reference.
      - Retornar. (O novo livro será processado pelo fluxo normal.)

   b. Se contém mesmo livro (active_book):
      - Resetar segments_since_book_mention = 0.
      - Retornar sem expirar. (Continuação da mesma referência.)

3. Verificar se o segmento contém continuação numérica:
   a. Se contém "capítulo N" ou número isolado (em PREPARE com active_book):
      - Resetar segments_since_book_mention = 0.
      - Retornar sem expirar. (Continuação da referência.)

4. Se segmento não contém livro nem continuação numérica:
   a. Incrementar segments_since_book_mention.
   b. Se segments_since_book_mention > expiry_threshold_segments:
      - Expirar referência pendente.
      - Publicar StateChanged(from=PREPARE, to=WAIT, reason="prepare_expired",
        detail="timeout: {segments_since_book_mention} segments without mention")
      - Limpar active_book, active_chapter, pending_reference.
```

### edge_cases

- **Mudança para livro que é menção narrativa (CAP-03):** se `IntentClassified` diz `NARRATIVE_MENTION` para o novo livro, não expirar o PREPARE atual. O novo livro é narrativo, não um pedido de abertura. Decisão: apenas expirar se o novo livro é classificado como `OPEN_REQUEST` ou `ACTIVE_CITATION`. Se é `NARRATIVE_MENTION`, incrementar `segments_since_book_mention` mas não expirar imediatamente.
- **Segmento com número que não é referência:** "há 14 dias" em PREPARE. O número 14 pode ser interpretado como capítulo. Detecção: se o número não vem precedido de "capítulo" nem "versículo" e `active_chapter` já está setado, não interpretar como versículo automaticamente. Mitigação: o algoritmo de CAP-02 já trata isso; o expiry manager apenas verifica se houve continuação.
- **Segmento vazio em PREPARE:** incrementar `segments_since_book_mention`. Não expirar imediatamente (um segmento vazio pode ser pausa do pregador).
- **Mudança de assunto sutil:** o pregador para de falar de Gênesis 3 e começa a falar sobre "a guerra" sem mencionar livro. Não há novo livro para disparar expiração. Detecção: timeout de segmentos.
- **Retorno ao mesmo livro após divagação:** "Gênesis 3" → 3 segmentos sobre outro assunto → "como eu dizia em Gênesis 3". Se `segments_since_book_mention` ainda não excedeu threshold, o PREPARE é mantido. Se excedeu, o sistema já transitou para WAIT e "Gênesis 3" é tratado como nova referência.
- **Expiração entre capítulo e versículo:** "João 3" (PREPARE) → 6 segmentos depois → "versículo 16". Se expirou, "versículo 16" chega em WAIT sem `active_book` e não completa referência. Este é o comportamento correto: se o pregador demora demais, o contexto expira.
- **Múltiplas referências pendentes:** o sistema só mantém uma `pending_reference` por vez. Se o pregador diz "Gênesis 3" e depois "João 10" sem completar nenhuma, a segunda substitui a primeira.
- **Silêncio prolongado:** se nenhum `SpeechTranscribed` chega por N segundos, tratar como timeout. O `segments_since_book_mention` deve incluir segmentos de silêncio.

### failure_modes

1. **Expiração prematura:** PREPARE expira antes de o pregador completar a referência. Causa: `expiry_threshold_segments` muito baixo. Detecção: `expired_reference_count` alto com `prepare_duration` curto. Mitigação: ajustar threshold; default conservador é 5.
2. **Expiração tardia:** PREPARE permanece ativo por muito tempo, causando associação errada. Causa: threshold muito alto ou segmentos de divagação resetam o contador. Detecção: `prepare_duration` excede 60 segundos. Mitigação: timeout absoluto em segundos, não apenas contagem de segmentos.
3. **Falsa mudança de livro:** menção narrativa de outro livro dispara expiração. Causa: `IntentClassified` não consultado. Detecção: `false_expiry_count`. Mitigação: verificar `intent_type` antes de expirar.
4. **Expiração não detecta mudança sutil:** pregador muda de assunto sem mencionar novo livro. Detecção: `prepare_duration` alto sem expiração. Mitigação: timeout de segmentos puro.

### telemetry

- `prepare_expired_count`: total de expirações
- `prepare_expired_by_book_change`: expirações por mudança de livro
- `prepare_expired_by_timeout`: expirações por timeout de segmentos
- `prepare_duration_ms`: tempo médio em PREPARE antes de expirar
- `false_expiry_count`: expirações seguidas de re-menção do mesmo livro (indicaria expiração prematura)
- `expired_reference_book`: distribuição de livros cuja referência expirou
- `prepare_to_present_ratio`: proporção de PREPARE que resultou em PRESENT vs expirou

### unit_tests

1. "PREPARE com novo livro detectado deve expirar e transitar para WAIT"
2. "PREPARE com mesmo livro detectado não deve expirar"
3. "PREPARE com continuação numérica não deve expirar"
4. "PREPARE após N segmentos sem menção deve expirar por timeout"
5. "PREPARE com segmento vazio deve incrementar contador mas não expirar"
6. "PREPARE com menção narrativa de outro livro não deve expirar imediatamente"
7. "Expiração deve limpar active_book, active_chapter e pending_reference"
8. "Expiração deve publicar StateChanged com reason=prepare_expired"
9. "Após expiração, número isolado não deve ser associado ao livro expirado"
10. "Threshold configurável deve ser respeitado"
11. "Retorno ao mesmo livro após expiração deve criar nova PREPARE, não reativar a anterior"
12. "Múltiplas referências pendentes: segunda substitui primeira"

### integration_tests

1. "Benchmark evento 7 → 8: Gênesis 3 em PREPARE, depois menção de Tessalônica deve expirar PREPARE e transitar para WAIT"
2. "Benchmark evento 8: após expiração, 'igreja de Tessalônica' não deve gerar ReferenceDetected"
3. "Benchmark evento 10: após expiração de Gênesis 3, '10:27' com active_book=João deve resolver para João 10:27, não Gênesis"
4. "Replay do benchmark: evento 8 deve produzir StateChanged com reason=prepare_expired"

### benchmark_mapping

[8]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `SermonContextEngine._apply_expiry()` expira por contagem de atualizações (15 para livro, 10 para capítulo), mas este mecanismo opera no fluxo paralelo do `SermonContext`, não no fluxo principal do `StateOrchestrator`. O `IncrementalBiblicalParser` não publica eventos de expiração. Não há detecção de mudança de assunto baseada em novo livro.

**Módulo que deverá evoluir:**
O `StateOrchestrator` (CAP-01) deve ser estendido com lógica de expiração que opera dentro do método `on_event`. A lógica de expiração do `SermonContextEngine._apply_expiry()` pode ser reutilizada como referência para a política de threshold, mas a execução deve ocorrer no orquestrador, que tem acesso ao estado atual e ao contexto.

**Por que este módulo foi escolhido:**
O orquestrador é o único componente que conhece o estado atual (PREPARE) e o contexto (`active_book`, `pending_reference`). A expiração é uma transição de estado, e o orquestrador é o responsável por transições. Estender o `SermonContextEngine` adicionaria um segundo ponto de decisão de estado, violando a centralização de CAP-01.

**Contratos que permanecem iguais:**
- `SermonContextEngine` não muda (continua operando em fluxo paralelo).
- `IncrementalBiblicalParser` não muda.
- `StateChanged` não muda schema (apenas novo valor de `reason`).

**Contratos que precisarão mudar:**
- O `StateOrchestrator` deve implementar lógica de expiração ativa (não apenas reativa).
- O `StateOrchestrator` deve consultar `IntentClassified` (de CAP-03) antes de expirar por mudança de livro.

### Invariantes

1. A expiração só ocorre quando `current_state == PREPARE`.
2. Após expiração, `pending_reference == null`, `active_book == null`, `active_chapter == null`.
3. Após expiração, `current_state == WAIT`.
4. Nenhum `ReferenceDetected` pode ser emitido para a referência expirada após a expiração.
5. A expiração por mudança de livro só ocorre se o novo livro é classificado como `OPEN_REQUEST` ou `ACTIVE_CITATION` (não `NARRATIVE_MENTION`).

### Pré-condições

1. `StateOrchestrator` (CAP-01) está operacional.
2. `current_state == PREPARE`.
3. `active_book` é não-null.
4. `IntentClassifier` (CAP-03) está operacional para classificar novo livro.

### Pós-condições

1. `pending_reference == null`
2. `active_book == null`
3. `active_chapter == null`
4. `current_state == WAIT`
5. `StateChanged` publicado com `from_state=PREPARE`, `to_state=WAIT`, `reason="prepare_expired"`
6. Nenhum `ReferenceDetected` será emitido para a referência expirada por qualquer segmento futuro que não contenha uma nova menção explícita ao livro.

---

## RFC CAP-06

id: CAP-06
title: Supressão conservadora de inferência teológica
objective: >
  Impedir que o semantic_engine e o ReferenceResolver publiquem
  ReferenceDetected para referências que não foram explicitamente citadas
  pelo pregador, bloqueando inferências baseadas em conhecimento teológico
  (ex.: "igreja de Tessalônica" → 1 Tessalonicenses, citação verbal → Isaías 30:21).

### current_behavior

O `SemanticEngine._run_inference()` consulta o LLM e publica `IntentCandidate`. O `ReferenceResolver` assina `IntentCandidate`, valida via `Searcher`, e pode publicar `ReferenceDetected`. O `_parser_already_resolved` verifica se o parser já resolveu a mesma referência, mas não há verificação inversa: ninguém verifica se o livro foi explicitamente mencionado no texto transcrito.

O `ReferenceResolver` confia no `IntentCandidate` do LLM. Se o LLM sugere "1 Tessalonicenses 5:23" a partir de "igreja de Tessalônica", o resolver valida a referência no Searcher (que retorna sucesso porque a referência existe) e publica `ReferenceDetected`.

Por que não atende ao benchmark: os eventos 3, 8 e 11 contêm menções indiretas e citações reconhecíveis que uma IA agressiva poderia inferir. O benchmark exige WAIT para todos esses casos. Sem o guardão, o sistema pode apresentar 1 Tess 5:23 no evento 8 ou Isaías 30:21 no evento 11.

### expected_behavior

O sistema nunca publica `ReferenceDetected` para uma referência onde o nome canônico do livro não foi explicitamente falado pelo pregador no segmento atual ou em segmento recente que ainda está no contexto ativo.

O `ReferenceResolver` deve rejeitar `IntentCandidate` que não tenha correspondência lexical explícita no texto transcrito. A verificação é determinística: o nome do livro (ou alias reconhecível) deve aparecer no texto normalizado do segmento que gerou o `IntentCandidate`.

Comportamento observável:
- "igreja de Tessalônica" → `IntentCandidate` do LLM pode sugerir 1 Tess 5:23, mas o resolver rejeita porque "Tessalonicenses" não foi falado.
- "Filho, este é o caminho, siga por ele" → `IntentCandidate` pode sugerir Isaías 30:21, mas o resolver rejeita porque "Isaías" não foi falado.
- "Lá em Gênesis 3" → `IntentCandidate` pode sugerir Gênesis 3, e o resolver aceita porque "Gênesis" foi explicitamente falado.
- "Abra comigo em João 10:27" → `IntentCandidate` pode sugerir João 10:27, e o resolver aceita porque "João" foi explicitamente falado.

### state_transitions

```
WAIT
  ↓ [IntentCandidate rejeitado por falta de correspondência lexical]
WAIT (sem transição)

PREPARE
  ↓ [IntentCandidate rejeitado por falta de correspondência lexical]
PREPARE (sem transição)

WAIT
  ↓ [IntentCandidate aceito (livro explicitamente mencionado)]
PREPARE ou PRESENT (depende da completude da referência)
```

### input_events

- `IntentCandidate` (do `SemanticEngine`)
- `SpeechTranscribed` (do STT, para verificar correspondência lexical)
- `ReferenceCandidate` (do `IncrementalBiblicalParser`, para verificar se o parser já detectou o livro)

### output_events

- `IntentRejected` (novo evento): contém `reason="no_lexical_match"`, `candidate_book`, `candidate_chapter`, `candidate_verse`, `raw_text`, `correlation_id`

Justificativa: hoje o `ReferenceResolver` simplesmente descarta `IntentCandidate` inválidos sem publicar evento. Sem um evento de rejeição, não há rastreabilidade da decisão conservadora. O `IntentRejected` permite auditar quantas inferências foram suprimidas.

### required_context

- `raw_text`: string (texto transcrito do segmento que gerou o `IntentCandidate`)
- `normalized_text`: string (texto normalizado para verificação lexical)
- `ParserBookTable`: instância para verificar se o nome do livro aparece no texto
- `recent_books`: list[str] (para verificar se o livro foi mencionado em segmento recente ainda no contexto)

### algorithms

```
ALGORITMO: ConservativeGuard.validate(intent_candidate, raw_text, normalized_text)

1. Extrair book do IntentCandidate:
   a. Se IntentCandidate.book é null ou vazio: rejeitar (reason="no_book_in_candidate")
   b. Se IntentCandidate.book_id é 0: rejeitar (reason="no_book_id")

2. Verificar correspondência lexical do livro no texto:
   a. Usar ParserBookTable.resolve(normalized_text) para tentar encontrar o livro.
   b. Se encontrado e book_id == IntentCandidate.book_id:
      - Aceitar. O livro foi explicitamente mencionado.
   c. Se encontrado mas book_id != IntentCandidate.book_id:
      - Rejeitar (reason="book_mismatch: text has {found_book}, candidate has {candidate_book}")
   d. Se não encontrado:
      - Tentar resolvedor anafórico (CAP-04) com recent_books.
      - Se resolvido e book_id == IntentCandidate.book_id:
        - Aceitar (o livro foi mencionado anafóricamente).
      - Se não resolvido:
        - Rejeitar (reason="no_lexical_match: {candidate_book} not found in text")

3. Se aceito:
   a. Encaminhar ao fluxo normal do ReferenceResolver.
4. Se rejeitado:
   a. Publicar IntentRejected com reason, candidate_book, raw_text.
   b. Não publicar ReferenceDetected.
```

### edge_cases

- **Livro mencionado por alias não canônica:** "Primeiro Coríntios" em vez de "1 Coríntios". O `ParserBookTable` deve resolver a alias. Se resolve, aceitar.
- **Livro mencionado em segmento anterior ainda no contexto:** "João" foi dito no segmento A, "3:16" no segmento B, e o LLM sugere "João 3:16" no segmento B. O texto do segmento B não contém "João", mas `active_book = "João"`. Decisão: aceitar se `active_book` corresponde ao `IntentCandidate.book`.
- **LLM sugere livro correto mas capítulo/versículo inventados:** "Gênesis" foi dito, LLM sugere "Gênesis 3:15" mas o pregador não disse "3" nem "15". O livro tem correspondência lexical, mas os números não. Decisão: rejeitar se os números não aparecem no texto. Verificar capítulo e versículo no texto normalizado.
- **LLM sugere livro e capítulo corretos mas versículo inventado:** "Gênesis 3" foi dito, LLM sugere "Gênesis 3:15". O versículo 15 não aparece no texto. Decisão: rejeitar a parte do versículo; aceitar apenas livro + capítulo (PREPARE, não PRESENT).
- **Citação verbal reconhecível:** "Filho, este é o caminho, siga por ele" é Isaías 30:21. Nenhum livro é mencionado. Decisão: rejeitar (reason="no_lexical_match").
- **Referência indireta:** "igreja de Tessalônica" sugere 1 Tessalonicenses. "Tessalonicenses" não é falado. Decisão: rejeitar.
- **Menção de cidade vs livro:** "Tessalônica" é cidade; "Tessalonicenses" é livro. O `ParserBookTable` não deve resolver "Tessalônica" como livro. Decisão: rejeitar.
- **Livro mencionado em outro contexto:** "Paulo escreveu aos Romanos". "Romanos" é detectável pelo parser. Se o LLM sugere "Romanos 8:28" mas o pregador não disse "8" nem "28", rejeitar versículo, aceitar livro.
- **STT corrompe nome do livro:** "Gênesis" reconhecido como "gêneseis". O `Normalizer` remove diacritics; "gêneseis" normaliza para "geneseis" que não casa com "genesis". Decisão: rejeitar (falso negativo aceitável; preferível a falso positivo).
- **Múltiplos IntentCandidates para o mesmo segmento:** validar cada um independentemente.

### failure_modes

1. **Falso negativo (rejeita referência válida):** o pregador disse "João 3:16" mas o STT corrompeu e o parser não encontrou "João". O guardão rejeita. Detecção: `false_rejection_count`. Mitigação: se o `IncrementalBiblicalParser` já publicou `ReferenceDetected` para a mesma referência, o guardão não é acionado (o parser tem precedência).
2. **Falso positivo (aceita referência inválida):** o guardão encontra o livro no texto mas o LLM inventou capítulo/versículo. Detecção: `false_verse_count`. Mitigação: verificar capítulo e versículo no texto, não apenas o livro.
3. **Guardão muito agressivo:** rejeita inferências legítimas onde o pregador usou pronome ("aquele texto" → referência anterior). Detecção: `legitimate_inference_rejected_count`. Mitigação: o guardão não rejeita se o `IntentCandidate` referencia `last_presented_reference` (o LLM está sugerindo repetição, não inferência teológica).
4. **Race condition:** `IntentCandidate` chega antes de `ReferenceCandidate` do parser. O guardão rejeita porque ainda não viu o livro no texto. Detecção: `race_condition_count`. Mitigação: o guardão deve aguardar um tempo curto (ex.: 100ms) pelo `ReferenceCandidate` antes de rejeitar.

### telemetry

- `intent_rejected_count`: total de IntentCandidates rejeitados
- `intent_rejected_no_lexical_match`: rejeições por falta de correspondência lexical do livro
- `intent_rejected_book_mismatch`: rejeições por livro diferente no texto vs candidato
- `intent_rejected_no_verse_match`: rejeições por versículo não presente no texto
- `intent_accepted_count`: IntentCandidates aceitos pelo guardão
- `false_rejection_count`: rejeições que o parser posteriormente confirmou (race condition)
- `conservative_guard_latency_ms`: latência da validação

### unit_tests

1. "IntentCandidate com livro não presente no texto deve ser rejeitado"
2. "IntentCandidate com livro presente no texto deve ser aceito"
3. "IntentCandidate com livro presente mas capítulo ausente no texto deve ter versículo rejeitado"
4. "IntentCandidate com livro por alias ('Primeiro Coríntios') deve ser aceito"
5. "IntentCandidate com livro resolvido anafóricamente (CAP-04) deve ser aceito"
6. "IntentCandidate para 'igreja de Tessalônica' deve ser rejeitado"
7. "IntentCandidate para citação não-atribuída deve ser rejeitado"
8. "IntentCandidate que referencia last_presented_reference deve ser aceito (repeat)"
9. "IntentCandidate com book_id=0 deve ser rejeitado"
10. "IntentCandidate com book=null deve ser rejeitado"
11. "Múltiplos IntentCandidates devem ser validados independentemente"
12. "IntentRejected deve ser publicado com reason correto"

### integration_tests

1. "Benchmark evento 3: 'pregava ontem sobre Gênesis' não deve gerar IntentCandidate aceito para Gênesis"
2. "Benchmark evento 8: 'igreja de Tessalônica' não deve gerar ReferenceDetected para 1 Tessalonicenses"
3. "Benchmark evento 11: 'Filho, este é o caminho' não deve gerar ReferenceDetected para Isaías 30:21"
4. "Benchmark evento 2: 'Primeiro Coríntios capítulo 14 versículo 10' deve ser aceito (livro explícito)"
5. "Benchmark evento 10: 'Evangelho de João 10:27' deve ser aceito (livro explícito)"
6. "Replay do benchmark: eventos 3, 8 e 11 devem produzir IntentRejected, não ReferenceDetected"

### benchmark_mapping

[3, 8, 11]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `ReferenceResolver` confia no `IntentCandidate` do LLM sem verificar se o livro foi explicitamente mencionado no texto. O `_parser_already_resolved` apenas verifica duplicação, não correspondência lexical. Não há guardão conservador entre o LLM e a publicação de `ReferenceDetected`.

**Módulo que deverá evoluir:**
O `ReferenceResolver` deve ser estendido com uma etapa de validação lexical antes de chamar o `Searcher` e publicar `ReferenceDetected`. Esta etapa usa o `ParserBookTable` já injetado no pipeline e o texto transcrito disponível no `IntentCandidate`.

**Por que este módulo foi escolhido:**
O `ReferenceResolver` é o único componente além do parser que pode publicar `ReferenceDetected`. É o ponto natural para o guardão, pois já assina `IntentCandidate` e já decide se publica ou não. Estender o `SemanticEngine` não funcionaria porque o engine não conhece o texto original (trabalha com contexto semântico, não texto cru).

**Contratos que permanecem iguais:**
- `SemanticEngine` não muda (continua publicando `IntentCandidate`).
- `IntentCandidate` não muda schema.
- `ReferenceDetected` não muda schema.
- `ParserBookTable` não muda.

**Contratos que precisarão mudar:**
- O `ReferenceResolver` deve ter acesso ao `raw_text` do `IntentCandidate` (já disponível no evento) e ao `ParserBookTable` (já disponível no pipeline).
- Novo evento `IntentRejected` no `PipelineEventBus`.

### Invariantes

1. Nenhum `ReferenceDetected` é publicado para uma referência cujo livro não aparece no texto transcrito (nem direta nem anafóricamente).
2. Nenhum `ReferenceDetected` é publicado com versículo que não aparece no texto transcrito (a menos que o versículo seja completado por contexto cross-segmento em PREPARE).
3. O guardão nunca rejeita um `IntentCandidate` se o `IncrementalBiblicalParser` já publicou `ReferenceDetected` para a mesma referência (parser tem precedência).
4. `IntentRejected` é publicado para toda rejeição, garantindo rastreabilidade.

### Pré-condições

1. `ReferenceResolver` está operacional e assinando `IntentCandidate`.
2. `ParserBookTable` está disponível para validação lexical.
3. O `raw_text` do segmento que gerou o `IntentCandidate` está acessível.

### Pós-condições

1. Se o livro do `IntentCandidate` não aparece no texto: `IntentRejected` é publicado, nenhum `ReferenceDetected` é publicado.
2. Se o livro aparece mas o versículo não: `IntentRejected` é publicado com `reason="no_verse_match"`, nenhum `ReferenceDetected` é publicado.
3. Se o livro e os números aparecem: o `ReferenceResolver` prossegue com o fluxo normal (validação no Searcher, publicação de `ReferenceDetected`).
4. Se o `IntentCandidate` referencia `last_presented_reference` (repeat): o guardão aceita sem verificar correspondência lexical (o LLM está sugerindo repetição, não inferência).

---

## RFC CAP-07

id: CAP-07
title: Detecção de referência repetida (re-citação)
objective: >
  Rastrear a última referência apresentada (last_presented_reference) e
  identificar quando o pregador re-cita a mesma referência, marcando o
  estado como PRESENT (repeat) para permitir decisão de UX na camada
  de apresentação.

### current_behavior

O `SermonContextEngine` tem `ReferenceRepeated` event e `_handle_reference_repeated` que re-adiciona a referência ao topo do histórico. O `VersePresentationService` tem `_pending_anticipations` para dedup de antecipação, mas não verifica se uma `ReferenceDetected` é repetição de uma referência já apresentada.

O `StateOrchestrator` (CAP-01) mantém `last_presented_reference` mas não compara `ReferenceDetected` contra ele para marcar repeat.

Por que não atende ao benchmark: o evento 5 é uma re-citação de 1 Cor 14:10 (mesma referência do evento 2). O sistema deve marcar como PRESENT (repeat), não como PRESENT (first). Sem esta capacidade, o sistema re-apresenta o versículo, causando piscar na tela.

### expected_behavior

Quando uma `ReferenceDetected` tem o mesmo `(book_id, chapter, verse)` que `last_presented_reference`, o sistema marca o evento como `repeat=true` no `StateChanged`. A camada de apresentação (`VersePresentationService`) recebe esta flag e decide se re-apresenta ou mantém o versículo atual na tela.

Comportamento observável:
- Após apresentar 1 Cor 14:10 (evento 2), `last_presented_reference = "1 Cor 14:10"`.
- Ao detectar 1 Cor 14:10 novamente (evento 5), o sistema publica `StateChanged` com `to_state=PRESENT`, `reason="repeat"`.
- O `VersePresentationService` recebe `repeat=true` e não re-apresenta (mantém o versículo na tela).
- Se a referência é diferente (ex.: João 10:27 após 1 Cor 14:10), `repeat=false` e o sistema apresenta normalmente.

### state_transitions

```
WAIT ou PREPARE
  ↓ [ReferenceDetected com (book, chapter, verse) == last_presented_reference]
PRESENT (repeat)

WAIT ou PREPARE
  ↓ [ReferenceDetected com (book, chapter, verse) != last_presented_reference]
PRESENT (first)

PRESENT (first)
  ↓ [próximo segmento sem referência]
WAIT (reset last_presented_reference? Não: manter para detectar repeat posterior)

PRESENT (repeat)
  ↓ [próximo segmento sem referência]
WAIT
```

### input_events

- `ReferenceDetected` (do `IncrementalBiblicalParser`, `BiblicalNLUService`, ou `StateOrchestrator` via CAP-02)
- `StateChanged` (do orquestrador, para saber se houve PRESENT anterior)

### output_events

- `StateChanged` (com `reason="repeat"` ou `reason="first"`, e campo `repeat: bool`)

Justificativa: reutiliza `StateChanged` de CAP-01. A novidade é o campo `repeat` e o `reason="repeat"` que distingue primeira apresentação de re-citação.

### required_context

- `last_presented_reference`: tuple(int, int, int) | null (book_id, chapter, verse)
- `current_state`: WAIT | PREPARE | PRESENT | IGNORE

### algorithms

```
ALGORITMO: RepeatDetector.on_reference_detected(reference_detected, last_presented_reference)

1. Extrair (book_id, chapter, verse) do ReferenceDetected.
   a. Se verse é null: não é referência completa. Não comparar. Retornar repeat=false.

2. Se last_presented_reference é null:
   a. É a primeira apresentação. Retornar repeat=false.
   b. Após apresentar, setar last_presented_reference = (book_id, chapter, verse).

3. Se (book_id, chapter, verse) == last_presented_reference:
   a. Retornar repeat=true.
   b. Publicar StateChanged com reason="repeat", repeat=true.

4. Se (book_id, chapter, verse) != last_presented_reference:
   a. Retornar repeat=false.
   b. Atualizar last_presented_reference = (book_id, chapter, verse).
   c. Publicar StateChanged com reason="first", repeat=false.
```

### edge_cases

- **Mesmo livro e capítulo mas versículo diferente:** 1 Cor 14:10 vs 1 Cor 14:25. Não é repeat. `repeat=false`. Apresentar normalmente.
- **Mesmo livro mas capítulo diferente:** 1 Cor 14:10 vs 1 Cor 15:1. Não é repeat.
- **Referência sem versículo:** "Gênesis 3" sem versículo. Não comparar para repeat (referência incompleta não é apresentada).
- **Repeat após expiração:** 1 Cor 14:10 foi apresentado, sistema passou por WAIT, e agora 1 Cor 14:10 é detectado novamente. `last_presented_reference` ainda contém 1 Cor 14:10. Decisão: é repeat. O sistema não esquece `last_presented_reference` ao transitar para WAIT.
- **Repeat cross-segmento:** 1 Cor 14:10 detectado via contexto (CAP-02) em segmento B, mas 1 Cor 14:10 já foi apresentado no segmento A. `last_presented_reference` contém 1 Cor 14:10. Decisão: repeat=true.
- **Três ou mais repeats:** o pregador cita 1 Cor 14:10 três vezes. Todas após a primeira são repeat=true.
- **Repeat com livro resolvido anafóricamente (CAP-04):** "Coríntios 14:10" resolve para 1 Cor 14:10 via anáfora. Se `last_presented_reference` é 1 Cor 14:10, repeat=true. A comparação é por (book_id, chapter, verse), não por string.
- **STT produz versículo ligeiramente diferente:** "versículo 10" vs "versículo dez". O `Normalizer` converte "dez" para "10". A comparação é numérica, não textual.
- **Referência de intervalo:** "João 10:27-30". Comparar apenas verso_start (27). Se `last_presented_reference` é João 10:27, repeat=true. Se é João 10:30, repeat=false.
- **Reset de last_presented_reference:** não deve ser resetado ao transitar para WAIT. Só deve ser resetado se uma nova referência diferente é apresentada (torna-se o novo `last_presented`).

### failure_modes

1. **Falso repeat:** referência ligeiramente diferente é marcada como repeat. Causa: comparação por string em vez de (book_id, chapter, verse). Detecção: `false_repeat_count`. Mitigação: comparar por tupla numérica, não por string.
2. **Falso first:** referência idêntica não é marcada como repeat. Causa: `last_presented_reference` foi resetado prematuramente. Detecção: `repeat_missed_count`. Mitigação: nunca resetar `last_presented_reference` ao transitar para WAIT.
3. **Repeat não chega à camada de apresentação:** o `StateChanged` com `repeat=true` é publicado mas o `VersePresentationService` não o consome. Detecção: `repeat_events_published` vs `repeat_events_consumed`. Mitigação: o `VersePresentationService` deve assinar `StateChanged`.

### telemetry

- `repeat_reference_count`: total de repeats detectados
- `first_reference_count`: total de firsts detectados
- `false_repeat_count`: repeats marcados incorretamente (referência era diferente)
- `repeat_missed_count`: repeats não detectados (referência era igual mas marcado como first)
- `repeat_presentation_suppressed_count`: vezes que a apresentação foi suprimida por repeat
- `last_presented_reference_age_ms`: tempo desde a última apresentação até o repeat

### unit_tests

1. "ReferenceDetected com mesma (book_id, chapter, verse) que last_presented_reference deve marcar repeat=true"
2. "ReferenceDetected com chapter diferente deve marcar repeat=false"
3. "ReferenceDetected com verse diferente deve marcar repeat=false"
4. "ReferenceDetected com book_id diferente deve marcar repeat=false"
5. "Primeira ReferenceDetected com last_presented_reference=null deve marcar repeat=false"
6. "ReferenceDetected sem verse não deve ser comparada para repeat"
7. "Após transição PRESENT → WAIT, last_presented_reference deve ser mantido"
8. "Repeat após expiração e retorno deve marcar repeat=true"
9. "Repeat com livro resolvido anafóricamente deve comparar por book_id"
10. "Três repeats consecutivos devem todos marcar repeat=true"
11. "Referência de intervalo deve comparar apenas verse_start"
12. "StateChanged com repeat=true deve conter reason='repeat'"

### integration_tests

1. "Benchmark evento 2: 1 Cor 14:10 deve marcar repeat=false (first)"
2. "Benchmark evento 5: 1 Cor 14:10 novamente deve marcar repeat=true"
3. "Benchmark evento 10: João 10:27 deve marcar repeat=false (first, referência diferente)"
4. "Replay do benchmark: evento 5 deve produzir StateChanged com repeat=true"
5. "Replay do benchmark: VersePresentationService deve suprimir re-apresentação no evento 5"

### benchmark_mapping

[5]

### Análise arquitetural

**Por que a arquitetura atual não atende:**
O `SermonContextEngine` tem `ReferenceRepeated` mas opera em fluxo paralelo. O `VersePresentationService` tem `_pending_anticipations` para dedup de antecipação mas não verifica repetição de referência já apresentada. O `StateOrchestrator` (CAP-01) mantém `last_presented_reference` mas não o usa para marcar repeat.

**Módulo que deverá evoluir:**
O `StateOrchestrator` (CAP-01) deve ser estendido para comparar `ReferenceDetected` contra `last_presented_reference` antes de publicar `StateChanged`. O `VersePresentationService` deve ser estendido para assinar `StateChanged` e respeitar a flag `repeat`.

**Por que estes módulos foram escolhidos:**
O orquestrador é o ponto onde `ReferenceDetected` é processado e `StateChanged` é publicado. Adicionar a comparação ali é natural. O `VersePresentationService` é o consumidor final que decide se apresenta ou não; ele precisa da flag `repeat` para tomar essa decisão.

**Contratos que permanecem iguais:**
- `ReferenceDetected` não muda schema.
- `SermonContextEngine` não muda.
- `IncrementalBiblicalParser` não muda.

**Contratos que precisarão mudar:**
- `StateChanged` ganha campo `repeat: bool` (default=false).
- `VersePresentationService` deve assinar `StateChanged` (novo assinante) e respeitar `repeat=true` suprimindo a re-apresentação.

### Invariantes

1. `last_presented_reference` é null apenas antes da primeira apresentação.
2. `last_presented_reference` não é resetado ao transitar para WAIT.
3. A comparação de repeat é por (book_id, chapter, verse_start), nunca por string.
4. `repeat=true` só é publicado quando `to_state == PRESENT`.

### Pré-condições

1. `StateOrchestrator` (CAP-01) está operacional.
2. `last_presented_reference` está disponível no contexto do orquestrador.
3. `VersePresentationService` está operacional.

### Pós-condições

1. Se `ReferenceDetected` tem mesma (book_id, chapter, verse) que `last_presented_reference`: `StateChanged` é publicado com `repeat=true`, `reason="repeat"`.
2. Se `ReferenceDetected` tem (book_id, chapter, verse) diferente: `StateChanged` é publicado com `repeat=false`, `reason="first"`, e `last_presented_reference` é atualizado.
3. Se `repeat=true`: `VersePresentationService` não re-apresenta o versículo (mantém o atual na tela).
4. `last_presented_reference` reflete a referência mais recentemente apresentada (first ou repeat).

---

## Tabela Final de Sumário

| Capacidade | Módulos afetados | Eventos adicionados | Eventos modificados | Novos estados | Impacto em regressão | Risco |
|---|---|---|---|---|---|---|
| CAP-01 | StateOrchestrator (novo), PipelineEventBus, VersePresentationService | StateChanged | Nenhum | WAIT, PREPARE, PRESENT, IGNORE | Baixo: novos componentes, fluxo existente não é alterado | Baixo: camada adicional não interfere no parser |
| CAP-02 | StateOrchestrator (extensão) | Nenhum | ReferenceCandidate (pode ser publicado pelo orquestrador), ReferenceDetected (pode ser publicado pelo orquestrador) | Nenhum | Médio: orquestrador passa a publicar eventos que antes só o parser publicava | Médio: risco de eventos duplicados se orquestrador e parser publicam simultaneamente |
| CAP-03 | StateOrchestrator (extensão), Parser._has_trigger (referência) | IntentClassified | Nenhum | Nenhum | Baixo: classificação é aditiva, não remove funcionalidade | Baixo: padrões lexicais são determinísticos |
| CAP-04 | StateOrchestrator (extensão), config/books.json (campo base_names) | Nenhum | ReferenceCandidate (book pode ser preenchido anafóricamente) | Nenhum | Baixo: fallback só atua quando parser retorna None | Médio: default errado gera referência incorreta |
| CAP-05 | StateOrchestrator (extensão) | Nenhum | StateChanged (novo reason="prepare_expired") | Nenhum | Médio: expiração pode descartar referência que o pregador ainda estava construindo | Médio: threshold muito baixo causa expiração prematura |
| CAP-06 | ReferenceResolver (extensão), PipelineEventBus | IntentRejected | Nenhum | Nenhum | Médio: rejeita IntentCandidates que antes eram aceitos | Baixo: supressão é conservadora por design |
| CAP-07 | StateOrchestrator (extensão), VersePresentationService (extensão) | Nenhum | StateChanged (campo repeat), VersePresentationService assina StateChanged | Nenhum | Baixo: flag aditiva, não remove funcionalidade | Baixo: repeat só suprime apresentação, não altera detecção |
