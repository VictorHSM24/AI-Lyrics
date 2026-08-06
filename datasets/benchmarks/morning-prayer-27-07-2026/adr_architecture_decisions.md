# Architecture Decision Records — AI Lyrics

Registro formal de decisões arquiteturais irreversíveis tomadas durante o design do sistema de detecção e apresentação de referências bíblicas.

Cada ADR documenta uma decisão já implícita nos documentos aprovados (benchmark, capability_gap_analysis.md, rfc_capabilities.md). Nenhum ADR propõe nova funcionalidade ou altera decisões existentes.

---

# ADR-001

## Introduzir StateOrchestrator

Status: Accepted

## Context

O pipeline original do AI Lyrics é linear e distribuído: o `IncrementalBiblicalParser` publica `ReferenceCandidate` e `ReferenceDetected`, o `BiblicalNLUService` converte `Intent` em `ReferenceDetected` ou `IntentUnknown`, o `SemanticEngine` publica `IntentCandidate` que o `ReferenceResolver` pode converter em `ReferenceDetected`, e o `VersePresentationService` consome `ReferenceDetected` e apresenta no Holyrics.

Nenhum componente centraliza a decisão de "em que estado o sistema está". O `VersePresentationService` reage a `ReferenceDetected` sem saber se o sistema estava aguardando, preparando, ou já apresentando. O `SermonContextEngine` mantém contexto mas opera em fluxo paralelo não conectado ao pipeline principal. O `IncrementalBiblicalParser` mantém estado interno (`_current_book`, `_current_chapter`, `_current_verse`) mas não o expõe como estado do sistema.

O benchmark define 11 eventos, todos caracterizados por transições de estado (WAIT, PREPARE, PRESENT, IGNORE). Sem um componente que produza essas transições, o sistema não consegue reproduzir nenhum evento do benchmark.

## Decision

Criar um componente `StateOrchestrator` que assina eventos do `PipelineEventBus` (`ReferenceCandidate`, `ReferenceDetected`, `IntentCandidate`, `IntentUnknown`, `SpeechTranscribed`) e publica `StateChanged` com o estado atual (WAIT, PREPARE, PRESENT, IGNORE) e o motivo da transição. O orquestrador é o ponto único e autoritativo de decisão de estado.

## Alternatives considered

### Alternativa 1: Estender o IncrementalBiblicalParser

Adicionar lógica de máquina de estados diretamente no parser incremental, que já mantém estado interno.

Rejeitada porque o parser tem responsabilidade de parsing (detecção lexical), não de orquestração. Misturar as duas responsabilidades viola separação de concerns e torna o parser testável apenas em conjunto com a lógica de estados. O parser seria o único componente do pipeline que simultaneamente detecta e decide, criando um ponto único de falha com responsabilidade excessiva.

### Alternativa 2: Estender o VersePresentationService

Adicionar lógica de estados no serviço de apresentação, que já é o consumidor final.

Rejeitada porque o `VersePresentationService` é o final do pipeline. Ele recebe `ReferenceDetected` depois de todas as decisões terem sido tomadas. Colocar a máquina de estados ali significa que os estados não estão disponíveis para outros componentes durante o processamento. O `SemanticEngine` e o `ReferenceResolver` não saberiam se o sistema está em PREPARE ou WAIT, impossibilitando CAP-02 (propagação de contexto) e CAP-05 (expiração).

### Alternativa 3: Usar o SermonContextEngine como orquestrador

O `SermonContextEngine` já mantém `SermonContext` com book, chapter, last_reference. Estendê-lo para publicar estados.

Rejeitada porque o `SermonContextEngine` opera em fluxo paralelo ao pipeline principal. Ele processa eventos assincronamente e não está no caminho crítico entre STT e Holyrics. Usá-lo como orquestrador adicionaria latência e criaria acoplamento entre o fluxo de contexto (que é analítico) e o fluxo de apresentação (que é tempo real). Além disso, o `SermonContext` é imutável por design; máquina de estados requer mutação de estado.

## Pros

- Ponto único de verdade para estado do sistema, facilitando debugging e telemetria.
- Não altera nenhum componente existente; é puramente aditivo.
- Permite que CAP-02, CAP-03, CAP-04, CAP-05 e CAP-07 sejam implementados como extensões do orquestrador, centralizando lógica de decisão.
- `StateChanged` é um evento rastreável que pode ser gravado e replayed.

## Cons

- Adiciona um componente ao caminho crítico, introduzindo latência adicional.
- O orquestrador acumula muita responsabilidade (estado + contexto + expiração + repeat), podendo se tornar um god component.
- Se o orquestrador falhar, o sistema inteiro para de transitar estados, mesmo que o parser continue detectando referências.

## Consequences

**Simples:** qualquer componente pode consultar o estado do sistema assinando `StateChanged`. Debugging torna-se trivial: basta observar a sequência de `StateChanged`.

**Complexo:** o orquestrador se torna o componente com maior acoplamento no sistema. Toda nova capacidade cognitiva (CAP-02 a CAP-07) é uma extensão do orquestrador. Isso significa que mudanças no orquestrador têm impacto sistêmico.

**Irreversível sem refatoração:** uma vez que o orquestrador é o ponto único de decisão de estado, removê-lo requer redistribuir lógica de estado para os componentes originais, o que é uma refatoração arquitetural completa. O evento `StateChanged` se torna parte do contrato do pipeline; consumidores não podem ser removidos sem quebra.

## Migration impact

Baixo. O orquestrador é aditivo: nenhum componente existente precisa mudar para que ele comece a funcionar. O `VersePresentationService` pode opcionalmente assinar `StateChanged` para saber sobre repeats (CAP-07), mas isso não é obrigatório na migração inicial.

## Future work

