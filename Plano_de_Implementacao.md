# Plano de Implementação — Assistente de IA Local para Versículos no Holyrics

> Versão: 1.0 · Data: 2026-07-13
> Documento de referência: `DOCUMENTACAO_TECNICA.md` (arquitetura v2.0) — fonte oficial de verdade.
> Princípio orientador: **nenhuma fase depende de funcionalidades que ainda não existam**; cada etapa deve ser validável antes de iniciar a próxima; minimizar retrabalho.

---

## 0. Princípios do Plano

1. **Bottom-up por dependência técnica:** começa pela infraestrutura que tudo depende (índice bíblico, cliente Holyrics, logs) e só sobe para camadas que consomem essas dependências.
2. **Cada fase entrega um sistema executável:** ao fim de cada fase, há um pipeline rodando ponta-a-ponta (mesmo que parcial), não apenas módulos isolados.
3. **Validação antes de avançar:** cada fase tem critérios de conclusão e testes mínimos explícitos. Não iniciar a próxima fase sem validar a atual.
4. **Sem retrabalho estrutural:** a arquitetura (parser-first, LLM fallback, busca híbrida, Confidence Manager multi-etapa, cache) é fixa desde o início; as fases only adicionam camadas, não reescrevem as anteriores.
5. **Complexidade crescente gradualmente:** o MVP usa apenas parser determinístico + Holyrics; o LLM e a busca híbrida entram depois, quando o caminho feliz já está validado.

---

## 1. Visão Geral das Fases

| Fase | Nome | Foco | Resultado executável |
|---|---|---|---|
| 0 | Fundação | Infraestrutura, índice, cliente Holyrics, logs | CLI que exibe versículo via Holyrics a partir de referência digitada |
| 1 | MVP | STT + parser + estado + motor mínimo | Voz → versículo na tela para comandos estruturados |
| 2 | Alpha | LLM + busca lexical + confidence parcial | Voz → versículo para paráfrases exatas + casos não-estruturados |
| 3 | Beta | Busca híbrida + cache completo + confidence total + UI | Voz → versículo para paráfrases semânticas + confirmação |
| 4 | Release | Hardening, fallback, benchmark, documentação | Sistema de produção validado |

Mapa de dependências entre fases:

```
Fase 0 (Fundação)
   │
   ▼
Fase 1 (MVP) ──────────────► validação do caminho feliz
   │
   ▼
Fase 2 (Alpha) ────────────► LLM + busca lexical
   │
   ▼
Fase 3 (Beta) ─────────────► busca híbrida + cache + UI
   │
   ▼
Fase 4 (Release) ──────────► hardening
```

---

## Fase 0 — Fundação

### Objetivo
Estabelecer a infraestrutura mínima que todas as outras fases consomem: estrutura de projeto, configuração, índice bíblico (FTS5), tabela canônica de livros, cliente Holyrics e log estruturado. Ao final, um CLI deve conseguir exibir um versículo no Holyrics a partir de uma referência digitada manualmente.

### Justificativa
Toda fase posterior depende de: (a) um índice bíblico consultável, (b) um cliente Holyrics funcional, (c) uma tabela de livros canônica compartilhada entre parser e estado, (d) logs estruturados para auditoria. Construir isso primeiro elimina a maior fonte de retrabalho — mudanças no esquema do índice ou no cliente Holyrics depois que módulos superiores já os consomem.

### Dependências
- Python 3.11+ instalado.
- Holyrics instalado e com API Server habilitado (token criado).
- Arquivo de texto bíblico fonte (ACF ou equivalente em domínio público) disponível.

### Módulos envolvidos
- `config/` — `config.yaml`, `books.json`
- `data/` — `bible.pt-br.sqlite`, `bible_source.json`
- `busca/indexer.py` — build do índice FTS5 (sem embeddings nesta fase)
- `integracao_holyrics/client.py` — cliente REST (`ShowVerse`, `GetBibleVersions`)
- `logs/` — estrutura de diretório + utilitário de log JSONL
- `core/decision.py` — esqueleto (validação de referência + chamada Holyrics)
- `scripts/build_index.py`

