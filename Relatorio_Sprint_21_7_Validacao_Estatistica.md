# Sprint 21.7 — Validação Estatística da Inferência Bíblica

## Data: 2026-07-25
## Status: Investigativo (nenhuma alteração funcional realizada)

---

## 1. Resumo Executivo

**Conclusão geral:** A remoção do `recent_text` do user prompt melhora significativamente a acurácia da inferência semântica para referências bíblicas completas, elevando o candidato primário correto de **11% para 42%** (+31 pontos percentuais) em um corpus de 100 frases. A melhora é observada em **todas as 8 categorias** testadas, com apenas **1 regressão** em 100 casos.

**Entretanto**, para frases dependentes de contexto ("Como vimos anteriormente", "Esse mesmo versículo"), o `recent_text` é **essencial**: sem ele, a acurácia cai de **100% para 20%** no candidato primário.

**Recomendação:** Adotar uma estratégia **híbrida** — remover `recent_text` para frases completas, mas mantê-lo (ou usar `last_book`/`last_chapter` do ContextEngine) para frases incompletas que dependem de contexto.

---

## 2. Estatísticas Completas

### 2.1 Métricas Globais (100 frases)

| Métrica | Baseline (A) | Sem recent (B) | Delta |
|---------|--------------|----------------|-------|
| Intent correto | 33/100 (33%) | 54/100 (54%) | **+21pp** |
| Candidato primário | 11/100 (11%) | 42/100 (42%) | **+31pp** |
| Candidato em qualquer posição | 18/100 (18%) | 42/100 (42%) | **+24pp** |
| Confiança média | 0.95 | 0.96 | +0.00 |
| Tempo médio (ms) | 3681 | 3481 | -200ms |

**Observação:** A acurácia absoluta do Experimento B (42%) é menor que a observada na Sprint 21.6 (100%) porque o corpus da Sprint 21.7 é significativamente maior e mais diverso, incluindo referências menos conhecidas e mais difíceis. A melhora relativa (+31pp) é consistente com a Sprint 21.6 (+67pp) e confirma o efeito benéfico da remoção do `recent_text`.

---

## 3. Resultados por Categoria

| Categoria | A primário | B primário | A qualquer | B qualquer | Δ primário |
|-----------|-----------|-----------|-----------|-----------|-----------|
| Cartas | 3/20 (15%) | 5/20 (25%) | 15% | 25% | +10pp |
| Evangelhos | 1/20 (5%) | 13/20 (65%) | 40% | 65% | **+60pp** |
| Explícitas | 2/5 (40%) | 5/5 (100%) | 40% | 100% | **+60pp** |
| Históricos | 0/10 (0%) | 1/10 (10%) | 0% | 10% | +10pp |
| Pentateuco | 1/10 (10%) | 4/10 (40%) | 10% | 40% | +30pp |
| Profetas | 0/10 (0%) | 4/10 (40%) | 0% | 40% | **+40pp** |
| Sabedoria | 1/10 (10%) | 4/10 (40%) | 10% | 40% | +30pp |
| Salmos | 3/15 (20%) | 6/15 (40%) | 20% | 40% | +20pp |

**Categorias que mais se beneficiam:**
1. **Evangelhos** (+60pp) — frases muito conhecidas que o `recent_text` confundia
2. **Explícitas** (+60pp) — referências explícitas que o `recent_text` fazia o LLM ignorar
3. **Profetas** (+40pp) — referências que o `recent_text` fazia o LLM classificar como `none`

**Categorias com menor benefício:**
1. **Históricos** (+10pp) — acurácia permanece baixa (10%) em ambos os experimentos
2. **Cartas** (+10pp) — melhora marginal, acurácia ainda baixa (25%)

**Nenhuma categoria piorou** com a remoção do `recent_text`.

### 3.1 Por Dificuldade

| Dificuldade | A primário | B primário | A qualquer | B qualquer | Δ primário |
|-------------|-----------|-----------|-----------|-----------|-----------|
| Fácil | 7/33 (21%) | 22/33 (67%) | 30% | 67% | **+45pp** |
| Média | 2/39 (5%) | 13/39 (33%) | 10% | 33% | **+28pp** |
| Difícil | 2/28 (7%) | 7/28 (25%) | 14% | 25% | +18pp |

**Observação:** As frases fáceis são as que mais se beneficiam (+45pp), confirmando que o `recent_text` confundia o LLM mesmo em referências muito conhecidas. As frases difíceis melhoram menos (+18pp), sugerindo que o modelo tem limitações intrínsecas para referências obscuras, independentemente do prompt.

---

## 4. Casos de Regressão

### 4.1 Regressões (A acertou, B errou) — **1 caso**

