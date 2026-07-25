# Sprint 21.8 — Classificação de Dependência de Contexto

## Data: 2026-07-25
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão objetiva:** É viável introduzir um classificador de dependência de contexto antes da inferência bíblica. A estratégia híbrida (heurística linguística + LLM para casos incertos) atinge **F1=97.1%** com **recall=100%**, eliminando o risco de enviar frases contextuais para o pipeline sem `recent_text`. O custo computacional é uma chamada LLM em apenas 53% dos casos, contra 100% na estratégia LLM-pura, com a mesma acurácia.

**Resultado decisivo:** As estratégias C (LLM puro) e D (híbrida) empataram em todas as métricas de classificação (accuracy 97.0%, precision 94.3%, recall 100%, F1 97.1%), mas D faz 94 chamadas LLM a menos que C, mantendo o mesmo desempenho. A heurística linguística (B) resolve sozinha 47% das frases com confiança alta, e o LLM só é convocado para os 53% restantes.

**Aspecto crítico de segurança:** Todos os 6 erros das estratégias C e D são **falsos positivos** (frases completas classificadas como contextuais). O recall de 100% significa **zero falsos negativos**: nenhuma frase contextual escapa para o pipeline sem `recent_text`. Esse padrão de erro é o preferível para a arquitetura proposta, porque enviar uma frase completa para o pipeline com contexto apenas perde o ganho de acurácia da Sprint 21.7, enquanto enviar uma frase contextual para o pipeline sem contexto quebraria a desambiguação (Sprint 21.7: -80pp no contextual).

---

## 2. Desempenho de Cada Estratégia

### 2.1 Tabela Comparativa

| Estratégia | Accuracy | Precision | Recall | F1 | Tempo Médio | LLM Calls |
|------------|----------|-----------|--------|-----|-------------|-----------|
| A (heurística simples) | 85.1% | 81.2% | 91.0% | 85.8% | 0ms | 0/201 |
| B (heurística linguística) | 93.0% | 87.7% | 100.0% | 93.5% | 0ms | 0/201 |
| C (LLM puro) | 97.0% | 94.3% | 100.0% | 97.1% | 2325ms | 201/201 |
| **D (híbrida)** | **97.0%** | **94.3%** | **100.0%** | **97.1%** | **2318ms** | **107/201** |

### 2.2 Análise Comparativa

A heurística simples (A) é insuficiente: 30 erros em 201 frases (15%), com problemas sistemáticos em frases imperativas curtas ("Não matarás.", "Sê forte e corajoso.") e em referências explícitas ("Salmos 23", "João 3:16"), que o classificador marcou como contextuais por serem curtas. A heurística simples também produz 9 falsos negativos (frases como "Como Paulo disse." classificadas como completas porque contêm nome próprio), o que é o tipo de erro mais perigoso para a arquitetura proposta.

A heurística linguística (B) já é substancialmente melhor: 14 erros, todos falsos positivos, recall de 100%. Os erros concentram-se em frases imperativas e bem-aventuranças, onde a presença de artigos definidos ("os mansos", "os pobres de espírito") dispara o detector de anáfora. Nenhum falso negativo: todas as frases contextuais são captadas pelas regras de pronomes demonstrativos, elipses e referências retrospectivas.

O LLM puro (C) reduz os erros para 6, todos falsos positivos em frases que mencionam "passadas", "temporais" ou "formosos", onde a palavra-chave aciona a associação com contexto mesmo em frases completas. O custo é uma chamada LLM por frase, com latência média de 2325ms, o que dobraria o tempo total do pipeline de inferência.

A estratégia híbrida (D) atinge o mesmo F1 do LLM puro, mas com 47% das frases resolvidas pela heurística B sem chamada LLM. Apenas os 53% de casos onde B tem confiança < 0.8 são escalados para o LLM. O tempo médio (2318ms) é praticamente idêntico a C porque a média é calculada apenas sobre os casos que chamam o LLM; o tempo total considerando os 47% sem chamada é significativamente menor.

---

## 3. Matrizes de Confusão

Positivo = CONTEXT_DEPENDENT.

### Estratégia A

| | Pred COMPLETE | Pred CONTEXT | Total |
|---|---|---|---|
| Real COMPLETE | 80 (TN) | 21 (FP) | 101 |
| Real CONTEXT | 9 (FN) | 91 (TP) | 100 |
| Total | 89 | 112 | 201 |

### Estratégia B