### Entregáveis
1. Repositório com estrutura de pastas da arquitetura (§16 da doc. técnica).
2. `config.yaml` com IP/porta/token do Holyrics, caminhos de dados, limiares default.
3. `books.json` com os 66 livros canônicos (PT-BR) + aliases + IDs (1..66).
4. `bible.pt-br.sqlite` com tabela FTS5 populada (uma versão, ex.: ACF).
5. Cliente Holyrics com `show_verse(id, version)` e `get_bible_versions()` funcionando.
6. CLI `cli_show.py` que recebe `"João 3:16"` por stdin, normaliza via `books.json`, calcula `BBCCCVVV` e chama `ShowVerse`.
7. Utilitário de log JSONL com schema base (ts, etapa, duration_ms, status).

### Critérios de conclusão
- `python scripts/build_index.py` gera `bible.pt-br.sqlite` sem erros.
- `SELECT * FROM verses WHERE verses MATCH 'deus amou o mundo'` retorna João 3:16.
- `python cli_show.py` com input `"João 3:16"` exibe o versículo na tela do Holyrics.
- `GetBibleVersions` retorna a lista de versões do Holyrics local.
- Log JSONL gravado com a execução do CLI.

### Testes mínimos
- **T0.1 — Build do índice:** rodar `build_index.py` em CI/local; verificar contagem de versículos ≈ 31 000 e presença dos 66 livros.
- **T0.2 — Consulta FTS5:** 10 queries exatas (ex.: "deus amou o mundo", "sal da terra", "todas as coisas cooperam") retornam o versículo esperado.
- **T0.3 — Cliente Holyrics:** `ShowVerse` com ID `43003016` (João 3:16) retorna `status: ok` e o versículo aparece na tela.
- **T0.4 — Normalização de livros:** `books.json` resolve "1 João", "I João", "primeira joão" para o mesmo ID.
- **T0.5 — Log estruturado:** linha JSONL válida (parseable por `json.loads`) gerada por execução do CLI.

### Riscos
| Risco | Mitigação |
|---|---|
| Licença da tradução bíblica impede uso | Verificar licença antes de importar; ACF/ARC em domínio público são fallback |
| Holyrics API Server desativado por padrão | Documentar setup no README; healthcheck no CLI |
| Token/permissões insuficientes no Holyrics | Checklist de permissões (`ShowVerse`, `GetBibleVersions`) |
| Esquema FTS5 inadequado para buscas futuras | Validar tokenizer `unicode61 remove_diacritics 2` com 10 queries antes de avançar |

---

## Fase 1 — MVP (STT + Parser + Estado)

### Objetivo
Construir o caminho feliz ponta-a-ponta com voz: microfone → faster-whisper → parser determinístico → estado → Holyrics. Comandos estruturados ("João 3:16", "próximo", "volta dois") devem funcionar em < 200 ms (após fim da frase), **sem LLM e sem busca híbrida**.

### Justificativa
O parser determinístico é o componente de maior retorno em latência e previsibilidade (§1.3 da doc. técnica). Validá-lo primeiro, com STT real, confirma que o caminho crítico funciona antes de adicionar a complexidade do LLM e da busca híbrida. Se o STT ou o parser tiverem problemas, é mais barato descobrir agora.

### Dependências
- Fase 0 concluída (índice, cliente Holyrics, `books.json`, logs).
- CUDA/cuDNN instalados para faster-whisper.
- Microfone USB funcional.

### Módulos envolvidos
- `microfone/capture.py` — captura 16 kHz mono + VAD (Silero)
- `transcricao/stt.py` — faster-whisper turbo INT8 + `avg_logprob`
- `parser/normalizer.py` — lowercase, diacritics, extenso→dígito, ordinais, romanos
- `parser/books.py` — aliases + longest-match (consome `books.json` da Fase 0)
- `parser/parser.py` — regex + classificação de intenção + `c_parser`
- `estado/state.py` — `BibleState` + regras de navegação next/previous/jump
- `cache/cache.py` — apenas `current_verse` (LRU 1)
- `core/pipeline.py` — orquestração asyncio + fila
- `core/decision.py` — motor mínimo (limiar único provisório em `c_parser`)

