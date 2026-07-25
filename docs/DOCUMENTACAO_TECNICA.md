# Documentação Técnica — Assistente de IA Local para Controle Inteligente de Versículos no Holyrics

> Versão: 2.0 (revisão técnica crítica) · Data: 2026-07-13
> Hardware-alvo: Ryzen 9 5900XT · NVIDIA RTX 4060 Ti (16 GB VRAM) · SSD NVMe · RAM suficiente
> Requisito-chave: funcionamento 100% offline, latência 500 ms – 2 s (ideal < 1 s)

---

## 0. Resumo Executivo

A descoberta mais importante da pesquisa é que **o Holyrics possui uma API REST oficial, pública e documentada** (`holyrics/API-Server` no GitHub), com actions específicas para Bíblia — em especial `ShowVerse`, que aceita referências em linguagem natural (`"John 3:16"`, `"Rm 12:2"`) e IDs numéricos no formato `BBCCCVVV`. Isso **elimina a necessidade de AutoHotkey, OCR ou automação de interface**: a integração é limpa, suportada e estável.

### 0.1 Mudanças principais nesta revisão (v2.0)

| # | Mudança | Motivo técnico |
|---|---|---|
| 1 | **Arquitetura híbrida parser-first**: comandos estruturados resolvidos por parser determinístico; LLM só para interpretação semântica complexa | Reduz latência (~200–350 ms → ~50–150 ms para comandos comuns), reduz consumo de GPU/VRAM, aumenta previsibilidade e robustez |
| 2 | **Busca híbrida FTS5 + embeddings densos + RRF** | FTS5 puro falha em paráfrases ("Deus amou tanto o mundo" ≠ "Porque Deus amou o mundo de tal maneira"); embeddings capturam semântica, RRF funde os dois |
| 3 | **Confidence Manager multi-etapa** (STT, parser, LLM, busca, final) | Confiança única é insuficiente para decidir executar/confirmar/ignorar com segurança |
| 4 | **Camada de cache** (versículo atual, buscas recentes, frequentes) | Evita reprocessamento e reduz latência em comandos repetidos |
| 5 | **STT: Parakeet TDT v3 adicionado como alternativa a testar** | Suporta PT (25 idiomas europeus), 600 M params, streaming nativo NeMo; Whisper turbo mantido como padrão por maturidade/licença |
| 6 | **Benchmarks separados por fonte** (publicados vs estimados vs a medir) | Evita apresentar como fato números que dependem de implementação específica |
| 7 | **Observabilidade ampliada** com timing por etapa e motivo da decisão | Permite otimização baseada em dados reais após implantação |

### 0.2 Stack recomendada

| Camada | Componente recomendado | Justificativa resumida |
|---|---|---|
| STT | **faster-whisper + large-v3-turbo (INT8)** (padrão); Parakeet TDT v3 (alternativa a benchmarkar) | ~8x mais rápido que large-v3, ~2,9 GB VRAM; Parakeet v3 suporta PT com streaming nativo |
| Parser | **Parser determinístico (regex + normalização PT-BR)** | Resolve ~80% dos comandos sem LLM, ~1 ms, zero VRAM |
| LLM | **Qwen3 8B (Q4_K_M via llama.cpp/Ollama)** — só quando o parser falha | Melhor que Llama 3.1 8B, Apache 2.0, ótimo em PT-BR, ~5–6 GB VRAM |
| Busca | **SQLite FTS5 + multilingual-e5-small + RRF** (híbrida) | FTS5 para termos exatos, embeddings para paráfrases, RRF funde; ~130 MB, CPU |
| Estado | Módulo Python em memória + persistência JSON | Simples, auditável |
| Cache | Camada LRU em memória + `frequentes.json` | Reduz latência de comandos repetidos |
| Integração | **Holyrics API REST (HTTP POST local)** | Oficial, suportada, sem hacks |
| Orquestração | Python + fila assíncrona interna (asyncio) | Menor latência, sem processo extra |

Tudo cabe nos 16 GB de VRAM da 4060 Ti com folga, rodando offline. O LLM pode sequer ser carregado na VRAM até ser necessário (lazy load), economizando ~5–6 GB no estado ocioso.

---

## 1. Arquitetura Recomendada

### 1.1 Diagrama de blocos (arquitetura híbrida parser-first)

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Microfone  │──▶│  Captura + VAD   │──▶│  faster-whisper │
│  (contínuo) │    │  (Silero/webrtcvad)│  │  (STT, GPU)     │
└─────────────┘    └──────────────────┘    └────────┬────────┘
                                                     │ texto + confiança STT
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│                   Fila de eventos (asyncio.Queue)            │
└──────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│  Parser determinístico (regex + normalização PT-BR)          │
│  ─────────────────────────────────────────────────────────── │
│  Reconhece: livro + cap + versículo | próximo | anterior |   │
│  mais N | volta N | ainda nesse capítulo                     │
│  Saída: JSON estruturado + confiança do parser               │
└──────────────────────────────────────────────────────────────┘
                                                     │
                                  ┌────────────────────┴────────────────────┐
                                  │ confiança parser ≥ limiar?              │
                                  │ e comando estruturado reconhecido?      │
                                  └────────────────────┬────────────────────┘
                                  sim                  │                 não
                                  ▼                    │                    ▼
                                  ┌────────────────────┐    ┌──────────────────────────┐
                                  │  Motor de decisão  │    │  LLM (Qwen3 8B)          │
                                  │  (direto)          │    │  interpretação semântica │
                                  └─────────┬──────────┘    │  → JSON + confiança LLM  │
                                            │               └────────────┬─────────────┘
                                            │                            │
                                            │              ┌─────────────┘
                                            │              │ action=search?
                                            │              ▼  sim
                                            │       ┌──────────────────────────┐
                                            │       │  Busca híbrida           │
                                            │       │  FTS5 + embeddings + RRF │
                                            │       │  → versículo + confiança │
                                            │       └────────────┬─────────────┘
                                            │                    │
                                            └─────────┬──────────┘
                                                      ▼
┌──────────────────────────────────────────────────────────────┐
│  Confidence Manager (combina STT + parser/LLM + busca)       │
│  Decide: executar | confirmar | ignorar                      │
└──────────────────────────────────────────────────────────────┘
                                                     │ ação validada + confiança final
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│  Motor de decisão (valida JSON, aplica regras de segurança)  │
│  + Cache (versículo atual, buscas recentes, frequentes)      │
│  + Estado (livro/cap/versículo)                              │
└──────────────────────────────────────────────────────────────┘
                                                     │ referência resolvida
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│  Cliente Holyrics API — POST /api/ShowVerse                  │
└──────────────────────────────────────────────────────────────┘
                                                     │
                                                     ▼
┌──────────────────────────────────────────────────────────────┐
│  Holyrics (tela) + Observabilidade (logs JSONL + métricas)   │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 Princípios de design

1. **Parser determinístico primeiro, LLM só quando necessário.** Comandos estruturados ("João 3:16", "próximo", "volta dois") são resolvidos sem LLM — menor latência, maior previsibilidade, menor custo de GPU. O LLM é invocado apenas quando o parser não reconhece a intenção com confiança suficiente.
2. **LLM nunca controla o Holyrics diretamente.** Ele só produz JSON; um motor de decisão determinístico valida, aplica regras de segurança e executa.
3. **Tudo offline.** Nenhuma chamada de rede externa. A única rede é HTTP local para o Holyrics.
4. **Pipeline assíncrono** com `asyncio` para não bloquear captura de áudio enquanto o LLM processa.
5. **Auditável.** Cada etapa grava em log estruturado (JSONL) com timestamp, duração, confiança e motivo da decisão.
6. **Fallback gracioso.** Se o LLM falhar/estiver lento, regras heurísticas cobrem os casos mais comuns ("próximo", "anterior", "volta dois").
7. **Lazy loading do LLM.** O modelo só é carregado na VRAM no primeiro comando não-estruturado, economizando recursos no estado ocioso.

### 1.3 Justificativa da arquitetura híbrida parser-first

A arquitetura anterior (v1.0) enviava toda frase candidata ao LLM. Análise crítica mostrou que isso é **desnecessário e contraproducente** para a maioria dos comandos reais:

