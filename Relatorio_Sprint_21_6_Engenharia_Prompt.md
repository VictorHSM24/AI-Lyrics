# Sprint 21.6 — Validação Final da Inferência Semântica e Engenharia de Prompt

## Data: 2026-07-25
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão objetiva:** A causa predominante da baixa acurácia na identificação de referências bíblicas implícitas no AI Lyrics é a **utilização do `recent_text` no user prompt**, que confunde o LLM e o faz escolher referências relacionadas à frase anterior em vez da frase atual. A engenharia de prompt, **sem trocar de modelo**, é capaz de elevar a acurácia de **33% para 100%** no candidato primário, simplesmente removendo o `recent_text` do prompt.

**Resultado experimental decisivo:**

| Experimento | Intent | Candidato Principal | Qualquer Candidato |
|-------------|--------|---------------------|--------------------|
| 1. Baseline | 83% | **33%** | 50% |
| 2. Sem recent_text | **100%** | **100%** | **100%** |
| 3. recent_text secundário | 67% | 33% | 33% |
| 4. Ordem invertida | 83% | 50% | 50% |

O Experimento 2 (sem `recent_text`) atingiu **100% de acerto** em todas as métricas com o mesmo modelo qwen3:8b-q4_K_M, provando que a capacidade do modelo é **suficiente** quando o prompt não contém ruído contextual.

---

## 2. Evidências Experimentais

### 2.1 Configuração Comum

- **Modelo:** qwen3:8b-q4_K_M (Ollama local, 5.2GB, Q4_K_M)
- **Temperature:** 0.1
- **top_p:** 0.9
- **max_tokens:** 300
- **think:** false
- **Timeout:** 120s
- **Warmup:** 2.4s (modelo pré-carregado)
- **Frases:** 6 (5 implícitas + 1 explícita de controle)
- **Ground truth:**
  1. "O Senhor é meu pastor." → Salmos 23:1
  2. "Porque Deus amou o mundo." → João 3:16
  3. "Ainda que eu ande pelo vale da sombra da morte." → Salmos 23:4
  4. "Tudo posso naquele que me fortalece." → Filipenses 4:13
  5. "A armadura de Deus." → Efésios 6
  6. "Provérbios 15:14" → Provérbios 15:14

### 2.2 Experimento 1 — Baseline (implementação atual)

**User prompt (exemplo, frase 2):**
```
Fala recente: O Senhor é meu pastor.
Texto atual: Porque Deus amou o mundo.

Responda apenas com JSON:
```

**Resultados:**

| Frase | Intent | Candidato Primário | Correto? | Esperado | ms |
|-------|--------|-------------------|----------|----------|-----|
| O Senhor é meu pastor. | show_reference | Salmos 23:1 (0.95) | ✅ | Salmos 23:1 | 4035 |
| Porque Deus amou o mundo. | show_reference | Salmos 23:1 (0.95) | ❌ | João 3:16 | 5368 |
| Ainda que eu ande... | none | — | ❌ | Salmos 23:4 | 2636 |
| Tudo posso naquele... | show_reference | Salmos 23:4 (0.95) | ❌ | Filipenses 4:13 | 5279 |
| A armadura de Deus. | show_reference | Filipenses 4:13 (0.95) | ❌ | Efésios 6 | 4139 |
| Provérbios 15:14 | show_reference | Provérbios 15:14 (1.00) | ✅ | Provérbios 15:14 | 4115 |

**Métricas:** Intent 83% | Primário 33% | Qualquer 50% | Conf 0.96 | Tempo 4262ms

**Observação:** Em 3 dos 4 casos com `recent_text` preenchido, o candidato primário é uma referência relacionada à frase **anterior**, não à atual. O LLM trata o `recent_text` como pista dominante.

### 2.3 Experimento 2 — Sem recent_text

**User prompt (exemplo, frase 2):**
```
Texto atual: Porque Deus amou o mundo.

Responda apenas com JSON:
```

**Resultados:**

| Frase | Intent | Candidato Primário | Correto? | Esperado | ms |
|-------|--------|-------------------|----------|----------|-----|
| O Senhor é meu pastor. | show_reference | Salmos 23:1 (0.95) | ✅ | Salmos 23:1 | 4028 |
| Porque Deus amou o mundo. | show_reference | João 3:16 (0.95) | ✅ | João 3:16 | 3992 |
| Ainda que eu ande... | show_reference | Salmos 23:4 (0.95) | ✅ | Salmos 23:4 | 4011 |
| Tudo posso naquele... | show_reference | Filipenses 4:13 (0.95) | ✅ | Filipenses 4:13 | 4210 |
| A armadura de Deus. | show_reference | Efésios 6:11 (0.95) | ✅ | Efésios 6 | 3999 |
| Provérbios 15:14 | show_reference | Provérbios 15:14 (1.00) | ✅ | Provérbios 15:14 | 4075 |

