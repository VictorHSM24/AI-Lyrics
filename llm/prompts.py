"""Prompts e validação de resposta para o LLM (Qwen3 8B via Ollama).

Contém:
  - ``SYSTEM_PROMPT``: instrução base que define o papel do modelo.
  - ``FEW_SHOT_EXAMPLES``: exemplos few-shot para guiar o formato JSON.
  - ``build_messages(text, state)``: monta a lista de messages para o endpoint
    ``/api/chat`` do Ollama.
  - ``validate_response(json_obj)``: valida o JSON de resposta contra o
    schema esperado (Blueprint §4.4).
  - ``CORRECTION_PROMPT``: prompt de correção para retry quando o JSON é
    inválido.

Schema esperado (Blueprint linhas 815-827):
    REQUIRED = {"action"}
    VALID_ACTIONS = {"show","next","previous","search","jump","none"}
    - action="show" exige ``book``
    - action="search" exige ``query``
"""

from __future__ import annotations

from typing import Any

from estado.state import BibleState


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Você é um interpretador de comandos bíblicos em português brasileiro.\n"
    "Sua tarefa é analisar o texto falado pelo usuário e produzir UM objeto JSON\n"
    "que represente a intenção do comando.\n"
    "\n"
    "Responda SOMENTE com JSON válido. Não inclua markdown, comentários,\n"
    "explicações ou texto adicional. A resposta deve ser parseável por\n"
    "json.loads() diretamente.\n"
    "\n"
    "Schema do JSON:\n"
    '{\n'
    '  "action": "show" | "next" | "previous" | "search" | "jump" | "none",\n'
    '  "book": "Nome do livro" (apenas para action="show"),\n'
    '  "chapter": número do capítulo (apenas para action="show"),\n'
    '  "verse": número do versículo ou null (apenas para action="show"),\n'
    '  "amount": número de versículos (apenas para next/previous/jump),\n'
    '  "query": "texto para busca" (apenas para action="search"),\n'
    '  "confidence": número de 0.0 a 1.0,\n'
    '  "keywords": ["palavra1", "palavra2", ...] (opcional, para action="search"),\n'
    '  "tema": "tema principal" (opcional, para action="search"),\n'
    '  "evento": "evento descrito" (opcional, para action="search"),\n'
    '  "personagens": ["personagem1", ...] (opcional, para action="search"),\n'
    '  "livros_sugeridos": ["Livro1", ...] (opcional, para action="search"),\n'
    '  "sinonimos": ["sinônimo1", ...] (opcional, para action="search"),\n'
    '  "conceitos": ["conceito1", ...] (opcional, para action="search")\n'
    '}\n'
    "\n"
    "Regras:\n"
    "1. action=\"show\": o usuário quer abrir um versículo específico.\n"
    "   Inclua book, chapter, verse. Use o nome canônico do livro\n"
    "   (ex.: \"Hebreus\", \"João\", \"1 Coríntios\", \"Gênesis\").\n"
    "2. action=\"search\": o usuário descreve um texto/passagem sem referência\n"
    "   direta. Extraia a frase de busca em \"query\".\n"
    "   IMPORTANTE: extraia também em \"keywords\" as palavras-chave relevantes\n"
    "   da frase (sem artigos, preposições ou stopwords). Estas keywords serão\n"
    "   usadas para uma busca mais flexível.\n"
    "   Se possível, identifique também:\n"
    "   - \"tema\": tema principal (ex.: \"fé\", \"amor\", \"salvação\")\n"
    "   - \"evento\": evento descrito (ex.: \"pesca milagrosa\", \"ressurreição\")\n"
    "   - \"personagens\": pessoas mencionadas (ex.: [\"Jesus\", \"Pedro\"])\n"
    "   - \"livros_sugeridos\": livros onde o versículo provavelmente está\n"
    "     (ex.: [\"João\", \"Mateus\"]). NÃO invente — apenas se for óbvio.\n"
    "   - \"sinonimos\": sinônimos de termos da query (ex.: \"lançar\" → \"jogar\")\n"
    "   - \"conceitos\": conceitos equivalentes (ex.: \"sem pecado\" → \"inocente\")\n"
    "   NÃO invente informações. Se não souber, deixe o campo vazio ou omita.\n"
    "3. action=\"next\": avançar versículo(s). Inclua \"amount\" (default 1).\n"
    "4. action=\"previous\": retroceder versículo(s). Inclua \"amount\" (default 1).\n"
    "5. action=\"none\": o texto não é um comando bíblico válido.\n"
    "6. confidence: sua confiança na interpretação (0.0 a 1.0).\n"
    "   - 0.9+: interpretação clara e inequívoca\n"
    "   - 0.7-0.9: interpretação provável\n"
    "   - <0.7: incerto\n"
    "\n"
    "REGRA CRÍTICA DE SEGURANÇA — NUNCA INVENTE REFERÊNCIAS BÍBLICAS:\n"
    "Você é um EXTRATOR de intenção, NÃO uma base de conhecimento bíblico.\n"
    "O banco de versículos é a fonte da verdade — a descoberta da referência\n"
    "exata acontece exclusivamente via busca textual, NUNCA via inferência.\n"
    "\n"
    "Use action=\"show\" APENAS quando o usuário citar EXPLICITAMENTE:\n"
    "  - nome do livro (ex.: \"João\", \"Romanos\", \"Salmos\")\n"
    "  - capítulo (ex.: \"3\", \"capítulo 3\")\n"
    "  - versículo (ex.: \"16\", \"versículo 16\", \"verso 16\")\n"
    "Exemplos válidos para action=\"show\":\n"
    "  - \"João 3:16\"  →  {\"action\": \"show\", \"book\": \"João\", \"chapter\": 3, \"verse\": 16}\n"
    "  - \"Abra em Hebreus capítulo 11 versículo 1\"\n"
    "  - \"vamos abrir em romanos 8 28\"\n"
    "\n"
    "Use action=\"search\" OBRIGATORIAMENTE quando o usuário NÃO citar\n"
    "explicitamente livro + capítulo + versículo, mesmo que você saiba\n"
    "qual versículo é. Extraia a frase descritiva em \"query\" e as\n"
    "palavras-chave em \"keywords\".\n"
    "Exemplos OBRIGATÓRIOS para action=\"search\":\n"
    "  - \"o texto que diz que todas as coisas cooperam para o bem\"\n"
    "    → {\"action\": \"search\", \"query\": \"todas as coisas cooperam para o bem\",\n"
    "       \"keywords\": [\"cooperam\", \"bem\"], \"tema\": \"providência\",\n"
    "       \"livros_sugeridos\": [\"Romanos\"]}\n"
    "  - \"o salmo do vale da sombra da morte\"\n"
    "    → {\"action\": \"search\", \"query\": \"vale da sombra da morte\",\n"
    "       \"keywords\": [\"vale\", \"sombra\", \"morte\"], \"livros_sugeridos\": [\"Salmos\"]}\n"
    "  - \"tudo posso naquele que me fortalece\"\n"
    "    → {\"action\": \"search\", \"query\": \"tudo posso naquele que me fortalece\",\n"
    "       \"keywords\": [\"posso\", \"fortalece\"], \"livros_sugeridos\": [\"Filipenses\"]}\n"
    "  - \"o versículo sobre a fé ser a certeza das coisas que se esperam\"\n"
    "    → {\"action\": \"search\", \"query\": \"fé é a certeza das coisas que se esperam\",\n"
    "       \"keywords\": [\"fé\", \"certeza\", \"coisas\", \"esperam\"],\n"
    "       \"tema\": \"fé\", \"livros_sugeridos\": [\"Hebreus\"]}\n"
    "  - \"Jesus manda lançar a rede à direita\"\n"
    "    → {\"action\": \"search\", \"query\": \"lançar rede direita barco\",\n"
    "       \"keywords\": [\"rede\", \"direita\", \"barco\"],\n"
    "       \"personagens\": [\"Jesus\"], \"evento\": \"pesca milagrosa\",\n"
    "       \"livros_sugeridos\": [\"João\"], \"sinonimos\": [\"lançar\", \"jogar\"]}\n"
    "\n"
    "NUNCA retorne action=\"show\" com book/chapter/verse que o usuário\n"
    "não citou explicitamente. Se há dúvida sobre se o usuário citou a\n"
    "referência, use action=\"search\".\n"
    "\n"
    "Use sempre os nomes canônicos dos livros em português:\n"
    "Gênesis, Êxodo, Levítico, Números, Deuteronômio, Josué, Juízes, Rute,\n"
    "1 Samuel, 2 Samuel, 1 Reis, 2 Reis, 1 Crônicas, 2 Crônicas, Esdras,\n"
    "Neemias, Ester, Jó, Salmos, Provérbios, Eclesiastes, Cânticos, Isaías,\n"
    "Jeremias, Lamentações, Ezequiel, Daniel, Oséias, Joel, Amós, Obadias,\n"
    "Jonas, Miqueias, Naum, Habacuque, Sofonias, Ageu, Zacarias, Malaquias,\n"
    "Mateus, Marcos, Lucas, João, Atos, Romanos, 1 Coríntios, 2 Coríntios,\n"
    "Gálatas, Efésios, Filipenses, Colossenses, 1 Tessalonicenses,\n"
    "2 Tessalonicenses, 1 Timóteo, 2 Timóteo, Tito, Filemom, Hebreus, Tiago,\n"
    "1 Pedro, 2 Pedro, 1 João, 2 João, 3 João, Judas, Apocalipse."
)


