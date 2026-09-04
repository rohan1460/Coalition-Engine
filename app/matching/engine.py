"""Semantic cross-merchant matching engine.

Embeds product catalogs with a sentence-transformer and finds companion
products *across* merchants using cosine similarity. Two deliberate design
choices matter here:

1. Same-merchant pairs are never considered — coalitions are only meaningful
   between non-competing stores.
2. A minimum affinity threshold gates every match. If nothing clears the bar we
   return NOTHING rather than surfacing a weak, misleading pairing. Knowing when
   *not* to recommend is as important as the recommendation itself.

Embeddings are cached in memory for the process lifetime and persisted to disk
(keyed by a hash of the embedding text) so restarts don't recompute them.
"""
import hashlib
import logging
import pickle
from pathlib import Path

import numpy as np

from app.audit import AuditLogger, EventType
from app.matching.catalog import DATA_DIR, load_products
from app.models import Product

logger = logging.getLogger("matching")

MODEL_NAME = "all-MiniLM-L6-v2"

# Cosine-similarity floor. MiniLM scores genuinely related-but-distinct products
# in roughly the 0.3–0.6 band; below ~0.3 pairs are essentially unrelated.
DEFAULT_MIN_AFFINITY = 0.30

CACHE_PATH = DATA_DIR / ".embedding_cache.pkl"


class CompanionMatch:
    """A ranked companion product from a different merchant.

    ``hops`` is 1 for a direct pairing and >1 when reached via a multi-hop
    coalition path in the graph. ``source`` records whether it came from the
    graph layer or the in-memory vector fallback.
    """

    def __init__(
        self,
        product: Product,
        affinity_score: float,
        hops: int = 1,
        source: str = "vector",
    ):
        self.product = product
        self.affinity_score = affinity_score
        self.hops = hops
        self.source = source

    def __repr__(self) -> str:
        return (
            f"CompanionMatch({self.product.product_id}, "
            f"score={self.affinity_score:.3f}, hops={self.hops}, "
            f"source={self.source})"
        )


