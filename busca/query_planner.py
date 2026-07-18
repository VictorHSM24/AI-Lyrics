"""Query planning — transforma uma intenção em um plano de busca estruturado.

Responsabilidade:
  - Receber um Intent (com optional enrichment do LLM) e produzir um
    QueryPlan imutável com keywords, termos de boost, livros sugeridos, etc.
  - Remover stopwords do PT-BR para focar em termos relevantes.
  - Gerar variações de query (OR, subsets de keywords) para múltiplas
    estratégias de busca.

Limites explícitos:
  - Não faz busca.
  - Não chama Searcher.
  - Não chama LLM.
  - Não modifica Intent.

Design:
  - QueryPlan é um DTO imutável (frozen dataclass).
  - QueryPlanner é stateless — pode ser instanciado uma vez.
  - Stopwords são centralizadas em _PT_STOPWORDS.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from busca.knowledge_enricher import KnowledgeMatch
    from core.types import Intent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stopwords PT-BR (artigos, preposições, conjunções, pronomes)
# ---------------------------------------------------------------------------

_PT_STOPWORDS: frozenset[str] = frozenset({
    # artigos
    "a", "o", "as", "os", "um", "uma", "uns", "umas",
    # preposições
    "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas",
    "por", "para", "pelo", "pela", "pelos", "pelas", "com", "sem",
    "apos", "após", "ate", "até", "entre", "sobre", "sob",
    # conjunções
    "e", "ou", "mas", "que", "se", "como", "quando", "onde", "porque",
    "embora", "ainda", "porem", "porém", "entao", "então",
    # pronomes
    "ele", "ela", "eles", "elas", "meu", "minha", "teu", "tua",
    "seu", "sua", "nosso", "nossa", "este", "esta", "esse", "essa",
    "aquele", "aquela", "isto", "isso", "aquilo",
    "quem", "cujos", "cujas", "quaisquer", "alguem", "alguém",
    "ninguem", "ninguém", "cada",
    # verbos auxiliares comuns
    "e", "ser", "esta", "estao", "tem", "tem", "ha", "ha",
    # outros
    "nao", "não", "sim", "ja", "já", "mais", "menos", "muito",
    "pouco", "tudo", "nada", "alguem", "alguém", "ninguem", "ninguém",
    "todo", "toda", "todos", "todas", "outro", "outra", "outros", "outras",
    "qual", "quais", "cujo", "cuja",
})


# ---------------------------------------------------------------------------
# QueryPlan DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QueryPlan:
    """Plano de busca estruturado, derivado de um Intent.

    Todos os campos são opcionais — nenhum dado é inventado.
    Se o LLM não forneceu enrichment, apenas original_query e
    normalized_query são preenchidos.

    Atributos:
        original_query: query original do Intent (ou texto do usuário).
        normalized_query: query normalizada (lowercase, sem diacritics).
        keywords: termos relevantes extraídos (sem stopwords).
        negative_keywords: termos a excluir da busca.
        people: personagens mencionados (ex.: "Jesus", "Pedro").
        places: lugares mencionados.
        events: eventos mencionados (ex.: "pesca milagrosa").
        themes: temas mencionados (ex.: "fé", "amor").
        suggested_books: livros bíblicos sugeridos pelo LLM.
        preferred_versions: versões preferidas para esta busca.
        search_modes: modos de busca a executar
            ("or", "keyword_subset", "book_filter", "fuzzy").
        boost_terms: termos que devem receber boost no ranking.
        filters: filtros adicionais (ex.: {"book_ids": [43, 45]}).
        confidence: confiança do plano (0.0 a 1.0).
    """

    original_query: str
    normalized_query: str
    keywords: tuple[str, ...] = ()
    negative_keywords: tuple[str, ...] = ()
    people: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    suggested_books: tuple[str, ...] = ()
    preferred_versions: tuple[str, ...] = ()
    search_modes: tuple[str, ...] = ("or", "keyword_subset", "fuzzy")
    boost_terms: tuple[str, ...] = ()
    filters: dict[str, list] = field(default_factory=dict)
    confidence: float = 0.5
    # --- Campos do grafo de conhecimento (FASE 7.5) ---
    # Estes campos existem para preparar futuras fases (Context Memory,
    # Concept Recommendation, Graph Traversal). NÃO são usados pelo
    # Searcher para alterar ranking ou expandir consultas.
    entity_id: str = ""
    entity_type: str = ""
    related: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Normaliza texto: lowercase, sem diacritics, whitespace único."""
    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


