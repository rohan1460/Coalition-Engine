"""Application configuration loaded from environment variables.

TEST MODE ONLY. Never put live Razorpay keys here.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Razorpay (test mode)
    RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")

    # Neo4j affinity graph
    NEO4J_URI: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER: str = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD: str = os.getenv("NEO4J_PASSWORD", "")

    # Anthropic (used ONLY for generating customer-facing offer copy).
    # Optional: if unset, the system falls back to deterministic copy.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # When true, checkout creates REAL Razorpay test-mode Orders (real order_
    # ids). Falls back to the mock client automatically if keys are missing.
    USE_REAL_RAZORPAY: bool = os.getenv("USE_REAL_RAZORPAY", "false").lower() in (
        "1", "true", "yes",
    )
    # Route transfers require the Route feature to be enabled on the merchant
    # account (needs KYC/activation). Until then, the split is simulated over a
    # real order. Flip to true once Route is activated to get real transfers.
    ROUTE_ENABLED: bool = os.getenv("ROUTE_ENABLED", "false").lower() in (
        "1", "true", "yes",
    )
    # Route linked-account ids (acc_...) — required for REAL transfers.
    RAZORPAY_ACC_A: str = os.getenv("RAZORPAY_ACC_A", "")
    RAZORPAY_ACC_B: str = os.getenv("RAZORPAY_ACC_B", "")
    # Webhook signing secret (Dashboard > Settings > Webhooks).
    RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    # Payment safety bounds.
    # Hard per-transaction ceiling (whole INR) — no bundle above this settles.
    MAX_TRANSACTION_INR: int = int(os.getenv("MAX_TRANSACTION_INR", "200000"))
    # How long an unconfirmed offer stays valid before it expires (seconds).
    OFFER_CONFIRMATION_TTL_SECONDS: int = int(
        os.getenv("OFFER_CONFIRMATION_TTL_SECONDS", "300")
    )


settings = Settings()
