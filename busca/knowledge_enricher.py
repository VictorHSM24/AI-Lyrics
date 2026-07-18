"""KnowledgeEnricher — enriquece Intent com conhecimento bíblico estruturado.

Responsabilidade:
  - Receber um Intent (após LLM) e identificar conceitos bíblicos conhecidos.
  - Consultar uma base de conhecimento local (JSON) — não depende de LLM,
    embeddings, ou banco de dados.
  - Retornar um KnowledgeMatch imutável com livros, capítulos, keywords,
    boost_terms, personagens, eventos, temas, tipo de entidade, relacionados.
  - Atuar ENTRE o LLM e o QueryPlanner no pipeline.

Fluxo:
    STT → Parser → LLM → KnowledgeEnricher → QueryPlanner → Searcher

Limites explícitos:
  - Não faz busca.
  - Não chama Searcher.
  - Não chama LLM.
  - Não consulta banco de dados.
  - Não consulta embeddings.
  - Não modifica Intent.
  - Não navega pelo grafo (related é retornado mas não expandido).

Design:
  - KnowledgeMatch é um DTO imutável (frozen dataclass).
  - KnowledgeEnricher carrega a base de conhecimento do disco (JSON).
  - Matching é feito por normalização de texto + comparação de aliases.
  - A base de conhecimento é editável sem recompilar código.
  - Múltiplos matches são possíveis (retorna lista ordenada por confiança).
  - A base suporta o formato de grafo (id, type, related) mas também
    o formato anterior (concept sem id/type) para compatibilidade.

Extensibilidade futura:
  - Para adicionar conceitos: editar config/knowledge_base.json.
  - Para trocar o formato: criar nova implementação de KnowledgeBase.
  - Para Feedback Learning: KnowledgeEnricher pode receber pesos de feedback.
  - Para Context Memory: KnowledgeEnricher pode consultar contexto do sermão.
  - Para Graph Traversal: related permite navegar pelo grafo (futuro).
  - Para Concept Recommendation: related + entity_type permitem sugestões.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from busca.biblical_entity import BiblicalEntity, BiblicalEntityType
from busca.bible_reference import BibleReference, parse_references

if TYPE_CHECKING:
    from core.types import Intent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# KnowledgeMatch DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeMatch:
    """Resultado de enriquecimento por conhecimento bíblico estruturado.

    Todos os campos são opcionais — nenhum dado é inventado.
    Se nenhum conceito foi identificado, apenas `concept` é vazio e
    `confidence` é 0.0.

    Atributos:
        concept: nome do conceito identificado (ex.: "filho pródigo").
            Vazio se nenhum conceito foi encontrado.
        aliases: apelidos/sinônimos que matcharam a consulta.
        books: livros bíblicos sugeridos (ex.: ["Lucas"]).
        chapters: capítulos sugeridos (ex.: [15]).
        characters: personagens mencionados (ex.: ["pai", "filho"]).
        events: eventos mencionados (ex.: ["parábola do filho pródigo"]).
        themes: temas mencionados (ex.: ["arrependimento", "perdão"]).
        keywords: termos relevantes para busca FTS.
        boost_terms: termos que devem receber boost no ranking.
        confidence: confiança do match (0.0 a 1.0).
        matched_alias: qual alias/conceito foi matchado na query.
        entity_id: identificador único da entidade no grafo (ex.: "filho_prodigo").
        entity_type: tipo da entidade (BiblicalEntityType). OUTRO se não definido.
        related: IDs de entidades relacionadas (arestas do grafo).
        references: referências bíblicas estruturadas como BibleReference.
        places: lugares mencionados (ex.: ["Betel", "Sicar"]).
    """

    concept: str = ""
    aliases: tuple[str, ...] = ()
    books: tuple[str, ...] = ()
    chapters: tuple[int, ...] = ()
    characters: tuple[str, ...] = ()
    events: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    boost_terms: tuple[str, ...] = ()
    confidence: float = 0.0
    matched_alias: str = ""
    # --- Campos do grafo de conhecimento (FASE 7.5) ---
    entity_id: str = ""
    entity_type: BiblicalEntityType = BiblicalEntityType.OUTRO
    related: tuple[str, ...] = ()
    # --- FASE 7.6: references são BibleReference (não strings) ---
    # --- FASE 7.7: renomeado de reference_ids → references ---
    references: tuple[BibleReference, ...] = ()
    places: tuple[str, ...] = ()

    @property
    def is_found(self) -> bool:
        """True se um conceito foi identificado."""
        return bool(self.concept) and self.confidence > 0.0


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Normaliza texto: lowercase, sem diacritics, whitespace único."""
    nfkd = unicodedata.normalize("NFKD", text)
    without_diacritics = "".join(c for c in nfkd if not unicodedata.combining(c))
    collapsed = re.sub(r"\s+", " ", without_diacritics)
    return collapsed.strip().lower()


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------