class SemanticMatcher:
    def __init__(
        self,
        model_name: str = MODEL_NAME,
        min_affinity: float = DEFAULT_MIN_AFFINITY,
        cache_path: Path = CACHE_PATH,
    ):
        self.model_name = model_name
        self.min_affinity = min_affinity
        self.cache_path = cache_path

        self._model = None
        self._products: dict[str, Product] = {}
        # product_id -> L2-normalized embedding vector
        self._embeddings: dict[str, np.ndarray] = {}
        self._ready = False

    # -- lifecycle ---------------------------------------------------------

    def _load_model(self):
        if self._model is None:
            # Imported lazily so importing this module (e.g. in tests that
            # don't match) doesn't pay the model-load cost.
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model '%s'", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _load_disk_cache(self) -> dict[str, list[float]]:
        if not self.cache_path.exists():
            return {}
        try:
            with open(self.cache_path, "rb") as fh:
                blob = pickle.load(fh)
            if blob.get("model") != self.model_name:
                return {}  # model changed -> cache invalid
            return blob.get("vectors", {})
        except Exception as exc:  # corrupt cache should never be fatal
            logger.warning("Ignoring unreadable embedding cache: %s", exc)
            return {}

    def _save_disk_cache(self, vectors: dict[str, list[float]]) -> None:
        try:
            with open(self.cache_path, "wb") as fh:
                pickle.dump({"model": self.model_name, "vectors": vectors}, fh)
        except Exception as exc:
            logger.warning("Could not persist embedding cache: %s", exc)

    @staticmethod
    def _text_key(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def _ensure_ready(self) -> None:
        """Load catalog + embeddings, using cache where possible."""
        if self._ready:
            return

        self._products = load_products()
        disk_cache = self._load_disk_cache()  # text_key -> list[float]
        updated = dict(disk_cache)
        to_compute: list[tuple[str, str]] = []  # (product_id, text_key)

        # First pass: reuse cached vectors, collect misses.
        for pid, product in self._products.items():
            key = self._text_key(product.embedding_text())
            if key in disk_cache:
                self._embeddings[pid] = self._normalize(
                    np.asarray(disk_cache[key], dtype=np.float32)
                )
            else:
                to_compute.append((pid, key))

        # Second pass: batch-encode only the misses.
        if to_compute:
            model = self._load_model()
            texts = [
                self._products[pid].embedding_text() for pid, _ in to_compute
            ]
            logger.info("Computing %d new embeddings", len(texts))
            vectors = model.encode(texts, convert_to_numpy=True)
            for (pid, key), vec in zip(to_compute, vectors):
                self._embeddings[pid] = self._normalize(
                    np.asarray(vec, dtype=np.float32)
                )
                updated[key] = np.asarray(vec, dtype=np.float32).tolist()
            self._save_disk_cache(updated)
        else:
            logger.info("All %d embeddings served from cache", len(self._products))

        self._ready = True

    # -- public API --------------------------------------------------------

    def all_cross_affinities(
        self, min_affinity: float | None = None
    ) -> list[tuple[str, str, float]]:
        """Return every cross-merchant pair scoring at/above the threshold.

        Yields unordered unique pairs as ``(product_id_a, product_id_b, score)``
        — used to populate COMPLEMENTS edges in the graph.
        """
        self._ensure_ready()
        threshold = self.min_affinity if min_affinity is None else min_affinity

        ids = list(self._products)
        pairs: list[tuple[str, str, float]] = []
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if self._products[a].merchant_id == self._products[b].merchant_id:
                    continue
                score = float(np.dot(self._embeddings[a], self._embeddings[b]))
                if score >= threshold:
                    pairs.append((a, b, score))
        return pairs

    def find_companion_products(
        self,
        product_id: str,
        top_k: int = 3,
        audit: AuditLogger | None = None,
        correlation_id: str | None = None,
    ) -> list[CompanionMatch]:
        """Return up to ``top_k`` companion products from *other* merchants.

        Only cross-merchant pairs are considered. Matches below the affinity
        threshold are dropped; if none clear it, an empty list is returned and
        the reasoning is logged. When an ``audit`` logger + ``correlation_id``
        are supplied, the raw affinity scores are recorded to the audit trail.
        """
        self._ensure_ready()

        if product_id not in self._products:
            raise KeyError(f"Unknown product_id: {product_id}")

        source = self._products[product_id]
        source_vec = self._embeddings[product_id]

        # Cross-merchant candidates only — never pair a merchant with itself.
        scored: list[CompanionMatch] = []
        for cand_id, candidate in self._products.items():
            if candidate.merchant_id == source.merchant_id:
                continue
            score = float(np.dot(source_vec, self._embeddings[cand_id]))
            scored.append(CompanionMatch(candidate, score))

        scored.sort(key=lambda m: m.affinity_score, reverse=True)

        if audit is not None and correlation_id is not None:
            audit.log(
                correlation_id=correlation_id,
                event_type=EventType.AFFINITY_SCORED,
                actor="matching_engine",
                reasoning=(
                    f"Embedded '{source.name}' and scored cosine similarity "
                    f"against {len(scored)} cross-merchant products "
                    f"(threshold {self.min_affinity})."
                ),
                inputs={
                    "product_id": product_id,
                    "product_name": source.name,
                    "min_affinity": self.min_affinity,
                    "model": self.model_name,
                },
                decision={
                    "scores": [
                        {
                            "product_id": m.product.product_id,
                            "name": m.product.name,
                            "affinity": round(m.affinity_score, 3),
                        }
                        for m in scored
                    ]
                },
            )

        # Apply the AI-judgment gate.
        accepted = [m for m in scored if m.affinity_score >= self.min_affinity]

        if not accepted:
            best = scored[0] if scored else None
            logger.info(
                "No companion for '%s' (%s): best candidate scored %.3f, "
                "below threshold %.2f. Returning nothing rather than a weak "
                "match.",
                product_id,
                source.name,
                best.affinity_score if best else float("nan"),
                self.min_affinity,
            )
            return []

        top = accepted[:top_k]
        logger.info(
            "Companions for '%s' (%s): %s",
            product_id,
            source.name,
            ", ".join(
                f"{m.product.product_id}={m.affinity_score:.3f}" for m in top
            ),
        )
        return top


# Module-level singleton so embeddings are computed once per process.
_matcher: SemanticMatcher | None = None


def get_matcher() -> SemanticMatcher:
    global _matcher
    if _matcher is None:
        _matcher = SemanticMatcher()
    return _matcher


def find_companion_products(
    product_id: str, top_k: int = 3
) -> list[CompanionMatch]:
    """Module-level convenience wrapper over the shared matcher singleton."""
    return get_matcher().find_companion_products(product_id, top_k=top_k)
