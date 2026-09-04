"""Bounded machine-to-machine negotiation between two merchant agents.

The engine runs a strictly bounded, alternating offer/counter-offer loop:

  * Merchant A's agent proposes on odd rounds, B's on even rounds.
  * Both sides' own-product discounts climb toward their OWN economics-derived
    ceiling in lockstep as rounds progress (see economics.py) — never past it.
  * A deal is struck the moment a proposal clears BOTH agents' hard ceilings
    (per-SKU margin floors) AND the stricter side's viability bar (the
    minimum blended discount that makes the coalition worth running).
  * The loop is hard-capped (default 5 rounds). If even both sides at full
    ceiling can't clear the viability bar, the negotiation FAILS cleanly and
    NO offer is produced. We never fabricate a fallback deal.

Every round — proposal and decision — is written to the audit trail with the
round number, the acting agent, the exact numbers, and the reasoning WHY.
"""
import logging
from dataclasses import asdict, dataclass
from uuid import uuid4

from app.agents.agent import MerchantAgent, NegotiationContext
from app.agents.copy import generate_offer_copy
from app.agents.money import Proposal
from app.audit import AuditLogger, EventType
from app.models import BundleOffer, BundleStatus, Product

logger = logging.getLogger("agents.negotiation")

DEFAULT_MAX_ROUNDS = 5


@dataclass
class NegotiationResult:
    negotiation_id: str
    status: BundleStatus            # AGREED or REJECTED
    reason: str
    rounds_used: int
    bundle: BundleOffer | None = None
    offer_copy: str | None = None   # customer-facing, LLM-generated (or fallback)