@dataclass
class _ConceptEntry:
    """Entrada individual da base de conhecimento (mutable, interna).

    Suporta tanto o formato antigo (concept sem id/type) quanto o novo
    formato de grafo (id, type, related, places, references).
    """

    concept: str
    aliases: list[str]
    books: list[str]
    chapters: list[int]
    characters: list[str]
    events: list[str]
    themes: list[str]
    keywords: list[str]
    boost_terms: list[str]
    confidence: float
    # --- Campos do grafo de conhecimento (FASE 7.5) ---
    entity_id: str = ""
    entity_type: BiblicalEntityType = BiblicalEntityType.OUTRO
    related: list[str] = field(default_factory=list)
    references: list[BibleReference] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    # Normalized aliases for fast matching
    _normalized_aliases: list[str] = field(default_factory=list)
    _normalized_concept: str = ""

    def __post_init__(self) -> None:
        self._normalized_concept = _normalize(self.concept)
        self._normalized_aliases = [_normalize(a) for a in self.aliases]
        # O conceito em si também é um alias
        if self._normalized_concept and self._normalized_concept not in self._normalized_aliases:
            self._normalized_aliases.append(self._normalized_concept)
        # Se entity_id não foi fornecido, gerar a partir do conceito
        if not self.entity_id and self.concept:
            self.entity_id = _normalize(self.concept).replace(" ", "_")

    def to_entity(self) -> BiblicalEntity:
        """Converte para BiblicalEntity (DTO imutável)."""
        return BiblicalEntity(
            id=self.entity_id,
            name=self.concept,
            type=self.entity_type,
            aliases=tuple(self.aliases),
            books=tuple(self.books),
            chapters=tuple(self.chapters),
            characters=tuple(self.characters),
            places=tuple(self.places),
            events=tuple(self.events),
            themes=tuple(self.themes),
            keywords=tuple(self.keywords),
            boost_terms=tuple(self.boost_terms),
            related=tuple(self.related),
            references=tuple(self.references),
            metadata=dict(self.metadata),
            confidence=self.confidence,
        )


