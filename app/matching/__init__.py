"""Semantic cross-merchant matching."""
from app.matching.engine import (
    CompanionMatch,
    SemanticMatcher,
    find_companion_products,
    get_matcher,
)
from app.matching.graph import GraphMatcher, GraphUnavailable, get_graph
from app.matching.resolver import CompanionFinder, find_companions, get_finder

__all__ = [
    # vector engine
    "SemanticMatcher",
    "CompanionMatch",
    "find_companion_products",
    "get_matcher",
    # graph layer
    "GraphMatcher",
    "GraphUnavailable",
    "get_graph",
    # resolver (graph-first, vector fallback)
    "CompanionFinder",
    "find_companions",
    "get_finder",
]
