"""Companion resolution with graph-first, vector-fallback strategy.

This is the single entrypoint the rest of the app should use to find companion
products. It prefers the Neo4j graph (which supports multi-hop coalitions) and
falls back to the in-memory vector matcher when the graph is unavailable.

The fallback is explicit and loud:
  * Before querying, availability is checked; if down, we log a warning and use
    vectors.
  * If the graph drops *mid-query*, ``GraphUnavailable`` is caught (only that
    signal) and we fall back — with a warning.
  * Any other error is a real bug and is left to propagate.
"""
import logging

from app.audit import AuditLogger, EventType
from app.matching.engine import CompanionMatch, SemanticMatcher, get_matcher
from app.matching.graph import GraphMatcher, GraphUnavailable, get_graph

logger = logging.getLogger("matching.resolver")


class CompanionFinder:
    def __init__(
        self,
        graph: GraphMatcher | None = None,
        vector: SemanticMatcher | None = None,
    ):
        self._graph = graph or get_graph()
        self._vector = vector or get_matcher()

    def find(
        self,
        product_id: str,
        top_k: int = 3,
        max_hops: int = 1,
        prefer_graph: bool = True,
        audit: AuditLogger | None = None,
        correlation_id: str | None = None,
    ) -> list[CompanionMatch]:
        matches: list[CompanionMatch] = []
        used_source = "vector"

        if prefer_graph:
            if self._graph.connect():
                try:
                    matches = self._graph.find_companions(
                        product_id, top_k=top_k, max_hops=max_hops
                    )
                    used_source = "graph"
                except GraphUnavailable as exc:
                    logger.warning(
                        "Graph dropped mid-query (%s). Falling back to "
                        "in-memory vector matching.",
                        exc,
                    )
            else:
                logger.warning(
                    "Graph layer unavailable. Using in-memory vector matching "
                    "(single-hop only)."
                )
            if not matches and max_hops > 1:
                logger.warning(
                    "Requested max_hops=%d but vector fallback is single-hop; "
                    "returning direct companions only.",
                    max_hops,
                )
            # Graph returned nothing (e.g. product not in the graph yet) —
            # fall back to vector rather than giving up.
            if used_source == "graph" and not matches:
                logger.warning(
                    "Graph returned no companions for '%s'; falling back to "
                    "vector matching.", product_id,
                )
                used_source = "vector"

        # Run vector scoring when it's the selection source, and also whenever
        # auditing — so the raw AFFINITY_SCORED event is always recorded, even
        # if the graph produced the final selection. Embeddings are cached, so
        # the extra scoring pass is cheap.
        if used_source != "graph":
            matches = self._vector.find_companion_products(
                product_id, top_k=top_k,
                audit=audit, correlation_id=correlation_id,
            )
        elif audit is not None and correlation_id is not None:
            self._vector.find_companion_products(
                product_id, top_k=top_k,
                audit=audit, correlation_id=correlation_id,
            )

        if audit is not None and correlation_id is not None:
            audit.log(
                correlation_id=correlation_id,
                event_type=EventType.MATCHING_PERFORMED,
                actor="matching_resolver",
                reasoning=(
                    f"Selected {len(matches)} companion(s) for '{product_id}' "
                    f"via {used_source} matching"
                    + ("" if matches else " — none cleared the threshold.")
                ),
                inputs={
                    "product_id": product_id,
                    "top_k": top_k,
                    "max_hops": max_hops,
                    "source": used_source,
                },
                decision={
                    "companions": [
                        {
                            "product_id": m.product.product_id,
                            "name": m.product.name,
                            "affinity": round(m.affinity_score, 3),
                            "hops": m.hops,
                        }
                        for m in matches
                    ]
                },
            )

        return matches


_finder: CompanionFinder | None = None


def get_finder() -> CompanionFinder:
    global _finder
    if _finder is None:
        _finder = CompanionFinder()
    return _finder


def find_companions(
    product_id: str,
    top_k: int = 3,
    max_hops: int = 1,
    prefer_graph: bool = True,
    audit: AuditLogger | None = None,
    correlation_id: str | None = None,
) -> list[CompanionMatch]:
    """Resolve companions, graph-first with vector fallback."""
    return get_finder().find(
        product_id, top_k=top_k, max_hops=max_hops, prefer_graph=prefer_graph,
        audit=audit, correlation_id=correlation_id,
    )