# ---------------------------------------------------------------------------
# Few-shot examples
# ---------------------------------------------------------------------------

FEW_SHOT_EXAMPLES: list[dict[str, str]] = [
    {
        "role": "user",
        "content": "aquele texto que diz que todas as coisas cooperam para o bem",
    },
    {
        "role": "assistant",
        "content": '{"action": "search", "query": "todas as coisas cooperam para o bem", "keywords": ["cooperam", "bem"], "tema": "providencia", "livros_sugeridos": ["Romanos"], "confidence": 0.92}',
    },
    {
        "role": "user",
        "content": "o versículo sobre a fé ser a certeza das coisas que se esperam",
    },
    {
        "role": "assistant",
        "content": '{"action": "search", "query": "a fé é a certeza das coisas que se esperam", "keywords": ["fé", "certeza", "coisas", "esperam"], "tema": "fé", "livros_sugeridos": ["Hebreus"], "confidence": 0.95}',
    },
    {
        "role": "user",
        "content": "salmo do vale da sombra da morte",
    },
    {
        "role": "assistant",
        "content": '{"action": "search", "query": "vale da sombra da morte", "keywords": ["vale", "sombra", "morte"], "livros_sugeridos": ["Salmos"], "confidence": 0.94}',
    },
    {
        "role": "user",
        "content": "tudo posso naquele que me fortalece",
    },
    {
        "role": "assistant",
        "content": '{"action": "search", "query": "tudo posso naquele que me fortalece", "keywords": ["posso", "fortalece"], "livros_sugeridos": ["Filipenses"], "confidence": 0.95}',
    },
    {
        "role": "user",
        "content": "vamos abrir em hebreus 11 verso 1",
    },
    {
        "role": "assistant",
        "content": '{"action": "show", "book": "Hebreus", "chapter": 11, "verse": 1, "confidence": 0.98}',
    },
    {
        "role": "user",
        "content": "abre romanos 8 28",
    },
    {
        "role": "assistant",
        "content": '{"action": "show", "book": "Romanos", "chapter": 8, "verse": 28, "confidence": 0.98}',
    },
]