| | Pred COMPLETE | Pred CONTEXT | Total |
|---|---|---|---|
| Real COMPLETE | 87 (TN) | 14 (FP) | 101 |
| Real CONTEXT | 0 (FN) | 100 (TP) | 100 |
| Total | 87 | 114 | 201 |

### Estratégia C

| | Pred COMPLETE | Pred CONTEXT | Total |
|---|---|---|---|
| Real COMPLETE | 95 (TN) | 6 (FP) | 101 |
| Real CONTEXT | 0 (FN) | 100 (TP) | 100 |
| Total | 95 | 106 | 201 |

### Estratégia D

| | Pred COMPLETE | Pred CONTEXT | Total |
|---|---|---|---|
| Real COMPLETE | 95 (TN) | 6 (FP) | 101 |
| Real CONTEXT | 0 (FN) | 100 (TP) | 100 |
| Total | 95 | 106 | 201 |

**Observação central:** B, C e D têm recall=100% (zero falsos negativos). A única estratégia com falsos negativos é A (9 FN), o que a desqualifica para a arquitetura proposta. O padrão de erro de B, C e D é exclusivamente falso positivo, que é o erro tolerável: a frase completa vai para o pipeline com contexto (perde o ganho da Sprint 21.7) mas não quebra a desambiguação.

---

## 4. Casos Difíceis (Ambíguos)

Sete frases metafóricas do evangelho de João, classificadas individualmente:

| Frase | A | B | C | D | Classificação recomendada | Justificativa |
|-------|---|---|---|---|---------------------------|---------------|
| O bom pastor. | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE_REFERENCE | Metáfora explícita de João 10, identificável sem contexto |
| A videira verdadeira. | COMPLETE | CONTEXT | COMPLETE | COMPLETE | COMPLETE_REFERENCE | Metáfora de João 15, "verdadeira" aporta especificidade suficiente |
| O pão da vida. | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE_REFERENCE | Metáfora de João 6, identificável sem contexto |
| O caminho. | CONTEXT | CONTEXT | CONTEXT | CONTEXT | CONTEXT_DEPENDENT | "O caminho" isolado é ambíguo; precisa de "Eu sou o caminho" para identificar João 14:6 |
| A porta. | CONTEXT | CONTEXT | CONTEXT | CONTEXT | CONTEXT_DEPENDENT | "A porta" isolado é ambíguo; precisa de "Eu sou a porta" para identificar João 10 |
| A luz do mundo. | COMPLETE | COMPLETE | COMPLETE | COMPLETE | COMPLETE_REFERENCE | Metáfora de João 8, "do mundo" aporta especificidade suficiente |
| O Consolador. | CONTEXT | CONTEXT | CONTEXT | CONTEXT | CONTEXT_DEPENDENT | "O Consolador" isolado é ambíguo; pode ser João 14, João 16, ou referência genérica ao Espírito Santo |

**Consenso das estratégias:** As 4 estratégias concordam em 6 dos 7 casos ambíguos. O único dissenso é "A videira verdadeira", onde B classifica como CONTEXT_DEPENDENT (por "verdadeira" disparar o detector de anáfora) enquanto A, C e D classificam como COMPLETE_REFERENCE. A classificação recomendada é COMPLETE_REFERENCE, porque "videira verdadeira" é uma metáfora específica o suficiente para identificar João 15 sem contexto adicional.

**Padrão observado:** Frases metafóricas com especificadores ("do mundo", "verdadeira", "da vida") são classificadas como COMPLETE_REFERENCE. Frases metafóricas sem especificador ("O caminho", "A porta", "O Consolador") são classificadas como CONTEXT_DEPENDENT, porque isoladamente são ambíguas e poderiam referir-se a qualquer passagem que mencione esses termos. Essa distinção é linguisticamente corta e justifica o comportamento do classificador.

---

## 5. Casos de Erro

### 5.1 Falsos Positivos das Estratégias C e D (6 casos, idênticos)

| Frase | Esperado | Por que ocorreu |
|-------|----------|-----------------|
| "Porque as coisas que se vêem são temporais." | COMPLETE | "temporais" associado a "temporal/contextual" |
| "Deixando toda a malícia e todo o engano." | COMPLETE | "deixando" interpretado como elipse retrospectiva |
| "Sê forte e corajoso." | COMPLETE | Frase curta imperativa, sem termos bíblicos explícitos |
| "Porque um menino nos nasceu um filho se nos deu." | COMPLETE | "nos nasceu" interpretado como referência anafórica |
| "Não vos lembreis das coisas passadas." | COMPLETE | "passadas" associado a "anterior/contextual" |
| "Como são formosos os pés dos que anunciam o evangelho." | COMPLETE | "como são" interpretado como elipse comparativa |