### Entregáveis
1. Captura contínua com VAD descartando silêncio.
2. faster-whisper turbo INT8 carregado na GPU, produzindo texto + `avg_logprob`.
3. Parser reconhecendo: referência direta (com/sem marcadores), `next`, `previous`, `mais N`, `volta N`, `ainda nesse capítulo`.
4. `BibleState` com navegação correta entre versículos/capítulos/livros.
5. Pipeline asyncio conectando microfone → STT → parser → decisão → estado → Holyrics.
6. Motor de decisão mínimo: se `c_parser ≥ 0,85`, executa; senão ignora + log (LLM entra na Fase 2).
7. Log JSONL com timing por etapa (STT, parser, Holyrics, total).

### Critérios de conclusão
- Dizer "vamos abrir em João capítulo três versículo dezesseis" → versículo aparece no Holyrics.
- Dizer "próximo" → João 3:17 aparece.
- Dizer "volta dois" → João 3:15 aparece.
- Dizer "Romanos oito vinte e oito" → Romanos 8:28 aparece.
- Latência fim-da-frase → versículo-na-tela < 200 ms para comandos estruturados (medir em 20 comandos).
- Fala comum de pregação (sem comando) não dispara `ShowVerse` (taxa de falso positivo < 5% em amostra de 5 min).

### Testes mínimos
- **T1.1 — STT offline:** 10 clipes de áudio curtos (gravados) transcritos com WER percebido aceitável; `avg_logprob` registrado para calibrar `c_stt`.
- **T1.2 — Parser unitário:** 30 casos de teste (refs diretas, navegação, extenso, ordinais, sinônimos) → JSON esperado + `c_parser` esperado.
- **T1.3 — Estado unitário:** navegação next/previous nos limites de capítulo e livro (ex.: fim de João 21 → Atos 1:1).
- **T1.4 — Pipeline ponta-a-ponta:** 20 comandos falados ao vivo, medir latência total e taxa de sucesso.
- **T1.5 — Falso positivo:** 5 min de áudio de pregação sem comandos, contar `ShowVerse` indevidos.
- **T1.6 — Log:** cada execução gera linha JSONL válida com todas as etapas.

### Riscos
| Risco | Mitigação |
|---|---|
| Alucinação do Whisper em silêncio | VAD obrigatório + `condition_on_previous_text=False` |
| Microfone capta ruído/eco | Microfone direcional; testar com VAD em ambiente real |
| Parser não cobre padrão comum | Medir `parser.matched`; ampliar regex antes de avançar |
| Latência STT > esperado | Medir RTF real; se > 0,1, testar `small` em vez de `turbo` |
| `avg_logprob` não correlaciona com qualidade | Registrar valores em T1.1; calibrar `c_stt` empiricamente |

---

## Fase 2 — Alpha (LLM + Busca Lexical + Confidence Parcial)

### Objetivo
Adicionar o LLM (Qwen3 8B, lazy load) para casos não-estruturados e a busca lexical (FTS5 puro, sem embeddings ainda) para `action=search`. Introduzir o Confidence Manager com `c_stt`, `c_parser`/`c_llm` e `c_search` (lexical apenas). Paráfrases exatas ("Deus amou o mundo" → João 3:16) devem funcionar.

### Justificativa
Com o caminho feliz validado (Fase 1), adicionar o LLM permite cobrir os casos que o parser não reconhece ("abre aquele texto que fala que Deus amou o mundo"). A busca lexical FTS5 já existe (Fase 0) e resolve paráfrases exatas sem o custo de embeddings — validá-la isoladamente antes de adicionar a camada semântica (Fase 3) isola a fonte de problemas.

### Dependências
- Fase 1 concluída (pipeline, parser, estado, STT).
- llama.cpp ou Ollama instalado; modelo Qwen3 8B Q4_K_M baixado.

### Módulos envolvidos
- `llm/client.py` — cliente OpenAI-compatible (llama.cpp/Ollama), lazy load
- `llm/prompts.py` — system prompt + few-shot (schema JSON da doc. §4.4)
- `busca/searcher.py` — busca FTS5 pura (sem embeddings) + `c_search` lexical
- `confidence/manager.py` — combina `c_stt` × `c_intent` × `c_search` (parcial: `c_search` só lexical)
- `core/decision.py` — estendido: rota LLM quando parser falha; rota busca quando `action=search`
- `core/pipeline.py` — estendido: integra LLM + busca no fluxo