# ---------------------------------------------------------------------------
# Prompt de correção (retry)
# ---------------------------------------------------------------------------

CORRECTION_PROMPT = (
    "A resposta anterior não é um JSON válido ou não segue o schema esperado.\n"
    "Por favor, responda novamente com SOMENTE um objeto JSON válido,\n"
    "sem markdown, sem comentários, sem texto adicional.\n"
    "O JSON deve ter obrigatoriamente o campo \"action\" com um dos valores:\n"
    "\"show\", \"next\", \"previous\", \"search\", \"jump\", \"none\".\n"
    "Se action=\"show\", inclua \"book\", \"chapter\" e \"verse\".\n"
    "Se action=\"search\", inclua \"query\".\n"
    "Inclua sempre \"confidence\" (0.0 a 1.0).\n"
    "\n"
    "LEMBRE-SE: action=\"show\" APENAS se o usuário citou explicitamente\n"
    "livro + capítulo + versículo. Caso contrário, use action=\"search\"\n"
    "com a frase descritiva em \"query\". NUNCA invente referências bíblicas."
)


# ---------------------------------------------------------------------------
# Construção de messages
# ---------------------------------------------------------------------------


def build_messages(text: str, state: BibleState | None = None) -> list[dict[str, str]]:
    """Monta a lista de messages para o endpoint /api/chat do Ollama.

    Args:
        text: texto transcrito pelo STT.
        state: estado atual da navegação bíblica (opcional, para contexto).

    Returns:
        Lista de messages no formato esperado pelo Ollama:
        [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}, ...]
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Contexto do estado atual (se disponível)
    if state is not None and not state.is_empty():
        context = (
            f"Contexto: o versículo atualmente aberto é "
            f"livro_id={state.book_id}, capítulo={state.chapter}"
        )
        if state.verse is not None:
            context += f", versículo={state.verse}"
        context += f", versão={state.version}."
        messages.append({"role": "system", "content": context})

    # Few-shot examples
    messages.extend(FEW_SHOT_EXAMPLES)

    # Input do usuário
    messages.append({"role": "user", "content": text})

    return messages


def build_correction_messages(
    original_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Monta messages para retry com prompt de correção.

    Args:
        original_messages: messages originais usadas na primeira tentativa.

    Returns:
        Novas messages com o prompt de correção adicionado.
    """
    messages = list(original_messages)
    messages.append({"role": "system", "content": CORRECTION_PROMPT})
    return messages