**Métricas:** Intent **100%** | Primário **100%** | Qualquer **100%** | Conf 0.96 | Tempo 4052ms

**Observação:** Todas as 6 frases reconhecidas corretamente, com o candidato correto em primeiro lugar. O modelo qwen3:8b tem conhecimento bíblico suficiente quando não é confundido pelo `recent_text`.

### 2.4 Experimento 3 — recent_text como contexto secundário

**System prompt (trecho adicionado):**
```
CONTEXTO SECUNDÁRIO:
A seção "Fala recente" serve apenas para desambiguar referências incompletas.
Identifique a referência exclusivamente do "Texto atual".
Nunca escolha um candidato apenas por causa da fala recente.
```

**User prompt (exemplo, frase 2):**
```
Fala recente: O Senhor é meu pastor.
Texto atual: Porque Deus amou o mundo.

Responda apenas com JSON:
```

**Resultados:**

| Frase | Intent | Candidato Primário | Correto? | Esperado | ms |
|-------|--------|-------------------|----------|----------|-----|
| O Senhor é meu pastor. | show_reference | Salmos 23:1 (0.95) | ✅ | Salmos 23:1 | 4042 |
| Porque Deus amou o mundo. | none | — | ❌ | João 3:16 | 2625 |
| Ainda que eu ande... | none | — | ❌ | Salmos 23:4 | 2625 |
| Tudo posso naquele... | show_reference | Salmos 23:4 (0.95) | ❌ | Filipenses 4:13 | 4053 |
| A armadura de Deus. | show_reference | Filipenses 4:13 (0.95) | ❌ | Efésios 6 | 4017 |
| Provérbios 15:14 | show_reference | Provérbios 15:14 (1.00) | ✅ | Provérbios 15:14 | 4078 |

**Métricas:** Intent 67% | Primário 33% | Qualquer 33% | Conf 0.96 | Tempo 3573ms

**Observação:** A instrução adicional no system prompt **piorou** o resultado em vez de melhorar. O LLM passou a retornar `intent=none` em 2 casos (vs 1 no baseline), sugerindo que a instrução o tornou mais conservador. A instrução no system prompt não foi suficiente para override do viés do `recent_text` no user prompt.

### 2.5 Experimento 4 — Ordem invertida

**User prompt (exemplo, frase 2):**
```
Texto atual: Porque Deus amou o mundo.
Fala recente: O Senhor é meu pastor.

Responda apenas com JSON:
```

**Resultados:**

| Frase | Intent | Candidato Primário | Correto? | Esperado | ms |
|-------|--------|-------------------|----------|----------|-----|
| O Senhor é meu pastor. | show_reference | Salmos 23:1 (0.95) | ✅ | Salmos 23:1 | 4074 |
| Porque Deus amou o mundo. | show_reference | João 3:16 (0.95) | ✅ | João 3:16 | 5213 |
| Ainda que eu ande... | show_reference | Salmos 23:4 (0.95) | ✅ | Salmos 23:4 | 5246 |
| Tudo posso naquele... | show_reference | Salmos 23:4 (0.95) | ❌ | Filipenses 4:13 | 5295 |
| A armadura de Deus. | show_reference | Filipenses 4:13 (0.95) | ❌ | Efésios 6 | 5433 |
| Provérbios 15:14 | none | — | ❌ | Provérbios 15:14 | 2658 |

**Métricas:** Intent 83% | Primário 50% | Qualquer 50% | Conf 0.95 | Tempo 4653ms

**Observação:** A inversão de ordem melhorou o candidato primário de 33% para 50% (2 casos adicionais corretos: "Porque Deus amou" e "Ainda que eu ande"), mas introduziu um erro novo (Provérbios 15:14 passou a `none`). O LLM ainda é influenciado pelo `recent_text`, mas menos quando o `Texto atual` vem primeiro.

---

## 3. Comparação Estatística

| Experimento | Intent | Candidato Principal | Qualquer Candidato | Conf Média | Tempo Médio |
|-------------|--------|---------------------|--------------------|------------|-------------|
| 1. Baseline | 5/6 (83%) | 2/6 (33%) | 3/6 (50%) | 0.96 | 4262ms |
| **2. Sem recent_text** | **6/6 (100%)** | **6/6 (100%)** | **6/6 (100%)** | **0.96** | **4052ms** |
| 3. recent_text secundário | 4/6 (67%) | 2/6 (33%) | 2/6 (33%) | 0.96 | 3573ms |
| 4. Ordem invertida | 5/6 (83%) | 3/6 (50%) | 3/6 (50%) | 0.95 | 4653ms |

