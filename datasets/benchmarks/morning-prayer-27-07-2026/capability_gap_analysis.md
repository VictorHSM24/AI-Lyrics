# Capability Gap Analysis — AI Lyrics Benchmark

## Premissa

O benchmark `morning-prayer-27-07-2026` é a verdade absoluta. Cada capacidade abaixo existe porque pelo menos um evento do benchmark a exige. Se um evento não depende de uma capacidade, ela não aparece aqui.

---

## Capacidades identificadas

### CAP-01

id: CAP-01
title: Orquestração de máquina de estados (WAIT / PREPARE / PRESENT / IGNORE)
description: >
  O sistema não possui uma máquina de estados unificada que mapeie a saída
  do parser e do semantic_engine para os quatro estados do benchmark.
  Hoje o Parser produz Intent (show/uncertain/none), o IncrementalBiblicalParser
  produz ReferenceCandidate/ReferenceDetected, e o VersePresentationService
  consome ReferenceDetected diretamente. Nada publica estados WAIT, PREPARE
  ou IGNORE. O sistema precisa de um componente que receba eventos do parser
  e do semantic_engine e produza transições de estado determinísticas.
why_it_exists: >
  Todos os 11 eventos do benchmark são definidos por transições de estado.
  Sem a máquina de estados, o sistema não consegue reproduzir nenhum evento.
current_architecture: >
  Parser.parse() retorna Intent com action="show"/"uncertain"/"none".
  IncrementalBiblicalParser publica ReferenceCandidate (0.40/0.75) e
  ReferenceDetected (0.98). BiblicalNLUService converte Intent em
  ReferenceDetected ou IntentUnknown. VersePresentationService consome
  ReferenceDetected e apresenta. Nenhum componente emite ou consome
  estados WAIT/PREPARE/PRESENT/IGNORE.
required_modules: IncrementalBiblicalParser, BiblicalNLUService, VersePresentationService, PipelineEventBus
difficulty: MEDIUM
priority: P0
risk_if_missing: >
  Sem esta capacidade, o sistema não consegue executar nenhum evento do
  benchmark. Não há como distinguir "sistema aguardando" de "sistema
  preparando" de "sistema apresentando".
benchmark_events: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
acceptance_criteria:
  - "O sistema deve publicar exatamente um estado (WAIT, PREPARE, PRESENT ou IGNORE) a cada segmento de fala processado."
  - "O estado só deve mudar quando uma condição de transição é satisfeita; segmentos sem referência não geram mudança de estado além de PRESENT → WAIT."
  - "ReferenceCandidate com confidence >= 0.40 deve mapear para PREPARE."
  - "ReferenceCandidate com confidence >= 0.75 e sem versículo deve mapear para PREPARE (nunca PRESENT)."
  - "ReferenceDetected com confidence >= 0.98 deve mapear para PRESENT."
  - "Segmentos sem livro detectado devem mapear para WAIT ou IGNORE."

### CAP-02

id: CAP-02
title: Propagação de contexto entre segmentos (active_book跨segmentos)
description: >
  O sistema precisa manter o livro ativo (active_book) entre segmentos
  de fala consecutivos para que "capítulo 14, versículo 10" ou "10:27"
  chegando como segmento separado seja associado ao livro detectado
  no segmento anterior. O IncrementalBiblicalParser mantém _current_book
  internamente, mas o BiblicalNLUService é stateless e não preserva
  contexto entre chamadas. O SermonContextEngine mantém book/chapter
  no SermonContext, mas não está conectado ao fluxo do parser.
why_it_exists: >
  Nos eventos 2, 5 e 10, o capítulo e versículo chegam em segmento
  separado do nome do livro. Sem propagação de contexto, o sistema
  não consegue completar a referência.