| Critério | LLM para tudo (v1.0) | Parser-first + LLM fallback (v2.0) |
|---|---|---|
| Latência (comando estruturado) | ~250–500 ms (LLM) | **~50–150 ms** (parser + Holyrics) |
| Latência (busca semântica) | ~300–600 ms | ~300–600 ms (igual — LLM necessário) |
| Consumo de GPU (estado ocioso) | LLM sempre carregado (~5–6 GB VRAM) | LLM lazy-load (0 GB até necessário) |
| Previsibilidade | probabilística (LLM pode variar JSON) | **determinística** para comandos estruturados |
| Taxa de erro (comandos comuns) | depende do LLM | regex é exato para o padrão coberto |
| Manutenção | editar prompt + few-shot | editar regex + tabela de sinônimos |
| Custo de desenvolvimento | menor (LLM cobre tudo) | maior inicialmente (parser a escrever) |

Conclusão: **a arquitetura híbrida é superior** para este projeto porque (a) a grande maioria dos comandos em pregação é estruturada, (b) latência < 1 s é requisito crítico, (c) previsibilidade é valorizada em ambiente de culto ao vivo. O custo é escrever e manter um parser determinístico — pago uma vez, com benefício permanente.

---

## 2. Transcrição (STT)

### 2.1 Comparação dos modelos/runtimes

| Runtime | Backend | Velocidade (4060 Ti) | VRAM (large-v3) | Notas |
|---|---|---|---|---|
| **faster-whisper** | CTranslate2 | ~40x realtime (INT8) | ~2,9 GB (INT8) / ~4,5 GB (FP16) | **Recomendado.** 4x mais rápido que openai/whisper, INT8 estável |
| whisper.cpp | GGML/C++ | ~12x realtime (CUDA) | ~4,1 GB | Binário único, ótimo para CPU/edge, mas mais lento que faster-whisper em GPU |
| openai/whisper | PyTorch | ~8x realtime | ~4,7 GB | Referência, lento, não recomendado para produção |
| NeMo (Parakeet/Canary) | NeMo/PyTorch | alto (streaming nativo) | ~2–3 GB | Streaming de baixa latência, mas dependência NeMo pesada |

### 2.2 Comparação dos tamanhos de modelo (Whisper)

| Modelo | Params | Multilíngue | Velocidade relativa | Precisão PT-BR |
|---|---|---|---|---|
| tiny | 39 M | sim | muito rápido | baixa — não usar para pregação |
| base | 74 M | sim | rápido | baixa |
| small | 244 M | sim | rápido | média |
| medium | 769 M | sim | média | boa |
| large-v3 | 1 550 M | sim | lenta | excelente |
| **large-v3-turbo** | 809 M | sim | **~8x mais rápido que large-v3** | **excelente (queda mínima)** |

### 2.3 Alternativas não-Whisper (reavaliadas nesta revisão)

| Modelo | Params | Idiomas | Licença | PT-BR | Veredito para este projeto |
|---|---|---|---|---|---|
| **NVIDIA Parakeet TDT 0.6B v3** | 600 M | 25 idiomas europeus **incl. PT** | CC BY-NC 4.0 (não-comercial) | PT-EU (Granary corpus); PT-BR não benchmarkado oficialmente | **Alternativa a testar.** Streaming nativo de baixa latência (chunked/wait-k), mas licença não-comercial e foco PT-EU |
| NVIDIA Canary-1B | 1 B | EN/DE/FR/ES apenas | CC BY-NC 4.0 | **não suporta PT** | Inviável |
| NVIDIA Canary-1B-PT (freds0) | 1 B | PT (fine-tune comunitário) | CC BY-NC 4.0 | não oficial, sem benchmark | Não recomendado (sem garantia) |
| Distil-whisper | variável | EN-only | MIT | **não suporta PT** | Inviável |

**Análise Parakeet TDT v3:**
- **Prós:** 600 M params (menor que large-v3-turbo de 809 M), streaming nativo NeMo com políticas `waitk`/`alignatt` (latência configurável), FastConformer eficiente (~3x economia de compute), suporta PT.
- **Contras:** licença **CC BY-NC 4.0** (proíbe uso comercial — verificar se o uso em igreja se enquadra), treinado em corpus europeu (Granary) — sotaque e vocabulário brasileiros não são garantidos, dependência NeMo (PyTorch pesado, instalação mais complexa que faster-whisper), menos maduro para produção que faster-whisper.
- **Decisão:** manter **Whisper large-v3-turbo como padrão** por maturidade, licença (MIT via OpenAI), simplicidade de deploy e qualidade comprovada em PT-BR. **Recomenda-se benchmarkar Parakeet v3** durante a fase de implementação com áudio real de pregação PT-BR; se WER for significativamente menor e licença for aceitável, pode substituir o Whisper.

### 2.4 Recomendação

**faster-whisper + `large-v3-turbo` em INT8 (`int8_float16`)** como padrão. Parakeet TDT v3 como alternativa a avaliar em benchmark com áudio real.

Justificativa do padrão:
- Na RTX 4060 Ti, large-v3 tem RTF ≈ 0,12 (8,3x realtime, benchmark publicado — ver §12); turbo é ~8x mais rápido → RTF estimado ≈ 0,015 (a confirmar em benchmark próprio).
- INT8 reduz VRAM para ~2,9 GB, deixando ~13 GB livres para o LLM e embeddings.
- Turbo mantém precisão praticamente igual a large-v3 em idiomas de médio/recurso como português.
- Para streaming em tempo real, usar modo **chunked** com `chunk_length_s=30` + VAD (Silero ou webrtcvad) para enviar apenas segmentos com fala.

### 2.5 Estratégia de streaming

1. Captura contínua a 16 kHz mono (chunk de 0,5 s).
2. VAD (Silero VAD, leve, GPU) descarta silêncio.
3. Ao detectar pausa ≥ 0,6 s (fim de enunciado), envia o segmento acumulado ao Whisper.
4. Para frases longas, usar `chunk_length_s=30` com `BatchedInferencePipeline`.
5. Saída parcial opcional (para feedback visual), final ao fim do enunciado.
6. Capturar `avg_logprob` do Whisper como **confiança da transcrição** (ver §10).

> **Atenção a alucinações:** Whisper tende a alucinar em silêncio. O VAD é obrigatório — nunca enviar áudio mudo ao modelo. Usar `condition_on_previous_text=False` para evitar propagação de erro.

---

## 3. Parsing Determinístico

> Capítulo adicionado na v2.0 para suportar a arquitetura híbrida parser-first.

### 3.1 Objetivo

Resolver comandos estruturados **sem invocar o LLM**, usando apenas regex, normalização textual e regras de negócio. Cobertura alvo: ~80% dos comandos reais em pregação.

### 3.2 Pipeline do parser

```
texto transcrito
   │
   ▼
[1] Normalização (lowercase, sem acentos, sem pontuação, whitespace único)
   │
   ▼
[2] Detecção de intenção de comando (palavras-gatilho + estrutura)
   │  se não há gatilho → action=none, devolve ao pipeline (não é comando)
   ▼
[3] Classificação do tipo de comando
   │  (navegação | referência direta | referência indireta)
   ▼
[4] Extração de entidades (livro, capítulo, versículo, quantidade)
   │
   ▼
[5] Validação contra tabela canônica (livro existe? cap/versículo no range?)
   │
   ▼
JSON estruturado + confiança do parser (0..1)
```

### 3.3 Normalização de números por extenso

Tabela de cardinal/ordinal → dígito, cobrindo 1–199 (suficiente para capítulos e versículos):

```python
UNITS = {"zero":0,"um":1,"dois":2,"três":3,"quatro":4,"cinco":5,
         "seis":6,"sete":7,"oito":8,"nove":9,"dez":10,"onze":11,
         "doze":12,"treze":13,"quatorze":14,"catorze":14,"quinze":15,
         "dezesseis":16,"dezassete":17,"dezesete":17,"dezoito":18,"dezenove":19,"dezenove":19,
         "vinte":20,"trinta":30,"quarenta":40,"cinquenta":50,"sessenta":60,
         "setenta":70,"oitenta":80,"noventa":90,"cem":100,"cento":100}
# composição: "vinte e três" → 20+3 = 23 ; "cento e vinte" → 100+20 = 120
```

Exemplos:
- "dezesseis" → 16
- "vinte e oito" → 28
- "cento e cinquenta" → 150

### 3.4 Reconhecimento de livros e sinônimos

Tabela canônica de 66 livros (PT-BR) com sinônimos e abreviações. Exemplo (parcial):

```json
{
  "id": 43, "canonical": "João",
  "aliases": ["joão","joao","jo","joo","são joão","sao joão","evangelho de joão","evangelho segundo joão"]
},
{
  "id": 46, "canonical": "1 Coríntios",
  "aliases": ["1 coríntios","i coríntios","primeira coríntios","primeira de coríntios",
              "primeira carta aos coríntios","1 corinto","1co","1cor","i corinto"]
}
```