### Entregáveis
1. LLM carregado lazy (só na primeira vez que o parser devolve `uncertain`).
2. Prompt system rígido com few-shot produzindo JSON no schema da doc. §4.4.
3. Busca FTS5 pura com ranking bm25 + `c_search` (gap top1/top2).
4. Confidence Manager com `c_stt`, `c_intent` (parser ou LLM), `c_search` (lexical).
5. Motor de decisão com tabela de decisão (executar/confirmar/ignorar) — sem UI de confirmação ainda (ignora se ambíguo).
6. Pipeline integrado: parser falha → LLM → busca lexical → confidence → decisão.

### Critérios de conclusão
- Dizer "abre aquele texto que fala que Deus amou o mundo" → João 3:16 aparece (via LLM → busca lexical).
- Dizer "mostra o sal da terra" → Mateus 5:13 aparece.
- Dizer "aquele versículo que diz que todas as coisas cooperam para o bem" → Romanos 8:28 aparece.
- Comandos estruturados continuam funcionando sem LLM (regressão: Fase 1 não quebra).
- Latência para buscas semânticas < 1 s (medir em 20 casos).
- LLM não é carregado na VRAM até o primeiro comando não-estruturado (verificar VRAM ociosa).

### Testes mínimos
- **T2.1 — LLM unitário:** 20 entradas não-estruturadas → JSON esperado + `c_llm` ≥ 0,7.
- **T2.2 — LLM nunca inventa versículo:** 10 entradas onde o LLM poderia alucinar; verificar que `action` é sempre `search`/`none`/`show` com refs válidas ou `query`.
- **T2.3 — Busca lexical:** 15 paráfrases exatas → versículo esperado no top-1.
- **T2.4 — Confidence Manager unitário:** 20 cenários (combinações de c_stt/c_intent/c_search) → decisão esperada (execute/confirm/ignore).
- **T2.5 — Pipeline ponta-a-ponta:** 20 comandos não-estruturados ao vivo, medir latência e taxa de sucesso.
- **T2.6 — Regressão Fase 1:** reexecutar T1.4 (20 comandos estruturados) — todos ainda passam.
- **T2.7 — VRAM ociosa:** após startup, VRAM usada < 4 GB (só Whisper); após primeiro comando não-estruturado, sobe para ~8–9 GB.

### Riscos
| Risco | Mitigação |
|---|---|
| LLM produz JSON inválido | Validação de schema + retry com prompt de correção (1 retry); se falhar, ignorar + log |
| LLM alucina versículo | `action=search` sempre vai à busca; `action=show` validada contra `books.json` |
| Busca lexical falha em paráfrases não-exatas | Esperado — Fase 3 adiciona embeddings; registrar falhas para o conjunto de teste |
| Cold start do LLM > 2 s | Medir; se problemático, preload opcional após primeiro áudio detectado |
| Prompt não funciona bem em PT-BR | Iterar few-shot; registrar casos de falha para ajuste |

---

## Fase 3 — Beta (Busca Híbrida + Cache Completo + UI)

### Objetivo
Substituir a busca lexical pura pela **busca híbrida** (FTS5 + embeddings e5-small + RRF) para resolver paráfrases semânticas ("Deus amou tanto o mundo" → João 3:16). Completar o Confidence Manager com `c_search` híbrido. Adicionar cache completo e interface tray para confirmação.

### Justificativa
A busca lexical (Fase 2) falha em paráfrases onde a frase falada não contém os termos exatos do versículo. Os embeddings capturam semântica; o RRF funde lexical + semântico. Esta fase só é possível depois que a busca lexical está validada (Fase 2), porque a híbrida a reutiliza como componente. O cache completo e a UI de confirmação só fazem sentido depois que o Confidence Manager decide quando confirmar.

### Dependências
- Fase 2 concluída (LLM, busca lexical, confidence parcial).
- `sentence-transformers` instalável; modelo `multilingual-e5-small` baixado.