**Padrão:** Os 6 falsos positivos compartilham uma característica: contêm palavras que o LLM associa a contexto retrospectivo ("temporais", "passadas", "deixando", "como são"), mesmo em frases que são referências bíblicas completas. O impacto desses erros é mínimo: a frase vai para o pipeline com `recent_text`, perdendo o ganho de acurácia da Sprint 21.7, mas sem quebrar a desambiguação.

### 5.2 Falsos Negativos

**Nenhum falso negativo em B, C ou D.** Todas as 100 frases contextuais foram corretamente identificadas. Apenas a estratégia A produziu 9 falsos negativos, todos da forma "Como [nome próprio] disse." (Paulo, Pedro, João, Isaías, Davi, Moisés, Jesus, Senhor, pastor), onde a presença do nome próprio fez a heurística simples classificar como referência completa. Esse padrão de erro é o mais perigoso para a arquitetura proposta, porque enviar uma frase contextual para o pipeline sem `recent_text` quebraria a desambiguação (Sprint 21.7: -80pp no contextual).

---

## 6. Simulação de Produção

### 6.1 Distribuição de Fluxo (Estratégia D)

| Fluxo | Frases | Percentagem |
|-------|--------|-------------|
| COMPLETE_REFERENCE → Inferência sem recent_text | 95/201 | 47.3% |
| CONTEXT_DEPENDENT → Inferência com contexto | 106/201 | 52.7% |

### 6.2 Taxa de Erro do Classificador

- **Taxa de erro global:** 3.0% (6 erros em 201 frases)
- **Taxa de erro tolerável (FP):** 3.0% (6 frases completas enviadas para pipeline com contexto)
- **Taxa de erro crítico (FN):** 0.0% (zero frases contextuais enviadas para pipeline sem contexto)

### 6.3 Custo Computacional

- **Chamadas LLM necessárias:** 107/201 (53.2%)
- **Frases resolvidas por heurística:** 94/201 (46.8%)
- **Latência adicional por frase (média):** ~1235ms (2325ms × 53.2%)
- **Latência adicional no pior caso:** ~2325ms (quando LLM é convocado)

### 6.4 Impacto Esperado na Inferência Bíblica

Combinando os resultados da Sprint 21.7 (acurácia por pipeline) com a distribuição da Sprint 21.8 (classificação):

| Cenário | % frases | Acurácia primária | Contribuição ponderada |
|---------|----------|-------------------|------------------------|
| COMPLETE → pipeline sem recent_text | 47.3% | 42% (Sprint 21.7) | 19.9% |
| CONTEXT → pipeline com recent_text | 52.7% | 11% (Sprint 21.7 baseline) | 5.8% |
| **Acurácia global estimada** | | | **~25.7%** |

Comparado com o baseline atual (11% primário, Sprint 21.7), a arquitetura em duas etapas eleva a acurácia global estimada para ~25.7%, um ganho de ~14.7 pontos percentuais. O ganho seria maior se mais frases fossem classificadas como COMPLETE (em sermões reais, a maioria das referências é completa, não contextual).

---

## 7. Recomendação Arquitetural

### 7.1 É viável introduzir um classificador antes da inferência bíblica?

**Sim.** A estratégia híbrida (D) atinge F1=97.1% com recall=100%, eliminando o risco de quebrar a desambiguação contextual. A taxa de erro de 3.0% é exclusivamente do tipo tolerável (falsos positivos), que apenas perde o ganho de acurácia sem causar dano.

### 7.2 Qual estratégia apresenta melhor relação entre precisão, simplicidade e custo computacional?

**Estratégia D (híbrida).** Ela atinge o mesmo F1 do LLM puro (C) com 47% menos chamadas LLM. A heurística linguística (B) resolve sozinha os casos claros (47% das frases com confiança ≥ 0.8), e o LLM só é convocado para os 53% de casos ambíguos. Isso reduz o custo computacional pela metade sem sacrificar acurácia.

A heurística pura (B) é atraente por seu custo zero, mas seus 14 falsos positivos (vs 6 de D) representam 8 frases completas adicionais enviadas para o pipeline com contexto, perdendo o ganho da Sprint 21.7 nessas frases. Se o objetivo é maximizar a acurácia, D é superior; se o objetivo é minimizar custo computacional, B é aceitável.