Normalização antes da busca: lowercase + `remove_diacritics` + collapse whitespace. Busca por **longest-match** (para não confundir "1 João" com "João").

### 3.5 Abreviações, ordinais e números romanos

| Forma falada | Normaliza para |
|---|---|
| "primeiro", "primeira", "i" | 1 |
| "segundo", "segunda", "ii" | 2 |
| "terceiro", "terceira", "iii" | 3 |
| "1º", "1ª", "i", "ii", "iii" | 1, 2, 3 |
| "capítulo", "cap", "cap." | marcador de capítulo |
| "versículo", "vers", "v", "vv" | marcador de versículo |

### 3.6 Padrões regex principais (esquemáticos)

```python
# Referência direta: livro + cap + versículo (com marcadores ou não)
BOOK = r"(?P<book>[a-zà-ú\s]+?)"  # casado contra tabela de aliases
NUM  = r"(?P<num>\d+|[a-z\s]+?)"  # dígito ou extenso (após normalização)
REF  = rf"{BOOK}\s+cap(?:ítulo)?\s+{NUM}\s+vers(?:ículo)?\s+{NUM}"
# "joão capítulo três versículo dezesseis"

# Forma compacta: "joão três dezesseis" / "romos oito vinte e oito"
REF_SHORT = rf"{BOOK}\s+{NUM}\s+{NUM}"

# Navegação relativa
NEXT     = r"(?:próximo|proximo|seguinte|avança|avancar)(?:\s+(?P<n>\d+|[a-z\s]+))?"
PREV     = r"(?:anterior|voltar|volta|voltou|retroceder)(?:\s+(?P<n>\d+|[a-z\s]+))?"
MORE     = r"(?:mais|avança mais|pula)\s+(?P<n>\d+|[a-z\s]+)"
STAY     = r"(?:ainda|continua|permanece)(?:\s+neste|nesse)?\s+(?:capítulo|capitulo|texto)"
```

### 3.7 Exemplos de resolução (sem LLM)

| Entrada (transcrição normalizada) | Saída do parser | Confiança |
|---|---|---|
| "vamos abrir em joao capitulo tres versiculo dezesseis" | `{"action":"show","book":"João","chapter":3,"verse":16}` | 0,98 |
| "romanos oito vinte e oito" | `{"action":"show","book":"Romanos","chapter":8,"verse":28}` | 0,95 |
| "primeiro corintios treze" | `{"action":"show","book":"1 Coríntios","chapter":13,"verse":null}` | 0,92 |
| "o próximo" | `{"action":"next","amount":1}` | 0,99 |
| "volta dois" | `{"action":"previous","amount":2}` | 0,99 |
| "mais três" | `{"action":"next","amount":3}` | 0,97 |
| "ainda nesse capítulo" | `{"action":"jump","chapter":"current"}` | 0,90 |

### 3.8 Ambiguidades e como tratar

| Ambiguidade | Estratégia |
|---|---|
| "João" pode ser Evangelho ou 1/2/3 João | Longest-match + contexto: se houve ordinal ("primeiro joão") → 1 João; senão → Evangelho |
| "capítulo" omitido ("joão três dezesseis") | Aceitar forma compacta, mas **baixar confiança** (0,85) — se < limiar, encaminhar ao LLM |
| Número ambíguo entre cap e versículo | Exigir marcador explícito ("cap"/"vers") para confiança alta; sem marcador, usar heurística (primeiro = cap, segundo = vers) com confiança média |
| "três" sozinho após livro ("joão três") | Interpretar como capítulo 3 inteiro (verse=null) |
| Livro não reconhecido | confiança 0 → encaminhar ao LLM |

### 3.9 Quando o parser encaminha ao LLM

O parser devolve `{"action":"uncertain","raw":"..."}` (ou confiança < limiar) nos casos:
- nenhuma intenção de comando reconhecida, mas há palavras suspeitas (ex.: "abre aquele texto...");
- livro não reconhecido;
- estrutura não casou com nenhum padrão, mas há gatilho ("abre", "mostra", "aquele versículo");
- referência indireta ("o versículo que lemos agora", "aquele da fé").

Nesses casos, o texto + estado atual são enviados ao LLM (§4).

---

## 4. Modelo de Linguagem (LLM)

### 4.1 Comparação

| Modelo | Params | Licença | VRAM (Q4) | Tok/s (4060 Ti aprox.) | PT-BR | Instrução/JSON |
|---|---|---|---|---|---|---|
| **Qwen3 8B** | 8 B | Apache 2.0 | ~5–6 GB | 120–175 | muito bom | excelente |
| Llama 3.1 8B | 8 B | Llama (restrita) | ~5–6 GB | 120–175 | bom | bom |
| Gemma 3 12B | 12 B | Gemma (restrita) | ~8–9 GB | 75–80 | bom | bom |
| Mistral Small 3 | ~7–8 B | Apache 2.0 | ~5–6 GB | 120–175 | bom | muito bom |

### 4.2 Recomendação

**Qwen3 8B quantizado Q4_K_M via llama.cpp (servidor local OpenAI-compatible) ou Ollama.** Carregamento **lazy** (só no primeiro comando não-estruturado).

Justificativa:
- Supera Llama 3.1 8B na maioria dos benchmarks atuais.
- Licença Apache 2.0 (sem restrições de uso).
- Excelente em seguir instruções e produzir JSON estruturado — exatamente o que esta tarefa exige.
- ~5–6 GB VRAM em Q4, cabendo junto com Whisper INT8 (~2,9 GB) nos 16 GB da 4060 Ti.
- Bom desempenho em português.

> **Alternativa:** se a qualidade em PT-BR for insuficiente em casos difíceis, Gemma 3 12B é o próximo degrau (melhor raciocínio), ao custo de ~8–9 GB VRAM e ~75 tok/s. Ainda cabe na 4060 Ti junto com Whisper INT8, mas com menos folga.

### 4.3 Papel do LLM (revisado)

Na arquitetura v2.0, o LLM é **invocado apenas quando o parser determinístico não resolve** com confiança suficiente. Seu papel continua sendo apenas **interpretar a intenção** e devolver JSON estruturado — nunca responder perguntas nem inventar versículos.

### 4.4 Schema de saída

```json
{
  "action": "show | next | previous | search | jump | none",
  "book": "string | null",
  "chapter": "int | null",
  "verse": "int | null",
  "amount": "int | null",
  "query": "string | null",
  "version": "string | null",
  "confidence": "float 0..1"
}
```

### 4.5 Exemplos de mapeamento (casos não-estruturados, encaminhados ao LLM)

| Entrada (transcrição) | Saída JSON |
|---|---|
| "Abre naquele versículo que fala que Deus amou o mundo" | `{"action":"search","query":"Deus amou o mundo"}` |
| "Mostra aquele texto que diz que o sal da terra" | `{"action":"search","query":"sal da terra"}` |
| "Aquele versículo sobre todas as coisas cooperarem para o bem" | `{"action":"search","query":"todas as coisas cooperam para o bem"}` |
| "Aquele texto da fé" | `{"action":"search","query":"fé"}` (ambíguo — ver §10) |

### 4.6 Garantias

- O LLM **nunca** inventa versículos: quando `action=search`, o versículo é resolvido pelo buscador, não pelo LLM.
- `confidence < 0,7` → motor de decisão pede confirmação (configurável).
- `action=none` para fala que não é comando (pregação comum).
- O LLM recebe o **estado atual** (livro/cap/versículo) no prompt, para resolver referências indiretas ("o próximo", "ainda nesse capítulo") — embora esses casos normalmente já tenham sido resolvidos pelo parser.

---

## 5. Busca Textual da Bíblia

### 5.1 Reavaliação da decisão (v1.0 → v2.0)

A v1.0 recomendava **SQLite FTS5 puro**. Análise crítica mostrou que FTS5 puro falha em **paráfrases** — exatamente o caso de uso mais valioso do projeto:

| Query falada | Texto bíblico (ACF) | FTS5 puro | Híbrido (FTS5+embeddings+RRF) |
|---|---|---|---|
| "Deus amou tanto o mundo" | "Porque Deus amou o mundo de tal maneira..." | match parcial (deus, amou, mundo) — pode acertar, mas sem ranking semântico | **acerta com alta confiança** (embeddings capturam "tanto" ≈ "de tal maneira") |
| "todas as coisas cooperam para o bem" | "todas as coisas cooperam para o bem" | acerta (match quase exato) | acerta (ambos concordam) |
| "o versículo do pão nosso" | "O pão nosso de cada dia nos dai hoje" | acerta | acerta |
| "não tentar o Senhor" | "Não tentarás o Senhor teu Deus" | match fraco (tentar, senhor) | **acerta melhor** (semântica) |