### Módulos envolvidos
- `busca/embeddings.py` — wrapper sentence-transformers (e5-small)
- `busca/indexer.py` — estendido: pré-calcular embeddings dos ~31 k versículos → `bible.embeddings.npy`
- `busca/searcher.py` — estendido: híbrida FTS5 + embeddings + RRF + `c_search` híbrido
- `cache/cache.py` — estendido: `recent_searches`, `frequent_verses`, `embedding_cache`, `holyrics_response`
- `confidence/manager.py` — estendido: `c_search` híbrido + caso ambíguo (gap top1/top2)
- `interface/tray.py` — tray icon (status + confirmação + modo auto/confirm/quick)
- `data/frequentes.json` — persistência de versículos frequentes

### Entregáveis
1. Embeddings pré-calculados de todos os versículos (memmap ~48 MB).
2. Busca híbrida com RRF (k=60) + `c_search` combinando score RRF e gap top1/top2.
3. Cache completo: `recent_searches` (LRU 50), `frequent_verses` (persistente), `embedding_cache` (LRU 200), `holyrics_response` (TTL 5 s).
4. Confidence Manager completo (§8 da doc. técnica) com tabela de decisão e fluxograma.
5. Interface tray: status do pipeline, confirmação de comandos ambíguos, alternância de modo.
6. `frequent_verses` desempatando buscas ambíguas.

### Critérios de conclusão
- Dizer "Deus amou tanto o mundo" → João 3:16 aparece (paráfrase não-exata, resolvida por embeddings).
- Dizer "não tentar o Senhor" → Mateus 4:7 ou Lucas 4:12 aparece (semântica).
- Busca repetida ("Deus amou o mundo" 2ª vez) retorna em < 50 ms (cache hit).
- Comando ambíguo ("aquele texto da fé") → tray pede confirmação ou usa `quick_presentation`.
- Recall@1 da busca híbrida ≥ 90% no conjunto de teste de paráfrases (~50 casos).
- Regressão: Fases 1 e 2 não quebram.

### Testes mínimos
- **T3.1 — Embeddings build:** `build_index.py --with-embeddings` gera `bible.embeddings.npy` com shape (N, 384), N ≈ 31 000.
- **T3.2 — Busca híbrida unitária:** 50 paráfrases (incluindo 20 não-exatas) → recall@1 ≥ 90%, recall@5 ≥ 98%.
- **T3.3 — RRF fusion:** 10 casos onde FTS5 e embeddings discordam → RRF produz ranking correto.
- **T3.4 — Cache:** busca repetida em < 50 ms; `frequent_verses` atualizado após `ShowVerse`.
- **T3.5 — Confidence ambíguo:** "fé" → decisão `confirm` (não `execute` direto).
- **T3.6 — Tray UI:** confirmar/cancelar via tray funciona; troca de modo persiste.
- **T3.7 — Regressão:** reexecutar T1.4 e T2.5 — todos ainda passam.
- **T3.8 — Latência busca híbrida:** p95 < 50 ms em 50 buscas.

### Riscos
| Risco | Mitigação |
|---|---|
| Embeddings e5-small fraco em PT-BR bíblico | Trocar por `ptbr-similarity-e5-small` ou `e5-large-sts-pt`; reexecutar T3.2 |
| Recall@1 < 90% | Ajustar peso RRF; adicionar reranker leve; ampliar conjunto de teste |
| Pré-cálculo de embeddings lento | One-shot no build; ~31 k × ~10 ms ≈ 5 min, aceitável |
| Tray UI adiciona complexidade | Mantê-la opcional; pipeline funciona sem UI (modo `auto`) |
| `frequent_verses` viesa resultados | Reset manual disponível; limite de influência (só desempate) |

---

## Fase 4 — Release (Hardening)

### Objetivo
Transformar o sistema validado em produção: detecção de intenção robusta, fallback heurístico, modos de operação completos, healthcheck, benchmark STT (Whisper vs Parakeet), conjunto de teste de paráfrases, dry-run, documentação de operação.

### Justificativa
As Fases 1–3 entregam funcionalidade; a Fase 4 entrega **confiabilidade de produção**. Em ambiente de culto ao vivo, falsos positivos e falhas silenciosas são inaceitáveis. O benchmark STT com áudio real decide se Whisper turbo permanece ou Parakeet v3 o substitui (decisão pendente na doc. técnica §2.3).

