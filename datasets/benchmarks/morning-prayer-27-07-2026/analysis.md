# Análise: Morning Prayer 27/07/2026

## 1. Resumo da estratégia do pregador ao citar referências

O pregador opera com duas referências centrais que funcionam como espinha dorsal do sermão: 1 Coríntios 14:10 (abertura) e João 10:27 (encerramento). A primeira é citada duas vezes em sequência: primeiro como pedido de abertura ("Abra comigo a sua Bíblia no livro de Primeiro Coríntios, capítulo 14, versículo 10") e depois re-referenciada na exposição ("aqui em Coríntios, capítulo 14, versículo 10"). A segunda é apresentada de forma completa em uma única frase ("Lá no Evangelho de João 10:27").

Além dessas duas referências completas, o pregador faz menções periféricas a Gênesis (duas vezes, uma como relato de sermão anterior e outra como "Gênesis 3" sem versículo) e a Salmos (sem capítulo/versículo). Há também uma referência indireta a Tessalonicenses via "igreja de Tessalônica" e uma citação não-atribuída ("Filho, este é o caminho, siga por ele"). O pregador não usa o padrão "abra em X capítulo Y versículo Z" consistentemente; alterna entre abertura formal, re-referência anafórica ("aqui em"), referência vaga ("Como diz lá em") e menção narrativa ("Lá em Gênesis 3").

## 2. Referências completas

| Referência | Local no sermão | Forma verbal |
|---|---|---|
| 1 Coríntios 14:10 | Linha 3 | "Abra comigo... Primeiro Coríntios, capítulo 14, versículo 10" |
| 1 Coríntios 14:10 (re-cita) | Linha 4 | "aqui em Coríntios, capítulo 14, versículo 10" |
| João 10:27 | Linha 10 | "Lá no Evangelho de João 10:27" |

## 3. Referências incompletas

| Referência parcial | Local | O que falta | Estado correto |
|---|---|---|---|
| Gênesis 3 | Linha 6 | Versículo | PREPARE (livro + capítulo) |
| Gênesis (menção passiva) | Linha 3 | Capítulo e versículo | WAIT ("pregava ontem sobre") |
| Salmos (vaga) | Linha 3 | Capítulo e versículo | WAIT ("Como diz lá em") |
| Tessalônica (indireta) | Linha 7 | Livro canônico, capítulo, versículo | WAIT (não inferir) |
| Citação não-atribuída | Linha 11 | Livro, capítulo, versículo | WAIT (não inferir) |

## 4. Referências que exigiram memória de contexto

**1 Coríntios 14:10 (evento 2):** O livro é detectado no evento 1 ("Primeiro Coríntios"). O capítulo e versículo chegam no evento 2 ("capítulo 14, versículo 10"). O parser precisa manter `active_book = 1 Coríntios` no contexto para completar a referência. Sem memória de curto prazo, o sistema não conseguiria associar "capítulo 14" ao livro correto.

**1 Coríntios 14:10 re-cita (evento 5):** O livro é re-detectado no evento 4 ("aqui em Coríntios"). O capítulo e versículo chegam no evento 5. Mesma dependência de contexto. Adicionalmente, `last_presented_reference` permite identificar que é uma repetição.

**João 10:27 (evento 10):** O livro é detectado no evento 9 ("Evangelho de João"). O capítulo e versículo chegam no evento 10 ("10:27"). O parser precisa manter `active_book = João` para completar a referência.

## 5. Trechos que poderiam gerar apresentação precoce caso a IA fosse agressiva

**"sobre Gênesis" (linha 3):** O parser pode detectar "Gênesis" como nome de livro e entrar PREPARE. Se a IA for agressiva e não verificar o contexto semântico ("pregava ontem sobre"), pode preparar uma apresentação para Gênesis sem capítulo/versículo. O semantic_engine deve reconhecer o tempo verbal passado e o contexto de sermão anterior para manter WAIT.

**"lá em Gênesis, no começo de tudo" (linha 3):** Repetição de Gênesis. "No começo de tudo" não é um número de capítulo, mas uma IA agressiva poderia inferir Gênesis 1 ou Gênesis 3 por conhecimento teológico. O sistema conservador não deve inferir.