- Considerar decomposição do orquestrador em sub-componentes (IntentClassifier, ContextPropagator, PrepareExpiryManager, RepeatDetector) se a complexidade interna crescer além do gerenciável.
- Avaliar persistência de `StateChanged` para permitir replay de sessões completas com inspeção de estado em cada ponto.

---

# ADR-002

## Representar comportamento usando máquina de estados (WAIT / PREPARE / PRESENT / IGNORE)

Status: Accepted

## Context

O sistema precisa decidir quando apresentar um versículo no Holyrics, quando preparar a infraestrutura, quando aguardar mais informação, e quando ignorar segmentos irrelevantes. Sem uma formalização de comportamento, cada componente toma essas decisões independentemente, levando a comportamentos inconsistentes: o parser pode detectar uma referência enquanto o contexto ainda está em outra referência, ou o serviço de apresentação pode re-apresentar um versículo que já está na tela.

O benchmark define explicitamente quatro estados e exige que cada mudança de estado seja um evento rastreável. A ausência de uma máquina de estados formal significa que o sistema não tem um contrato verificável de comportamento.

## Decision

Adotar uma máquina de estados finita com quatro estados (WAIT, PREPARE, PRESENT, IGNORE) como representação canônica do comportamento do sistema. O `StateOrchestrator` (ADR-001) é o único componente autorizado a produzir transições. As transições são determinísticas e baseadas em eventos do pipeline.

- **WAIT:** sistema aguardando. Nenhuma referência ativa. Números isolados não são processados.
- **PREPARE:** referência parcial detectada (livro, ou livro + capítulo). Sistema acumulando informação.
- **PRESENT:** referência completa detectada. Versículo deve ser apresentado.
- **IGNORE:** segmento sem conteúdo bíblico. Sistema descarta sem processamento semântico.

## Alternatives considered

### Alternativa 1: Sistema orientado a eventos sem estados explícitos

Manter a arquitetura atual onde cada componente reage a eventos independentemente, sem noção de estado global. O `VersePresentationService` apresenta quando recebe `ReferenceDetected`, ponto.

Rejeitada porque o benchmark exige que o sistema saiba distinguir "aguardando" de "preparando" de "apresentando". Sem estados, não há como implementar expiração de PREPARE (CAP-05), supressão de menções narrativas (CAP-03), ou detecção de repeat (CAP-07). O sistema atual já falha no benchmark porque não tem estados.

### Alternativa 2: Máquina de estados com mais estados (ex.: PREPARE_BOOK, PREPARE_CHAPTER, PREPARE_VERSE)

Subdividir PREPARE em sub-estados para granularidade fina.

Rejeitada porque o benchmark não exige essa granularidade. O benchmark define apenas WAIT, PREPARE, PRESENT e IGNORE. Adicionar sub-estados aumenta complexidade sem valor observável. A granularidade de PREPARE é interna ao orquestrador (que rastreia `active_book`, `active_chapter`, `pending_reference`) e não precisa ser exposta como estados distintos.

### Alternativa 3: Máquina de estados baseada em tempo (timeout-driven)

Usar timers em vez de eventos para transitar estados. Ex.: PREPARE expira após 10 segundos independentemente de atividade.

Rejeitada porque o benchmark é orientado a eventos, não a tempo. O evento 8 (expiração de Gênesis 3) ocorre porque o pregador mudou de assunto, não porque um timer disparou. Timers são úteis como mecanismo de fallback (CAP-05 usa timeout de segmentos), mas não podem ser o driver primário de transições.

## Pros

- Comportamento do sistema é formalmente verificável: dada uma sequência de eventos, a sequência de estados é determinística.
- Facilita testes de regressão: basta comparar sequência de `StateChanged` com o benchmark.
- Quatro estados é um número pequeno o suficiente para ser compreendido mentalmente por qualquer desenvolvedor.

## Cons

- Quatro estados podem ser insuficientes para casos complexos não cobertos pelo benchmark (ex.: referência de intervalo, múltiplas referências simultâneas).
- A máquina de estados é rígida: adicionar um novo estado requer mudança no orquestrador e em todos os consumidores de `StateChanged`.

## Consequences

**Simples:** qualquer componente pode saber o estado do sistema com um único evento. Testes de regressão tornam-se comparação de sequências de estados.

**Complexo:** toda nova capacidade cognitiva precisa mapear para os quatro estados. Se uma capacidade não se encaixa (ex.: sistema precisa de um estado "PAUSED" para quando o operador pausa a apresentação), a máquina de estados precisa ser estendida.

**Irreversível sem refatoração:** uma vez que o comportamento é definido por quatro estados, adicionar ou remover estados quebra todos os consumidores de `StateChanged` e invalida o benchmark. A máquina de estados é o contrato mais fundamental do sistema.

## Migration impact

Moderado. Componentes existentes não precisam mudar imediatamente, mas o `VersePresentationService` eventualmente precisa assinar `StateChanged` para respeitar repeat (CAP-07). O `SemanticEngine` e `ReferenceResolver` não precisam mudar, mas suas saídas (`IntentCandidate`, `ReferenceDetected`) passam a ser inputs do orquestrador em vez de irem direto para apresentação.

## Future work

- Avaliar adição de estado PAUSED se o sistema precisar suportar intervenção manual do operador.
- Considerar hierarquia de estados (HSM) se a complexidade de PREPARE crescer.

---

# ADR-003

## Parser continua determinístico

Status: Accepted

## Context

O `Parser` e o `IncrementalBiblicalParser` são componentes determinísticos que detectam nomes de livros via `ParserBookTable.resolve()` e extraem capítulo/versículo via `_parse_ref_suffix()`. O `Normalizer` converte ordinais, romanos e extenso para dígitos. Os thresholds de confiança (0.40 para livro, 0.75 para livro+capítulo, 0.98 para completo) são fixos.

O `SemanticEngine` usa um LLM para inferir intenções e pode sugerir referências que o parser não detectou. O `ReferenceResolver` pode converter `IntentCandidate` do LLM em `ReferenceDetected`.