# ---------------------------------------------------------------------------
# Validação de resposta
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: frozenset[str] = frozenset({"action"})
VALID_ACTIONS: frozenset[str] = frozenset({
    "show", "next", "previous", "search", "jump", "none",
})


def validate_response(json_obj: Any) -> bool:
    """Valida o JSON de resposta do LLM contra o schema esperado.

    Regras (Blueprint §4.4, linhas 815-827):
      - Deve ser um dict.
      - ``action`` é obrigatório e deve ser um valor válido.
      - ``action="show"`` exige ``book``.
      - ``action="search"`` exige ``query``.
      - ``confidence`` se presente deve ser float 0..1.

    Args:
        json_obj: objeto parseado do JSON de resposta.

    Returns:
        True se válido, False caso contrário.
    """
    if not isinstance(json_obj, dict):
        return False

    # action é obrigatório
    action = json_obj.get("action")
    if action not in VALID_ACTIONS:
        return False

    # action="show" exige book
    if action == "show":
        book = json_obj.get("book")
        if not isinstance(book, str) or not book.strip():
            return False

    # action="search" exige query
    if action == "search":
        query = json_obj.get("query")
        if not isinstance(query, str) or not query.strip():
            return False

    # confidence se presente deve ser 0..1
    confidence = json_obj.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            return False
        if not (0.0 <= float(confidence) <= 1.0):
            return False

    return True