### Dependências
- Fase 3 concluída (sistema completo funcional).
- Conjunto de áudio real de pregação PT-BR para benchmark (gravar ~30 min em ambiente de culto).

### Módulos envolvidos
- `core/pipeline.py` — detecção de intenção refinada (gatilhos + `action=none` robusto)
- `core/decision.py` — fallback heurístico quando LLM indisponível
- `interface/tray.py` — modos `auto`/`confirm`/`quick` completos
- `config/config.yaml` — todos os limiares e modos externalizados
- `scripts/benchmark.py` — benchmark STT (Whisper vs Parakeet) + busca
- `tests/paráfrases.json` — conjunto de teste de ~50 paráfrases
- Documentação de operação (README + guia de setup)

### Entregáveis
1. Detecção de intenção refinada: palavras-gatilho + análise estrutural para reduzir `action=none` indevido.
2. Fallback heurístico: se LLM indisponível/timeout, parser + regras cobrem comandos comuns.
3. Modos `auto`/`confirm`/`quick_presentation` completos e configuráveis.
4. Healthcheck no startup: Holyrics reachability, versões de Bíblia, STT carregado, índice + embeddings carregados, LLM disponível (se não lazy).
5. Benchmark STT: WER e latência de Whisper turbo vs Parakeet v3 em áudio real PT-BR → decisão documentada.
6. Conjunto de teste de paráfrases (~50 casos) com recall@1 medido e registrado.
7. Modo dry-run: processa áudio e mostra o que faria sem chamar Holyrics.
8. Documentação de operação: setup Holyrics (API Server, token, permissões), microfone, instalação de modelos, troubleshooting.

### Critérios de conclusão
- Falso positivo em pregação comum < 1% em 30 min de áudio real.
- Fallback heurístico mantém navegação básica (next/previous) com LLM desligado.
- Healthcheck falha graciosamente se Holyrics offline (mensagem clara, sem crash).
- Benchmark STT documentado com decisão (Whisper ou Parakeet) justificada por dados.
- Dry-run reproduzível: mesmo áudio → mesma decisão.
- Documentação de operação permite que um novo operador configure o sistema do zero.

### Testes mínimos
- **T4.1 — Detecção de intenção:** 30 min de pregação sem comandos → < 1% de `ShowVerse` indevidos.
- **T4.2 — Fallback:** matar processo LLM → comandos estruturados + next/previous ainda funcionam.
- **T4.3 — Healthcheck:** Holyrics offline → mensagem clara; índice faltando → mensagem clara.
- **T4.4 — Benchmark STT:** 10 clipes de áudio real → WER Whisper vs Parakeet + latência; decisão documentada.
- **T4.5 — Paráfrases:** 50 casos → recall@1 ≥ 90% (confirma Fase 3 em áudio real).
- **T4.6 — Dry-run:** 10 comandos em modo dry-run → decisões corretas, zero chamadas ao Holyrics.
- **T4.7 — Regressão completa:** reexecutar T1.4, T2.5, T3.2 — todos passam.
- **T4.8 — Documentação:** um operador externo configura o sistema seguindo apenas a documentação.

### Riscos
| Risco | Mitigação |
|---|---|
| Falso positivo ainda alto em áudio real | Ajustar gatilhos; considerar janela de contexto (só ativar após versículo recente) |
| Parakeet v3 licença CC BY-NC 4.0 inviável | Permanecer com Whisper (MIT); benchmark serve apenas para documentar a decisão |
| Áudio real pior que o de teste (ruído, eco) | Re-treinar limiares `c_stt` com áudio real; ajustar VAD |
| Operador não consegue configurar | Iterar documentação com teste T4.8; adicionar screenshots |
| Sistema instável em execução longa (vazamento) | Teste de stress (2 h contínuas); monitorar RAM/VRAM |

---

## 2. Roadmap Consolidado

### MVP (Fases 0 + 1)

**Escopo:** infraestrutura + STT + parser determinístico + estado + Holyrics, para comandos estruturados.

**Resultado:** o pregador diz "João capítulo três versículo dezesseis" e o versículo aparece na tela em < 200 ms. "Próximo", "volta dois", "Romanos oito vinte e oito" funcionam. Sem LLM, sem busca híbrida, sem UI.