Há tentação de usar o LLM para substituir ou complementar o parser em casos onde o parser falha (ex.: "Coríntios" sem ordinal, referências indiretas). Isso introduziria não-determinismo no pipeline.

## Decision

O parser permanece o caminho determinístico e primário para detecção de referências. O LLM (`SemanticEngine`) é secundário e nunca pode publicar `ReferenceDetected` diretamente; passa por `ReferenceResolver` que aplica validação lexical (CAP-06). O parser tem precedência: se o parser já resolveu uma referência, o `ReferenceResolver` não publica uma segunda `ReferenceDetected` para a mesma.

## Alternatives considered

### Alternativa 1: Substituir parser por LLM

Usar o LLM como detector primário de referências, eliminando o parser determinístico.

Rejeitada porque LLMs são não-determinísticos: a mesma entrada pode produzir saídas diferentes. O benchmark exige comportamento reproduzível. Um sistema onde a mesma pregação pode produzir diferentes sequências de estados a cada execução não pode ser testado por regressão. Além disso, LLMs têm latência significativamente maior que parsing determinístico, inviabilizando tempo real.

### Alternativa 2: Parser e LLM em paralelo com merge

Executar parser e LLM simultaneamente e fazer merge dos resultados.

Rejeitada porque o merge introduz ambiguidade: se o parser detecta "1 Cor 14:10" e o LLM sugere "1 Cor 14:11", qual prevalece? O benchmark exige que o parser tenha precedência (decision_source="parser" nos eventos), mas um merge paralelo adiciona latência e complexidade sem benefício observável no benchmark.

### Alternativa 3: Parser com fallback para LLM

Usar parser primeiro; se retornar None, consultar LLM.

Rejeitada como caminho primário porque o `ReferenceResolver` já implementa algo similar: assina `IntentCandidate` e pode publicar `ReferenceDetected`. A diferença é que o resolver aplica validação lexical (CAP-06), garantindo que o LLM não infira referências sem correspondência lexical. Fallback direto parser→LLM sem validação lexical violaria o princípio conservador do benchmark.

## Pros

- Detecção de referências é reproduzível e testável.
- Latência mínima para o caso comum (referências explícitas).
- LLM é usado apenas onde agrega valor (casos ambíguos, classificação de intenção), não onde é perigoso (detecção primária).

## Cons

- Parser determinístico não detecta referências indiretas ou nomes sem ordinal (CAP-04 é necessário como fallback).
- Manutenção da tabela de aliases (`books.json`) é contínua: novos sinônimos ou variações de STT precisam ser cadastrados.

## Consequences

**Simples:** o parser é testável com unit tests puros, sem mock de LLM. Comportamento do parser é idêntico em todas as execuções.

**Complexo:** o parser precisa cobrir todos os formatos de referência que o benchmark exige. Se o pregador usa um formato não catalogado, o parser falha e o LLM precisa compensar, mas com validação lexical (CAP-06) que pode rejeitar.

**Irreversível sem refatoração:** uma vez que o parser é o caminho primário, substituí-lo por LLM requer reimplementar toda a lógica de aliases, normalização, thresholds e confiança em um modelo não-determinístico, além de invalidar todos os testes de regressão baseados em saída determinística.

## Migration impact

Nenhum. Esta decisão mantém o status quo. O parser não muda; apenas se formaliza que ele não será substituído.

## Future work

- Avaliar ampliação da tabela de aliases conforme novos benchmarks revelarem formatos não catalogados.
- Considerar fine-tuning de modelo de linguagem específico para referências bíblicas apenas se o parser determinístico provar ser insuficiente para um benchmark futuro.

---

# ADR-004

## Semantic Engine nunca apresenta sozinho

Status: Accepted

## Context

O `SemanticEngine` consulta um LLM e publica `IntentCandidate`. O `ReferenceResolver` assina `IntentCandidate`, valida via `Searcher`, e pode publicar `ReferenceDetected`. O `VersePresentationService` consome `ReferenceDetected` e apresenta no Holyrics.

Se o `SemanticEngine` pudesse publicar `ReferenceDetected` diretamente, ele poderia apresentar versículos sem passar pelo `ReferenceResolver`, bypassando validação lexical (CAP-06) e validação de existência da referência no `Searcher`.

## Decision

O `SemanticEngine` nunca publica `ReferenceDetected`. Ele só publica `IntentCandidate`. O `ReferenceResolver` é o único componente que pode converter `IntentCandidate` em `ReferenceDetected`, e só o faz após validação lexical (CAP-06) e validação no `Searcher`. O parser também pode publicar `ReferenceDetected` diretamente, mas o LLM nunca.

## Alternatives considered

### Alternativa 1: SemanticEngine publica ReferenceDetected diretamente

Permitir que o `SemanticEngine` publique `ReferenceDetected` após sua inferência, eliminando o `ReferenceResolver` como intermediário.

Rejeitada porque remove o guardão conservador (CAP-06). O LLM poderia inferir "1 Tess 5:23" a partir de "igreja de Tessalônica" e publicar `ReferenceDetected` sem ninguém verificar se "Tessalonicenses" foi explicitamente falado. O benchmark exige WAIT para o evento 8; sem o resolver, o sistema apresentaria a referência inferida.

### Alternativa 2: SemanticEngine e ReferenceResolver em paralelo

Permitir que ambos publiquem `ReferenceDetected`; o `VersePresentationService` decide qual usar.

Rejeitada porque cria ambiguidade: se o parser publica `ReferenceDetected` para 1 Cor 14:10 e o LLM publica `ReferenceDetected` para 1 Cor 14:11 no mesmo segmento, o `VersePresentationService` recebe dois eventos conflitantes. O benchmark define `decision_source="parser"` para o evento 2, indicando que o parser é autoritativo. Paralelismo viola essa precedência.