**Decisão v2.0: adotar busca híbrida** — FTS5 (BM25) + embeddings densos + fusão RRF (Reciprocal Rank Fusion). FTS5 permanece como componente lexical (rápido, exato para termos bíblicos); embeddings capturam semântica para paráfrases.

### 5.2 Por que não embeddings puros?

Embeddings puros falham em **termos exatos raros** (nomes próprios, números) — problema documentado em sistemas RAG de produção. Para "Romanos 8:28" ou "sal da terra", FTS5 é mais preciso. A combinação híbrida é superior a qualquer um isoladamente.

### 5.3 Comparação de soluções

| Solução | Tipo | Latência (~31 k versículos) | Dependências | Veredito |
|---|---|---|---|---|
| **SQLite FTS5 + embeddings + RRF** | Híbrido embutido | FTS5: 1–5 ms; embeddings: ~10–20 ms (CPU) | sentence-transformers | **Recomendado.** Melhor recall, ainda offline |
| SQLite FTS5 puro | Embutido | 1–5 ms | nenhuma | Insuficiente para paráfrases |
| Tantivy | Embutido (Rust) | < 1 ms | binding Rust/Python | Mais rápido, mas só lexical |
| Meilisearch | Servidor | ~ms | processo separado | Overkill, exige servidor |
| Elasticsearch | Servidor | ~ms | JVM pesada | Overkill, muita RAM |

### 5.4 Modelo de embeddings recomendado

**`intfloat/multilingual-e5-small`** (ou fine-tune PT-BR `jmbrito/ptbr-similarity-e5-small`).

| Propriedade | multilingual-e5-small | ptbr-similarity-e5-small |
|---|---|---|
| Params | ~118 M | ~118 M |
| Dimensão | 384 | 384 |
| Tamanho | ~470 MB (FP32) / ~130 MB (INT8) | idem |
| Idiomas | multilíngue (incl. PT) | PT-BR fine-tuned (ASSIN2) |
| Latência (CPU, query única) | ~10–20 ms | ~10–20 ms |
| Latência (GPU, query única) | ~3–8 ms | ~3–8 ms |

> **Decisão:** usar `multilingual-e5-small` como padrão (multilíngue, bem documentado, mantido). Se recall em PT-BR for insuficiente em testes, trocar por `ptbr-similarity-e5-small` ou `e5-large-sts-pt` (maior, ~600 M params, melhor qualidade).

### 5.5 Estrutura do índice

**FTS5 (lexical):**
```sql
CREATE VIRTUAL TABLE verses USING fts5(
  book,
  chapter UNINDEXED,
  verse UNINDEXED,
  text,
  version UNINDEXED,
  id UNINDEXED,            -- BBCCCVVV
  tokenize = 'unicode61 remove_diacritics 2'
);
```

**Embeddings (semântico):**
- Pré-calcular embedding (384-dim) de cada versículo no build.
- Armazenar em `numpy.memmap` (31 000 × 384 × 4 bytes ≈ **48 MB**) ou `sqlite-vec` (extensão SQLite para vetores).
- Normalização L2 para similaridade cosseno via dot product.

### 5.6 Pipeline de busca híbrida

```
query (do LLM ou parser)
   │
   ├──▶ [FTS5] SELECT id, bm25(verses) ... LIMIT 20  ──▶ ranking_lexical
   │
   └──▶ [Embeddings] encode(query) · dot(verses) ──▶ ranking_semantic
                          │
                          ▼
              [RRF fusion]  score = Σ 1/(k + rank_i),  k=60
                          │
                          ▼
              top-N versículos + score combinado
                          │
                          ▼
              [Confidence Manager] decide executar/confirmar/ignorar
```

### 5.7 Resolução de busca por frase (exemplos esperados)

| Query | Versículo esperado | Mecanismo dominante |
|---|---|---|
| "todas as coisas cooperam para o bem" | Romanos 8:28 | FTS5 (match quase exato) |
| "Deus amou o mundo" | João 3:16 | ambos |
| "Deus amou tanto o mundo" | João 3:16 | **embeddings** (paráfrase) |
| "sal da terra" | Mateus 5:13 | FTS5 |
| "não tentar o Senhor" | Mateus 4:7 / Lucas 4:12 | **embeddings** + desempate por frequência |
| "fé" | Hebreus 11 (múltiplos) | ambíguo → confirmação (ver §10) |

### 5.8 Múltiplas traduções

- Uma linha FTS5 por (versículo, versão); filtrar por `version`.
- Embeddings: uma versão principal (ex.: ACF) para evitar duplicação; fallback para outra versão se a principal não tiver o livro.
- `GetBibleVersions` no startup do Holyrics para alinhar com versões disponíveis lá.

### 5.9 Fonte do texto bíblico

Usar uma tradução de domínio público ou com licença permissiva em PT-BR (ex.: **Almeida Corrigida Fiel (ACF)** ou **João Ferreira de Almeida** em domínio público). Importar como JSON/SQL no build do índice. Manter múltiplas versões em coluna `version` para permitir fallback.

> Verificar a licença da tradução escolhida antes de distribuir. ACF e Almeida Revista e Corrigida (ARC) são as opções mais comuns para uso local.

---

## 6. Gerenciador de Contexto / Estado

Estado em memória (com persistência opcional em JSON):

```python
@dataclass
class BibleState:
    book: str | None = None        # ex.: "João"
    book_id: int | None = None     # 1..66 (para cálculo de navegação)
    chapter: int | None = None
    verse: int | None = None
    version: str = "ACF"
    last_shown_at: float = 0.0
```

### 6.1 Regras de navegação

- `next` com `amount=1`: avança 1 versículo; se passar do último do capítulo, vai ao cap. seguinte v. 1; se passar do último capítulo do livro, vai ao próximo livro.
- `previous`: análogo, em sentido inverso.
- `jump` com `chapter="current"`: mantém livro/capítulo, aguarda versículo explícito ou abre o capítulo inteiro.
- Referências indiretas ("aquele que lemos agora", "ainda nesse texto") → mantém estado atual.

### 6.2 Mapeamento livro ↔ ID

Tabela canônica de 66 livros (PT-BR) com sinônimos ("Primeira João" = "1 João" = "I João" = "1Jo"). O motor de decisão normaliza antes de consultar o Holyrics. Esta tabela é **compartilhada entre o parser (§3) e o estado** para consistência.

---

## 7. Sistema de Cache

> Capítulo adicionado na v2.0.

### 7.1 Objetivo

Evitar reprocessamento e reduzir latência em comandos repetidos ou recorrentes.

### 7.2 Camadas de cache

| Cache | Conteúdo | Tamanho | Invalidação |
|---|---|---|---|
| **`current_verse`** | último versículo exibido (ref + texto + versão) | 1 entrada | a cada `ShowVerse` bem-sucedido |
| **`recent_searches`** | LRU das últimas N buscas (query → resultado) | 50 entradas | LRU; ao mudar versão padrão |
| **`frequent_verses`** | contador de uso por referência (persistente) | ~1000 entradas | nunca (apodera lentamente); reset manual |
| **`embedding_cache`** | embedding da query (query normalizada → vetor) | 200 entradas | LRU |
| **`holyrics_response`** | última resposta do Holyrics por action | 10 entradas | TTL 5 s |

### 7.3 Quando utilizar

- **`current_verse`**: comando `next`/`previous` calcula a partir do cache sem rebuscar; se o cache expirou (TTL 60 s sem uso) ou estado inconsistente, recarrega do estado persistente.
- **`recent_searches`**: se o pregador repetir "Deus amou o mundo" pouco depois, devolve instantaneamente o versículo já resolvido.
- **`frequent_verses`**: desempata buscas ambíguas — versículo mais usado historicamente vence.
- **`embedding_cache`**: queries repetidas não recalculam embedding (~10–20 ms economizados).
- **`holyrics_response`**: evita re-chamar `GetBibleVersions` a cada startup de action.

### 7.4 Impacto na latência

| Cenário | Sem cache | Com cache |
|---|---|---|
| "próximo" (após versículo recente) | ~50–150 ms (parser + estado + Holyrics) | **~30–80 ms** (estado em cache + Holyrics) |
| Busca repetida ("Deus amou o mundo" 2ª vez) | ~300–600 ms (LLM + híbrida) | **~20–40 ms** (cache direto) |
| `GetBibleVersions` no healthcheck | ~20 ms | ~0 ms (cacheado) |