current_architecture: >
  IncrementalBiblicalParser mantém _current_book, _current_chapter,
  _current_verse como estado interno entre chamadas de process().
  BiblicalNLUService é explicitamente stateless. SermonContextEngine
  mantém SermonContext.book/chapter mas opera em um fluxo paralelo
  não conectado ao parser. Parser.parse() recebe BibleState opcional
  mas este representa o estado da Bíblia no Holyrics, não o estado
  do parser incremental.
required_modules: IncrementalBiblicalParser, SermonContextEngine, BiblicalNLUService
difficulty: MEDIUM
priority: P0
risk_if_missing: >
  Sem esta capacidade, eventos 2, 5 e 10 falham. O sistema ouve
  "capítulo 14, versículo 10" sem saber de qual livro se trata,
  e não consegue apresentar a referência.
benchmark_events: [2, 5, 10]
acceptance_criteria:
  - "O sistema deve manter active_book no contexto entre segmentos até que o livro expire ou seja substituído."
  - "Quando o parser detecta apenas capítulo/versículo (sem nome de livro), o sistema deve usar active_book do contexto para completar a referência."
  - "O sistema deve diferenciar números isolados que são continuação de referência (após PREPARE) de números isolados aleatórios (em estado WAIT)."
  - "O formato compacto '10:27' deve ser parseado como capítulo 10, versículo 27 quando há active_book no contexto."

### CAP-03

id: CAP-03
title: Classificação de intenção do pregador (pedido de abertura vs. menção narrativa)
description: >
  O parser é puramente sintático: encontra nomes de livros e números.
  Não distingue "Abra comigo a sua Bíblia no livro de Primeiro Coríntios"
  (pedido de abertura, deve entrar PREPARE) de "pregava ontem sobre Gênesis"
  (menção passiva, deve manter WAIT). O sistema precisa classificar a
  intenção do pregador ao mencionar um livro bíblico para decidir se
  a menção é um pedido de abertura ou uma referência narrativa.
why_it_exists: >
  O evento 3 contém "Gênesis" e "Salmos" como nomes de livros detectáveis
  pelo parser, mas o contexto é de menção passiva ("pregava ontem sobre")
  e referência vaga ("Como diz lá em"). O sistema deve manter WAIT
  e não entrar PREPARE para essas menções.
current_architecture: >
  Parser._has_trigger() verifica verbos de comando (abre, mostrar, exibe)
  e pronomes demonstrativos. Se um livro é encontrado sem números, retorna
  action="uncertain". Não há classificação de intenção além da detecção
  de gatilhos lexicais. O semantic_engine pode inferir intenção via LLM,
  mas não há um mecanismo que use essa inferência para suprimir PREPARE.
required_modules: Parser, SemanticEngine, IncrementalBiblicalParser
difficulty: HIGH
priority: P0
risk_if_missing: >
  Sem esta capacidade, o sistema entra PREPARE para toda menção de livro
  bíblico, gerando falsos positivos massivos. O evento 3 é o teste mais
  crítico de falso positivo do benchmark.
benchmark_events: [3, 7]
acceptance_criteria:
  - "O sistema deve reconhecer 'Abra comigo em [livro]' como pedido de abertura e entrar PREPARE."
  - "O sistema deve reconhecer 'pregava ontem sobre [livro]' como menção passiva e manter WAIT."
  - "O sistema deve reconhecer 'Como diz lá em [livro]' sem capítulo/versículo como referência vaga e manter WAIT."
  - "O sistema deve reconhecer 'Lá em [livro] [capítulo]' como referência bíblica ativa e entrar PREPARE."
  - "A classificação de intenção deve ser determinística quando possível (padrões lexicais) e usar semantic_engine apenas como fallback."

### CAP-04

id: CAP-04
title: Resolução anafórica de livro (nome sem ordinal)
description: >
  O pregador diz "aqui em Coríntios" sem o prefixo "Primeiro". O alias
  "coríntios" (sem ordinal) não está na tabela de aliases do books.json.
  O sistema precisa resolver nomes de livros sem ordinal usando o
  contexto (last_presented_reference ou recent_books) para determinar
  se "Coríntios" se refere a 1 Coríntios ou 2 Coríntios.