### Alternativa 3: SemanticEngine publica via ReferenceResolver sem validação lexical

Manter o `ReferenceResolver` como intermediário mas remover a validação lexical (CAP-06).

Rejeitada porque o `ReferenceResolver` sem validação lexical é apenas um pass-through: valida no `Searcher` (que confirma que a referência existe) e publica. Isso não impede inferência teológica. O benchmark exige que "igreja de Tessalônica" não gere apresentação; sem validação lexical, o resolver publica `ReferenceDetected` para 1 Tess 5:23 porque a referência existe no `Searcher`.

## Pros

- Caminho do LLM para apresentação tem dois guardões: validação lexical (CAP-06) e validação de existência (Searcher).
- Parser mantém precedência: se o parser já resolveu, o resolver não duplica.
- Responsabilidades são claras: LLM sugere, resolver valida, parser decide.

## Cons

- Latência adicional: `IntentCandidate` → `ReferenceResolver` → `ReferenceDetected` → `VersePresentationService` é uma cadeia longa.
- Se o `ReferenceResolver` falhar, o LLM nunca consegue apresentar, mesmo quando sua inferência está correta.

## Consequences

**Simples:** o LLM pode ser agressivo em suas sugestões sem risco de apresentação indevida, porque o resolver filtra. Isso permite que o prompt do LLM seja otimizado para recall (sugerir muito) sem preocupação com precisão.

**Complexo:** o `ReferenceResolver` se torna um ponto crítico de falha. Se ele cai, o LLM é completamente inutilizado. O sistema precisa monitorar a saúde do resolver.

**Irreversível sem refatoração:** uma vez que o LLM não pode publicar `ReferenceDetected`, dar essa capacidade a ele no futuro requer adicionar um segundo caminho de publicação, que precisa ser coordenado com o parser para evitar duplicação. Isso é uma mudança arquitetural, não uma extensão.

## Migration impact

Nenhum. Esta decisão formaliza o fluxo existente. O `SemanticEngine` já publica apenas `IntentCandidate`; o `ReferenceResolver` já é o intermediário.

## Future work

- Avaliar se o `ReferenceResolver` pode ser estendido para suportar múltiplos `IntentCandidate` simultâneos sem race conditions.
- Considerar cache de validações lexicais para reduzir latência.

---

# ADR-005

## Referências incompletas entram em PREPARE

Status: Accepted

## Context

O pregador frequentemente menciona um livro sem imediatamente citar capítulo e versículo. No benchmark, o evento 1 é "Abra comigo no livro de Primeiro Coríntios" sem capítulo nem versículo. O evento 7 é "Lá em Gênesis 3" sem versículo. O evento 9 é "Evangelho de João" sem capítulo nem versículo.

O sistema precisa decidir o que fazer quando detecta um livro mas a referência está incompleta. Três opções: aguardar em WAIT (ignorar até ter a referência completa), entrar em PREPARE (sinalizar que uma referência está sendo construída), ou apresentar imediatamente o que tiver (ex.: abrir o livro no Holyrics sem capítulo específico).

O benchmark define que o evento 1 (livro sem capítulo) deve transitar para PREPARE, não WAIT e não PRESENT. O evento 7 (livro + capítulo sem versículo) também deve transitar para PREPARE.

## Decision

Referências incompletas (livro detectado sem capítulo, ou livro + capítulo sem versículo) entram em PREPARE. O sistema nunca apresenta uma referência incompleta (não vai para PRESENT sem versículo). PREPARE é o estado de acumulação: o sistema sabe que uma referência está sendo construída e aguarda os componentes faltantes.

## Alternatives considered

### Alternativa 1: Permanecer em WAIT até ter referência completa

Ignorar referências parciais. Só transitar para PRESENT quando livro + capítulo + versículo estão todos presentes em um único segmento.

Rejeitada porque o benchmark exige PREPARE para o evento 1 (só livro) e evento 7 (livro + capítulo). Além disso, o pregador frequentemente constrói referências ao longo de múltiplos segmentos (eventos 1→2, 9→10). Se o sistema ignora referências parciais, perde a oportunidade de propagar contexto (CAP-02) e não consegue completar referências cross-segmento.

### Alternativa 2: Apresentar referência parcial em PRESENT

Abrir o livro no Holyrics quando o livro é detectado, mesmo sem capítulo. Abrir o capítulo quando capítulo é detectado, mesmo sem versículo.

Rejeitada porque o benchmark exige que PRESENT só ocorra quando a referência está completa (livro + capítulo + versículo). Apresentar parcialmente causa flicker na tela: o Holyrics abriria o livro, depois o capítulo, depois o versículo, em três passos. O benchmark define `action="PRESENT"` apenas para referências completas.

### Alternativa 3: PREPARE apenas para livro, WAIT para livro+capítulo sem versículo

Diferenciar: livro sozinho entra PREPARE, mas livro+capítulo sem versículo permanece em WAIT porque o versículo pode nunca chegar.

Rejeitada porque o benchmark define o evento 7 ("Gênesis 3" sem versículo) como PREPARE. Livro + capítulo sem versículo é uma referência mais completa que livro sozinho; se livro sozinho entra PREPARE, livro+capítulo também deve entrar. A distinção criaria um comportamento não intuitivo onde mais informação resulta em menos preparação.

## Pros

- Sistema sinaliza ao operador e à infraestrutura que uma referência está sendo construída, permitindo pré-carregamento.
- Contexto é mantido para completar referências cross-segmento (CAP-02).
- Comportamento corresponde exatamente ao benchmark.

## Cons

- PREPARE pode durar indefinidamente se o pregador nunca completa a referência (mitigado por CAP-05: expiração).
- Falsos PREPARE ocorrem quando o pregador menciona um livro narrativamente (mitigado por CAP-03: classificação de intenção).

