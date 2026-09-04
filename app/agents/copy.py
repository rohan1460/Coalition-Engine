"""Customer-facing offer copy — the one place an LLM is genuinely useful.

Writing a natural, appealing one-line bundle pitch is a language/judgment task,
so we use Claude here. It is *descriptive only* — it never sees or influences
the money math, which is already finalized by the time this runs.

Resilience: copy is a cosmetic enhancement on top of an already-valid offer, so
if there's no API key or the call fails, we fall back to a deterministic
template and log why. A copywriting hiccup must never break a payment.
"""
import logging

from app.agents.money import Proposal
from app.config import settings
from app.models import Product

logger = logging.getLogger("agents.copy")

_SYSTEM = (
    "You are a concise e-commerce copywriter. Write ONE upbeat sentence "
    "(max 30 words) promoting a two-product bundle to a customer at checkout, "
    "highlighting the value of buying them together. "
    "Respond with ONLY the sentence — no preamble, no quotes."
)


def _fallback_copy(
    proposal: Proposal, product_a: Product, product_b: Product
) -> str:
    return (
        f"Buy {product_a.name} with {product_b.name} and save "
        f"{proposal.discount_pct:.0f}% — pay Rs.{proposal.bundle_price_inr} for "
        f"both instead of Rs.{proposal.discount_amount_inr + proposal.bundle_price_inr}."
    )


def generate_offer_copy(
    proposal: Proposal, product_a: Product, product_b: Product
) -> str:
    if not settings.ANTHROPIC_API_KEY:
        logger.info("No ANTHROPIC_API_KEY set; using deterministic offer copy.")
        return _fallback_copy(proposal, product_a, product_b)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        user_prompt = (
            f"Product A: {product_a.name} — {product_a.description}\n"
            f"Product B: {product_b.name} — {product_b.description}\n"
            f"Bundle price: Rs.{proposal.bundle_price_inr} "
            f"({proposal.discount_pct:.0f}% off)."
        )
        message = client.messages.create(
            model="claude-opus-4-8",
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = next(
            (b.text for b in message.content if b.type == "text"), ""
        ).strip()
        return text or _fallback_copy(proposal, product_a, product_b)
    except Exception as exc:  # copy is non-critical — degrade, never crash
        logger.warning(
            "LLM copy generation failed (%s); using deterministic fallback.", exc
        )
        return _fallback_copy(proposal, product_a, product_b)