class KnowledgeBase:
    """Carrega e gerencia a base de conhecimento bíblico (JSON).

    A base é carregada do disco uma vez e mantida em memória.
    Para adicionar/corrigir conceitos, basta editar o arquivo JSON —
    não é necessário recompilar código.

    Args:
        path: caminho para o arquivo JSON da base de conhecimento.

    Example:
        >>> base = KnowledgeBase("config/knowledge_base.json")
        >>> entry = base.find("filho pródigo")
        >>> print(entry.concept)  # "filho pródigo"
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._entries: list[_ConceptEntry] = []
        self._load()

    def _load(self) -> None:
        """Carrega a base de conhecimento do disco.

        Suporta tanto o formato antigo (concept sem id/type/related) quanto
        o novo formato de grafo (id, type, related, places, references).
        Campos novos são opcionais — entradas antigas continuam funcionando.
        """
        if not os.path.isfile(self._path):
            logger.warning(
                "KnowledgeBase: file not found at %s — knowledge enrichment disabled",
                self._path,
            )
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)

            concepts = data.get("concepts", [])
            for c in concepts:
                # name é o novo campo; concept é compatibilidade
                name = c.get("name", c.get("concept", ""))
                entry = _ConceptEntry(
                    concept=name,
                    aliases=c.get("aliases", []),
                    books=c.get("books", []),
                    chapters=c.get("chapters", []),
                    characters=c.get("characters", []),
                    events=c.get("events", []),
                    themes=c.get("themes", []),
                    keywords=c.get("keywords", []),
                    boost_terms=c.get("boost_terms", []),
                    confidence=float(c.get("confidence", 0.9)),
                    # --- Campos do grafo (FASE 7.5) ---
                    entity_id=c.get("id", ""),
                    entity_type=BiblicalEntityType.from_string(c.get("type", "")),
                    related=c.get("related", []),
                    # references: strings → BibleReference (FASE 7.6)
                    references=parse_references(c.get("references", [])),
                    places=c.get("places", []),
                    metadata=c.get("metadata", {}),
                )
                self._entries.append(entry)

            logger.info(
                "KnowledgeBase: loaded %d concepts from %s",
                len(self._entries),
                self._path,
            )
        except Exception as e:
            logger.warning("KnowledgeBase: failed to load %s: %s", self._path, e)

    @property
    def size(self) -> int:
        """Número de conceitos cadastrados."""
        return len(self._entries)

    @property
    def is_loaded(self) -> bool:
        """True se a base foi carregada com sucesso."""
        return len(self._entries) > 0

    def find(self, query: str) -> _ConceptEntry | None:
        """Encontra o conceito que melhor matcha a query.

        Matching:
            1. Normaliza a query.
            2. Para cada conceito, verifica se algum alias aparece como
               substring da query (ou vice-versa).
            3. Retorna o conceito com o alias mais longo que matcha
               (mais específico = melhor).

        Args:
            query: texto da consulta do usuário.

        Returns:
            _ConceptEntry do melhor match, ou None se nenhum conceito matcha.
        """
        if not self._entries:
            return None

        normalized_query = _normalize(query)
        if not normalized_query:
            return None

        best_entry: _ConceptEntry | None = None
        best_alias_len = 0
        best_alias = ""

        for entry in self._entries:
            for alias_norm in entry._normalized_aliases:
                if not alias_norm:
                    continue
                # Match: alias aparece na query OU query aparece no alias
                # (para queries curtas como "Babel" → "torre de Babel")
                if alias_norm in normalized_query or normalized_query == alias_norm:
                    # Preferir alias mais longo (mais específico)
                    if len(alias_norm) > best_alias_len:
                        best_alias_len = len(alias_norm)
                        best_entry = entry
                        # Encontrar o alias original que matchou
                        best_alias = alias_norm

        if best_entry is not None:
            logger.info(
                "KnowledgeBase: matched concept=%r alias=%r (query=%r)",
                best_entry.concept,
                best_alias,
                query[:80],
            )

        return best_entry

    def find_all(self, query: str) -> list[_ConceptEntry]:
        """Encontra todos os conceitos que matcham a query.

        Útil para consultas que podem referenciar múltiplos conceitos.

        Args:
            query: texto da consulta do usuário.

        Returns:
            Lista de _ConceptEntry que matcham, ordenada por
            comprimento do alias (mais específico primeiro).
        """
        if not self._entries:
            return []

        normalized_query = _normalize(query)
        if not normalized_query:
            return []

        matches: list[tuple[int, _ConceptEntry]] = []
        for entry in self._entries:
            for alias_norm in entry._normalized_aliases:
                if not alias_norm:
                    continue
                if alias_norm in normalized_query or normalized_query == alias_norm:
                    matches.append((len(alias_norm), entry))
                    break  # um match por conceito é suficiente

        # Ordenar por alias mais longo (mais específico) primeiro
        matches.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in matches]

    def get_entity(self, entity_id: str) -> BiblicalEntity | None:
        """Recupera uma entidade pelo seu ID.

        Útil para Graph Traversal futuro (navegar por related).

        Args:
            entity_id: ID da entidade (ex.: "filho_prodigo").

        Returns:
            BiblicalEntity correspondente, ou None se não encontrada.
        """
        for entry in self._entries:
            if entry.entity_id == entity_id:
                return entry.to_entity()
        return None

    def get_related_entities(self, entity_id: str) -> list[BiblicalEntity]:
        """Recupera entidades relacionadas a uma entidade.

        Útil para Concept Recommendation e Graph Traversal futuro.
        Não é usado pelo KnowledgeEnricher.enrich() — apenas para futuras
        fases que precisem navegar pelo grafo.

        Args:
            entity_id: ID da entidade (ex.: "filho_prodigo").

        Returns:
            Lista de BiblicalEntity relacionadas. Lista vazia se a entidade
            não existe ou não tem relacionados.
        """
        entity = self.get_entity(entity_id)
        if entity is None or not entity.related:
            return []
        result: list[BiblicalEntity] = []
        for rid in entity.related:
            related = self.get_entity(rid)
            if related is not None:
                result.append(related)
        return result

    def all_entities(self) -> list[BiblicalEntity]:
        """Retorna todas as entidades cadastradas.

        Útil para Continuous Evaluation e métricas.

        Returns:
            Lista de todas as BiblicalEntity.
        """
        return [entry.to_entity() for entry in self._entries]

    @property
    def total_relationships(self) -> int:
        """Número total de arestas no grafo (soma de related)."""
        return sum(len(entry.related) for entry in self._entries)


# ---------------------------------------------------------------------------
# KnowledgeEnricher
# ---------------------------------------------------------------------------


class KnowledgeEnricher:
    """Enriquece um Intent com conhecimento bíblico estruturado.

    Atua ENTRE o LLM e o QueryPlanner no pipeline:
        LLM → KnowledgeEnricher → QueryPlanner

    Não substitui o LLM — complementa-o com conhecimento estruturado
    que não depende de inferência linguística.

    Args:
        knowledge_base: instância de KnowledgeBase carregada.
            Se None, o enricher é desativado (no-op).

    Example:
        >>> base = KnowledgeBase("config/knowledge_base.json")
        >>> enricher = KnowledgeEnricher(base)
        >>> match = enricher.enrich(intent)
        >>> if match.is_found:
        ...     print(match.concept, match.books, match.chapters)
    """

    def __init__(self, knowledge_base: KnowledgeBase | None) -> None:
        self._base = knowledge_base

    @property
    def is_available(self) -> bool:
        """True se a base de conhecimento está carregada."""
        return self._base is not None and self._base.is_loaded

    def enrich(self, intent: Intent) -> KnowledgeMatch:
        """Enriquece um Intent com conhecimento bíblico estruturado.

        Args:
            intent: Intent após processamento do LLM.

        Returns:
            KnowledgeMatch imutável. Se nenhum conceito foi identificado,
            retorna KnowledgeMatch vazio (is_found=False).
        """
        if not self.is_available:
            return KnowledgeMatch()

        # Usar a query do Intent (ou raw como fallback)
        query = intent.query or intent.raw or ""
        if not query:
            return KnowledgeMatch()

        entry = self._base.find(query)
        if entry is None:
            return KnowledgeMatch()

        # Encontrar qual alias original matchou
        normalized_query = _normalize(query)
        matched_alias = ""
        for alias in entry.aliases:
            if _normalize(alias) in normalized_query:
                matched_alias = alias
                break
        if not matched_alias:
            matched_alias = entry.concept

        return KnowledgeMatch(
            concept=entry.concept,
            aliases=tuple(entry.aliases),
            books=tuple(entry.books),
            chapters=tuple(entry.chapters),
            characters=tuple(entry.characters),
            events=tuple(entry.events),
            themes=tuple(entry.themes),
            keywords=tuple(entry.keywords),
            boost_terms=tuple(entry.boost_terms),
            confidence=entry.confidence,
            matched_alias=matched_alias,
            # --- Campos do grafo (FASE 7.5) ---
            entity_id=entry.entity_id,
            entity_type=entry.entity_type,
            related=tuple(entry.related),
            references=tuple(entry.references),
            places=tuple(entry.places),
        )

    def enrich_all(self, intent: Intent) -> list[KnowledgeMatch]:
        """Enriquece um Intent com todos os conceitos que matcham.

        Útil para consultas que podem referenciar múltiplos conceitos
        (ex.: "Jesus e Pedro andando sobre as águas").

        Args:
            intent: Intent após processamento do LLM.

        Returns:
            Lista de KnowledgeMatch ordenada por confiança decrescente.
            Lista vazia se nenhum conceito foi identificado.
        """
        if not self.is_available:
            return []

        query = intent.query or intent.raw or ""
        if not query:
            return []

        entries = self._base.find_all(query)
        if not entries:
            return []

        normalized_query = _normalize(query)
        matches: list[KnowledgeMatch] = []
        for entry in entries:
            matched_alias = ""
            for alias in entry.aliases:
                if _normalize(alias) in normalized_query:
                    matched_alias = alias
                    break
            if not matched_alias:
                matched_alias = entry.concept

            matches.append(KnowledgeMatch(
                concept=entry.concept,
                aliases=tuple(entry.aliases),
                books=tuple(entry.books),
                chapters=tuple(entry.chapters),
                characters=tuple(entry.characters),
                events=tuple(entry.events),
                themes=tuple(entry.themes),
                keywords=tuple(entry.keywords),
                boost_terms=tuple(entry.boost_terms),
                confidence=entry.confidence,
                matched_alias=matched_alias,
                # --- Campos do grafo (FASE 7.5) ---
                entity_id=entry.entity_id,
                entity_type=entry.entity_type,
                related=tuple(entry.related),
                references=tuple(entry.references),
                places=tuple(entry.places),
            ))

        return matches