| Frase | Categoria | Esperado | A retornou | B retornou |
|-------|-----------|----------|------------|------------|
| "Sede sóbrios e vigilantes." | Cartas | 1 Pedro 5:8 | ✅ acertou | ❌ `intent=none` |

**Análise:** Apenas 1 regressão em 100 casos (1%). O caso "Sede sóbrios e vigilantes" foi classificado como `none` sem o `recent_text`, mas acertou com ele. Isso sugere que o `recent_text` pode ter fornecido uma pista contextual que ajudou o LLM a reconhecer a referência. **Impacto mínimo** comparado ao ganho de +31pp.

### 4.2 Melhorias (A errou, B acertou) — **32 casos**

32 casos onde o Baseline errou e o novo prompt acertou. Destaques:

- **"Porque Deus amou o mundo de tal maneira."** — A retornou `none`, B acertou João 3:16
- **"Tudo posso naquele que me fortalece."** — A retornou `none`, B acertou Filipenses 4:13
- **"A armadura de Deus."** — A retornou `none`, B acertou Efésios 6:11
- **"No princípio criou Deus os céus e a terra."** — A retornou `none`, B acertou Gênesis 1:1
- **"Eis que a virgem conceberá..."** — A retornou `none`, B acertou Isaías 7:14
- **"Salmos 23"** (explícita) — A retornou `none`, B acertou Salmos 23
- **"Romanos 8:28"** (explícita) — A retornou `none`, B acertou Romanos 8:28
- **"Filipenses 4:13"** (explícita) — A retornou `none`, B acertou Filipenses 4:13

**Padrão observado:** Muitas das melhorias são casos onde o Baseline retornou `intent=none` (não reconheceu a referência), enquanto o Experimento B reconheceu corretamente. Isso confirma que o `recent_text` não apenas confunde o ranking dos candidatos, mas também **impede o LLM de reconhecer referências** que ele conseguiria identificar sem o ruído contextual.

---

## 5. Casos Dependentes de Contexto

### 5.1 Métricas Contextuais (5 frases)

| Métrica | Com recent (A) | Sem recent (B) | Delta |
|---------|----------------|----------------|-------|
| Intent correto | 5/5 (100%) | 4/5 (80%) | -20pp |
| Candidato primário | 5/5 (100%) | 1/5 (20%) | **-80pp** |
| Candidato em qualquer | 5/5 (100%) | 1/5 (20%) | **-80pp** |

### 5.2 Detalhes por Frase

| Frase | recent_text | Esperado | A (com recent) | B (sem recent) |
|-------|-------------|----------|----------------|----------------|
| "Como vimos anteriormente." | "O Senhor é meu pastor." | Salmos 23 | ✅ Salmos 23:1 | ❌ Salmos 119:0 |
| "Esse mesmo versículo." | "Porque Deus amou o mundo." | João 3:16 | ✅ João 3:16 | ✅ João 3:16 |
| "No capítulo anterior." | "Tudo posso naquele que me fortalece." | Filipenses 4 | ✅ Filipenses 4:13 | ❌ Salmos 23:0 |
| "A mesma passagem." | "A armadura de Deus." | Efésios 6 | ✅ Efésios 6:11 | ❌ Salmos 23:0 |
| "Voltando ao texto." | "Guarda o teu coração." | Provérbios 4:23 | ✅ Provérbios 4:23 | ❌ `intent=none` |

### 5.3 Análise Contextual

**O `recent_text` é essencial para frases dependentes de contexto.** Sem ele, o LLM não tem como saber a que referência a frase se refere, e retorna referências aleatórias (Salmos 23:0, Salmos 119:0) ou `intent=none`.

**Apenas 1 dos 5 casos contextuais** ("Esse mesmo versículo.") foi resolvido corretamente sem `recent_text`, provavelmente porque o LLM inferiu "versículo" como uma referência genérica a João 3:16 (a referência mais popular do Novo Testamento).

**Implicação:** A remoção completa do `recent_text` **não é viável** para frases dependentes de contexto. É necessário um mecanismo que:
1. Detecte frases incompletas/dependentes de contexto
2. Mantenha o `recent_text` (ou use `last_book`/`last_chapter`) apenas para esses casos

---

## 6. Análise Técnica

### 6.1 A remoção do `recent_text` melhora todas as categorias?

**Sim.** Todas as 8 categorias testadas apresentaram melhora no candidato primário, variando de +10pp (Históricos, Cartas) a +60pp (Evangelhos, Explícitas). Nenhuma categoria piorou.

### 6.2 Existe alguma categoria em que o `recent_text` seja realmente útil?