**"Como diz lá em Salmos" (linha 3):** O parser detecta "Salmos" como livro. Sem capítulo/versículo, uma IA agressiva poderia tentar inferir o salmo a partir da citação ("assenta-se, detém e para") ou usar conhecimento teológico. O sistema conservador deve manter WAIT.

**"igreja de Tessalônica" (linha 7):** O semantic_engine pode inferir 1 Tessalonicenses a partir de "igreja de Tessalônica" e reconhecer a citação de 1 Tess 5:23. Uma IA agressiva poderia apresentar 1 Tess 5:23. O sistema conservador não deve inferir livro, capítulo ou versículo.

**"Filho, este é o caminho, siga por ele" (linha 11):** Citação verbalmente reconhecível como Isaías 30:21. Uma IA agressiva com RAG poderia recuperar esta passagem e apresentá-la. O sistema conservador não deve apresentar sem referência explícita do pregador.

**Gênesis 3 (linha 6):** Referência parcial (livro + capítulo, sem versículo). Uma IA agressiva com anticipation_threshold baixo poderia apresentar Gênesis 3 imediatamente (apresentação antecipada de capítulo). O sistema conservador deve manter PREPARE e aguardar versículo. Se o versículo nunca vier (como ocorre neste sermão), a referência expira sem apresentação.

## 6. Trechos que representam bons testes de regressão

**Evento 1+2 (1 Cor 14:10, abertura completa):** Testa o caminho feliz completo: WAIT → PREPARE → PRESENT. O parser deve detectar o livro, manter contexto, e completar com capítulo/versículo. Regressão aqui indica que o parser básico quebrou.

**Evento 3 (PRESENT → WAIT com menções passivas):** Testa se o semantic_engine reconhece "pregava ontem sobre Gênesis" como menção passiva e não entra PREPARE. Também testa se "Como diz lá em Salmos" mantém WAIT. Este é o teste mais importante de falso positivo do sermão.

**Evento 4+5 (re-referência de 1 Cor 14:10):** Testa se o sistema detecta corretamente uma referência repetida. O `last_presented_reference` deve estar preenchido, permitindo que o sistema identifique a repetição. Regressão aqui indica problema na memória de contexto entre referências.

**Evento 7 (Gênesis 3, PREPARE sem versículo):** Testa se o sistema entra PREPARE corretamente para livro+capítulo sem versículo, e se NÃO apresenta antecipadamente. Regressão aqui indica que o anticipation_threshold está muito baixo ou o sistema está apresentando capítulos sem versículo.

**Evento 8 (PREPARE → WAIT por mudança de assunto):** Testa se o sistema abandona Gênesis 3 quando o pregador muda para Tessalônica. Também testa se NÃO infere 1 Tessalonicenses a partir de "igreja de Tessalônica". Regressão aqui indica que o semantic_engine está inferindo referências ausentes.

**Evento 9+10 (João 10:27, formato compacto):** Testa se o parser reconhece "Evangelho de João" como livro canônico (ignorando prefixo "Evangelho de") e se parseia "10:27" como capítulo:versículo. Regressão aqui indica problema no parsing de formato numérico compacto.

**Evento 11 (citação não-atribuída):** Testa se o sistema NÃO infere Isaías 30:21 a partir da citação verbal. Regressão aqui indica que o RAG ou semantic_engine está completando referências sem evidência explícita.

## 7. Casos onde um operador humano aguardaria antes de apresentar

**"sobre Gênesis" (linha 3):** Um operador humano reconhece imediatamente que "pregava ontem sobre Gênesis" é um relato, não um pedido de abertura. Aguardaria sem preparar nada.

**"lá em Gênesis, no começo de tudo" (linha 3):** Um operador humano reconhece que não há capítulo numérico. "No começo de tudo" é descritivo, não referencial. Aguardaria.

**"Como diz lá em Salmos" (linha 3):** Um operador humano sabe que sem capítulo/versículo, não há o que apresentar. Aguardaria.

**Gênesis 3 (linha 6):** Um operador humano ouviria "Gênesis 3" e prepararia mentalmente, mas aguardaria o versículo. Como o versículo nunca vem, o operador não apresentaria nada.

**"igreja de Tessalônica" (linha 7):** Um operador humano pode saber que a citação é de 1 Tess 5:23, mas aguardaria o pregador citar a referência explicitamente. Se o pregador não citar, o operador não apresenta.

