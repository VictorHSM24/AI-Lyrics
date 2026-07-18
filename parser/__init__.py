"""Módulo parser determinístico.

API pública:
    Normalizer — normalizador de texto PT-BR.
    ParserBookTable — resolução de livros com confiança e prioridade.
    BookResolveResult — resultado da resolução de livro.
    Parser — parser principal de comandos bíblicos.
    load_parser_books — carrega tabela de livros de books.json.
"""

from parser.books import BookResolveResult, ParserBookTable, load_parser_books
from parser.normalizer import Normalizer
from parser.parser import Parser

__all__ = [
    "Normalizer",
    "ParserBookTable",
    "BookResolveResult",
    "Parser",
    "load_parser_books",
]