**Para frases completas, não.** Nenhuma categoria de frases completas se beneficiou do `recent_text`. A única regressão foi 1 caso isolado ("Sede sóbrios e vigilantes") em 100 frases.

**Para frases dependentes de contexto, sim.** O `recent_text` é **essencial** para desambiguar frases como "Como vimos anteriormente" ou "A mesma passagem". Sem ele, a acurácia cai de 100% para 20%.

### 6.3 Existem regressões?

**Sim, 1 regressão em 100 casos (1%).** A frase "Sede sóbrios e vigilantes." (1 Pedro 5:8) foi classificada como `none` sem o `recent_text`, mas acertou com ele. Isso representa um impacto mínimo comparado ao ganho de +31pp.

### 6.4 Qual categoria mais se beneficia da remoção?

**Evangelhos (+60pp)** e **Explícitas (+60pp)**. As referências explícitas ("Salmos 23", "Romanos 8:28") que o Baseline classificava como `none` foram todas reconhecidas corretamente sem o `recent_text`. Isso é particularmente preocupante para o sistema atual, pois referências explícitas deveriam ser triviais.

### 6.5 Qual categoria piora?

**Nenhuma categoria piora** para frases completas. A única regressão é um caso isolado na categoria Cartas.

### 6.6 O ganho observado na Sprint 21.6 permanece estatisticamente significativo?

**Sim.** A Sprint 21.6 observou +67pp em 6 frases. A Sprint 21.7 observou +31pp em 100 frases. A diferença na magnitude é esperada, pois o corpus da Sprint 21.7 é mais diverso e inclui referências difíceis que o modelo não consegue identificar independentemente do prompt. A direção do efeito é consistente: **remover `recent_text` melhora a acurácia** em ambos os estudos.

**Significância:** Com 100 frases e +31pp de melhora, o resultado é estatisticamente significativo (p < 0.001 em teste binomial, assumindo hipótese nula de 50% de chance de melhora).

---

## 7. Conclusão

### 7.1 A remoção do `recent_text` deve se tornar o comportamento padrão?

**Sim, para frases completas.** A evidência é estatisticamente significativa:
- +31pp no candidato primário (11% → 42%)
- +21pp no intent correto (33% → 54%)
- +24pp em qualquer candidato (18% → 42%)
- Apenas 1 regressão em 100 casos
- Melhora em todas as 8 categorias
- Melhora em todos os 3 níveis de dificuldade

### 7.2 Exceção: frases dependentes de contexto

**A remoção completa do `recent_text` não é viável** para frases dependentes de contexto. Sem o `recent_text`, a acurácia contextual cai de 100% para 20%.

**Solução recomendada:** Estratégia híbrida:
1. **Para frases completas** (maioria dos casos): remover `recent_text` do prompt
2. **Para frases incompletas** ("Como vimos anteriormente", "Esse versículo"): manter `recent_text` ou usar `last_book`/`last_chapter` do ContextEngine

### 7.3 Resposta ao Critério de Aceite

> A remoção do `recent_text` pode ser adotada como padrão em produção ou deve ser aplicada apenas em cenários específicos?

**Resposta:** A remoção do `recent_text` deve ser adotada como **padrão para frases completas**, com uma **exceção explícita** para frases dependentes de contexto. A decisão é fundamentada em:

1. **Evidência quantitativa:** +31pp de melhora no candidato primário em 100 frases, com apenas 1 regressão
2. **Evidência por categoria:** melhora em todas as 8 categorias testadas
3. **Evidência por dificuldade:** melhora em todos os 3 níveis (fácil +45pp, média +28pp, difícil +18pp)
4. **Evidência contextual:** o `recent_text` é essencial para frases incompletas (-80pp sem ele)
5. **Consistência com Sprint 21.6:** ambos os estudos mostram melhora significativa

**Implementação recomendada:**
- Detectar frases incompletas (heurística: < 5 palavras, ou contém palavras como "anteriormente", "mesmo", "capítulo", "passagem", "versículo", "texto")
- Para frases incompletas: manter `recent_text` no prompt
- Para frases completas: remover `recent_text` do prompt
- Como fallback, usar `last_book`/`last_chapter` do ContextEngine para desambiguação

---

## 8. Arquivos de Evidência

| Arquivo | Descrição |
|---------|-----------|
| `_diag_sprint21_7_corpus.py` | Corpus de 100 frases + 5 contextuais |
| `_diag_sprint21_7.py` | Script de execução dos 2 experimentos + teste contextual |
| `_diag_sprint21_7_output.txt` | Logs completos (390 linhas) |
| `_diag_sprint21_7_summary.txt` | Relatório resumido com tabelas e métricas |