### 7.5 Implementação

```python
from functools import lru_cache
from collections import OrderedDict

class RecentSearchCache:
    def __init__(self, capacity=50):
        self._map: OrderedDict[str, list] = OrderedDict()
        self._cap = capacity
    def get(self, query_normalized: str): ...
    def put(self, query_normalized: str, results: list): ...
```

`frequent_verses` persiste em `data/frequentes.json` (contador por `BBCCCVVV`).

---

## 8. Confidence Manager

> Capítulo adicionado na v2.0 — substitui a confiança única da v1.0.

### 8.1 Motivação

A v1.0 usava uma única confiança (do LLM). Isso é insuficiente porque:
- o STT pode transcrever errado mesmo que o LLM "tenha certeza" do que recebeu;
- o parser pode casar um padrão mas o texto original estar errado;
- a busca pode retornar um versículo com score alto mas semanticamente errado;
- é impossível auditar **onde** a incerteza está sem separar as fontes.

### 8.2 Confianças por etapa

| Símbolo | Etapa | Fonte | Range |
|---|---|---|---|
| `c_stt` | Transcrição | `avg_logprob` do Whisper → sigmoide normalizada | 0..1 |
| `c_parser` | Parser determinístico | regra: 0,98 se casou com marcadores explícitos; 0,85 se forma compacta; 0 se não casou | 0..1 |
| `c_llm` | LLM | campo `confidence` do JSON do LLM | 0..1 |
| `c_search` | Busca híbrida | score RRF normalizado + gap top1/top2 | 0..1 |
| `c_final` | Final combinada | ver §8.3 | 0..1 |

### 8.3 Combinação

```python
def combine(c_stt, c_intent, c_search=1.0):
    # c_intent = c_parser se veio do parser; c_llm se veio do LLM
    # c_search só relevante para action=search
    c_final = c_stt * c_intent * c_search
    return c_final
```

Multiplicação (em vez de média) é **conservadora**: qualquer etapa fraca derruba a confiança final. Isso atende o princípio "nunca executar comandos duvidosos".

### 8.4 Limiares (defaults, configuráveis)

| `c_final` | Ação | Modo |
|---|---|---|
| ≥ 0,85 | **executar automaticamente** | auto |
| 0,60 – 0,85 | **confirmar** (tray/overlay) ou `quick_presentation` (popup) | confirm / quick |
| < 0,60 | **ignorar** + log | — |

### 8.5 Tabela de decisão detalhada

| `c_stt` | `c_intent` | `c_search` | `c_final` | Decisão |
|---|---|---|---|---|
| alta (≥0,8) | alta (parser, ≥0,9) | — (não-search) | ≥0,72 | **executar** |
| alta | alta | alta (≥0,8) | ≥0,58 | executar se ≥0,85; senão confirmar |
| alta | baixa (LLM <0,7) | — | <0,56 | **ignorar** ou confirmar |
| baixa (<0,5) | qualquer | qualquer | <0,45 | **ignorar** (STT ruim) |
| qualquer | qualquer | ambígua (gap top1/top2 < 0,15) | — | **confirmar** independentemente do score |

### 8.6 Fluxograma de decisão

```
                    [c_stt < 0,5?]
                    /            \
                  sim            não
                  ▼              ▼
              IGNORAR      [action == search?]
                            /              \
                          sim              não
                          ▼                ▼
                  [c_search ambígua?]   [c_intent ≥ 0,9?]
                  /          \           /            \
                sim          não        sim           não
                ▼            ▼           ▼             ▼
            CONFIRMAR   [c_final]   EXECUTAR      [c_final]
                        /     \                   /     \
                     ≥0,85  <0,85              ≥0,85  <0,85
                      ▼       ▼                 ▼       ▼
                   EXECUTAR CONFIRMAR        EXECUTAR CONFIRMAR
```

### 8.7 Caso especial: "fé" (busca ambígua)

"Abre aquele texto da fé" → `action=search, query="fé"` → busca retorna dezenas de versículos (Hebreus 11 inteiro, etc.) com scores próximos → `c_search` marcada como ambígua → **CONFIRMAR** mesmo se `c_final` for alto. Desempate por `frequent_verses` (Hebreus 11:1 é o mais frequente para "fé").

---

## 9. Integração com Holyrics

### 9.1 Resultado da pesquisa (importante)

**O Holyrics possui uma API REST oficial, pública e documentada.**

- Repositório: **https://github.com/holyrics/API-Server** (README em PT e EN)
- Wiki gerada: https://deepwiki.com/holyrics/API-Server
- Biblioteca JS para customização: https://github.com/holyrics/jslib

**Respostas às perguntas específicas:**

| Pergunta | Resposta |
|---|---|
| Existe API oficial? | **Sim.** |
| Documentação pública? | **Sim**, no GitHub. |
| REST API? | **Sim** — HTTP POST, `Content-Type: application/json`. |
| WebSocket? | Não documentado (não é necessário — REST é suficiente). |
| Protocolo TCP? | Via HTTP (porta configurável). |
| SDK? | Não há SDK formal; é REST simples. |
| Sistema de plugins? | **Sim** — funções JavaScript customizadas via JSLIB. |
| Integração por Java? | O Holyrics é Java, mas a integração externa é por HTTP. |
| Documentação para automação? | **Sim.** |
| API interna? | A API Server é a interface oficial. |
| Comunicação via HTTP? | **Sim**, local e internet. |
| Projetos open source relacionados? | `Pelezi/obs-holyrics-plugin-finder` (OBS), `holyrics/jslib`. |
| Comunidade que automatizou? | Sim — integração com OBS e controle remoto via app. |

### 9.2 Endpoints

| Tipo | URL |
|---|---|
| Rede local (token) | `http://[IP]:[PORT]/api/{action}?token=abcdef` |
| Rede local (hash, mais seguro) | `http://[IP]:[PORT]/api/{action}?dtoken=xyz&sid=456&rid=3` |
| Internet — send (fire-and-forget) | `https://api.holyrics.com.br/send/{action}` |
| Internet — request (espera resposta) | `https://api.holyrics.com.br/request/{action}` |

Para este projeto: **rede local com token** (offline, baixa latência, sem depender de internet).

### 9.3 Actions de Bíblia relevantes

| Action | Função |
|---|---|
| **`ShowVerse`** | Inicia apresentação de versículo. Aceita `id` (BBCCCVVV), `ids[]`, `references` (natural: `"John 3:16"`), `version`, `quick_presentation`. Máx. 100 versículos/requisição. |
| `GetBibleVersions` / `GetBibleVersionsV2` | Lista traduções disponíveis. |
| `GetBibleSettings` / `SetBibleSettings` | Lê/altera configurações (versão padrão, números, tema, etc.). |
| `SelectVerse` | Seleciona versículo(s) para uso posterior. |

### 9.4 Formato de ID (BBCCCVVV)

`BB` = livro (2 dígitos), `CCC` = capítulo (3), `VVV` = versículo (3).
Ex.: `19023001` = Salmo 23:1 (livro 19, cap. 023, vers. 001).

### 9.5 Exemplo de chamada (Python)

```python
import requests

HOLYRICS = "http://127.0.0.1:3000/api/ShowVerse"
TOKEN = "abcdef"

def show_verse(book_id: int, chapter: int, verse: int, version: str = "ACF",
               quick: bool = False):
    vid = f"{book_id:02d}{chapter:03d}{verse:03d}"   # BBCCCVVV
    r = requests.post(
        HOLYRICS,
        params={"token": TOKEN},
        json={"input": {"id": vid}, "version": version,
              "quick_presentation": quick},
        timeout=2.0,
    )
    r.raise_for_status()
    return r.json()
```

Ou usando referência natural (deixa o Holyrics resolver):

```python
requests.post(HOLYRICS, params={"token": TOKEN},
              json={"input": {"references": "João 3:16"}, "version": "ACF"},
              timeout=2.0)
```

### 9.6 Comparação de estratégias de integração

| Estratégia | Viabilidade | Latência | Robustez | Veredito |
|---|---|---|---|---|
| **API REST oficial** | ✅ | ~5–20 ms local | alta (suportada) | **Usar.** |
| Plugin JS (JSLIB) | ✅ | igual | alta | Para ações não cobertas pela API padrão. |
| AutoHotkey | ⚠️ | alta | baixa (quebra com mudanças de UI) | Não recomendado. |
| Automação de interface | ⚠️ | alta | baixa | Não recomendado. |
| OCR | ❌ | altíssima | baixíssima | Só em último caso — não necessário aqui. |

### 9.7 Configuração necessária no Holyrics