why_it_exists: >
  O evento 4 contém "aqui em Coríntios" que deve resolver para
  1 Coríntios. Sem esta capacidade, o parser não encontra o livro
  e o evento 4 não dispara PREPARE.
current_architecture: >
  ParserBookTable.resolve() faz longest-match contra aliases normalizadas.
  As aliases de 1 Coríntios incluem "1 coríntios", "primeiro coríntios",
  "i coríntios", mas não "coríntios" isolado. SermonContextEngine mantém
  recent_books no SermonContext, mas o parser não consulta este contexto.
required_modules: ParserBookTable, config/books.json, SermonContextEngine
difficulty: LOW
priority: P1
risk_if_missing: >
  Sem esta capacidade, o evento 4 falha. O sistema não detecta
  "Coríntios" como livro e não entra PREPARE. A re-referência
  de 1 Cor 14:10 é perdida.
benchmark_events: [4]
acceptance_criteria:
  - "O sistema deve resolver 'Coríntios' (sem ordinal) usando contexto quando há um livro compatível em recent_books ou last_presented_reference."
  - "Se ambos 1 Coríntios e 2 Coríntios estão no histórico, o sistema deve preferir o mais recente."
  - "Se nenhum livro compatível está no contexto, o sistema deve tentar resolver 'Coríntios' como 1 Coríntios (default para ordinal omitido)."
  - "A resolução anafórica não deve aplicar-se a livros sem ambiguidade de ordinal (ex.: 'João' sempre resolve para João, não '1 João')."

### CAP-05

id: CAP-05
title: Expiração de referência pendente por mudança de assunto
description: >
  Quando o sistema está em PREPARE (ex.: Gênesis 3 sem versículo) e o
  pregador muda para outro assunto que não completa a referência, o
  sistema deve expirar o PREPARE e voltar para WAIT. A expiração não
  deve ocorrer imediatamente, mas após detectar que o tópico mudou
  (novo livro mencionado, ou segmento sem continuação numérica após
  N atualizações).
why_it_exists: >
  O evento 8 testa exatamente isto: Gênesis 3 está em PREPARE (evento 7),
  e quando o pregador passa a falar sobre Tessalônica, o sistema deve
  abandonar Gênesis 3 e voltar para WAIT.
current_architecture: >
  SermonContextEngine._apply_expiry() expira book/chapter após N
  atualizações (book_expiry=15, chapter_expiry=10). IncrementalBiblicalParser
  mantém _current_book/_current_chapter mas não tem mecanismo de expiração
  explícito. O parser incremental publica ReferenceCandidate mas não tem
  um evento de "expiração" ou "abandono" quando o contexto muda.
required_modules: IncrementalBiblicalParser, SermonContextEngine
difficulty: MEDIUM
priority: P1
risk_if_missing: >
  Sem esta capacidade, o sistema permanece em PREPARE indefinidamente
  após Gênesis 3. Quando "10:27" chega no evento 10, o sistema pode
  incorretamente associá-lo a Gênesis 3 em vez de João.
benchmark_events: [8]
acceptance_criteria:
  - "O sistema deve expirar PREPARE quando um novo livro é detectado (BookChanged) sem completar a referência pendente."
  - "O sistema deve expirar PREPARE após N segmentos sem continuação numérica (configurável, default conservador)."
  - "Ao expirar, o sistema deve publicar transição PREPARE → WAIT e limpar active_book/active_chapter/pending_reference."
  - "A expiração não deve ocorrer entre segmentos que claramente continuam a mesma referência (ex.: livro detectado, capítulo detectado, versículo pendente)."

### CAP-06

