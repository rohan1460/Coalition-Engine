"""Deterministic money math for a bundle proposal.

=====================================================================
DESIGN DECISION — an LLM must NEVER compute money.
=====================================================================
Every rupee in a proposal is computed here, in plain deterministic Python:
each merchant's own-product concession, the resulting Route split, and the
final customer price. LLMs are non-deterministic and can hallucinate numbers
that silently violate a margin floor or fail to reconcile — unacceptable for
a financial transaction that must be bounded, auditable, and repeatable.

The agents' LLM-ish "judgment" is confined to *strategy* (how aggressive to
be, what to say). The instant a number is involved, it flows through this
module and is validated. The customer-facing offer copy is the only place a
real LLM is used — and it is purely descriptive, never authoritative.

Each side's discount is set INDEPENDENTLY against its own product's price —
never as a shared blended percentage split by some other formula. That's the
whole point: an anchor product's 1.8% and a companion product's 35.7% are two
different, independently-bounded numbers, not one number divided up.
"""
from dataclasses import dataclass


@dataclass
class Proposal:
    """A fully-reconciled bundle proposal. All amounts in whole INR."""

    discount_pct: float            # BLENDED bundle discount (weighted by price)
    discount_pct_a: float          # A's own discount % on ITS OWN product
    discount_pct_b: float          # B's own discount % on ITS OWN product
    discount_amount_inr: int
    a_concession_inr: int          # INR merchant A gives up
    b_concession_inr: int          # INR merchant B gives up
    merchant_a_amount_inr: int     # what A receives via Route
    merchant_b_amount_inr: int     # what B receives via Route
    bundle_price_inr: int          # what the customer pays


def compute_split(
    price_a_inr: int,
    price_b_inr: int,
    discount_pct_a: float,
    discount_pct_b: float,
) -> Proposal:
    """Compute a reconciled proposal from each side's OWN discount %.

    Each percentage is applied only to that side's own product price — there
    is no shared "blended discount" input to divide up; the blend is a
    downstream, weighted-average OUTPUT of the two independent decisions.
    Negative inputs are clamped to 0 (a "discount" can't be negative).
    """
    a_conc = round(price_a_inr * max(0.0, discount_pct_a) / 100)
    b_conc = round(price_b_inr * max(0.0, discount_pct_b) / 100)

    merchant_a_amount = price_a_inr - a_conc
    merchant_b_amount = price_b_inr - b_conc
    bundle_price = merchant_a_amount + merchant_b_amount

    total_price = price_a_inr + price_b_inr
    discount_amount = a_conc + b_conc
    blended_pct = (discount_amount / total_price * 100) if total_price > 0 else 0.0

    # Re-derive the displayed per-side percentages from the ACTUAL rounded
    # rupee amounts, so what's shown always reconciles exactly with the money.
    pct_a = (a_conc / price_a_inr * 100) if price_a_inr > 0 else 0.0
    pct_b = (b_conc / price_b_inr * 100) if price_b_inr > 0 else 0.0

    return Proposal(
        discount_pct=round(blended_pct, 2),
        discount_pct_a=round(pct_a, 2),
        discount_pct_b=round(pct_b, 2),
        discount_amount_inr=discount_amount,
        a_concession_inr=a_conc,
        b_concession_inr=b_conc,
        merchant_a_amount_inr=merchant_a_amount,
        merchant_b_amount_inr=merchant_b_amount,
        bundle_price_inr=bundle_price,
    )