1. Menu **Arquivo > Configurações > API Server**.
2. Habilitar o servidor, definir porta (ex.: 3000).
3. Criar token em **"gerenciar permissões"** com permissões para actions de Bíblia (`ShowVerse`, `GetBibleVersions`, etc.).
4. Anotar IP:porta para o cliente.

---

## 10. Tratamento de Erros e Ambiguidade

### 10.1 Princípio: nunca executar comandos duvidosos

O motor de decisão aplica estas regras (em conjunto com o Confidence Manager — §8) antes de chamar o Holyrics:

1. **`c_final < min_confidence` (default 0,60)** → ignorar; log.
2. **`c_final` em [0,60; 0,85)** → confirmar (interface/tray) ou `quick_presentation` (popup).
3. **Busca com múltiplos resultados próximos** (gap de score < `search_gap`, default 0,15):
   - Ordenar por RRF.
   - Se houver versículo no `frequent_verses` → preferir.
   - Senão → confirmar ou `quick_presentation`.
4. **Referência inválida** (livro inexistente, cap/versículo fora do range) → log + ignorar.
5. **STT com baixa confiança** (`c_stt < 0,5`) → ignorar antes mesmo de parser/LLM.
6. **Timeout do Holyrics** (2 s) → log + retringir no máximo 1 vez.
7. **LLM indisponível/lento** → fallback ao parser; se parser também falhar, ignorar com log.
8. **Parser e LLM em conflito** (parser diz `none`, LLM diz `search`) → confiar no LLM (ele foi invocado justamente porque o parser falhou).

### 10.2 Histórico de versículos frequentes

Manter `frequentes.json` com contador por referência. Em buscas ambíguas, desempatar por frequência.

### 10.3 Modos de confirmação

Configurável:
- `auto` (default): executa se `c_final ≥ 0,85`.
- `confirm`: sempre pede confirmação (clique no tray).
- `quick`: usa `quick_presentation=true` (popup) para buscas ambíguas.

---

## 11. Modelo de Decisão (segurança)

O LLM (e o parser) **não** falam com o Holyrics. Fluxo obrigatório:

```
Parser/LLM → JSON estruturado → Confidence Manager → Motor de decisão
→ (Buscador se search) → Estado → Cache → Holyrics
```

O motor de decisão é **determinístico** (Python puro, testável, sem IA) e:
- valida o JSON contra o schema;
- normaliza livro/cap/versículo;
- resolve `next`/`previous` via estado;
- resolve `search` via buscador híbrido;
- aplica limiares de confiança (§8);
- consulta/atualiza cache (§7);
- grava auditoria em `logs/pipeline.jsonl` (§13).

Isso torna o sistema **previsível, auditável e seguro**.

---

## 12. Benchmarks e Estimativas

> Revisão v2.0: separar valores **publicados**, **estimados** e **a medir**. A v1.0 apresentava números excessivamente precisos sem distinguir fonte.

### 12.1 Valores publicados (documentação oficial / benchmarks públicos)

| Métrica | Valor | Fonte |
|---|---|---|
| Whisper large-v3 RTF na 4060 Ti (FP16) | **0,12** (8,3x realtime) | GIGAGPU benchmark |
| Whisper large-v3 VRAM (FP16) | 4,5 GB (faster-whisper) / 4,7 GB (openai) | SYSTRAN/faster-whisper README |
| Whisper large-v3 VRAM (INT8) | **2,9 GB** | SYSTRAN/faster-whisper README |
| faster-whisper speedup vs openai/whisper | **~4x** | SYSTRAN/faster-whisper README |
| Whisper turbo speedup vs large-v3 | **~8x** (decoder 32→4 layers) | OpenAI HuggingFace model card |
| Whisper turbo params | 809 M | OpenAI model card |
| Parakeet TDT v3 params | 600 M | NVIDIA NGC / HuggingFace |
| Parakeet TDT v3 idiomas | 25 europeus (incl. PT) | NVIDIA NGC |
| Canary-1B idiomas | EN/DE/FR/ES (sem PT) | NVIDIA HuggingFace |
| multilingual-e5-small dimensão | 384 | HuggingFace model card |
| multilingual-e5-small params | ~118 M | HuggingFace model card |
| Qwen3 8B licença | Apache 2.0 | QwenLM GitHub |
| Llama 3.1 8B VRAM (Q4_K_M) | ~5–6 GB | InsiderLLM / Ollama cheat sheet |
| Tok/s 7B–8B Q4 em GPU equivalente | 120–175 | ComputingForGeeks Ollama cheat sheet |
| Tok/s 12B–14B Q4 em GPU equivalente | 75–80 | ComputingForGeeks |
| SQLite FTS5 latência (corpus médio) | single-digit ms | Medium/SQLite blog |

### 12.2 Estimativas (extrapolação a partir de publicados — não confirmadas neste setup)

| Métrica | Estimativa | Base da estimativa |
|---|---|---|
| Whisper turbo RTF na 4060 Ti (INT8) | **~0,015–0,05** | large-v3 RTF 0,12 ÷ ~8x (turbo) ÷ ~1,3x (INT8) |
| Embedding query (e5-small, CPU) | ~10–20 ms | modelo 118 M, query única, CPU moderno |
| Embedding query (e5-small, GPU) | ~3–8 ms | GPU batch=1 |
| LLM Qwen3 8B Q4, 30 tokens saída | ~200–500 ms | 120–175 tok/s ÷ 30 tokens + overhead |
| HTTP Holyrics local | ~5–20 ms | POST JSON em loopback |

### 12.3 Valores a medir durante implementação

Estes **não podem ser afirmados a priori** — dependem do áudio real, microfone, ruído ambiente, versão exata dos modelos, drivers CUDA, etc.:

- WER do Whisper turbo em áudio de pregação PT-BR real (com sotaque brasileiro, ruído de igreja).
- WER do Parakeet v3 no mesmo corpus (comparação direta).
- Latência total fim-a-fim (fim da frase → versículo na tela) em condições reais.
- `c_stt` típico (avg_logprob) em áudio limpo vs. ruidoso — para calibrar limiares.
- Recall@1 da busca híbrida em um conjunto de ~50 paráfrases de teste.
- Latência do LLM no primeiro comando (cold start com lazy load).

### 12.4 Estimativa de latência total (comando estruturado, parser-first)

| Etapa | Latência estimada | Observações |
|---|---|---|
| Captura + VAD | ~10 ms (por chunk 0,5 s) | CPU |
| STT (turbo INT8, 1 s de fala) | ~15–50 ms (estimado) | GPU |
| Parser determinístico | **< 1 ms** | CPU |
| Confidence Manager + decisão | < 1 ms | CPU |
| Cache + estado | < 1 ms | CPU |
| HTTP Holyrics (local) | 5–20 ms | rede local |
| **Total (comando estruturado)** | **~30–80 ms** | **muito abaixo do alvo < 1 s** |

### 12.5 Estimativa de latência total (busca semântica, LLM + híbrida)

| Etapa | Latência estimada | Observações |
|---|---|---|
| Captura + VAD | ~10 ms | CPU |
| STT | ~15–50 ms | GPU |
| Parser (falha → encaminha ao LLM) | < 1 ms | CPU |
| LLM (Qwen3 8B Q4, ~30 tokens) | ~200–500 ms (estimado) | GPU |
| Busca híbrida (FTS5 + embeddings + RRF) | ~15–30 ms | CPU |
| Confidence + decisão + cache | < 2 ms | CPU |
| HTTP Holyrics | 5–20 ms | rede local |
| **Total (busca semântica)** | **~250–600 ms** | **dentro do alvo < 1 s** |

### 12.6 VRAM total

| Componente | VRAM |
|---|---|
| faster-whisper turbo INT8 | ~2,9 GB |
| Qwen3 8B Q4 (lazy, só quando necessário) | ~5–6 GB |
| Embeddings e5-small (pode ficar em CPU) | ~0,5 GB (GPU) ou 0 (CPU) |
| **Total (LLM carregado)** | **~8–9 GB** dos 16 GB |
| **Total (LLM não carregado, ocioso)** | **~3–3,5 GB** |

Folga confortável para contexto/KV cache em ambos os cenários.

---

## 13. Observabilidade

> Seção ampliada na v2.0.

### 13.1 Log estruturado (JSONL)

Cada execução do pipeline grava uma linha em `logs/pipeline.jsonl`:

