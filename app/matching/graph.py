"""Neo4j graph layer for cross-merchant coalitions.

Products are stored as ``(:Product)`` nodes and cross-merchant affinities as
``[:COMPLEMENTS {affinity}]`` relationships. Modelling the affinities as a graph
(rather than only a flat similarity matrix) lets us traverse multi-hop
coalitions later: A -> B -> C, where a laptop pulls in a bag which pulls in a
compatible accessory from a third merchant.

Resilience contract
--------------------
The graph is *optional*. Only genuine connectivity problems raise
``GraphUnavailable`` — which the resolver treats as a signal to fall back to the
in-memory vector matcher. Everything else (unknown product, malformed Cypher)
propagates as a real error. We never wrap logic in a bare ``except`` that hides
bugs.
"""
import logging

from neo4j import GraphDatabase
from neo4j.exceptions import (
    AuthError,
    ConfigurationError,
    ServiceUnavailable,
)

from app.config import settings
from app.matching.catalog import load_products
from app.matching.engine import CompanionMatch, SemanticMatcher, get_matcher
from app.models import Product

logger = logging.getLogger("matching.graph")

# Connectivity failures we treat as "graph is down" rather than "bug".
_CONNECTIVITY_ERRORS = (ServiceUnavailable, AuthError, ConfigurationError, OSError)


class GraphUnavailable(RuntimeError):
    """Raised when Neo4j cannot serve a request; a signal to fall back."""


class GraphMatcher:
    def __init__(
        self,
        uri: str = settings.NEO4J_URI,
        user: str = settings.NEO4J_USER,
        password: str = settings.NEO4J_PASSWORD,
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None
        self._available: bool | None = None  # None = not yet probed
        self._products: dict[str, Product] = {}

    # -- connectivity ------------------------------------------------------

    def connect(self) -> bool:
        """Establish (once) and verify a driver. Returns availability.

        A failure here is logged as a warning and returns False — it is never
        fatal to the caller.
        """
        if self._available is not None:
            return self._available

        try:
            driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
            driver.verify_connectivity()
        except _CONNECTIVITY_ERRORS as exc:
            logger.warning(
                "Neo4j unavailable at %s (%s: %s). Graph features disabled; "
                "falling back to in-memory vector matching.",
                self.uri,
                type(exc).__name__,
                exc,
            )
            self._driver = None
            self._available = False
            return False

        self._driver = driver
        self._available = True
        logger.info("Connected to Neo4j at %s", self.uri)
        return True

    @property
    def is_available(self) -> bool:
        return bool(self._available)

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def _catalog(self) -> dict[str, Product]:
        if not self._products:
            self._products = load_products()
        return self._products

    # -- loading -----------------------------------------------------------

    def load_catalog(self, matcher: SemanticMatcher | None = None) -> dict:
        """Load products + COMPLEMENTS edges into Neo4j.

        Affinity edge weights come from the vector matcher, so the graph and the
        fallback stay consistent. Idempotent via MERGE.
        """
        if not self.connect():
            raise GraphUnavailable("Cannot load catalog: Neo4j is unreachable.")

        matcher = matcher or get_matcher()
        products = self._catalog()
        affinities = matcher.all_cross_affinities()

        try:
            with self._driver.session() as session:
                # Schema changes can't share a transaction with writes, so the
                # constraint runs first as its own auto-commit statement.
                session.run(
                    "CREATE CONSTRAINT product_id IF NOT EXISTS "
                    "FOR (p:Product) REQUIRE p.product_id IS UNIQUE"
                )
                session.execute_write(self._write_catalog_tx, products, affinities)
        except _CONNECTIVITY_ERRORS as exc:
            self._available = False
            raise GraphUnavailable(f"Neo4j dropped during load: {exc}") from exc

        summary = {"nodes": len(products), "edges": len(affinities)}
        logger.info(
            "Loaded %d Product nodes and %d COMPLEMENTS edges into Neo4j",
            summary["nodes"],
            summary["edges"],
        )
        return summary

    @staticmethod
    def _write_catalog_tx(tx, products: dict[str, Product], affinities: list):
        for p in products.values():
            tx.run(
                """
                MERGE (p:Product {product_id: $product_id})
                SET p.merchant_id = $merchant_id,
                    p.name = $name,
                    p.category = $category,
                    p.price_inr = $price_inr,
                    p.stock_qty = $stock_qty
                """,
                product_id=p.product_id,
                merchant_id=p.merchant_id,
                name=p.name,
                category=p.category,
                price_inr=p.price_inr,
                stock_qty=p.stock_qty,
            )
        for a_id, b_id, score in affinities:
            # Undirected semantics: one MERGE'd edge per unordered pair,
            # traversable either way in Cypher (no arrow in the match).
            tx.run(
                """
                MATCH (a:Product {product_id: $a_id})
                MATCH (b:Product {product_id: $b_id})
                MERGE (a)-[r:COMPLEMENTS]-(b)
                SET r.affinity = $score
                """,
                a_id=a_id,
                b_id=b_id,
                score=score,
            )

    # -- querying ----------------------------------------------------------

    def find_companions(
        self, product_id: str, top_k: int = 3, max_hops: int = 1
    ) -> list[CompanionMatch]:
        """Traverse COMPLEMENTS to find companion products.

        With ``max_hops > 1`` this returns multi-hop coalition partners (A -> B
        -> C). The path score is the product of the edge affinities along the
        path; the best path per companion wins.
        """
        if not self.connect():
            raise GraphUnavailable("Neo4j is unreachable.")

        max_hops = int(max_hops)  # inlined into the pattern -> must be a safe int
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")

        try:
            with self._driver.session() as session:
                rows = session.execute_read(
                    self._companions_tx, product_id, top_k, max_hops
                )
        except _CONNECTIVITY_ERRORS as exc:
            self._available = False
            raise GraphUnavailable(f"Neo4j dropped mid-query: {exc}") from exc

        products = self._catalog()
        matches = [
            CompanionMatch(
                product=products[row["product_id"]],
                affinity_score=row["path_score"],
                hops=row["hops"],
                source="graph",
            )
            for row in rows
            if row["product_id"] in products
        ]
        logger.info(
            "Graph companions for '%s' (max_hops=%d): %s",
            product_id,
            max_hops,
            ", ".join(
                f"{m.product.product_id}={m.affinity_score:.3f}@{m.hops}h"
                for m in matches
            )
            or "(none)",
        )
        return matches

    @staticmethod
    def _companions_tx(tx, product_id: str, top_k: int, max_hops: int):
        # Neo4j does not allow a parameter as the variable-length upper bound,
        # so max_hops is validated as an int above and inlined here.
        cypher = f"""
        MATCH path = (src:Product {{product_id: $product_id}})
                     -[rels:COMPLEMENTS*1..{max_hops}]-(companion:Product)
        WHERE companion.product_id <> $product_id
          AND companion.merchant_id <> src.merchant_id
        WITH companion,
             reduce(s = 1.0, r IN rels | s * r.affinity) AS path_score,
             length(path) AS hops
        ORDER BY path_score DESC
        WITH companion,
             head(collect({{score: path_score, hops: hops}})) AS best
        RETURN companion.product_id AS product_id,
               best.score AS path_score,
               best.hops AS hops
        ORDER BY path_score DESC
        LIMIT $top_k
        """
        result = tx.run(
            cypher, product_id=product_id, top_k=int(top_k)
        )
        return [r.data() for r in result]


# Module-level singleton.
_graph: GraphMatcher | None = None


def get_graph() -> GraphMatcher:
    global _graph
    if _graph is None:
        _graph = GraphMatcher()
    return _graph
