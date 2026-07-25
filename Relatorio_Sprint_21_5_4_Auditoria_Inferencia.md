# Sprint 21.5.4 — Auditoria da Inferência Semântica (Teste Controlado)

## Data: 2026-07-25
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão:** O pipeline de inferência semântica **funciona corretamente** do ponto de vista mecânico: SpeechPartial chega ao SemanticEngine, o prompt é construído, o payload é enviado ao Ollama, a resposta RAW é parseada, o JSON é validado e o IntentCandidate é publicado. **Nenhuma etapa da cadeia perde informação por bug ou falha de software.**

**Entretanto**, a qualidade das respostas do LLM (qwen3:8b-q4_K_M) é **inconsistente** para referências implícitas:

- **5 de 6 frases** foram classificadas como `show_reference` (intenção correta)
- **1 de 6 frases** ("Ainda que eu ande pelo vale da sombra da morte.") foi classificada como `none` (erro do LLM)
- **3 de 5 candidatos** primários estão **incorretos** (livro/capítulo/versículo errados)

A cadeia de inferência **é capaz** de reconhecer referências implícitas quando recebe transcrições perfeitas, mas a **acurácia do LLM** é o fator limitante.

---

## 2. Configuração do Teste

| Componente | Versão | Status |
|-----------|--------|--------|
| SemanticEngine | Real (Sprint 21.5) | Instrumentado |
| ContextEngine | Real | Instrumentado |
| LocalLLMProvider | Real | Instrumentado |
| OllamaBackend | Real | Instrumentado |
| Ollama | Local (localhost:11434) | Ativo |
| Modelo | qwen3:8b-q4_K_M | 5.2GB, Q4_K_M |
| ReferenceResolver | Não disponível | SearchConfig incompatível |
| SermonMemoryEngine | Real | Ativo |
| StreamingSTTService | Não utilizado | — |
| Whisper | Não utilizado | — |
| Microfone | Não utilizado | — |

**Timeouts:** `request_timeout_s=120s`, `timeout_ms=120000ms`, warmup prévio de 3.1s.

---

## 3. Resultados por Frase

### 3.1 "O Senhor é meu pastor." (IMPLÍCITA)

**Entrada:**
- Correlation: `a87f4d1b-d323-40b0-8f93-982a0b421599`
- Texto bruto: `'O Senhor é meu pastor.'`
- Texto normalizado: `'o senhor é meu pastor.'`

**Contexto enviado:**
```
current_text: 'O Senhor é meu pastor.'
recent_text: ''
last_book: ''
last_chapter: 0
last_reference: ''
sermon_book: ''
sermon_chapter: 0
sermon_theme: ''
sermon_entities: []
sermon_confidence: 0.0
```

**User Prompt:**
```
Texto atual: O Senhor é meu pastor.

Responda apenas com JSON:
```

**Resposta RAW (4.0s):**
```json
{
  "intent": "show_reference",
  "candidates": [
    {
      "book": "Salmos",
      "chapter": 23,
      "verse": 1,
      "confidence": 0.95,
      "reason": "frase conhecida do salmo 23"
    }
  ]
}
```

**Parser:** OK, 1 candidato validado.

**IntentCandidate publicado:**
- book=Salmos, chapter=23, verse=1, confidence=0.95, reason="frase conhecida do salmo 23"

**Avaliação:** ✅ **CORRETO**. "O Senhor é meu pastor" é a primeira frase do Salmo 23:1.

---

### 3.2 "Porque Deus amou o mundo." (IMPLÍCITA)

**Entrada:**
- Texto: `'Porque Deus amou o mundo.'`
- Contexto: `recent_text='O Senhor é meu pastor.'`, `sermon_entities=['Deus']`, `sermon_confidence=0.05`

**User Prompt:**
```
Fala recente: O Senhor é meu pastor.
Texto atual: Porque Deus amou o mundo.

Responda apenas com JSON:
```

**Resposta RAW (5.2s):**
```json
{
  "intent": "show_reference",
  "candidates": [
    {
      "book": "Salmos",
      "chapter": 23,
      "verse": 1,
      "confidence": 0.95,
      "reason": "Frase característica do Salmo 23"
    },
    {
      "book": "João",
      "chapter": 3,
      "verse": 16,
      "confidence": 0.85,
      "reason": "Mensagem de amor universal"
    }
  ]
}
```