**Validação final (MVP):**
- T0.1–T0.5 (Fundação) ✓
- T1.1–T1.6 (STT + Parser) ✓
- Latência < 200 ms para 20 comandos estruturados ✓
- Falso positivo < 5% em 5 min de pregação ✓

**O que NÃO está no MVP:** LLM, busca (qualquer tipo), Confidence Manager completo, cache completo, UI, fallback, benchmark.

---

### Versão Alpha (Fase 2)

**Escopo:** MVP + LLM (lazy) + busca lexical FTS5 + Confidence Manager parcial (`c_stt`, `c_intent`, `c_search` lexical).

**Resultado:** paráfrases exatas ("Deus amou o mundo" → João 3:16) e comandos não-estruturados ("abre aquele texto que fala que Deus amou o mundo") funcionam via LLM → busca lexical. Comandos estruturados continuam sem LLM.

**Validação final (Alpha):**
- T2.1–T2.7 ✓
- Latência busca semântica < 1 s em 20 casos ✓
- Regressão MVP (T1.4) ✓
- VRAM ociosa < 4 GB antes do primeiro comando não-estruturado ✓

**O que NÃO está no Alpha:** busca híbrida (embeddings), cache completo, UI de confirmação, fallback, benchmark.

---

### Versão Beta (Fase 3)

**Escopo:** Alpha + busca híbrida (FTS5 + e5-small + RRF) + cache completo + Confidence Manager completo + UI tray.

**Resultado:** paráfrases semânticas ("Deus amou tanto o mundo" → João 3:16) funcionam. Comandos ambíguos pedem confirmação via tray. Buscas repetidas são servidas por cache em < 50 ms.

**Validação final (Beta):**
- T3.1–T3.8 ✓
- Recall@1 ≥ 90% em 50 paráfrases ✓
- Regressão MVP + Alpha ✓
- UI tray funcional (confirmação, modos) ✓

**O que NÃO está no Beta:** detecção de intenção refinada, fallback heurístico, benchmark STT, dry-run, documentação de operação.

---

### Release (Fase 4)

**Escopo:** Beta + hardening (detecção de intenção, fallback, healthcheck, modos completos) + benchmark STT + dry-run + documentação de operação.

**Resultado:** sistema de produção validado em áudio real de culto, com fallback, observabilidade completa, e documentação que permite operação por terceiros.

**Validação final (Release):**
- T4.1–T4.8 ✓
- Falso positivo < 1% em 30 min de pregação real ✓
- Fallback com LLM desligado ✓
- Benchmark STT documentado com decisão ✓
- Dry-run reproduzível ✓
- Documentação validada por operador externo ✓

---

## 3. Matriz de Cobertura de Módulos por Fase

| Módulo | Fase 0 | Fase 1 (MVP) | Fase 2 (Alpha) | Fase 3 (Beta) | Fase 4 (Release) |
|---|---|---|---|---|---|
| `config/` | ✅ | — | — | — | refinamento |
| `data/` (FTS5) | ✅ | — | — | +embeddings | — |
| `microfone/` | — | ✅ | — | — | — |
| `transcricao/` | — | ✅ | — | — | benchmark |
| `parser/` | — | ✅ | — | — | refinamento |
| `llm/` | — | — | ✅ | — | — |
| `busca/` (lexical) | indexer | — | ✅ searcher | — | — |
| `busca/` (híbrida) | — | — | — | ✅ | — |
| `estado/` | — | ✅ | — | — | — |
| `cache/` | — | current_verse | — | ✅ completo | — |
| `confidence/` | — | — | ✅ parcial | ✅ completo | — |
| `integracao_holyrics/` | ✅ | — | — | — | healthcheck |
| `interface/` | — | — | — | ✅ tray | modos completos |
| `core/pipeline.py` | — | ✅ | estendido | estendido | intenção refinada |
| `core/decision.py` | esqueleto | ✅ mínimo | estendido | estendido | fallback |
| `logs/` | ✅ base | estendido | estendido | estendido | — |
| `tests/` | T0.x | T1.x | T2.x | T3.x | T4.x + paráfrases |
| `scripts/` | build_index | — | — | — | benchmark |