```json
{
  "ts": "2026-07-13T19:32:45.123",
  "id": "uuid",
  "audio_ms": 1200,
  "stt": {
    "text": "vamos abrir em joao capitulo tres versiculo dezesseis",
    "avg_logprob": -0.32,
    "c_stt": 0.91,
    "duration_ms": 38
  },
  "parser": {
    "matched": true,
    "pattern": "REF",
    "json": {"action":"show","book":"João","chapter":3,"verse":16},
    "c_parser": 0.98,
    "duration_ms": 0.4
  },
  "llm": {
    "used": false,
    "duration_ms": 0
  },
  "search": {
    "used": false,
    "duration_ms": 0
  },
  "confidence": {
    "c_final": 0.89,
    "decision": "execute"
  },
  "decision": {
    "reason": "parser high confidence, c_final >= 0.85",
    "action_final": "show",
    "ref": "João 3:16",
    "id": "43003016"
  },
  "holyrics": {
    "status": "ok",
    "duration_ms": 12
  },
  "cache": {
    "hit": false,
    "frequent_updated": true
  },
  "total_ms": 62
}
```

### 13.2 Métricas por etapa (sempre registradas)

| Métrica | Uso para otimização |
|---|---|
| `audio_ms` / `stt.duration_ms` | RTF real; detectar degradação de GPU |
| `stt.avg_logprob` / `c_stt` | calibrar limiar de STT; detectar microfone ruim |
| `parser.duration_ms` / `parser.matched` | cobertura do parser; se `matched` baixo, ampliar regex |
| `llm.used` / `llm.duration_ms` | % de comandos que chegam ao LLM (alvo: < 30%); cold start |
| `search.duration_ms` / `c_search` | latência da híbrida; recall |
| `confidence.c_final` / `confidence.decision` | taxa de execute/confirm/ignore; ajustar limiares |
| `decision.reason` | auditar por que decidiu; debug de falsos positivos |
| `holyrics.duration_ms` / `holyrics.status` | saúde da integração; timeouts |
| `cache.hit` | eficácia do cache |
| `total_ms` | latência fim-a-fim; SLA |

### 13.3 Métricas agregadas (dashboard opcional)

- **p50/p95/p99 de `total_ms`** por tipo de comando (show/next/search).
- **Taxa de `action=none`** (falsa detecção de comando em pregação comum).
- **Taxa de `confirm`** vs `execute` vs `ignore`.
- **Top-N versículos mais exibidos** (alimenta `frequent_verses`).
- **WER percebido** (via auditoria manual periódica de amostras).

### 13.4 Uso para otimização futura

- Se `parser.matched` < 70% dos comandos → ampliar padrões regex ou tabela de sinônimos.
- Se `llm.used` > 50% → melhorar parser (mais comandos estruturados cobertos).
- Se `c_stt` médio < 0,7 → investigar microfone/ganho/VAD.
- Se `search.c_search` médio < 0,6 → ajustar peso RRF ou trocar modelo de embeddings.
- Se `holyrics.duration_ms` p95 > 50 ms → investigar rede/configuração.

---

## 14. Riscos e Limitações

| Risco | Impacto | Mitigação |
|---|---|---|
| Alucinação do Whisper em silêncio | comando fantasma | VAD obrigatório + `condition_on_previous_text=False` |
| LLM inventar versículo | versículo errado na tela | LLM só emite JSON; buscador resolve; `action=search` nunca usa texto do LLM como versículo |
| Parser muito restrito | comandos válidos vão ao LLM (latência maior) | medir `parser.matched`; ampliar regex iterativamente |
| Parser muito permissivo | falsos positivos | limiar `c_parser` + tabela canônica de validação |
| Fala do pregador confundida com comando | exibição indevida | detector de intenção (gatilhos) + `c_final` + `action=none` |
| Ruído ambiente / microfone ruim | STT ruim | microfone direcional + VAD + ganho automático; monitorar `c_stt` |
| Holyrics com API desativada | sem integração | checklist de setup + healthcheck no startup |
| Versão da Bíblia indisponível no Holyrics | erro | `GetBibleVersions` no startup; fallback para versão padrão |
| Latência do LLM em pico (cold start) | > 1 s na primeira busca | lazy load opcional com preload após primeiro áudio; modelo menor (Qwen3 4B) como opção |
| Ambiguidade de livro ("João" = Evangelho vs 1/2/3 João) | versículo errado | longest-match + desambiguação por contexto/estado |
| Overlap de fala (pregador fala rápido) | segmentação ruim | VAD com pausa configurável + chunked STT |
| Embeddings não capturam teologia sutil | busca errada em paráfrases difíceis | `frequent_verses` + confirmação para `c_search` ambígua |
| Parakeet licença CC BY-NC 4.0 | uso comercial bloqueado | Whisper (MIT) como padrão; Parakeet só se licença for aceitável |

Limitações conhecidas:
- STT streaming do Whisper não é verdadeiramente contínuo/low-latency como Parakeet/NeMo; há latência de segmentação. Para este uso (comandos esporádicos em meio à pregação) é aceitável.
- O LLM pode errar em referências muito indiretas ("aquele versículo do amor") — depende da qualidade da busca híbrida.
- Não há detecção de tom/pergunta; apenas texto.
- Parser determinístico exige manutenção ao surgir novos padrões de fala não cobertos.

---

## 15. Boas Práticas

- **Logs estruturados** (JSONL) com timestamp, etapa, entrada, saída, latência, confiança, motivo da decisão (§13).
- **Healthcheck no startup**: Holyrics reachability, versões de Bíblia disponíveis, modelo STT carregado, LLM respondendo (se não lazy), índice FTS5 + embeddings carregados.
- **Configuração externalizada** (`config.yaml`) — sem segredos no código; token do Holyrics via variável de ambiente ou config local.
- **Testes unitários** do parser (casos do enunciado + sinônimos + extenso), do buscador híbrido ("Deus amou o mundo" → João 3:16, "sal da terra" → Mt 5:13, "todas as coisas cooperam para o bem" → Rm 8:28, "Deus amou tanto o mundo" → João 3:16) e do Confidence Manager (limiares).
- **Conjunto de teste de paráfrases** (~50 casos) para medir recall da busca híbrida a cada mudança.
- **Modo de teste/dry-run**: processa áudio e mostra o que faria sem chamar o Holyrics.
- **Hot-reload de prompt LLM e tabela de sinônimos** para iterar sem reiniciar tudo.
- **Métricas**: latência por etapa, taxa de `action=none`, taxa de confirmação, `parser.matched` rate.

---

## 16. Organização do Projeto

```
ai-lyrics/
├── config/
│   ├── config.yaml          # IP/porta Holyrics, token, modelo STT/LLM, limiares, pesos RRF
│   └── books.json           # mapeamento 66 livros + sinônimos (PT-BR) — compartilhado parser/estado
├── data/
│   ├── bible.pt-br.sqlite   # índice FTS5 (gerado no build)
│   ├── bible.embeddings.npy # embeddings memmap (31k × 384) — gerado no build
│   ├── bible_source.json    # texto bíblico bruto
│   └── frequentes.json      # contador de versículos frequentes (persistente)
├── microfone/
│   └── capture.py           # captura contínua 16 kHz + VAD
├── transcricao/
│   └── stt.py               # faster-whisper (streaming/chunked) + avg_logprob
├── parser/
│   ├── normalizer.py        # lowercase, diacritics, extenso→dígito, ordinais, romanos
│   ├── books.py             # tabela de aliases + longest-match
│   └── parser.py            # regex + classificação de intenção + confiança
├── llm/
│   ├── client.py            # cliente llama.cpp/Ollama (OpenAI-compatible), lazy load
│   └── prompts.py           # system prompt + few-shot
├── busca/
│   ├── indexer.py           # build do índice FTS5 + embeddings
│   ├── searcher.py          # busca híbrida (FTS5 + embeddings + RRF)
│   └── embeddings.py        # wrapper sentence-transformers (e5-small)
├── estado/
│   └── state.py             # BibleState + regras de navegação
├── cache/
│   └── cache.py             # current_verse, recent_searches, embedding_cache, holyrics_response
├── confidence/
│   └── manager.py           # Confidence Manager multi-etapa + tabela de decisão
├── integracao_holyrics/
│   └── client.py            # cliente REST (ShowVerse etc.)
├── interface/
│   └── tray.py              # (opcional) tray icon + status + confirmação
├── logs/
│   └── pipeline.jsonl       # log estruturado por execução
├── core/
│   ├── pipeline.py          # orquestração asyncio + fila
│   └── decision.py          # motor de decisão (valida JSON, regras, chama cache/estado/busca)
├── tests/
│   ├── test_parser.py
│   ├── test_search.py
│   ├── test_confidence.py
│   └── paráfrases.json      # conjunto de teste de paráfrases
├── scripts/
│   ├── build_index.py
│   └── benchmark.py         # benchmark STT (Whisper vs Parakeet) + busca
├── requirements.txt
└── README.md
```