## Consequences

**Simples:** a regra é clara: sem versículo, é PREPARE. Com versículo, é PRESENT. Sem livro, é WAIT.

**Complexo:** o sistema precisa distinguir menções narrativas de pedidos de abertura (CAP-03) para evitar PREPARE indevido. PREPARE também introduz a necessidade de expiração (CAP-05), que adiciona complexidade ao orquestrador.

**Irreversível sem refatoração:** uma vez que referências incompletas entram em PREPARE, remover esse comportamento significa que o sistema só reage a referências completas, o que invalida CAP-02 (propagação de contexto cross-segmento) e todos os eventos do benchmark onde a referência é construída em múltiplos segmentos.

## Migration impact

Baixo. O `IncrementalBiblicalParser` já publica `ReferenceCandidate` com confiança 0.40 (livro) e 0.75 (livro+capítulo). O orquestrador apenas mapeia esses candidatos para PREPARE em vez de ignorá-los.

## Future work

- Avaliar se o sistema deve pré-carregar o livro no Holyrics durante PREPARE (sem exibir ao público) para reduzir latência quando PRESENT ocorrer.
- Considerar se PREPARE com livro+capítulo deve ter prioridade de pré-carregamento maior que PREPARE com apenas livro.

---

# ADR-006

## Inferência teológica é proibida

Status: Accepted

## Context

O `SemanticEngine` usa um LLM que tem conhecimento teológico. Dada a entrada "igreja de Tessalônica", o LLM pode inferir "1 Tessalonicenses 5:23". Dada a entrada "Filho, este é o caminho, siga por ele", o LLM pode reconhecer a citação de Isaías 30:21. Dada a entrada "no princípio criou Deus os céus e a terra", o LLM pode inferir Gênesis 1:1.

O benchmark exige que o sistema permaneça em WAIT para todos esses casos (eventos 3, 8, 11). O pregador não citou explicitamente o livro, capítulo e versículo. Apresentar uma referência inferida a partir de conhecimento teológico viola o princípio conservador: o sistema não deve inventar ou completar referências que o pregador não fez.

## Decision

O sistema nunca publica `ReferenceDetected` para uma referência cujo livro não foi explicitamente mencionado pelo pregador no segmento atual ou em segmento recente ainda no contexto ativo. O `ReferenceResolver` aplica validação lexical (CAP-06) que rejeita `IntentCandidate` sem correspondência lexical do livro no texto transcrito. Inferência teológica, reconhecimento de citações verbais, e mapeamento de nomes de cidades para livros são todos proibidos como fontes de `ReferenceDetected`.

## Alternatives considered

### Alternativa 1: Permitir inferência teológica com flag de baixa confiança

Permitir que o LLM infira referências mas marcá-las com `confidence < 0.5` e só apresentar se o operador aprovar manualmente.

Rejeitada porque o benchmark não tem conceito de aprovação manual. O benchmark define `action="WAIT"` para os eventos 3, 8 e 11, não `action="PRESENT_WITH_LOW_CONFIDENCE"`. Introduzir um caminho de baixa confiança adiciona complexidade ao orquestrador e à máquina de estados sem suporte no benchmark.

### Alternativa 2: Permitir inferência teológica apenas para citações verbais reconhecíveis

Criar uma lista de citações conhecidas (ex.: "Filho, este é o caminho" → Isaías 30:21) e permitir apresentação quando a citação é reconhecida.

Rejeitada porque o benchmark explicitamente exige WAIT para o evento 11, que é exatamente uma citação verbal não-atribuída. Permitir reconhecimento de citações viola diretamente o benchmark. Além disso, manter uma base de dados de citações é frágil: citações podem ser parciais, parafraseadas, ou atribuídas erroneamente pelo pregador.

### Alternativa 3: Permitir inferência teológica mas exigir confirmação do pregador

Apresentar a referência inferida e esperar que o pregador confirme no segmento seguinte. Se o pregador não confirmar, reverter.

Rejeitada porque o benchmark não tem conceito de "apresentação provisória". O Holyrics exibe o versículo para a congregação; reverter causaria flicker e confusão. O sistema conservador não apresenta nada até ter certeza.

## Pros

- Sistema é conservador por design: nunca apresenta algo que o pregador não pediu explicitamente.
- Comportamento é reproduzível: a validação lexical é determinística.
- Operador e congregação não veem falsos positivos teológicos.

## Cons

- Sistema perde capacidade de apresentar referências que o pregador cita verbalmente sem atribuir (ex.: evento 11).
- LLM é subutilizado: seu conhecimento teológico é deliberadamente ignorado.
- Se o pregador usa uma paráfrase de uma citação conhecida, o sistema não reconhece.

## Consequences

**Simples:** a regra é binária: o livro foi explicitamente mencionado? Se não, rejeita. Não há gray area.

**Complexo:** o `ReferenceResolver` precisa acesso ao texto transcrito e ao `ParserBookTable` para validação lexical, adicionando dependências. O guardão (CAP-06) é um ponto adicional de rejeição que pode gerar falsos negativos se o STT corrompe o nome do livro.

**Irreversível sem refatoração:** uma vez que inferência teológica é proibida, permitir no futuro requer adicionar um novo caminho no `ReferenceResolver` que bypassa a validação lexical, o que é uma mudança arquitetural. O benchmark também precisaria ser revisado para incluir casos de inferência aceitos, o que invalida o benchmark atual.

## Migration impact

Moderado. O `ReferenceResolver` precisa ser estendido com validação lexical (CAP-06). O `SemanticEngine` não muda. O `IntentRejected` é um novo evento no `PipelineEventBus`.

## Future work

- Avaliar se o sistema deve oferecer um modo "agressivo" opcional (configurável) onde inferência teológica é permitida com confirmação do operador. Este modo não seria validado pelo benchmark atual.
- Considerar log de inferências rejeitadas para análise post-hoc: se muitas inferências corretas são rejeitadas, o benchmark pode precisar de revisão.

