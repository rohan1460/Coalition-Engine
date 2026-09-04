"""BundleOffer schema — the negotiated cross-merchant offer.

This is the artifact produced by the two merchant agents' negotiation and
shown to the customer at checkout. It carries both the money math (bounded and
explainable) and the rationale required by the audit trail.
"""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class BundleStatus(str, Enum):
    PROPOSED = "proposed"          # created by matching, pre-negotiation
    NEGOTIATING = "negotiating"    # agents exchanging offers
    AGREED = "agreed"              # agents converged, within guardrails
    REJECTED = "rejected"          # no deal (guardrail breach / max rounds)
    CONFIRMED = "confirmed"        # customer passed OTP / human gate
    SETTLED = "settled"            # Route transfers released
    FAILED = "failed"             # saga aborted / compensated


class BundleOffer(BaseModel):
    bundle_id: str = Field(..., description="Unique offer identifier.")

    # The two products being bundled (one per merchant).
    product_a_id: str
    product_b_id: str
    merchant_a_id: str
    merchant_b_id: str

    # Why these two were paired (semantic similarity from the matching engine).
    affinity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Cosine similarity of the two products."
    )

    # Money math (whole INR). Enforced consistent by the validator below.
    original_total_inr: int = Field(..., ge=0, description="Sum of both prices.")
    discount_pct: float = Field(
        ..., ge=0.0, le=100.0,
        description="BLENDED bundle discount off the total (weighted by price).",
    )
    # Per-merchant discount %, shown separately because the blended figure
    # alone misleads: on an anchor+companion pair, each side discounts by a
    # very different amount (e.g. anchor 1.8% vs companion 35.7%).
    merchant_a_discount_pct: float = Field(
        ..., ge=0.0, le=100.0, description="A's discount on its OWN product %."
    )
    merchant_b_discount_pct: float = Field(
        ..., ge=0.0, le=100.0, description="B's discount on its OWN product %."
    )
    bundle_price_inr: int = Field(
        ..., ge=0, description="Final price the customer pays."
    )

    # Margin split of the discounted revenue across the two merchants.
    merchant_a_amount_inr: int = Field(..., ge=0)
    merchant_b_amount_inr: int = Field(..., ge=0)

    # Explainability / audit: human-readable justification for the deal and the
    # split, produced by the negotiating agents.
    rationale: str = Field(
        default="", description="Why this bundle and this split were agreed."
    )

    status: BundleStatus = BundleStatus.PROPOSED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _check_money_consistency(self) -> "BundleOffer":
        """Guardrail: the merchant split must equal what the customer pays.

        A cross-merchant payment split that doesn't reconcile is a safety bug,
        so we reject it at the schema boundary rather than at settlement time.
        """
        split_total = self.merchant_a_amount_inr + self.merchant_b_amount_inr
        if split_total != self.bundle_price_inr:
            raise ValueError(
                f"Merchant split {split_total} != bundle price "
                f"{self.bundle_price_inr}; splits must reconcile exactly."
            )
        return self