---

## 17. Linguagem de Programação

### 17.1 Comparação

| Linguagem | Desenho | Bibliotecas IA | Áudio/GPU | Automação | Manutenção |
|---|---|---|---|---|---|
| **Python** | bom (caminho crítico em C/CUDA) | **excelente** (faster-whisper, llama-cpp-python, sentence-transformers, sqlite3) | excelente (sounddevice, webrtcvad, silero) | excelente (requests) | fácil |
| C# | bom | regular (ONNX, ML.NET) | boa (NAudio) | boa (HttpClient) | média |
| Rust | excelente | crescente (candle, burn) | boa (cpal) | boa (reqwest) | mais difícil |
| Go | excelente | fraca para LLM/STT | fraca | boa | fácil |

### 17.2 Recomendação

**Python como linguagem principal**, com possível **Rust para o buscador** (Tantivy) caso a latência da híbrida não seja suficiente (improvável com 31 k versículos).

Justificativa:
- faster-whisper, llama-cpp-python, sentence-transformers e sqlite3 são todos maduros em Python.
- O caminho crítico (STT, LLM, embeddings) roda em CUDA/CTranslate2 — a linguagem de orquestração não é o gargalo.
- Manutenção e iteração rápidas — importante para ajustar parser, prompts e regras.
- Integração HTTP com Holyrics é trivial.

### 17.3 Arquitetura híbrida (opcional)

Se no futuro a latência da busca híbrida for insuficiente (cenário improvável), mover o buscador para um microserviço Rust/Tantivy exposto via HTTP local. O resto permanece em Python.

---

## 18. Comunicação entre Módulos

### 18.1 Comparação

| Solução | Latência | Complexidade | Veredito |
|---|---|---|---|
| **asyncio.Queue (fila em processo)** | ~µs | baixa | **Usar.** Tudo num processo. |
| Pub/Sub (ZeroMQ) | ~µs–ms | média | Só se houver processos separados. |
| WebSocket interno | ~ms | média | Desnecessário. |
| gRPC | ~ms | alta | Overkill. |
| HTTP interno | ~ms | média | Só para serviços externos (Holyrics, LLM server). |

### 18.2 Recomendação

**Fila `asyncio.Queue` em um único processo Python**, com:
- 1 task produtora: captura + VAD → enfileira áudio.
- 1 task STT: consome áudio, produz texto + `c_stt` → enfileira.
- 1 task orquestradora: consome texto, chama parser → (LLM se necessário) → confidence → decisão → (busca se necessário) → estado/cache → Holyrics.

O servidor LLM (llama.cpp/Ollama) roda como **processo separado** (HTTP local, OpenAI-compatible) — isso isola crashes e permite reiniciar o LLM sem derrubar o áudio. O modelo é carregado **lazy** (endpoint `/api/generate` carrega na primeira chamada, ou preload controlado).

---

## 19. Sugestão de Implementação por Etapas

### MVP (semana 1–2)
- Captura + VAD + faster-whisper (turbo INT8) → texto + `c_stt`.
- **Parser determinístico** (referência direta + navegação next/previous).
- Motor de decisão mínimo (sem Confidence Manager completo — limiar único provisório).
- Cliente Holyrics `ShowVerse` por ID (BBCCCVVV).
- Estado (livro/cap/versículo) + cache `current_verse`.
- **Objetivo:** "João 3:16" e "próximo" → versículo na tela em < 200 ms.

### Beta (semana 3–4)
- Busca híbrida (FTS5 + e5-small + RRF) + `c_search`.
- Confidence Manager multi-etapa completo (§8).
- Tabela de sinônimos de livros completa + extenso + ordinais + romanos.
- `frequent_verses` + `recent_searches` + `embedding_cache`.
- LLM (Qwen3 8B, lazy load) para casos não-estruturados.
- Logs estruturados + métricas por etapa.
- Interface tray (status + confirmação).

### Versão Final (semana 5–6)
- Detecção de intenção refinada (gatilhos + `action=none` robusto).
- Modos `auto`/`confirm`/`quick_presentation`.
- Fallback heurístico quando LLM indisponível.
- Healthcheck + config externalizada.
- **Benchmark STT** (Whisper turbo vs Parakeet v3) com áudio real de pregação PT-BR.
- Conjunto de teste de paráfrases (~50 casos) + recall@1 medido.
- Testes completos + dry-run.
- Documentação de operação (setup Holyrics, microfone, modelos).

---

## 20. Referências

### Holyrics API (oficial)
- Repositório: https://github.com/holyrics/API-Server
- README EN: https://github.com/holyrics/API-Server/blob/main/README-en.md
- README PT: https://github.com/holyrics/API-Server/blob/main/README.md
- Bible Management: https://deepwiki.com/holyrics/API-Server/4.3-bible-management
- API Actions Reference: https://deepwiki.com/holyrics/API-Server/4-api-actions-reference
- JSLIB (custom JS): https://github.com/holyrics/jslib
- Plugin OBS (comunidade): https://github.com/Pelezi/obs-holyrics-plugin-finder

### STT
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- Whisper large-v3-turbo: https://huggingface.co/openai/whisper-large-v3-turbo
- Benchmark 4060 Ti (large-v3): https://gigagpu.com/whisper-large-v3-on-rtx-4060-ti-benchmark/
- Benchmark turbo: https://gigagpu.com/whisper-turbo-v3-self-hosted/
- Parakeet TDT 0.6B v3: https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3
- Parakeet TDT v3 (NGC): https://catalog.ngc.nvidia.com/orgs/nvidia/collections/parakeet-tdt-0.6b
- Canary-1B: https://huggingface.co/nvidia/canary-1b
- NeMo streaming decoding: https://docs.nvidia.com/nemo-framework/user-guide/latest/nemotoolkit/asr/streaming_decoding/canary_chunked_and_streaming_decoding.html

### LLM
- Qwen3 (Apache 2.0): https://github.com/QwenLM/Qwen3
- Ollama: https://ollama.com
- llama.cpp: https://github.com/ggerganov/llama.cpp
- Comparação local 2026: https://computingforgeeks.com/open-source-llm-comparison/
- Ollama cheat sheet: https://computingforgeeks.com/ollama-models-cheat-sheet/

### Busca / Embeddings
- SQLite FTS5: https://www.sqlite.org/fts5.html
- Benchmark FTS (VADOSWARE): https://github.com/VADOSWARE/fts-benchmark
- Tantivy (alternativa): https://github.com/quickwit-oss/tantivy
- multilingual-e5-small: https://huggingface.co/intfloat/multilingual-e5-small
- ptbr-similarity-e5-small: https://huggingface.co/jmbrito/ptbr-similarity-e5-small
- e5-large-sts-pt: https://huggingface.co/iara-project/e5-large-sts-pt
- MTEB-PT benchmark: https://arxiv.org/html/2607.04071
- Hybrid search production: https://tianpan.co/blog/2026-04-12-hybrid-search-production-bm25-dense-embeddings
- Hybrid search + reranking 2026: https://appscale.blog/en/blog/hybrid-search-and-reranking-production-rag-bm25-dense-cross-encoder-2026

---

## 21. Conclusão

O projeto é **viável e com baixo risco técnico** graças a três fatores decisivos:

1. **O Holyrics já expõe uma API REST oficial** com action `ShowVerse` que aceita referências em linguagem natural — nenhuma automação frágil (AutoHotkey/OCR) é necessária.
2. **O hardware-alvo (RTX 4060 Ti 16GB) comporta com folga** faster-whisper turbo (INT8, ~2,9 GB) + Qwen3 8B Q4 (~5–6 GB, lazy) + e5-small (~0,5 GB ou CPU) simultaneamente, com latência total estimada de **30–80 ms para comandos estruturados** (parser-first) e **250–600 ms para buscas semânticas** — dentro do alvo de < 1 s.
3. **A arquitetura híbrida parser-first + LLM fallback** reduz drasticamente a latência e o consumo de GPU para a maioria dos comandos, mantendo o LLM como rede de segurança para interpretação semântica complexa — o melhor dos dois mundos.

A arquitetura mantém o LLM isolado da execução (apenas JSON), com um motor de decisão determinístico e auditável, um Confidence Manager multi-etapa que separa incerteza por fonte, e uma busca híbrida que cobre tanto termos exatos quanto paráfrases — atendendo ao requisito de segurança de nunca executar comandos duvidosos.
