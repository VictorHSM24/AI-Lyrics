# Relatório — Evidence Layer (Refinamento Arquitetural do Sermon Intelligence)

**Data:** 18 de julho de 2026
**Fase:** Refinamento arquitetural sobre a Fase 11 (Sermon Intelligence)
**Status:** Concluído
**Testes:** 2087 passaram (1995 existentes + 92 novos)

---

## 1. Objetivo

Aumentar a granularidade da explicabilidade do Sermon Intelligence sem
alterar o comportamento do sistema nem quebrar APIs públicas.

**Conceito central:** cada `IntelligenceSignal` passa a ser sustentado
por uma ou mais `Evidence` — fatos concretos observáveis que justificam
parte da decisão de uma Strategy.

**Fluxo antes:**
```
Strategy → Signal → Score
```

**Fluxo depois:**
```
Strategy → Evidence(s) → Signal → Score
```

---

## 2. Componentes Criados

### 2.1 `intelligence/evidence.py` (novo)

Arquivo único contendo cinco componentes coesos:

| Componente       | Responsabilidade                                              |
|------------------|---------------------------------------------------------------|
| `EvidenceType`   | Enum extensível (19 tipos + CUSTOM).                          |
| `Evidence`       | DTO imutável, hashable, serializável.                         |
| `EvidencePolicy` | Política stateless: pesos, prioridades, limites.              |
| `EvidenceFactory`| Helpers padronizados para produzir evidências.                |
| `SignalBuilder`  | Transforma Evidences em `IntelligenceSignal`.                 |

#### `EvidenceType` (Enum)

19 tipos cobrindo todos os domínios das Strategies:

- **Contexto:** `CONTEXT_BOOK_MATCH`, `CONTEXT_CHAPTER_MATCH`,
  `CONTEXT_REFERENCE_MATCH`, `CONTEXT_THEME_MATCH`
- **Feedback:** `FEEDBACK_ACCEPTANCE`, `FEEDBACK_REJECTION`,
  `FEEDBACK_HISTORY`
- **Continuidade:** `CONTINUITY_BOOK`, `CONTINUITY_CHAPTER`,
  `CONTINUITY_REFERENCE`
- **Livro:** `BOOK_RECENT`
- **Referência:** `REFERENCE_REPEAT`
- **Tema:** `THEME_MATCH`, `THEME_HISTORY`
- **Avaliação:** `EVALUATION_PRECISION`, `EVALUATION_VOLUME`,
  `EVALUATION_RELIABILITY`
- **Confiança:** `CONFIDENCE_CONSISTENCY`
- **Genérico:** `CUSTOM`

#### `Evidence` (DTO)

```python
@dataclass(frozen=True)
class Evidence:
    id: str
    type: EvidenceType
    description: str
    value: float = 0.0          # [-1.0, 1.0]
    weight: float = 0.0         # [0.0, 1.0]
    confidence: float = 0.0     # [0.0, 1.0]
    metadata: tuple = ()        # pares (chave, valor)
    timestamp: float = 0.0
```

Properties: `contribution` (value * weight), `to_dict()`.

#### `EvidencePolicy`

Centraliza parâmetros (sem números mágicos no código):
- Pesos por tipo de evidência.
- Prioridades (para ordenação em explicabilidade).
- Confiança padrão.
- Limite máximo de evidências por signal (20).

#### `EvidenceFactory`

Helpers para todos os tipos de evidência:
`book_match`, `chapter_match`, `context_no_match`,
`feedback_acceptance`, `feedback_rejection`, `feedback_history`,
`feedback_none`, `continuity_book`, `continuity_chapter`,
`continuity_none`, `book_recent`, `book_not_recent`,
`reference_repeat`, `reference_no_repeat`, `theme_match`,
`theme_no_match`, `evaluation_precision`, `evaluation_volume`,
`evaluation_reliability`, `evaluation_none`,
`confidence_consistency`, `confidence_none`, `custom`.