**Parser:** OK, 2 candidatos validados.

**Avaliação:** ⚠️ **PARCIALMENTE CORRETO**. O candidato correto (João 3:16) está em **segundo lugar** (confidence=0.85), atrás de Salmos 23:1 (confidence=0.95) que é **incorreto** para esta frase. O LLM foi confundido pelo `recent_text` ("O Senhor é meu pastor.") e manteve o Salmo 23 como candidato principal. O ReferenceResolver escolheria o candidato de maior confiança (Salmos 23:1), que está errado.

---

### 3.3 "Ainda que eu ande pelo vale da sombra da morte." (IMPLÍCITA)

**Entrada:**
- Texto: `'Ainda que eu ande pelo vale da sombra da morte.'`
- Contexto: `recent_text='Porque Deus amou o mundo.'`, `sermon_entities=['Deus']`

**User Prompt:**
```
Fala recente: Porque Deus amou o mundo.
Texto atual: Ainda que eu ande pelo vale da sombra da morte.

Responda apenas com JSON:
```

**Resposta RAW (2.6s):**
```json
{
  "intent": "none",
  "candidates": []
}
```

**Parser:** OK, 0 candidatos.

**Avaliação:** ❌ **INCORRETO**. "Ainda que eu ande pelo vale da sombra da morte" é Salmo 23:4. O LLM **não reconheceu** a referência implícita, mesmo sendo uma das frases mais conhecidas da Bíblia. Este é o **primeiro ponto de perda de informação**: o LLM classificou como `none` quando deveria ser `show_reference`.

---

### 3.4 "Tudo posso naquele que me fortalece." (IMPLÍCITA)

**Entrada:**
- Texto: `'Tudo posso naquele que me fortalece.'`
- Contexto: `recent_text='Ainda que eu ande pelo vale da sombra da morte.'`, `sermon_entities=['Deus']`

**User Prompt:**
```
Fala recente: Ainda que eu ande pelo vale da sombra da morte.
Texto atual: Tudo posso naquele que me fortalece.

Responda apenas com JSON:
```

**Resposta RAW (5.3s):**
```json
{
  "intent": "show_reference",
  "candidates": [
    {
      "book": "Salmos",
      "chapter": 23,
      "verse": 4,
      "confidence": 0.95,
      "reason": "Frase correspondente ao salmo 23"
    },
    {
      "book": "Gálatas",
      "chapter": 6,
      "verse": 9,
      "confidence": 0.75,
      "reason": "Frase correspondente ao versículo 9"
    }
  ]
}
```

**Avaliação:** ❌ **INCORRETO**. "Tudo posso naquele que me fortalece" é Filipenses 4:13. O LLM retornou Salmos 23:4 (que é "Ainda que eu ande pelo vale da sombra da morte", a frase anterior) como candidato principal. O candidato correto (Filipenses 4:13) **não aparece** na lista. O `recent_text` confundiu o LLM, fazendo-o associar a frase atual com a anterior.

---

### 3.5 "A armadura de Deus." (IMPLÍCITA)

**Entrada:**
- Texto: `'A armadura de Deus.'`
- Contexto: `recent_text='Tudo posso naquele que me fortalece.'`, `sermon_entities=['Deus']`

**User Prompt:**
```
Fala recente: Tudo posso naquele que me fortalece.
Texto atual: A armadura de Deus.

Responda apenas com JSON:
```

**Resposta RAW (4.1s):**
```json
{
  "intent": "show_reference",
  "candidates": [
    {
      "book": "Filipenses",
      "chapter": 4,
      "verse": 13,
      "confidence": 0.95,
      "reason": "menção direta a fortalecimento e armadura de Deus"
    }
  ]
}
```

**Avaliação:** ❌ **INCORRETO**. "A armadura de Deus" é Efésios 6:10-18. O LLM retornou Filipenses 4:13 (que é "Tudo posso naquele que me fortalece", a frase anterior). O `recent_text` novamente confundiu o LLM.

---

