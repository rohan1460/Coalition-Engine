"""Health + dependency-status route."""
import logging

from fastapi import APIRouter

from app.config import settings

router = APIRouter(tags=["system"])

logger = logging.getLogger("api.health")


def _neo4j_status() -> dict:
    """Best-effort Neo4j reachability (never raises)."""
    try:
        from app.matching.graph import get_graph
        reachable = get_graph().connect()
    except Exception as exc:  # never let a health check crash
        return {"reachable": False, "error": str(exc)}
    return {"reachable": reachable,
            "note": None if reachable else "graph down — vector fallback in use"}


def _razorpay_status() -> dict:
    real = settings.USE_REAL_RAZORPAY and settings.RAZORPAY_KEY_ID.startswith(
        "rzp_test_"
    ) and settings.RAZORPAY_KEY_ID != "rzp_test_placeholder"
    return {
        "configured": bool(
            settings.RAZORPAY_KEY_ID
            and settings.RAZORPAY_KEY_ID != "rzp_test_placeholder"
        ),
        "test_mode": settings.RAZORPAY_KEY_ID.startswith("rzp_test_"),
        "live_orders": real,  # real Razorpay Orders API in use
        "route_mode": "live" if settings.ROUTE_ENABLED else "simulated",
        "note": (
            "real Razorpay test orders"
            if real
            else "mock payment client (set USE_REAL_RAZORPAY=1 with test keys)"
        ),
    }


@router.get("/health")
def health() -> dict:
    """Service liveness plus dependency status (Neo4j, Razorpay)."""
    deps = {"neo4j": _neo4j_status(), "razorpay": _razorpay_status()}
    # The service itself is up regardless — dependencies are degradable.
    return {"status": "ok", "dependencies": deps}
