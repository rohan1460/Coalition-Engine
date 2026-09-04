"""MerchantAgent — one autonomous negotiator per merchant.

Each side's proposal moves its OWN product's discount toward its OWN
economics-derived ceiling (see economics.py) — never past it. There is no
shared "blended discount" to split; the blend is a downstream, weighted
average of two independently-bounded decisions. All numeric output goes
through money.py; the agent only decides strategy (how fast to concede
toward its ceiling) and writes the human-readable reasoning for the audit log,
citing the actual constraint driving its position.
"""
from app.agents.economics import SkuFloor, compute_sku_floor
from app.agents.money import Proposal, compute_split
from app.agents.policy import MerchantPolicy, Stance
from app.models.product import ProductRole


def _lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * max(0.0, min(1.0, t))


class NegotiationContext:
    """Immutable facts both agents reason over during one negotiation."""

    def __init__(
        self,
        negotiation_id: str,
        product_a_id: str,
        product_b_id: str,
        merchant_a_id: str,
        merchant_b_id: str,
        price_a_inr: int,
        price_b_inr: int,
        cost_a_inr: int,
        cost_b_inr: int,
        role_a: ProductRole,
        role_b: ProductRole,
        affinity_score: float,
        correlation_id: str | None = None,
    ):
        self.negotiation_id = negotiation_id
        # Session-wide id that ties matching, negotiation, payment, etc.
        # Defaults to the negotiation id when a session id isn't supplied.
        self.correlation_id = correlation_id or negotiation_id
        self.product_a_id = product_a_id
        self.product_b_id = product_b_id
        self.merchant_a_id = merchant_a_id
        self.merchant_b_id = merchant_b_id
        self.price_a_inr = price_a_inr
        self.price_b_inr = price_b_inr
        self.total_inr = price_a_inr + price_b_inr
        self.affinity_score = affinity_score

        # The entire negotiable envelope for each side, derived once from real
        # unit economics. Both agents can see both — the ceilings aren't
        # secret, they're a fact of each product's cost structure.
        self.sku_a: SkuFloor = compute_sku_floor(price_a_inr, cost_a_inr, role_a)
        self.sku_b: SkuFloor = compute_sku_floor(price_b_inr, cost_b_inr, role_b)


# Opening offer as a fraction of each side's ceiling — negotiations don't
# open at the wall on round one, they climb toward it.
_OPENING_FRACTION = 0.3


class MerchantAgent:
    def __init__(self, policy: MerchantPolicy):
        self.policy = policy

    @property
    def merchant_id(self) -> str:
        return self.policy.merchant_id

    @staticmethod
    def _sku(ctx: NegotiationContext, is_a: bool) -> SkuFloor:
        return ctx.sku_a if is_a else ctx.sku_b

    @staticmethod
    def _other_sku(ctx: NegotiationContext, is_a: bool) -> SkuFloor:
        return ctx.sku_b if is_a else ctx.sku_a

    # -- proposing / evaluating --------------------------------------------

    def propose(
        self, ctx: NegotiationContext, is_a: bool, level: float
    ) -> tuple[Proposal, str]:
        mine = self._sku(ctx, is_a)
        theirs = self._other_sku(ctx, is_a)

        my_pct = _lerp(
            mine.discount_ceiling_pct * _OPENING_FRACTION,
            mine.discount_ceiling_pct,
            level,
        )
        ask_pct = _lerp(
            theirs.discount_ceiling_pct * _OPENING_FRACTION,
            theirs.discount_ceiling_pct,
            level,
        )
        pct_a, pct_b = (my_pct, ask_pct) if is_a else (ask_pct, my_pct)
        proposal = compute_split(ctx.price_a_inr, ctx.price_b_inr, pct_a, pct_b)

        reasoning = (
            f"{self.policy.stance.value} stance, {mine.role} role: holding my own "
            f"discount at {my_pct:.1f}% — margin floor is {mine.margin_floor_pct:.1f}% "
            f"on this SKU (natural margin {mine.margin_pct:.1f}%, and I've capped "
            f"myself at a {mine.discount_ceiling_pct:.1f}% ceiling; I won't go past "
            f"that no matter what). Asking the {theirs.role} side for {ask_pct:.1f}% "
            f"(their ceiling is {theirs.discount_ceiling_pct:.1f}%). Blended so far: "
            f"{proposal.discount_pct:.2f}% -> customer would pay "
            f"Rs.{proposal.bundle_price_inr}. [round progress {level:.2f}]"
        )
        return proposal, reasoning

    def evaluate(
        self,
        ctx: NegotiationContext,
        proposal: Proposal,
        is_a: bool,
        counterpart_min_viable_pct: float,
    ) -> tuple[bool, str]:
        mine = self._sku(ctx, is_a)
        my_pct_used = proposal.discount_pct_a if is_a else proposal.discount_pct_b

        # Tolerance absorbs whole-rupee rounding noise (a discount % is
        # re-derived from the rounded concession, e.g. Rs.280 on a Rs.699 item
        # reads back as 40.06% against a 40.00% ceiling) without masking a
        # genuine breach, which would be orders of magnitude larger than this.
        ceiling_ok = my_pct_used <= mine.discount_ceiling_pct + 0.1
        # The deal only genuinely works once it clears BOTH sides' viability
        # bar — whoever happens to be evaluating this round checks for both,
        # so a lenient side can never rubber-stamp a deal the stricter side
        # would still walk away from.
        required = max(self.policy.min_viable_discount_pct, counterpart_min_viable_pct)
        viable = proposal.discount_pct >= required - 0.01

        if ceiling_ok and viable:
            return True, (
                f"ACCEPT: blended {proposal.discount_pct:.2f}% clears the "
                f"{required:.1f}% viability bar this coalition needs to be worth "
                f"running, and my own {my_pct_used:.1f}% discount stays within my "
                f"{mine.discount_ceiling_pct:.1f}% ceiling (margin floor "
                f"{mine.margin_floor_pct:.1f}% on this SKU)."
            )

        reasons = []
        if not ceiling_ok:
            reasons.append(
                f"the {my_pct_used:.1f}% discount on my side would breach my "
                f"{mine.discount_ceiling_pct:.1f}% ceiling — margin floor is "
                f"{mine.margin_floor_pct:.1f}% on this SKU, non-negotiable"
            )
        if not viable:
            reasons.append(
                f"blended {proposal.discount_pct:.2f}% is below the {required:.1f}% "
                f"viability bar this coalition needs — not worth running even at "
                f"full ceilings on both sides"
            )
        return False, "REJECT: " + "; ".join(reasons)
