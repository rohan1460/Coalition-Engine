"""END-TO-END HAPPY PATH DEMO — Multi-Agent Cross-Merchant Coalition Engine.

Runs the complete flow in-process (no server needed) and prints each stage:

  1. Customer starts checkout for a laptop (Merchant A).
  2. Semantic matching finds a companion product from Merchant B.
  3. The two merchants' AI agents negotiate a bundle discount + margin split.
  4. The customer is shown the offer and confirms with an OTP (human gate).
  5. The saga reserves inventory, captures payment, and splits via Route.
  6. The full audit story is printed.

Run:
    python demo.py
"""
import logging

from app.audit import AuditLogger
from app.checkout import CheckoutService
from app.payments import MockPaymentClient

logging.basicConfig(level=logging.ERROR)  # keep output clean; audit tells the story

SOURCE_PRODUCT = "a_lap_15biz"  # 15-inch business laptop from Merchant A


def hr(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> None:
    audit = AuditLogger(":memory:")
    svc = CheckoutService(
        payment_client=MockPaymentClient(), audit=audit,
    )

    hr("STAGE 1 — Customer starts checkout (Merchant A: laptop)")
    result = svc.initiate(SOURCE_PRODUCT)
    cid = result["correlation_id"]
    print(f"  correlation_id: {cid}")
    if not result.get("offer"):
        print("  No bundle offer produced:", result.get("reason"))
        return

    offer = result["offer"]
    hr("STAGE 2 & 3 — Matching + machine-to-machine negotiation")
    print(f"  Companion found: {offer['product_b']['name']} "
          f"(affinity {offer['affinity_score']})")
    print(f"  Negotiated discount: {offer['discount_pct']:.1f}%")
    print(f"  Original total: Rs.{offer['original_total_inr']}  ->  "
          f"Bundle price: Rs.{offer['bundle_price_inr']}")
    print(f"  Route split -> A ({offer['product_a']['merchant']}): "
          f"Rs.{offer['product_a']['amount_inr']}  |  "
          f"B ({offer['product_b']['merchant']}): "
          f"Rs.{offer['product_b']['amount_inr']}")

    hr("STAGE 4 — Customer sees the offer at checkout")
    print(f"  \"{offer['copy']}\"")
    otp = result["otp_for_demo"]
    print(f"  (OTP issued to customer — human gate): {otp}")

    hr("STAGE 5 — Customer confirms with OTP -> saga executes")
    settle = svc.confirm(cid, otp)
    print(f"  Saga status: {settle['status'].upper()}")
    for leg in settle["legs"]:
        print(f"    - {leg['merchant_id']}: Rs.{leg['amount_inr']} [{leg['status']}]")
    print(f"  Net customer charge: Rs.{settle['net_customer_charge_inr']}")
    print(f"  Money left in a stuck state: Rs.{settle['stuck_money_inr']}")

    hr(f"STAGE 6 — Full audit story  (GET /audit/{cid})")
    for e in audit.get_story(cid):
        ts = e.timestamp.strftime("%H:%M:%S")
        print(f"  [{ts}] {e.event_type.value.upper():<22} {e.actor}")
        print(f"         {e.reasoning}")

    hr("RESULT")
    print("  Bundle sold, payment split across both merchants, zero stuck money,")
    print("  and every agent decision is explained in the audit trail. ✅")


if __name__ == "__main__":
    main()