#### `SignalBuilder`

Transforma Evidences em `IntelligenceSignal`:
- Calcula `value` agregado (soma ponderada normalizada).
- Suporta `value_override` para compatibilidade com lógica existente.
- Aplica clamp `[-1.0, 1.0]`.
- Limita número de evidências ao máximo da policy.

### 2.2 Modificações em arquivos existentes

| Arquivo                  | Mudança                                                |
|--------------------------|--------------------------------------------------------|
| `intelligence/dtos.py`   | `IntelligenceSignal` ganha campo `evidences: tuple = ()` + properties `has_evidences`, `evidence_count` + `to_dict` atualizado. |
| `intelligence/__init__.py` | Exporta `Evidence`, `EvidenceType`, `EvidencePolicy`, `EvidenceFactory`, `SignalBuilder`. |
| `intelligence/strategies.py` | Todas as 8 strategies refatoradas para produzir Evidences via `EvidenceFactory` e construir Signals via `SignalBuilder`. |

### 2.3 Strategies refatoradas

| Strategy              | Evidences produzidas                                      |
|-----------------------|-----------------------------------------------------------|
| `ContextStrategy`     | `CONTEXT_BOOK_MATCH`, `CONTEXT_CHAPTER_MATCH`             |
| `FeedbackStrategy`    | `FEEDBACK_ACCEPTANCE`, `FEEDBACK_REJECTION`, `FEEDBACK_HISTORY` |
| `ContinuityStrategy`  | `CONTINUITY_BOOK`, `CONTINUITY_CHAPTER`                   |
| `ReferenceStrategy`   | `REFERENCE_REPEAT`                                        |
| `ThemeStrategy`       | `THEME_MATCH`                                             |
| `BookStrategy`        | `BOOK_RECENT`                                             |
| `EvaluationStrategy`  | `EVALUATION_VOLUME`, `EVALUATION_PRECISION`, `EVALUATION_RELIABILITY` |
| `ConfidenceStrategy`  | `CONFIDENCE_CONSISTENCY`                                  |

---

## 3. Compatibilidade

- **Nenhuma API pública quebra.**
- `IntelligenceSignal.evidences` tem default `()` — código existente
  que constrói Signals diretamente continua funcionando.
- `value_override` no `SignalBuilder` preserva exatamente os mesmos
  valores de `value` que as Strategies produziam antes.
- Todos os 1995 testes existentes passam sem modificação.
- `IntelligenceScore`, `IntelligenceRecommendation`,
  `SignalCombiner`, `IntelligenceCoordinator`,
  `SermonIntelligenceEngine` não foram modificados.

---

## 4. Testes

### 4.1 Novos arquivos

| Arquivo                                  | Testes | Cobertura                                             |
|------------------------------------------|--------|-------------------------------------------------------|
| `tests/test_evidence_layer.py`           | 32     | `EvidenceType`, `Evidence`, `EvidencePolicy`          |
| `tests/test_evidence_integration.py`     | 60     | `EvidenceFactory`, `SignalBuilder`, `IntelligenceSignal.evidences`, integração com 8 strategies |
| **Total**                                | **92** |                                                       |

### 4.2 Cobertura detalhada

**`test_evidence_layer.py`:**
- `EvidenceType`: enum, str subclass, valores uppercase, lookup por valor.
- `Evidence`: imutabilidade, hashability, defaults, contribution
  (positiva, negativa, zero), `to_dict` (chaves, type como string,
  metadata como list, contribution).
- `EvidencePolicy`: default_confidence, max_evidences, weight_for,
  priority_for (chapter >= book, feedback alta), all_types,
  is_valid_type, sort_by_priority (decrescente, vazio).

**`test_evidence_integration.py`:**
- `EvidenceFactory`: todos os 23 helpers (tipos corretos, valores,
  descrições, metadata, confidence).