id: CAP-06
title: Supressão conservadora de inferência teológica
description: >
  O semantic_engine e o ReferenceResolver podem inferir referências
  a partir de conhecimento teológico: "igreja de Tessalônica" implica
  1 Tessalonicenses, "Filho, este é o caminho, siga por ele" é Isaías
  30:21. O sistema conservador não deve completar referências ausentes
  a partir de inferência teológica. Esta capacidade é um guardão que
  impede o semantic_engine de publicar IntentCandidate que mapeie
  para uma referência não explicitamente citada pelo pregador.
why_it_exists: >
  Os eventos 3, 8 e 11 contêm menções indiretas e citações reconhecíveis
  que uma IA agressiva poderia inferir. O benchmark exige WAIT para
  todos esses casos.
current_architecture: >
  SemanticEngine._run_inference() consulta o LLM e publica IntentCandidate.
  ReferenceResolver assina IntentCandidate, valida via Searcher, e pode
  publicar ReferenceDetected. Não há guardão explícito que impeça a
  inferência de referências a partir de menções indiretas ou citações.
  O _parser_already_resolved verifica se o parser já resolveu, mas não
  há verificação inversa: impedir o resolver de publicar quando o
  pregador não citou explicitamente.
required_modules: SemanticEngine, ReferenceResolver
difficulty: MEDIUM
priority: P0
risk_if_missing: >
  Sem esta capacidade, o sistema pode apresentar 1 Tess 5:23 no
  evento 8 ou Isaías 30:21 no evento 11, violando o princípio
  conservador e gerando falsos positivos.
benchmark_events: [3, 8, 11]
acceptance_criteria:
  - "O sistema nunca deve publicar ReferenceDetected para uma referência onde o nome canônico do livro não foi explicitamente falado pelo pregador."
  - "O sistema nunca deve inferir capítulo ou versículo a partir do conteúdo de uma citação verbal."
  - "O sistema nunca deve mapear 'igreja de Tessalônica' para 1 Tessalonicenses sem que o pregador cite o livro, capítulo e versículo."
  - "O sistema nunca deve mapear uma citação verbal não-atribuída para sua referência de origem."
  - "O semantic_engine pode sugerir IntentCandidate, mas o resolver deve rejeitar candidatos que não tenham correspondência lexical explícita no texto transcrito."

### CAP-07

id: CAP-07
title: Detecção de referência repetida (re-citação)
description: >
  O sistema deve rastrear a última referência apresentada
  (last_presented_reference) e identificar quando o pregador
  re-cita a mesma referência. O estado deve ser PRESENT (repeat),
  permitindo que a camada de apresentação decida se re-apresenta
  ou mantém o versículo atual na tela.
why_it_exists: >
  O evento 5 é uma re-citação de 1 Cor 14:10 (mesma referência
  do evento 2). O sistema deve marcar como PRESENT (repeat),
  não como PRESENT (first).
current_architecture: >
  SermonContextEngine tem ReferenceRepeated event e _handle_reference_repeated
  que re-adiciona a referência ao topo do histórico. VersePresentationService
  tem _pending_anticipations para dedup de antecipação, mas não verifica
  se uma ReferenceDetected é repetição de uma referência já apresentada.
  Não há campo last_presented_reference no contexto do parser ou do
  estado da máquina de estados.
required_modules: SermonContextEngine, VersePresentationService, máquina de estados (CAP-01)
difficulty: LOW
priority: P2
risk_if_missing: >
  Sem esta capacidade, o sistema re-apresenta 1 Cor 14:10 no evento 5,
  causando piscar na tela. Não é um erro de referência, mas é um
  problema de UX. O benchmark marca como PRESENT (repeat) para
  permitir decisão de UX.
benchmark_events: [5]
acceptance_criteria:
  - "O sistema deve manter last_presented_reference no contexto da máquina de estados."
  - "Quando uma ReferenceDetected tem o mesmo (book_id, chapter, verse) que last_presented_reference, o sistema deve marcar como repeat."
  - "O estado deve ser PRESENT (repeat), não PRESENT (first)."
  - "A camada de apresentação deve receber a flag repeat para decidir se re-apresenta ou mantém."

---

## Agrupamento por área