---

# ADR-007

## Uma única referência ativa por vez

Status: Accepted

## Context

O pregador pode mencionar múltiplos livros em rápida sucessão. No benchmark, o evento 3 menciona "Gênesis" e "Salmos" no mesmo segmento narrativo. O evento 7 menciona "Gênesis 3" enquanto o sistema ainda tem contexto de 1 Coríntios. O evento 8 menciona Tessalônica enquanto Gênesis 3 está em PREPARE.

O sistema precisa decidir se mantém múltiplas referências ativas simultaneamente (ex.: PREPARE para Gênesis e PREPARE para Tessalônica ao mesmo tempo) ou se apenas uma referência pode estar ativa em PREPARE.

O benchmark define que quando o pregador muda de Gênesis 3 para Tessalônica (evento 8), Gênesis 3 é expirado e o sistema volta para WAIT. Não há nenhum evento no benchmark onde duas referências estão em PREPARE simultaneamente.

## Decision

O sistema mantém exatamente uma referência ativa por vez em PREPARE. Quando um novo livro é detectado em PREPARE, a referência anterior é expirada (CAP-05) e substituída. O contexto (`active_book`, `active_chapter`, `pending_reference`) representa apenas a referência atual. Não há fila de referências pendentes.

## Alternatives considered

### Alternativa 1: Múltiplas referências em PREPARE simultaneamente

Manter uma fila de referências pendentes. O sistema pode estar em PREPARE para Gênesis 3 e simultaneamente em PREPARE para Tessalônica.

Rejeitada porque o benchmark não tem nenhum evento que exija múltiplas referências em PREPARE. A máquina de estados (ADR-002) tem um único estado global; não há conceito de "PREPARE para X e PREPARE para Y". Múltiplas referências exigiriam uma máquina de estados por referência, o que é uma complexidade não justificada pelo benchmark.

### Alternativa 2: Múltiplas referências com prioridade

Manter múltiplas referências em PREPARE mas com prioridade (a mais recente tem precedência para PRESENT).

Rejeitada pela mesma razão que a Alternativa 1, com complexidade adicional de priorização. O benchmark não exige priorização; exige que a referência anterior seja expirada quando uma nova é detectada.

### Alternativa 3: Uma referência ativa mas sem expiração da anterior

Substituir a referência anterior sem expirá-la explicitamente. Simplesmente sobrescrever `active_book` e `pending_reference`.

Rejeitada porque o benchmark exige que a expiração seja um evento rastreável (evento 8 produz `StateChanged` com `reason="prepare_expired"`). Sobrescrever sem expirar não gera o evento, violando o contrato do benchmark. Além disso, sem expiração explícita, o sistema não limpa `active_chapter` da referência anterior, podendo associar capítulo errado à nova referência.

## Pros

- Modelo mental simples: uma referência ativa, um PREPARE, um contexto.
- Expiração é explícita e rastreável.
- Contexto é previsível: `active_book` e `active_chapter` sempre se referem à mesma referência.

## Cons

- Sistema perde contexto de referências anteriores que o pregador pode retomar (ex.: "como eu dizia em Gênesis 3" após divagar). Se expirou, é tratado como nova referência.
- Não suporta pregações onde o pregador alterna entre duas referências (ex.: comparando João 3:16 com Romanos 5:8).

## Consequences

**Simples:** o orquestrador mantém um único conjunto de variáveis de contexto. Não há necessidade de listas, filas ou mapas de referências pendentes.

**Complexo:** a expiração (CAP-05) precisa ser precisa: expirar cedo demais perde referências que o pregador retoma; expirar tarde demais mantém contexto stale que pode causar associações erradas.

**Irreversível sem refatoração:** uma vez que o sistema suporta apenas uma referência ativa, adicionar suporte a múltiplas requer mudar a máquina de estados de um único PREPARE para múltiplos PREPAREs, o que afeta o orquestrador, o `StateChanged`, e todos os consumidores. O benchmark também não tem eventos para múltiplas referências, então não há como testar esse comportamento.

## Migration impact

Nenhum. O sistema atual já mantém uma referência ativa no `IncrementalBiblicalParser` (`_current_book`, `_current_chapter`, `_current_verse`). Esta decisão formaliza que não haverá múltiplas.

## Future work

- Se um benchmark futuro exigir comparação entre duas referências, avaliar extensão da máquina de estados para suportar PREPARE_A e PREPARE_B.
- Considerar se `recent_books` (histórico de livros mencionados) é suficiente para retomar referências expiradas sem precisar de múltiplos PREPAREs.

---

# ADR-008

## Contexto expira

Status: Accepted

## Context

O `SermonContextEngine` já implementa expiração de contexto via `_apply_expiry()`: `book_expiry=15` updates, `chapter_expiry=10` updates. O `IncrementalBiblicalParser` mantém `_current_book`/`_current_chapter` indefinidamente. O `StateOrchestrator` (CAP-01) mantém `active_book` e `pending_reference`.

Sem expiração, o sistema permanece em PREPARE indefinidamente após uma referência incompleta. O evento 8 do benchmark exige que Gênesis 3 (PREPARE) seja abandonado quando o pregador muda de assunto. O evento 10 exige que "10:27" seja associado a João (evento 9) e não a Gênesis (evento 7), o que só é possível se o contexto de Gênesis expirou.

## Decision

O contexto do orquestrador (`active_book`, `active_chapter`, `pending_reference`) expira por dois mecanismos: (1) detecção de novo livro com intenção de abertura (expiração imediata), e (2) contagem de segmentos sem menção ao livro (expiração por timeout, threshold configurável, default=5). Ao expirar, o sistema transita PREPARE → WAIT e limpa todo o contexto da referência pendente.

## Alternatives considered

