Sprint 22.0 — Bible Knowledge Base (RAG Local)
Contexto

Até a Sprint 21.9, o AI Lyrics utiliza o modelo de linguagem como principal mecanismo para identificar referências bíblicas a partir das transcrições.

Os testes em ambiente real demonstraram que, embora o modelo obtenha bons resultados em passagens muito conhecidas (ex.: João 3:16), ele apresenta limitações em referências menos frequentes, como a bênção sacerdotal de Números 6:24–26.

Entretanto, o projeto já possui uma base de conhecimento muito mais confiável que a memória paramétrica do LLM.

Em:

data/sources/

existem atualmente oito versões completas da Bíblia em SQLite:

ACF
ARA
ARC
JFAA
NAA
NTLH
NVT

Essas bases são locais, rápidas, offline e representam a fonte oficial de conhecimento do sistema.

A partir desta Sprint, o LLM deixará de ser responsável por "lembrar" toda a Bíblia.

Seu novo papel será interpretar e desambiguar candidatos recuperados diretamente da base bíblica local.

Objetivo

Transformar a Bíblia local na principal fonte de conhecimento do AI Lyrics.

O SemanticEngine deverá receber candidatos previamente recuperados da base SQLite, em vez de depender exclusivamente do conhecimento interno do modelo.

Mudança arquitetural

Arquitetura atual:

SpeechPartial
        ↓
SemanticEngine
        ↓
ReferenceResolver
        ↓
Holyrics

Nova arquitetura:

SpeechPartial
        ↓
BibleRetriever
        ↓
Top-K candidatos
        ↓
SemanticEngine
        ↓
ReferenceResolver
        ↓
Holyrics
Princípios

A Bíblia local passa a ser a única fonte de verdade.

O modelo de linguagem não deverá mais responder perguntas como:

"Qual é este versículo?"

Sua responsabilidade passa a ser:

"Entre os versículos recuperados pela Bíblia local, qual melhor corresponde ao texto ouvido?"

Novo componente

Criar:

knowledge/
    bible_retriever.py

Responsabilidade única:

retrieve(
    text: str,
    top_k: int = 20
) -> list[BibleCandidate]

Não adicionar regras de negócio.

Não chamar LLM.

Não acessar SemanticEngine.

Apenas recuperar candidatos.

BibleCandidate

Criar estrutura semelhante a:

BibleCandidate

book

chapter

verse

canonical_reference

aggregated_score

versions[]

Onde versions contém:

BibleVersionMatch

version

text

score

Exemplo:

Números 6:24

ACF
"O Senhor te abençoe..."

score 0.94

ARA
"O Senhor te abençoe..."

score 0.91

NVT
"Que o Senhor o abençoe..."

score 0.89
Recuperação

Pesquisar simultaneamente em todas as versões disponíveis.

Atualmente:

ACF
ARA
ARC
JFAA
NAA
NTLH
NVT

Não assumir quantidade fixa de versões.

As versões deverão ser descobertas automaticamente a partir do diretório:

data/sources/
Agregação

Se várias versões representam o mesmo versículo:

Números 6:24

elas deverão ser agrupadas.

Não retornar sete candidatos idênticos.

Retornar apenas um candidato canônico contendo todas as versões encontradas.

Ranking

O ranking deverá considerar:

melhor score entre versões;
quantidade de versões encontradas;
média dos scores;
posição nas buscas.

Documentar claramente a estratégia utilizada.

SemanticEngine

Modificar o prompt.

Antes:

Identifique a referência bíblica.

Depois:

Texto ouvido:

"O Senhor te abençoe e te guarde..."

Os seguintes candidatos foram encontrados na Bíblia local.

1.

Números 6:24

ACF
...

ARA
...

NVT
...

2.

Salmos 145:2

...

Escolha apenas um candidato.

Caso nenhum corresponda, responda NONE.

Nunca invente referências fora da lista apresentada.

O modelo não poderá criar candidatos inexistentes.

Toda decisão deverá ocorrer apenas sobre a lista fornecida.

Fallback

Caso o BibleRetriever não encontre candidatos relevantes:

Searcher

↓

0 candidatos

o SemanticEngine poderá utilizar o comportamento atual como fallback.

Esse comportamento deverá ser configurável.

Warm-up

Não carregar a Bíblia durante o warm-up do LLM.

O warm-up continuará apenas verificando:

disponibilidade do Ollama;
carregamento do modelo;
tempo de resposta.

Criar, separadamente, um warm-up do BibleRetriever.

No startup:

localizar automaticamente todas as bases SQLite;
validar integridade;
abrir conexões;
preparar índices necessários;
registrar tempo de inicialização;
registrar quantidade de versões carregadas;
registrar quantidade total de versículos disponíveis.
Telemetria

Registrar:

consulta recebida;
versões pesquisadas;
candidatos encontrados;
score individual;
score agregado;
candidatos enviados ao LLM;
candidato escolhido;
tempo da recuperação;
tempo da decisão.
Performance

Objetivo:

BibleRetriever:

<100 ms

SemanticEngine:

reduzir latência total, pois o LLM decidirá apenas entre poucos candidatos.

Não sacrificar precisão por velocidade sem justificativa.

Compatibilidade

Não remover componentes existentes.

Toda a nova arquitetura deverá coexistir com a anterior durante esta Sprint.

Adicionar configuração para alternar entre:

Modo Atual

LLM direto

e

Modo RAG Local

BibleRetriever

↓

SemanticEngine

Permitindo testes A/B.

Critério de aceite

Ao final da Sprint deverá ser possível:

iniciar o sistema normalmente;
detectar automaticamente todas as versões presentes em data/sources/;
recuperar candidatos relevantes consultando simultaneamente todas as Bíblias locais;
agrupar automaticamente traduções do mesmo versículo;
enviar apenas candidatos recuperados ao SemanticEngine;
impedir que o modelo proponha referências fora da lista recebida;
manter compatibilidade com o pipeline anterior por meio de configuração.
Resultado esperado

O AI Lyrics deixará de depender da memória paramétrica do modelo para identificar referências bíblicas. A Bíblia local passará a ser a fonte primária de conhecimento, enquanto o LLM atuará como um componente de desambiguação e seleção sobre candidatos recuperados da própria base oficial do sistema. Essa arquitetura deve aumentar a precisão, reduzir alucinações e tornar o comportamento mais consistente entre diferentes modelos de linguagem, preservando o funcionamento offline do projeto.