**Delta vs Baseline:**

| Experimento | Δ Intent | Δ Primário | Δ Qualquer | Δ Tempo |
|-------------|----------|------------|------------|---------|
| 2. Sem recent_text | +17pp | **+67pp** | +50pp | -210ms |
| 3. Secundário | -16pp | 0pp | -17pp | -689ms |
| 4. Invertido | 0pp | +17pp | 0pp | +391ms |

**Conclusão estatística:** O Experimento 2 (sem `recent_text`) é **dominante** em todas as métricas de acurácia, com melhora de **+67 pontos percentuais** no candidato primário.

---

## 4. Análise Técnica

### 4.1 O `recent_text` melhora ou piora a acurácia?

**Piora significativamente.** A presença do `recent_text` no user prompt reduz a acurácia do candidato primário de **100% para 33%** (queda de 67 pontos percentuais). O mecanismo de erro é claro: o LLM trata o `recent_text` como uma pista forte para o candidato, retornando referências relacionadas à frase anterior em vez da atual.

**Evidência:** Em 3 dos 4 casos com `recent_text` preenchido no baseline, o candidato primário corresponde à frase anterior:
- "Porque Deus amou o mundo." com `recent_text="O Senhor é meu pastor."` → candidato primário: Salmos 23:1 (referência da frase anterior)
- "Tudo posso naquele que me fortalece." com `recent_text="Ainda que eu ande..."` → candidato primário: Salmos 23:4 (referência da frase anterior)
- "A armadura de Deus." com `recent_text="Tudo posso naquele..."` → candidato primário: Filipenses 4:13 (referência da frase anterior)

### 4.2 A posição do `recent_text` influencia o resultado?

**Sim, parcialmente.** A inversão de ordem (Texto atual antes de Fala recente) melhorou o candidato primário de 33% para 50%, mas não eliminou o problema. O LLM ainda é influenciado pelo `recent_text` mesmo quando aparece depois do `Texto atual`. A inversão também introduziu um erro novo (Provérbios 15:14 passou a `none`), sugerindo instabilidade.

### 4.3 O Prompt atual induz o modelo ao erro?

**Sim.** O user prompt atual coloca o `recent_text` antes do `Texto atual`, sem nenhuma instrução explícita sobre como usá-lo. O LLM interpreta o `recent_text` como contexto primário e o `Texto atual` como complemento, invertendo a prioridade correta.

### 4.4 A engenharia de prompt consegue melhorar significativamente a acurácia sem trocar de modelo?

**Sim, de forma dramática.** A simples remoção do `recent_text` elevou a acurácia de 33% para 100% no candidato primário, mantendo o mesmo modelo (qwen3:8b-q4_K_M). Isso prova que a engenharia de prompt é **suficiente** para resolver o problema de acurácia para as frases testadas, sem necessidade de trocar de modelo.

### 4.5 O modelo demonstra limitações intrínsecas mesmo com prompts melhores?

**Não para as 6 frases testadas.** Com o prompt sem `recent_text`, o modelo acertou todas as 6 frases, incluindo as 5 referências implícitas. Isso indica que o qwen3:8b tem conhecimento bíblico suficiente para as referências comuns testadas. **Entretanto**, o teste não cobre referências obscuras ou incomuns, onde o modelo pode ter limitações. O resultado é válido apenas para o conjunto testado.

---

## 5. Causa Raiz

### Causa predominante: **Engenharia de prompt (uso indevido do `recent_text`)**

**Justificativa baseada nos experimentos:**

1. **O Experimento 2 provou** que a remoção do `recent_text` resolve 100% dos casos, mantendo o mesmo modelo. Isso isola a variável: a causa não é o modelo, é o prompt.

2. **O Experimento 3 provou** que tentar corrigir o problema com instrução no system prompt **não funciona** (piora em vez de melhorar). O `recent_text` no user prompt tem influência dominante sobre a instrução no system prompt.

3. **O Experimento 4 provou** que a posição do `recent_text` tem influência parcial (melhora de 33% para 50%), mas não resolve o problema. A simples presença do `recent_text` já é suficiente para confundir o LLM.

4. **A confiança média é idêntica (0.96)** em todos os experimentos, indicando que o modelo está "confiante" mesmo quando erra. Isso confirma que o erro é sistemático (induzido pelo prompt), não aleatório (incerteza do modelo).

**Descartado: Capacidade do modelo.** O mesmo modelo que acerta 33% com o prompt baseline acerta 100% sem o `recent_text`. A capacidade do modelo é suficiente para as referências testadas.