### Alternativa 1: Contexto nunca expira

Manter `active_book` indefinidamente até que um novo livro seja explicitamente detectado.

Rejeitada porque o evento 10 do benchmark exige que "10:27" seja associado a João, não a Gênesis. Se o contexto de Gênesis nunca expira, "10:27" chega em PREPARE com `active_book="Gênesis"` e é interpretado como Gênesis 10:27, que está errado. O evento 8 (menção de Tessalônica) é uma menção narrativa que não deveria substituir o contexto, mas também não deveria mantê-lo indefinidamente.

### Alternativa 2: Expiração apenas por tempo absoluto (segundos)

Expirar PREPARE após N segundos independentemente de atividade.

Rejeitada porque o pregador pode construir uma referência ao longo de 30 segundos (eventos 1→2: "Primeiro Coríntios" ... pausa ... "capítulo 14, versículo 10"). Um timeout absoluto curto expira prematuramente; um timeout longo não detecta mudança de assunto rápida. O benchmark é orientado a eventos (segmentos de fala), não a tempo absoluto.

### Alternativa 3: Expiração apenas por detecção de novo livro

Expirar PREPARE apenas quando um novo livro com intenção de abertura é detectado. Sem timeout.

Rejeitada porque o pregador pode mudar de assunto sem mencionar um novo livro (ex.: "agora vamos falar sobre a guerra" sem referência bíblica). Sem timeout, o sistema permanece em PREPARE para Gênesis 3 indefinidamente, esperando um versículo que nunca chega. O evento 8 do benchmark mostra que a mudança de assunto pode ser sutil e não envolver necessariamente um novo livro detectável.

## Pros

- Sistema não permanece preso em PREPARE para referências abandonadas.
- Dois mecanismos complementares: expiração imediata (novo livro) e expiração gradual (timeout).
- Threshold configurável permite ajuste fino sem mudança de código.

## Cons

- Threshold de timeout é um parâmetro sensível: muito baixo causa expiração prematura; muito alto causa associação errada.
- Expiração por novo livro depende de CAP-03 (classificação de intenção) para não expirar por menções narrativas.

## Consequences

**Simples:** o sistema sempre volta para WAIT se nada acontece. Não há estado "zombie" PREPARE permanente.

**Complexo:** o threshold de expiração precisa ser ajustado por contexto (pregador rápido vs. pregador pausado). A expiração por novo livro requer coordenação com CAP-03 (não expirar se a menção é narrativa).

**Irreversível sem refatoração:** uma vez que o contexto expira, remover a expiração significa que o sistema pode permanecer em PREPARE indefinidamente, o que invalida o evento 8 e potencialmente o evento 10 do benchmark. A expiração é parte do contrato do orquestrador.

## Migration impact

Moderado. O `SermonContextEngine` já tem `_apply_expiry()` mas opera em fluxo paralelo. O `StateOrchestrator` precisa implementar sua própria expiração ativa (CAP-05), que é o mecanismo autoritativo. A expiração do `SermonContextEngine` pode permanecer como mecanismo secundário.

## Future work

- Avaliar threshold adaptativo: ajustar `expiry_threshold_segments` dinamicamente com base no ritmo do pregador (segmentos por minuto).
- Considerar se `recent_books` deve ter expiração independente de `active_book` para permitir resolução anafórica (CAP-04) mesmo após expiração de PREPARE.

---

# ADR-009

## Replay é a verdade para regressão

Status: Accepted

## Context

O sistema precisa de um mecanismo para verificar se mudanças no código não quebram comportamentos já corretos. Tradicionalmente, unit tests verificam componentes isolados e integration tests verificam integração entre componentes. Mas o AI Lyrics tem um requisito especial: o comportamento esperado é definido por uma sequência de estados e eventos extraídos de uma pregação real.

O benchmark `morning-prayer-27-07-2026` contém 11 eventos com transições de estado, contexto, confiança, ação esperada, razão e fonte de decisão. Esta sequência é a especificação executável do comportamento esperado.

## Decision

O mecanismo primário de teste de regressão é o replay do benchmark: alimentar a transcrição da pregação no pipeline e comparar a sequência de `StateChanged` (e eventos derivados) com os 11 eventos do benchmark YAML. Se a sequência produzida difere da sequência esperada, o teste falha. Unit tests permanecem para testes de componentes isolados, mas o replay é a verdade final para aceitação de regressão.

## Alternatives considered

### Alternativa 1: Apenas unit tests por componente

Testar cada componente isoladamente: parser, orquestrador, resolver, contexto. Sem teste de integração.

Rejeitada porque unit tests não capturam interações entre componentes. O benchmark exige coordenação entre parser (detecção), orquestrador (estado), contexto (propagação cross-segmento) e apresentação (repeat). Um unit test do parser pode passar enquanto o orquestrador falha em mapear a saída do parser para o estado correto.

### Alternativa 2: Integration tests ad-hoc sem replay estruturado

Escrever integration tests que simulam segmentos de fala e verificam eventos, mas sem um arquivo canônico de benchmark.

Rejeitada porque sem um arquivo canônico, os testes são frágeis e subjetivos. Cada desenvolvedor pode escrever testes diferentes com expectativas diferentes. O benchmark YAML é a fonte única de verdade: se o replay produz exatamente os 11 eventos, o sistema está correto. Sem replay, não há critério objetivo de aceitação.

### Alternativa 3: Replay com tolerância fuzzy

Permitir que o replay produza eventos "aproximadamente" iguais ao benchmark (ex.: mesma referência mas confidence diferente, mesmo estado mas reason diferente).

Rejeitada porque o benchmark define campos exatos para cada evento, incluindo `confidence`, `decision_source`, `action` e `reason`. Tolerância fuzzy mascara regressões: se a confidence muda de 0.98 para 0.75, o sistema pode parar de publicar `ReferenceDetected` e o comportamento muda silenciosamente. O replay deve ser estrito: correspondência exata em todos os campos.