- `SignalBuilder`: build básico, com evidences, cálculo de value,
  value_override, clamp (positivo e negativo), sem evidences,
  peso zero, limite de evidências, policy.
- `IntelligenceSignal.evidences`: default vazio, com evidences,
  `to_dict` com evidences, hashability.
- **Integração com Strategies:** todas as 8 strategies produzem
  evidences em todos os caminhos (match, no-match, sem dados).

### 4.3 Resultado final

```
2087 passed in 203.66s
```

- 1995 testes existentes: **todos passam** (zero regressão).
- 92 testes novos: **todos passam**.

---

## 5. Exemplo de Uso

```python
from intelligence import (
    EvidenceFactory, SignalBuilder, EvidenceType,
)

factory = EvidenceFactory()
builder = SignalBuilder()

# Strategy coleta fatos e produz evidences
ev_book = factory.book_match("ev1", "João", "João", value=0.10)
ev_chapter = factory.chapter_match(
    "ev2", "João", 21, "João", 21, value=0.15)

# SignalBuilder transforma evidences em signal
signal = builder.build(
    signal_type="context",
    weight=0.20,
    evidences=(ev_book, ev_chapter),
    explanation="Contexto João 21 corresponde ao candidato",
)

print(signal.value)           # 0.150
print(signal.evidence_count)  # 2
print(signal.evidences[0].description)
# "Livro ativo 'João' = livro do candidato 'João'"
```

---

## 6. Arquitetura Final

```
┌─────────────────────────────────────────────────────────┐
│                   SermonIntelligenceEngine               │
│                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │  ContextStr  │   │ FeedbackStr  │   │ ContinuityStr│ │
│  │  ┌────────┐  │   │  ┌────────┐  │   │  ┌────────┐  │ │
│  │  │Evidence│  │   │  │Evidence│  │   │  │Evidence│  │ │
│  │  │Factory │  │   │  │Factory │  │   │  │Factory │  │ │
│  │  └───┬────┘  │   │  └───┬────┘  │   │  └───┬────┘  │ │
│  │      │       │   │      │       │   │      │       │ │
│  │  ┌───▼────┐  │   │  ┌───▼────┐  │   │  ┌───▼────┐  │ │
│  │  │Signal │  │   │  │Signal │  │   │  │Signal │  │ │
│  │  │Builder│  │   │  │Builder│  │   │  │Builder│  │ │
│  │  └───┬────┘  │   │  └───┬────┘  │   │  └───┬────┘  │ │
│  │      │Signal │   │      │Signal │   │      │Signal │ │
│  └──────┼───────┘   └──────┼───────┘   └──────┼───────┘ │
│         │                   │                   │        │
│         ▼                   ▼                   ▼        │
│  ┌──────────────────────────────────────────────────┐   │
│  │              SignalCombiner                       │   │
│  │         (combina Signals → Score)                 │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                                │
│                         ▼                                │
│              IntelligenceRecommendation                  │
│              (com Evidences em cada Signal)              │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Conclusão

O Evidence Layer foi implementado com sucesso como um refinamento
arquitetural não-invasivo. As principais conquistas:

1. **Explicabilidade granular:** cada Signal agora carrega as
   Evidences que o sustentam, permitindo responder "por que este
   sinal tem este valor?" com fatos concretos.
2. **Zero regressão:** todos os 1995 testes existentes passam
   sem modificação.
3. **Padronização:** `EvidenceFactory` elimina duplicação de código
   entre Strategies.
4. **Extensibilidade:** novos tipos de `EvidenceType` podem ser
   adicionados sem quebrar existentes.
5. **Centralização:** `EvidencePolicy` concentra todos os
   parâmetros (pesos, prioridades, limites) sem números mágicos.
6. **Testes robustos:** 92 novos testes cobrem DTOs, Policy,
   Factory, Builder e integração com todas as 8 Strategies.