class NegotiationEngine:
    def __init__(
        self,
        agent_a: MerchantAgent,
        agent_b: MerchantAgent,
        audit: AuditLogger,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ):
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.agent_a = agent_a
        self.agent_b = agent_b
        self.audit = audit
        self.max_rounds = max_rounds

    def _progress(self, round_no: int) -> float:
        """How far BOTH sides have moved toward their ceilings by this round.

        Global (not per-agent-turn): round 1 is everyone's opening, the final
        round is everyone at full ceiling — regardless of who's proposing that
        round. This is what lets convergence hinge purely on whether the
        ceilings, once both fully extended, can clear the viability bar.
        """
        if self.max_rounds == 1:
            return 1.0
        return (round_no - 1) / (self.max_rounds - 1)

    def negotiate(
        self,
        ctx: NegotiationContext,
        product_a: Product,
        product_b: Product,
    ) -> NegotiationResult:
        nid = ctx.negotiation_id
        cid = ctx.correlation_id
        self.audit.log(
            correlation_id=cid,
            event_type=EventType.NEGOTIATION_STARTED,
            actor="engine",
            reasoning=(
                f"Bundling {product_a.name} (Rs.{ctx.price_a_inr}, "
                f"{ctx.sku_a.role} role, margin {ctx.sku_a.margin_pct:.1f}%, "
                f"ceiling {ctx.sku_a.discount_ceiling_pct:.1f}%) + "
                f"{product_b.name} (Rs.{ctx.price_b_inr}, {ctx.sku_b.role} role, "
                f"margin {ctx.sku_b.margin_pct:.1f}%, ceiling "
                f"{ctx.sku_b.discount_ceiling_pct:.1f}%); affinity "
                f"{ctx.affinity_score:.3f}. Max {self.max_rounds} rounds."
            ),
            inputs={
                "negotiation_id": nid,
                "product_a": ctx.product_a_id,
                "product_b": ctx.product_b_id,
                "total_inr": ctx.total_inr,
                "affinity_score": ctx.affinity_score,
                "max_rounds": self.max_rounds,
                "sku_a": asdict(ctx.sku_a),
                "sku_b": asdict(ctx.sku_b),
                "min_viable_a_pct": self.agent_a.policy.min_viable_discount_pct,
                "min_viable_b_pct": self.agent_b.policy.min_viable_discount_pct,
                "stance_a": self.agent_a.policy.stance.value,
                "stance_b": self.agent_b.policy.stance.value,
            },
        )

        for round_no in range(1, self.max_rounds + 1):
            a_is_proposer = round_no % 2 == 1
            proposer = self.agent_a if a_is_proposer else self.agent_b
            responder = self.agent_b if a_is_proposer else self.agent_a
            level = self._progress(round_no)

            proposal, propose_reason = proposer.propose(
                ctx, is_a=a_is_proposer, level=level
            )
            self.audit.log(
                correlation_id=cid,
                event_type=EventType.NEGOTIATION_ROUND,
                actor=proposer.merchant_id,
                reasoning=propose_reason,
                inputs={"round": round_no, "role": "proposer"},
                decision={"action": "propose", **asdict(proposal)},
            )

            accepted, decide_reason = responder.evaluate(
                ctx, proposal, is_a=not a_is_proposer,
                counterpart_min_viable_pct=proposer.policy.min_viable_discount_pct,
            )
            self.audit.log(
                correlation_id=cid,
                event_type=EventType.NEGOTIATION_ROUND,
                actor=responder.merchant_id,
                reasoning=decide_reason,
                inputs={"round": round_no, "role": "responder"},
                decision={"action": "accept" if accepted else "counter",
                          "accepted": accepted},
            )

            if accepted:
                return self._finalize(
                    ctx, proposal, product_a, product_b, round_no,
                    propose_reason, decide_reason,
                )

        # Hard cap reached — even both sides at full ceiling didn't clear the
        # stricter side's viability bar. Genuine walk-away, not a stall.
        reason = (
            f"No proposal cleared both merchants' bounds within "
            f"{self.max_rounds} rounds — even at full ceilings "
            f"({ctx.sku_a.discount_ceiling_pct:.1f}% / "
            f"{ctx.sku_b.discount_ceiling_pct:.1f}%), the blended discount "
            f"couldn't reach the viability bar this coalition needs. Walking away. "
            f"No offer produced."
        )
        self.audit.log(
            correlation_id=cid,
            event_type=EventType.NEGOTIATION_FAILED,
            actor="engine",
            reasoning=reason,
            decision={"rounds_used": self.max_rounds, "offer": None},
        )
        return NegotiationResult(
            negotiation_id=nid,
            status=BundleStatus.REJECTED,
            reason=reason,
            rounds_used=self.max_rounds,
        )

    def _finalize(
        self,
        ctx: NegotiationContext,
        proposal: Proposal,
        product_a: Product,
        product_b: Product,
        round_no: int,
        propose_reason: str,
        decide_reason: str,
    ) -> NegotiationResult:
        rationale = (
            f"Agreed in round {round_no}. {propose_reason} || {decide_reason}"
        )
        bundle = BundleOffer(
            bundle_id=ctx.negotiation_id,
            product_a_id=ctx.product_a_id,
            product_b_id=ctx.product_b_id,
            merchant_a_id=ctx.merchant_a_id,
            merchant_b_id=ctx.merchant_b_id,
            affinity_score=ctx.affinity_score,
            original_total_inr=ctx.total_inr,
            discount_pct=proposal.discount_pct,
            merchant_a_discount_pct=proposal.discount_pct_a,
            merchant_b_discount_pct=proposal.discount_pct_b,
            bundle_price_inr=proposal.bundle_price_inr,
            merchant_a_amount_inr=proposal.merchant_a_amount_inr,
            merchant_b_amount_inr=proposal.merchant_b_amount_inr,
            rationale=rationale,
            status=BundleStatus.AGREED,
        )

        # LLM used ONLY here — descriptive copy over an already-final offer.
        offer_copy = generate_offer_copy(proposal, product_a, product_b)

        self.audit.log(
            correlation_id=ctx.correlation_id,
            event_type=EventType.OFFER_PRESENTED,
            actor="engine",
            reasoning=(
                f"Deal in round {round_no}: {product_a.name} at "
                f"{proposal.discount_pct_a:.1f}% off, {product_b.name} at "
                f"{proposal.discount_pct_b:.1f}% off; blended "
                f"{proposal.discount_pct:.2f}% -> customer pays "
                f"Rs.{proposal.bundle_price_inr}; Route split "
                f"A:Rs.{proposal.merchant_a_amount_inr} / "
                f"B:Rs.{proposal.merchant_b_amount_inr}."
            ),
            inputs={"round": round_no, "bundle_id": bundle.bundle_id},
            decision={
                "offer_copy": offer_copy,
                **asdict(proposal),
            },
        )

        return NegotiationResult(
            negotiation_id=ctx.negotiation_id,
            status=BundleStatus.AGREED,
            reason=f"Converged in {round_no} round(s).",
            rounds_used=round_no,
            bundle=bundle,
            offer_copy=offer_copy,
        )


def new_negotiation_id() -> str:
    return f"neg_{uuid4().hex[:12]}"