Legenda: ✅ = criado/implementado na fase; "estendido" = funcionalidade adicionada sobre o existente; "—" = sem mudança.

---

## 4. Critérios Transversais (valem para todas as fases)

1. **Sem quebra de regressão:** ao iniciar uma fase, reexecutar os testes mínimos de todas as fases anteriores. Se algo quebra, corrigir antes de avançar.
2. **Log estruturado desde a Fase 0:** toda execução grava JSONL com timing e confiança por etapa (schema expande a cada fase).
3. **Configuração externalizada:** nenhum valor mágico no código (limiares, IPs, modelos) — tudo em `config.yaml`.
4. **Validação em áudio real:** Fases 1–4 devem incluir pelo menos um teste com áudio gravado em ambiente de culto (não só clipes sintéticos).
5. **Documentação incremental:** ao fim de cada fase, atualizar o README com o que está funcionando e o que falta.

---

## 5. Dependências Externas a Resolver Antes de Cada Fase

| Fase | Dependência externa | Ação |
|---|---|---|
| 0 | Texto bíblico fonte (licença) | Confirmar licença ACF/ARC; baixar JSON/SQL |
| 0 | Holyrics API Server habilitado | Configurar token + permissões no Holyrics |
| 1 | CUDA/cuDNN para faster-whisper | Instalar drivers + CUDA toolkit |
| 1 | Microfone USB | Adquirir/testar microfone direcional |
| 2 | Ollama/llama.cpp + Qwen3 8B Q4 | Instalar runtime; baixar modelo (~5 GB) |
| 3 | sentence-transformers + e5-small | `pip install sentence-transformers`; baixar modelo (~470 MB) |
| 4 | Áudio real de pregação PT-BR | Gravar ~30 min em culto (com consentimento) |
| 4 | (opcional) Parakeet v3 + NeMo | Instalar NeMo se benchmark for feito |

---

## 6. Notas sobre Retrabalho e Decisões Diferíveis

Para minimizar retrabalho, as seguintes decisões são **diferíveis** e não devem ser tomadas prematuramente:

| Decisão | Quando decidir | Por quê |
|---|---|---|
| Whisper turbo vs Parakeet v3 | Fase 4 (benchmark) | Precisa de áudio real; Whisper funciona desde a Fase 1 |
| `multilingual-e5-small` vs `ptbr-similarity-e5-small` | Fase 3 (após T3.2) | Só importa quando busca híbrida existe |
| Versão bíblica padrão (ACF vs ARC vs outra) | Fase 0, mas revisável | FTS5 suporta múltiplas versões; trocar é reindexar |
| Modo default (auto/confirm/quick) | Fase 4 | Depende de observação de uso real |
| Preload do LLM vs lazy estrito | Fase 2 (após medir cold start) | Dado empírico |

Decisões **não diferíveis** (tomadas na arquitetura e fixas desde o início):
- Parser-first com LLM fallback.
- Busca híbrida FTS5 + embeddings + RRF (não FTS5 puro, não embeddings puros).
- Confidence Manager multi-etapa com combinação multiplicativa.
- Holyrics API REST (não AutoHotkey/OCR).
- Python como linguagem principal.
- `asyncio.Queue` em processo único.

---

## 7. Conclusão

Este plano transforma a arquitetura v2.0 em um caminho de implementação incremental onde:

- **Cada fase entrega um sistema executável** (não apenas módulos isolados).
- **Nenhuma fase depende de funcionalidade futura** — a ordem respeita estritamente as dependências técnicas.
- **O retrabalho é minimizado** — decisões diferíveis são postergadas até ter dados para decidir; decisões fixas são tomadas uma vez na arquitetura.
- **Cada fase é validável** com critérios de conclusão e testes mínimos explícitos antes de avançar.
- **A complexidade cresce gradualmente** — MVP sem LLM nem busca; Alpha adiciona LLM + busca lexical; Beta adiciona híbrida + cache + UI; Release adiciona hardening.

O MVP (Fases 0 + 1) já entrega valor utilizável (comandos estruturados por voz em < 200 ms), permitindo validação com o pregador antes de investir nas camadas mais complexas.