### Parser

| Capacidade | Descrição |
|---|---|
| CAP-03 | Classificação de intenção (pedido vs. menção) |
| CAP-04 | Resolução anafórica de livro sem ordinal |

### Context Engine

| Capacidade | Descrição |
|---|---|
| CAP-02 | Propagação de active_book entre segmentos |
| CAP-05 | Expiração de referência pendente por mudança de assunto |

### Decision Engine

| Capacidade | Descrição |
|---|---|
| CAP-01 | Máquina de estados WAIT/PREPARE/PRESENT/IGNORE |
| CAP-07 | Detecção de referência repetida |

### Semantic Engine

| Capacidade | Descrição |
|---|---|
| CAP-06 | Supressão conservadora de inferência teológica |

---

## Matriz de dependências

| Capacidade | Depende de | Eventos impactados | Complexidade | Prioridade |
|---|---|---|---|---|
| CAP-01 | (nenhuma) | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11 | MEDIUM | P0 |
| CAP-02 | CAP-01 | 2, 5, 10 | MEDIUM | P0 |
| CAP-03 | CAP-01 | 3, 7 | HIGH | P0 |
| CAP-06 | CAP-01 | 3, 8, 11 | MEDIUM | P0 |
| CAP-04 | CAP-02 | 4 | LOW | P1 |
| CAP-05 | CAP-01, CAP-02 | 8 | MEDIUM | P1 |
| CAP-07 | CAP-01, CAP-02 | 5 | LOW | P2 |

---

## Roadmap técnico

### Sprint 1: Fundação

**Objetivo:** O sistema consegue produzir estados e transições.

| Capacidade | Entrega |
|---|---|
| CAP-01 | Máquina de estados que mapeia parser/semantic_engine output para WAIT/PREPARE/PRESENT/IGNORE |

**Validação:** Eventos 1, 6, 9, 11 devem produzir transições corretas (PREPARE para livro detectado, WAIT para não-referência). Eventos 2, 5, 10 ainda falham (sem contexto cross-segment). Eventos 3, 7, 8 ainda falham (sem classificação de intenção).

### Sprint 2: Contexto e semântica

**Objetivo:** O sistema propaga contexto entre segmentos e classifica intenção do pregador.

| Capacidade | Entrega |
|---|---|
| CAP-02 | active_book mantido entre segmentos; capítulo/versículo isolado completado com contexto |
| CAP-03 | Padrões lexicais determinísticos distinguem "Abra comigo em" de "pregava ontem sobre" |
| CAP-06 | Guardão no resolver rejeita IntentCandidate sem correspondência lexical explícita |

**Validação:** Eventos 2, 5, 10 devem passar (contexto propagado). Evento 3 deve passar (menção passiva mantém WAIT). Eventos 8, 11 devem passar (inferência suprimida). Evento 7 deve passar (PREPARE para Gênesis 3). Restam eventos 4 e 8 (precisam de CAP-04 e CAP-05).

### Sprint 3: Refinamento de contexto

**Objetivo:** O sistema resolve nomes anafóricos e expira referências pendentes.

| Capacidade | Entrega |
|---|---|
| CAP-04 | "Coríntios" sem ordinal resolve para 1 Coríntios via contexto ou default |
| CAP-05 | PREPARE expira quando pregador muda de assunto sem completar referência |

**Validação:** Evento 4 deve passar (resolução anafórica). Evento 8 deve passar completamente (Gênesis 3 expirado, Tessalônica não inferida). Todos os 11 eventos do benchmark devem passar.

### Sprint 4: Polimento

**Objetivo:** O sistema identifica re-citações e permite decisão de UX.

| Capacidade | Entrega |
|---|---|
| CAP-07 | last_presented_reference rastreado; repeat flag emitido para re-citações |

**Validação:** Evento 5 marcado como PRESENT (repeat). Camada de apresentação pode decidir se re-apresenta ou mantém. Benchmark 100% conforme.