### 3.6 "Provérbios 15:14" (CONTROLE EXPLÍCITA)

**Entrada:**
- Texto: `'Provérbios 15:14'`
- Contexto: `recent_text='A armadura de Deus.'`, `sermon_entities=['Deus']`

**User Prompt:**
```
Fala recente: A armadura de Deus.
Texto atual: Provérbios 15:14

Responda apenas com JSON:
```

**Resposta RAW (4.2s):**
```json
{
  "intent": "show_reference",
  "candidates": [
    {
      "book": "Provérbios",
      "chapter": 15,
      "verse": 14,
      "confidence": 0.95,
      "reason": "Texto atual menciona Provérbios 15:14"
    }
  ]
}
```

**Avaliação:** ✅ **CORRETO**. Referência explícita reconhecida perfeitamente.

---

## 4. Tabela Consolidada

| # | Frase | Intent | Candidato 1 | Correto? | Esperado | inference_ms |
|---|-------|--------|-------------|----------|----------|--------------|
| 1 | O Senhor é meu pastor. | show_reference | Salmos 23:1 (0.95) | ✅ SIM | Salmos 23:1 | 4044 |
| 2 | Porque Deus amou o mundo. | show_reference | Salmos 23:1 (0.95) | ❌ NÃO | João 3:16 | 5155 |
| 3 | Ainda que eu ande pelo vale... | none | (nenhum) | ❌ NÃO | Salmos 23:4 | 2625 |
| 4 | Tudo posso naquele que me fortalece. | show_reference | Salmos 23:4 (0.95) | ❌ NÃO | Filipenses 4:13 | 5320 |
| 5 | A armadura de Deus. | show_reference | Filipenses 4:13 (0.95) | ❌ NÃO | Efésios 6:10-18 | 4125 |
| 6 | Provérbios 15:14 (controle) | show_reference | Provérbios 15:14 (0.95) | ✅ SIM | Provérbios 15:14 | 4169 |

**Métricas:**
- Intent correto: 5/6 (83%)
- Candidato primário correto: 2/6 (33%)
- Candidato correto em qualquer posição: 3/6 (50%) — apenas #1, #2 (João 3:16 em 2º), #6

---

## 5. Primeiro Ponto de Perda de Informação

| Frase | Perda ocorre em? | Detalhe |
|-------|------------------|---------|
| #1 O Senhor é meu pastor. | Nenhuma perda | LLM acertou |
| #2 Porque Deus amou o mundo. | **LLM** (ranking errado) | Candidato correto em 2º lugar; `recent_text` confundiu |
| #3 Ainda que eu ande... | **LLM** (intent=none) | LLM não reconheceu a referência |
| #4 Tudo posso naquele... | **LLM** (candidato errado) | `recent_text` fez LLM associar com frase anterior |
| #5 A armadura de Deus. | **LLM** (candidato errado) | `recent_text` fez LLM associar com frase anterior |
| #6 Provérbios 15:14 | Nenhuma perda | LLM acertou |

**Em todos os casos, a perda ocorre no LLM (qwen3:8b), não no software.** O parser, o validador de schema, o ContextEngine e o PromptBuilder funcionam corretamente.

---

## 6. Análise do System Prompt

O system prompt é **fixo** (1826 chars) e bem estruturado:

```
Você é um mecanismo de identificação de referências bíblicas.
NÃO utilize raciocínio explícito. NÃO explique sua resposta. NÃO converse.
NÃO escreva texto antes ou depois do JSON. NÃO produza markdown. NÃO utilize tags <think>.
Sua única saída válida é um JSON compatível com o schema informado.
[...]
Exemplos:
- "o texto onde Jesus conversa com Nicodemos" → João 3
- "o versículo que fala para guardar o coração" → Provérbios 4:23
- "a passagem do bom pastor" → João 10
- "como vimos anteriormente" → depende do contexto
[...]
Schema JSON obrigatório: { intent, candidates: [{book, chapter, verse, confidence, reason}] }
```

**Observações:**
- O prompt tem apenas 4 exemplos de referências implícitas
- Nenhum dos exemplos cobre as frases testadas (Salmo 23, João 3:16, Filipenses 4:13, Efésios 6)
- O prompt não avisa o LLM para não ser influenciado pelo `recent_text` ao escolher o candidato principal

