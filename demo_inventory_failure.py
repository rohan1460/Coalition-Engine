"""FAILURE-PATH DEMO — Merchant B inventory lock fails.

Same flow as demo.py, but Merchant B's product is forced out of stock before
the customer confirms. The saga degrades gracefully: Merchant A's laptop is
still fulfilled and charged, Merchant B's leg is dropped, the customer is NOT
charged for the bag, and no money is left stuck.

Run:
    python demo_inventory_failure.py
"""
import logging

from app.audit import AuditLogger
from app.checkout import CheckoutService
from app.payments import MockPaymentClient

logging.basicConfig(level=logging.ERROR)

SOURCE_PRODUCT = "a_lap_15biz"


def hr(title: str) -> None:
    print("\n" + "=" * 74)
    print(title)
    print("=" * 74)


def main() -> None:
    audit = AuditLogger(":memory:")
    svc = CheckoutService(payment_client=MockPaymentClient(), audit=audit)

    hr("STAGE 1 — Customer starts checkout (Merchant A: laptop)")
    result = svc.initiate(SOURCE_PRODUCT)
    cid = result["correlation_id"]
    if not result.get("offer"):
        print("  No bundle offer:", result.get("reason"))
        return
    offer = result["offer"]
    companion_id = offer["product_b"]["id"]
    print(f"  correlation_id: {cid}")
    print(f"  Offer: {offer['product_a']['name']} + {offer['product_b']['name']} "
          f"@ {offer['discount_pct']:.1f}% off = Rs.{offer['bundle_price_inr']}")

    hr("INJECT FAILURE — Merchant B's product goes out of stock")
    svc._inventory.set_stock(companion_id, 0)
    print(f"  Forced stock of '{companion_id}' to 0 before confirmation.")

    hr("STAGE 5 — Customer confirms -> saga hits B inventory failure")
    settle = svc.confirm(cid, result["otp_for_demo"])
    print(f"  Saga status: {settle['status'].upper()}")
    for leg in settle["legs"]:
        print(f"    - {leg['merchant_id']}: Rs.{leg['amount_inr']} [{leg['status']}]"
              + (f"  ({leg['note']})" if leg["note"] else ""))
    print(f"  Net customer charge: Rs.{settle['net_customer_charge_inr']} "
          f"(laptop only — NOT charged for the bag)")
    print(f"  Money left in a stuck state: Rs.{settle['stuck_money_inr']}")

    hr(f"AUDIT STORY  (GET /audit/{cid})")
    for e in audit.get_story(cid):
        ts = e.timestamp.strftime("%H:%M:%S")
        print(f"  [{ts}] {e.event_type.value.upper():<22} {e.actor}")
        print(f"         {e.reasoning}")

    hr("RESULT")
    print("  Merchant B's inventory failed, but the customer still gets the laptop,")
    print("  is charged only for the laptop, and no money is stuck. Graceful. ✅")


if __name__ == "__main__":
    main()