**Descartado: Combinação prompt+modelo.** A combinação funciona perfeitamente quando o prompt não contém `recent_text`. O problema é exclusivamente do prompt.

---

## 6. Recomendações

### Recomendação 1 (CRÍTICA): Remover `recent_text` do user prompt

**Ação:** Modificar `LocalLLMProvider._build_user_prompt()` para não incluir a linha `Fala recente: {recent_text}`.

**Impacto esperado:** Acurácia do candidato primário de 33% para ~100% (baseado no Experimento 2).

**Complexidade:** Baixa (1 linha removida).

**Riscos:** 
- Para referências incompletas como "como vimos anteriormente", o `recent_text` pode ser útil para desambiguar. **Mitigação:** usar `last_book`/`last_chapter` do ContextEngine (que já está implementado) em vez de `recent_text` para desambiguação.
- Pode haver casos não testados onde o `recent_text` ajuda. **Mitigação:** testar com corpus maior antes de promover para produção.

### Recomendação 2 (ALTA): Adicionar mais exemplos de referências implícitas no system prompt

**Ação:** Adicionar exemplos como:
- "O Senhor é meu pastor" → Salmos 23
- "Porque Deus amou o mundo" → João 3:16
- "Tudo posso naquele que me fortalece" → Filipenses 4:13
- "A armadura de Deus" → Efésios 6
- "Ainda que eu ande pelo vale" → Salmos 23:4

**Impacto esperado:** Aumentar a robustez para variações de phrasing das mesmas referências.

**Complexidade:** Baixa (adicionar linhas ao `_SYSTEM_PROMPT`).

**Riscos:** Aumentar o system prompt pode aumentar o tempo de inferência (mais tokens de entrada). Impacto provavelmente mínimo (~50 tokens adicionais).

### Recomendação 3 (MÉDIA): Implementar fallback com `recent_text` apenas para `intent=none`

**Ação:** Se a primeira inferência (sem `recent_text`) retornar `intent=none`, fazer uma segunda inferência **com** `recent_text` para tentar desambiguar.

**Impacto esperado:** Cobrir casos de referências incompletas sem degradar a acurácia das referências completas.

**Complexidade:** Média (modificar `LocalLLMProvider.infer()` para retry condicional).

**Riscos:** Aumenta latência em caso de fallback (segunda chamada ao LLM). Pode ser mitigado com timeout menor no fallback.

### Recomendação 4 (BAIXA): Considerar modelo maior para referências obscuras

**Ação:** Para referências não cobertas pelos exemplos do system prompt, considerar qwen3:14b ou qwen3:32b.

**Impacto esperado:** Melhor acurácia para referências incomuns.

**Complexidade:** Alta (requer GPU com mais VRAM, aumenta latência).

**Riscos:** Custo de infraestrutura, latência aumentada pode violar SLA de tempo real.

---

## 7. Conclusão Final

> Qual é a causa predominante da baixa acurácia na identificação de referências bíblicas implícitas no AI Lyrics?

**A causa predominante é a engenharia de prompt, especificamente a inclusão do `recent_text` no user prompt.** O `recent_text` confunde o LLM, fazendo-o escolher referências relacionadas à frase anterior em vez da frase atual. A presença do `recent_text` reduz a acurácia do candidato primário de **100% para 33%** (queda de 67 pontos percentuais).

> É possível atingir um nível satisfatório apenas com melhorias na engenharia de prompt, ou será necessário adotar um modelo de linguagem mais capaz?

**É possível atingir um nível satisfatório apenas com melhorias na engenharia de prompt.** A simples remoção do `recent_text` do user prompt elevou a acurácia para **100%** em todas as métricas (intent, candidato primário, qualquer candidato) com o mesmo modelo qwen3:8b-q4_K_M. A troca de modelo **não é necessária** para o conjunto de referências testadas.

**Evidência decisiva:** O Experimento 2 (sem `recent_text`) atingiu 6/6 (100%) no candidato primário, vs 2/6 (33%) no baseline. O modelo qwen3:8b tem conhecimento bíblico suficiente para as referências comuns testadas; o problema era exclusivamente o ruído contextual introduzido pelo `recent_text`.

**Caveat:** O teste cobre 6 frases e 5 referências implícitas. Para referências mais obscuras (ex: "a passagem onde Paulo fala sobre o corpo místico"), um modelo maior pode ser necessário. Recomenda-se testar com corpus maior antes de promover para produção.

---

## 8. Arquivos de Evidência

| Arquivo | Descrição |
|---------|-----------|
| `_diag_sprint21_6.py` | Script com 4 experimentos controlados |
| `_diag_sprint21_6_output.txt` | Saída completa (1510 linhas) com prompts, payloads, respostas RAW e métricas |