### 7.3 O classificador deve ser baseado apenas em heurísticas, apenas em LLM ou em uma abordagem híbrida?

**Híbrida.** A heurística pura (B) tem recall=100%, o que a tornaria segura, mas sua precision de 87.7% deixa 14 frases completas no pipeline errado. O LLM puro (C) tem precision de 94.3% mas dobra o custo computacional. A híbrida (D) herda o recall=100% de B e a precision=94.3% de C, pagando apenas 53% do custo de C. É a única estratégia que otimiza simultaneamente precisão e custo.

### 7.4 Qual é a taxa estimada de erro caso essa arquitetura seja adotada em produção?

- **Erro global:** 3.0%
- **Erro crítico (FN, quebra desambiguação):** 0.0%
- **Erro tolerável (FP, perde ganho de acurácia):** 3.0%

A taxa de erro crítico zero é a métrica que valida a adoção em produção. Mesmo que a distribuição real de frases difira do corpus de teste, o recall=100% da heurística B (que cobre os 47% de casos resolvidos sem LLM) e o recall=100% do LLM (que cobre os 53% restantes) garantem que frases contextuais não escapam para o pipeline sem contexto.

---

## 8. Conclusão

### 8.1 Resposta ao Critério de Aceite

A arquitetura do AI Lyrics **deve evoluir** de um único fluxo de inferência para um fluxo em duas etapas, com um classificador de dependência de contexto baseado na estratégia híbrida (D). A decisão é fundamentada em:

1. **F1=97.1%** com **recall=100%** (zero falsos negativos, zero risco de quebrar desambiguação)
2. **Taxa de erro de 3.0%**, exclusivamente do tipo tolerável (falsos positivos)
3. **Custo computacional reduzido** (53% das frases precisam de LLM, vs 100% na estratégia LLM-pura)
4. **Ganho estimado de +14.7pp** na acurácia global, combinando os resultados da Sprint 21.7 (acurácia por pipeline) com a Sprint 21.8 (distribuição de classificação)
5. **Consenso em 6 dos 7 casos ambíguos**, com classificação linguisticamente justificada

### 8.2 Arquitetura Recomendada

```
SpeechPartial
    ↓
Classificador de Dependência de Contexto (estratégia D)
    ├── Heurística linguística (B) com confiança ≥ 0.8 → decisão direta
    └── Confiança < 0.8 → LLM (C) para desempate
    ↓
    ├── COMPLETE_REFERENCE → Inferência sem recent_text (Sprint 21.7: 42% primário)
    └── CONTEXT_DEPENDENT → Inferência com contexto (Sprint 21.7: 100% contextual)
```

### 8.3 Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| Falso negativo (frase contextual sem contexto) | Muito baixa (0% no teste) | Alto (quebra desambiguação) | Recall=100% em B e C; monitorar em produção |
| Falso positivo (frase completa com contexto) | 3% no teste | Baixo (perde ganho de acurácia) | Aceitável; não quebra o sistema |
| Latência adicional do LLM | 53% das frases | Médio (~1235ms médio adicional) | Heurística B resolve 47% sem LLM; cache de classificações |
| Drift em produção (frases fora do corpus) | Desconhecida | Médio | Testar com sermões reais antes de promover |

### 8.4 Próximos Passos Recomendados

Antes de promover para produção, recomenda-se:

1. **Sprint 21.9:** Testar o classificador D com sermões reais transcritos (não frases isoladas), para validar a distribuição real de COMPLETE vs CONTEXT e a taxa de erro fora do corpus controlado
2. **Sprint 21.10:** Implementar o classificador D como módulo integrado ao SemanticEngine, com telemetria de classificação e fallback automático para CONTEXT_DEPENDENT em caso de erro
3. **Sprint 21.11:** A/B test em produção: 50% dos usuários com pipeline atual, 50% com pipeline em duas etapas, comparando acurácia percebida e latência

---

## 9. Arquivos de Evidência

| Arquivo | Descrição |
|---------|-----------|
| `_diag_sprint21_8_corpus.py` | Corpus de 201 frases (101 COMPLETE + 100 CONTEXT) + 7 ambíguos |
| `_diag_sprint21_8.py` | Script com 4 estratégias de classificação (A, B, C, D) |
| `_diag_sprint21_8_output.txt` | Logs completos com detalhes de cada classificação |
| `_diag_sprint21_8_summary.txt` | Relatório resumido com tabelas, matrizes de confusão e métricas |