## Pros

- Critério de aceitação é objetivo e binário: o replay produz os 11 eventos ou não produz.
- Novos benchmarks podem ser adicionados sem mudar o framework de teste.
- Replay captura interações entre todos os componentes automaticamente.

## Cons

- Replay só testa a pregação do benchmark. Pregações com padrões diferentes podem quebrar sem o teste detectar.
- Se o benchmark tem erros (ex.: evento mal especificado), o replay reprova código correto.
- Replay não substitui unit tests para edge cases não cobertos pelo benchmark.

## Consequences

**Simples:** adicionar um novo benchmark (nova pregação) cria automaticamente um novo teste de regressão sem código adicional.

**Complexo:** qualquer mudança no pipeline que afete a sequência de eventos precisa ser validada contra todos os benchmarks existentes. Se há 10 benchmarks, uma mudança precisa passar em 10 replays.

**Irreversível sem refatoração:** uma vez que o replay é a verdade, mudar o formato do benchmark (ex.: adicionar campos, mudar estrutura do YAML) invalida todos os replays existentes. O formato do benchmark é um contrato tão fundamental quanto a máquina de estados.

## Migration impact

Baixo. O benchmark YAML já existe e está aprovado. O mecanismo de replay precisa ser construído, mas não altera componentes existentes.

## Future work

- Avaliar suporte a múltiplos benchmarks simultâneos (suite de regressão).
- Considerar diff visual entre sequência esperada e produzida para facilitar debugging de regressões.
- Avaliar se o replay deve incluir telemetria (ex.: latência, context_hits) além de eventos.

---

# ADR-010

## Benchmark é fonte oficial de comportamento

Status: Accepted

## Context

O sistema AI Lyrics tem múltipros documentos que descrevem comportamento esperado: o `benchmark.yaml` define eventos e estados, o `analysis.md` descreve a estratégia do pregador e riscos, o `capability_gap_analysis.md` identifica capacidades faltantes, o `rfc_capabilities.md` especifica como implementar cada capacidade.

Há potencial para conflito: se o `analysis.md` diz que algo é "raro" mas o benchmark inclui um evento para isso, qual prevalece? Se o RFC descreve um comportamento que o benchmark não testa, esse comportamento é obrigatório?

## Decision

O `benchmark.yaml` é a fonte única e oficial de comportamento esperado do sistema. Qualquer comportamento não coberto pelo benchmark é opcional e não pode ser usado como critério de rejeição em testes de regressão. Se há conflito entre o benchmark e qualquer outro documento, o benchmark prevalece. O `analysis.md` é contexto interpretativo; os RFCs são especificações de implementação; o benchmark é o contrato verificável.

## Alternatives considered

### Alternativa 1: RFCs são a fonte oficial

Usar `rfc_capabilities.md` como fonte de verdade. O benchmark é apenas um exemplo.

Rejeitada porque RFCs descrevem como implementar, não o que o sistema deve fazer observavelmente. RFCs podem ter ambiguidades, omissões ou over-specification. O benchmark é executável e verificável: dada uma entrada, há exatamente uma saída esperada. RFCs são meios; benchmark é fim.

### Alternativa 2: Análise é a fonte oficial

Usar `analysis.md` como fonte de verdade. O benchmark é derivado da análise.

Rejeitada porque a análise é interpretativa: descreve intenções do pregador, riscos e estratégias. Não é executável. Dois desenvolvedores podem ler a mesma análise e implementar comportamentos diferentes. O benchmark foi derivado da análise precisamente para remover ambiguidade.

### Alternativa 3: Múltiplas fontes com precedência definida por documento

Definir que benchmark prevalece sobre RFCs, RFCs prevalecem sobre análise, análise prevalece sobre código existente.

Rejeitada porque cria um sistema legalístico de precedência que é difícil de aplicar na prática. Se o benchmark diz WAIT mas o RFC descreve um edge case que implique PREPARE, o desenvolvedor precisa resolver o conflito manualmente. Com o benchmark como fonte única, não há conflito: se o benchmark não testa o edge case, ele é opcional.

## Pros

- Fonte de verdade é única, executável e não-ambígua.
- Disputas sobre comportamento são resolvidas consultando o benchmark, não debatendo interpretações.
- Documentos secundários (análise, RFCs) podem evoluir independentemente sem invalidar o contrato.

## Cons

- Comportamentos não cobertos pelo benchmark são não-testados e podem regredir silenciosamente.
- Se o benchmark tem um erro, o erro é a verdade até o benchmark ser corrigido.
- Benchmark é específico a uma pregação; padrões não presentes nessa pregação não são testados.

## Consequences

**Simples:** qualquer discussão sobre "o que o sistema deve fazer" é resolvida apontando para o evento específico no benchmark.

**Complexo:** o benchmark precisa ser mantido com rigor: qualquer erro ou omissão tem impacto direto no sistema. Adicionar um novo benchmark é um processo formal que precisa de revisão.

**Irreversível sem refatoração:** uma vez que o benchmark é a fonte oficial, mudar o benchmark para corrigir um erro ou adicionar um caso é uma mudança de contrato que pode invalidar implementações existentes. O benchmark é tão fundamental quanto a máquina de estados e o formato de eventos.

## Migration impact

Nenhum. Esta decisão formaliza a relação já implícita entre os documentos.

## Future work

- Estabelecer processo formal para adição de novos benchmarks (revisão, aprovação, versionamento).
- Avaliar versionamento do benchmark (ex.: `benchmark-v1.yaml`, `benchmark-v2.yaml`) se mudanças forem necessárias sem invalidar implementações existentes.
- Considerar se o benchmark deve incluir casos negativos explícitos (ex.: "este segmento NÃO deve gerar evento") além dos 11 eventos positivos.