---

## 7. Análise do User Prompt e Contexto

O user prompt é construído por `_build_user_prompt()` e inclui:

1. **Contexto do sermão** (se `sermon_book` disponível) — não disponível nos testes
2. **Fala recente** (`recent_text`) — preenchida com a frase anterior
3. **Texto atual** (`current_text`) — a frase sendo testada
4. **"Responda apenas com JSON:"**

**Problema observado:** O `recent_text` está **causando confusão** no LLM. Em 3 dos 4 casos com `recent_text` preenchido (#2, #4, #5), o LLM retornou como candidato principal uma referência relacionada à frase anterior, não à atual.

**Evidência:**
- #2: `recent_text="O Senhor é meu pastor."` → candidato 1 = Salmos 23:1 (referência da frase anterior)
- #4: `recent_text="Ainda que eu ande..."` → candidato 1 = Salmos 23:4 (referência da frase anterior)
- #5: `recent_text="Tudo posso naquele..."` → candidato 1 = Filipenses 4:13 (referência da frase anterior)

O LLM está tratando o `recent_text` como uma pista forte para o candidato, quando deveria usá-lo apenas como contexto secundário.

---

## 8. Análise do Payload HTTP

Payload enviado ao Ollama (`POST /api/chat`):

```json
{
  "model": "qwen3:8b-q4_K_M",
  "messages": [
    {"role": "system", "content": "<SYSTEM_PROMPT 1826 chars>"},
    {"role": "user", "content": "<USER_PROMPT variável>"}
  ],
  "stream": false,
  "options": {
    "temperature": 0.1,
    "top_p": 0.9,
    "num_predict": 300
  },
  "think": false
}
```

**Configuração:**
- `temperature=0.1` (baixa, para respostas determinísticas)
- `top_p=0.9` (foco nos tokens mais prováveis)
- `num_predict=300` (máx 300 tokens de saída)
- `think=false` (desabilita raciocínio explícito do qwen3)
- `stream=false` (resposta síncrona)

**Avaliação:** O payload está correto e bem configurado. O `think=false` é respeitado pelo Ollama (não há tags `<think>` nas respostas).

---

## 9. Análise do Parser

O método `_parse_and_validate()` recebe o conteúdo da resposta e:

1. **Extrai JSON** de dentro de possíveis blocos markdown (```` ```json ... ``` ````) ou texto envolvente
2. **Parseia** o JSON com `json.loads()`
3. **Valida** cada candidato com `_validate_candidate()`:
   - `book`: string não vazia, máx 40 chars
   - `chapter`: número >= 0
   - `verse`: número >= 0
   - `confidence`: clamped entre 0.0 e 1.0
   - `reason`: string, máx 80 chars

**Resultado:** Em todos os 6 testes, o parser funcionou corretamente. **Zero erros de parsing.** Todas as respostas RAW já vinham em JSON puro (sem markdown, sem texto extra, sem tags `<think>`), graças ao `think=false` e ao system prompt rigoroso.

---

## 10. ReferenceResolver

O ReferenceResolver **não pôde ser instanciado** nos testes devido a uma incompatibilidade no `SearchConfig` (`unexpected keyword argument 'index_path'`). Isso significa que a etapa final de validação das referências via Searcher não foi testada.

**Impacto:** Sem o ReferenceResolver, não é possível confirmar se os candidatos incorretos (ex: Salmos 23:1 para "Porque Deus amou o mundo") seriam rejeitados pela validação do Searcher. Entretanto, como o ReferenceResolver apenas **filtra** candidatos (não os corrige), e o candidato correto frequentemente não está na lista, o ReferenceResolver não resolveria o problema de acurária do LLM.

---

## 11. Resposta ao Critério de Aceite

> O pipeline de inferência semântica é capaz de reconhecer corretamente referências implícitas quando recebe transcrições perfeitas, sem interferência do áudio?

**Resposta: PARCIALMENTE.**

O pipeline **mecânico** funciona corretamente em todas as etapas (SemanticEngine → PromptBuilder → LocalLLMProvider → Ollama → JSON Parser → IntentCandidate). Nenhuma etapa de software perde informação.

**Entretanto**, a qualidade das respostas do LLM (qwen3:8b-q4_K_M) é **insuficiente** para referências implícitas:

- **83% de acerto na intenção** (5/6 classificadas como `show_reference`)
- **33% de acerto no candidato primário** (2/6 com referência correta em 1º lugar)
- **50% de acerto em qualquer posição** (3/6 com referência correta em qualquer posição)

**Fatores que degradam a acurácia:**

1. **`recent_text` confunde o LLM** em 3 dos 4 casos testados, fazendo-o escolher referências relacionadas à frase anterior em vez da atual
2. **Falta de exemplos no system prompt** para as referências testadas (Salmo 23, João 3:16, Filipenses 4:13, Efésios 6)
3. **Capacidade limitada do modelo** qwen3:8b para raciocínio bíblico sem contexto explícito

---

## 12. Recomendações (sem implementar)

### Recomendação 1 (ALTA): Revisar a inclusão de `recent_text` no user prompt

O `recent_text` está **degradando** a acurácia em vez de melhorá-la. Opções:

- **A:** Remover `recent_text` do user prompt para referências implícitas
- **B:** Mover `recent_text` para depois de `current_text` (ordem importa no prompt)
- **C:** Adicionar instrução no system prompt: "Use `Fala recente` apenas como contexto secundário; o `Texto atual` é a referência a identificar"

### Recomendação 2 (ALTA): Adicionar mais exemplos de referências implícitas no system prompt

Os 4 exemplos atuais não cobrem as referências mais comuns. Adicionar:
- "O Senhor é meu pastor" → Salmos 23
- "Porque Deus amou o mundo" → João 3:16
- "Tudo posso naquele que me fortalece" → Filipenses 4:13
- "A armadura de Deus" → Efésios 6
- "Ainda que eu ande pelo vale" → Salmos 23:4

### Recomendação 3 (MÉDIA): Considerar modelo maior

O qwen3:8b-q4_K_M tem 8.2B parâmetros quantizados em Q4_K_M. Para acurácia bíblica, modelos maiores (14B, 32B) podem ter melhor desempenho, ao custo de maior latência.

### Recomendação 4 (MÉDIA): Implementar retry com prompt reformulado

Quando o LLM retorna `intent=none` para uma frase que parece ser uma referência (heurística: contém palavras como "Senhor", "Deus", "pastor", "armadura"), reformular o prompt com mais exemplos e tentar novamente.

### Recomendação 5 (BAIXA): Corrigir a instância do ReferenceResolver

O `SearchConfig` usado no teste tem argumentos incompatíveis com a versão atual. Verificar a assinatura do `SearchConfig.__init__()` e instanciar corretamente para validar a etapa final da cadeia.

---

## 13. Arquivos de Evidência

| Arquivo | Descrição |
|---------|-----------|
| `_diag_sprint21_5_4.py` | Script de instrumentação da cadeia de inferência |
| `_diag_sprint21_5_4_output.txt` | Saída completa (952 linhas) com prompts, payloads, respostas RAW e parser |

---

## 14. Conclusão

| Pergunta | Resposta |
|----------|----------|
| A cadeia mecânica funciona? | **SIM** — todas as etapas executam sem erro |
| O prompt é construído corretamente? | **SIM** — system + user prompt bem formados |
| O payload HTTP está correto? | **SIM** — formato nativo Ollama com `think=false` |
| O parser extrai o JSON corretamente? | **SIM** — 6/6 respostas parseadas sem erro |
| O IntentCandidate é publicado? | **SIM** — 6/6 eventos de telemetria publicados |
| O LLM reconhece referências implícitas? | **PARCIALMENTE** — 83% de acerto na intenção, 33% no candidato primário |
| Onde está a perda de informação? | **No LLM** (qwen3:8b), não no software |
| O `recent_text` ajuda ou atrapalha? | **ATRAPALHA** em 3/4 casos com `recent_text` preenchido |
| O ReferenceResolver foi testado? | **NÃO** — SearchConfig incompatível |
| O pipeline é capaz de reconhecer referências implícitas? | **SIM, com acurária limitada** — 33% de acerto no candidato primário |