def _extract_keywords(text: str) -> list[str]:
    """Extrai keywords removendo stopwords."""
    normalized = _normalize(text)
    tokens = normalized.split()
    return [t for t in tokens if t and t not in _PT_STOPWORDS and len(t) > 1]


# ---------------------------------------------------------------------------
# QueryPlanner
# ---------------------------------------------------------------------------


class QueryPlanner:
    """Transforma um Intent em um QueryPlan estruturado.

    Fluxo:
        1. Extrair query do Intent (intent.query ou intent.raw).
        2. Normalizar query.
        3. Extrair keywords (remover stopwords).
        4. Se Intent tem enrichment (do LLM), usar keywords/themes/books
           fornecidos pelo LLM.
        5. Construir QueryPlan imutável.

    Example:
        >>> planner = QueryPlanner()
        >>> plan = planner.plan(intent)
        >>> print(plan.keywords)
        ('fe', 'certeza', 'coisas', 'esperam')
    """

    def __init__(self, enable_semantic: bool = False) -> None:
        """Inicializa o QueryPlanner.

        Args:
            enable_semantic: se True, adiciona "semantic" aos search_modes
                dos planos gerados. Deve ser True apenas quando
                EmbeddingSearcher está disponível e carregado.
        """
        self._enable_semantic = enable_semantic

    def plan(
        self,
        intent: Intent,
        knowledge: KnowledgeMatch | None = None,
    ) -> QueryPlan:
        """Constrói um QueryPlan a partir de um Intent.

        Args:
            intent: Intent com action="search" (query preenchida).
                Pode conter enrichment dict com campos do LLM:
                keywords, tema, evento, personagens, livros_sugeridos,
                sinonimos, conceitos.
            knowledge: KnowledgeMatch opcional do KnowledgeEnricher.
                Se fornecido, seus dados têm PRIORIDADE sobre o LLM
                enrichment e a extração base.
                Prioridade: Conhecimento estruturado > LLM > extração simples.

        Returns:
            QueryPlan imutável.
        """
        original = intent.query or intent.raw or ""
        normalized = _normalize(original)

        # Extrair keywords da query
        base_keywords = _extract_keywords(original)

        # Se o LLM forneceu enrichment, usar esses dados
        enrichment = getattr(intent, "enrichment", None) or {}

        # --- Knowledge Match (PRIORIDADE MÁXIMA) ---
        # Se KnowledgeEnricher identificou um conceito, seus dados
        # têm prioridade sobre o LLM e a extração base.
        kb_keywords: list[str] = []
        kb_boost_terms: list[str] = []
        kb_books: list[str] = []
        kb_people: list[str] = []
        kb_places: list[str] = []
        kb_events: list[str] = []
        kb_themes: list[str] = []
        kb_confidence = 0.0
        kb_entity_id = ""
        kb_entity_type = ""
        kb_related: list[str] = []
        if knowledge is not None and knowledge.is_found:
            kb_keywords = list(knowledge.keywords)
            kb_boost_terms = list(knowledge.boost_terms)
            kb_books = list(knowledge.books)
            kb_people = list(knowledge.characters)
            kb_places = list(knowledge.places)
            kb_events = list(knowledge.events)
            kb_themes = list(knowledge.themes)
            kb_confidence = knowledge.confidence
            # --- Campos do grafo (FASE 7.5) ---
            kb_entity_id = knowledge.entity_id
            kb_entity_type = (
                knowledge.entity_type.value
                if hasattr(knowledge.entity_type, "value")
                else str(knowledge.entity_type)
            )
            kb_related = list(knowledge.related)

        # --- LLM enrichment ---
        llm_keywords = self._parse_list(enrichment.get("keywords"))
        synonyms = self._parse_list(enrichment.get("sinonimos"))
        concepts = self._parse_list(enrichment.get("conceitos"))
        llm_boost_terms = self._merge_unique(synonyms, concepts)
        llm_people = self._parse_list(enrichment.get("personagens"))
        llm_places = self._parse_list(enrichment.get("lugares"))
        llm_events = self._parse_list(enrichment.get("evento"))
        llm_themes = self._parse_list(enrichment.get("tema"))
        llm_books = self._parse_list(enrichment.get("livros_sugeridos"))
        preferred_versions = self._parse_list(enrichment.get("versoes_preferidas"))
        negative_keywords = self._parse_list(enrichment.get("negative_keywords"))

        # --- Merge com prioridade: Knowledge > LLM > base ---
        # Keywords: KB keywords primeiro, depois LLM, depois base
        # (keywords são normalizadas para lowercase pelo _merge_unique)
        if kb_keywords:
            keywords = self._merge_unique(kb_keywords, llm_keywords, base_keywords)
        elif llm_keywords:
            keywords = self._merge_unique(llm_keywords, base_keywords)
        else:
            keywords = base_keywords

        # Boost terms: KB boost primeiro, depois LLM
        # (boost_terms são normalizadas para lowercase pelo _merge_unique)
        boost_terms = self._merge_unique(kb_boost_terms, llm_boost_terms)

        # People, events, themes, books: preservar capitalização original
        # do LLM quando não há knowledge match (compatibilidade).
        # Quando há knowledge match, KB tem prioridade (normalizado lowercase).
        if kb_people:
            people = self._merge_unique(kb_people, llm_people)
        else:
            people = llm_people

        # Places: KB primeiro, depois LLM (KB agora tem places — FASE 7.5)
        if kb_places:
            places = self._merge_unique(kb_places, llm_places)
        else:
            places = llm_places

        if kb_events:
            events = self._merge_unique(kb_events, llm_events)
        else:
            events = llm_events

        if kb_themes:
            themes = self._merge_unique(kb_themes, llm_themes)
        else:
            themes = llm_themes

        if kb_books:
            suggested_books = self._merge_unique(kb_books, llm_books)
        else:
            suggested_books = llm_books

        # Search modes: determinar com base nos dados disponíveis
        search_modes: list[str] = ["or", "keyword_subset", "fuzzy"]
        if suggested_books:
            search_modes.append("book_filter")
        if self._enable_semantic:
            search_modes.append("semantic")

        # Filters: book_ids se suggested_books contém nomes resolúveis
        filters: dict[str, list] = {}
        if suggested_books:
            # Apenas armazenar nomes — resolução para IDs acontece no Searcher
            filters["suggested_book_names"] = list(suggested_books)

        # Adicionar chapters do KnowledgeMatch aos filters (se disponíveis)
        if knowledge is not None and knowledge.is_found and knowledge.chapters:
            filters["suggested_chapters"] = list(knowledge.chapters)

        # Confidence: KnowledgeMatch > LLM enrichment > intent
        if kb_confidence > 0:
            confidence = kb_confidence
        else:
            confidence = float(enrichment.get("plan_confidence", intent.confidence))

        return QueryPlan(
            original_query=original,
            normalized_query=normalized,
            keywords=tuple(keywords),
            negative_keywords=tuple(negative_keywords),
            people=tuple(people),
            places=tuple(places),
            events=tuple(events),
            themes=tuple(themes),
            suggested_books=tuple(suggested_books),
            preferred_versions=tuple(preferred_versions),
            search_modes=tuple(search_modes),
            boost_terms=tuple(boost_terms),
            filters=filters,
            confidence=confidence,
            # --- Campos do grafo (FASE 7.5) ---
            # Passados para futuras fases. NÃO usados pelo Searcher.
            entity_id=kb_entity_id,
            entity_type=kb_entity_type,
            related=tuple(kb_related),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_list(value: object) -> list[str]:
        """Parse de valor que pode ser list, str, ou None → list[str]."""
        if value is None:
            return []
        if isinstance(value, str):
            # String única → lista com um elemento
            return [value.strip()] if value.strip() else []
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if v and str(v).strip()]
        return []

    @staticmethod
    def _merge_unique(*lists: list[str]) -> list[str]:
        """Merge listas removendo duplicatas, preservando ordem."""
        seen: set[str] = set()
        result: list[str] = []
        for lst in lists:
            for item in lst:
                normalized = _normalize(item)
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    result.append(normalized)
        return result