**"Filho, este é o caminho, siga por ele" (linha 11):** Um operador humano pode reconhecer a citação, mas sem referência explícita do pregador, aguardaria. Se o pregador não citar, não apresenta.

## 8. Casos onde uma IA conservadora deve preferir WAIT em vez de PRESENT

**"sobre Gênesis" (linha 3):** WAIT. Menção passiva em tempo passado. Não há intenção de abrir a Bíblia.

**"lá em Gênesis, no começo de tudo" (linha 3):** WAIT. Sem capítulo numérico. "No começo de tudo" não é parseável como capítulo.

**"Como diz lá em Salmos" (linha 3):** WAIT. Referência vaga sem capítulo/versículo. Mesmo que a citação seja reconhecível, o sistema não deve inferir o salmo.

**"igreja de Tessalônica" (linha 7):** WAIT. Referência indireta sem nome canônico do livro, sem capítulo, sem versículo. Inferir 1 Tess 5:23 exigiria conhecimento teológico, o que viola a regra de conservadorismo.

**"Filho, este é o caminho, siga por ele" (linha 11):** WAIT. Citação sem atribuição. Inferir Isaías 30:21 exigiria conhecimento teológico.

**Gênesis 3 (linha 6):** PREPARE (não WAIT, não PRESENT). Há livro e capítulo explícitos, mas sem versículo o sistema não deve apresentar. PREPARE é o estado correto: guardar contexto e aguardar. Se o versículo nunca vier, o estado expira para WAIT.

---

## Summary

```yaml
summary:
  total_events: 11
  wait: 4          # eventos 3, 6, 8, 11
  prepare: 4       # eventos 1, 4, 7, 9
  present: 3       # eventos 2, 5, 10
  ignore: 0        # trechos sem evento: linhas 1, 2, 8, 9, 12, 13, 14
  explicit_references: 3   # 1 Cor 14:10 (x2), João 10:27
  partial_references: 5    # Gênesis (passiva), Gênesis 3, Salmos (vaga), Tessalônica (indireta), citação não-atribuída
  books_detected: 4        # 1 Coríntios, Gênesis, Salmos, João
  false_positive_risk: high
  # 6 trechos com risco de falso positivo:
  #   1. "sobre Gênesis" (menção passiva)
  #   2. "lá em Gênesis, no começo de tudo" (sem capítulo numérico)
  #   3. "Como diz lá em Salmos" (vaga, sem capítulo/versículo)
  #   4. "igreja de Tessalônica" (referência indireta, exigiria inferência teológica)
  #   5. "Filho, este é o caminho, siga por ele" (citação sem atribuição)
  #   6. "Gênesis 3" (PREPARE sem versículo, risco de apresentação antecipada)
  recommendations:
    - "O semantic_engine deve distinguir menção passiva ('pregava ontem sobre') de pedido de abertura ('Abra comigo em'). Este é o teste de regressão mais crítico."
    - "O parser deve reconhecer prefixos comuns como 'Evangelho de João' mapeando para o livro canônico 'João'."
    - "O parser deve suportar formato numérico compacto '10:27' como capítulo:versículo, não apenas formato por extenso 'capítulo 10, versículo 27'."
    - "O anticipation_threshold não deve permitir apresentação de capítulo sem versículo. Gênesis 3 (evento 7) deve permanecer PREPARE e expirar para WAIT sem apresentação."
    - "O semantic_engine não deve inferir referências a partir de conhecimento teológico. 'igreja de Tessalônica' não deve mapear para 1 Tessalonicenses, e 'Filho, este é o caminho' não deve mapear para Isaías 30:21."
    - "O sistema deve rastrear last_presented_reference para identificar re-apresentações (evento 5). A decisão de re-apresentar ou manter é de UX, mas o estado deve ser PRESENT (repeat)."
    - "O ContextEngine deve expirar referências parciais (PREPARE sem versículo) quando o pregador muda de assunto. O evento 8 testa esta expiração: Gênesis 3 deve ser abandonado quando o pregador passa a Tessalônica."
    - "Considerar adicionar um teste de regressão automatizado para cada um dos 11 eventos, comparando o estado produzido pelo pipeline contra o estado esperado neste benchmark."
```
