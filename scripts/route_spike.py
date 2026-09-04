"""Real Razorpay TEST-MODE Route spike — genuine API calls, real ids.

This is a standalone verification tool. It talks to the real Razorpay test API
using the credentials in .env and prints back real, dashboard-verifiable ids
(order_..., trf_..., acc_...). Nothing here is mocked.

Prereqs in .env (TEST MODE keys — from Razorpay Dashboard > Settings > API Keys
while the top-left toggle is on "Test Mode"):
    RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxx
    RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

Optional — two existing linked accounts (fastest: create them in the dashboard
under Route > Accounts, they activate immediately). Put their acc_ ids here:
    RAZORPAY_ACC_A=acc_xxxxxxxxxxxxxx
    RAZORPAY_ACC_B=acc_xxxxxxxxxxxxxx

If the acc ids are absent, pass --create-accounts to have this script create two
linked accounts via the API (best-effort; test mode).

Run:
    python -m scripts.route_spike
    python -m scripts.route_spike --create-accounts
"""
import os
import sys
import json

import razorpay
import requests

from app.config import settings

API = "https://api.razorpay.com"


def _auth():
    kid = settings.RAZORPAY_KEY_ID
    ksec = settings.RAZORPAY_KEY_SECRET
    if not kid or kid == "rzp_test_placeholder" or not kid.startswith("rzp_test_"):
        sys.exit(
            "✗ Set REAL test keys in .env first (RAZORPAY_KEY_ID=rzp_test_..., "
            "RAZORPAY_KEY_SECRET=...). Current key looks like a placeholder."
        )
    return kid, ksec


def create_linked_account(kid, ksec, label, email) -> str:
    """Create a Route linked account via /v2/accounts (test mode)."""
    body = {
        "email": email,
        "phone": "9000090000",
        "type": "route",
        "legal_business_name": label,
        "business_type": "partnership",
        "contact_name": label,
        "profile": {
            "category": "ecommerce",
            "subcategory": "electronics",
            "addresses": {
                "registered": {
                    "street1": "1 Test Street",
                    "street2": "MG Road",
                    "city": "Bengaluru",
                    "state": "Karnataka",
                    "postal_code": "560001",
                    "country": "IN",
                }
            },
        },
    }
    r = requests.post(
        f"{API}/v2/accounts", auth=(kid, ksec),
        headers={"Content-Type": "application/json"}, data=json.dumps(body),
    )
    if r.status_code >= 400:
        raise RuntimeError(f"account create failed ({r.status_code}): {r.text}")
    acc = r.json()
    print(f"  ✓ created linked account for {label}: {acc['id']}")
    return acc["id"]


def main() -> None:
    kid, ksec = _auth()
    client = razorpay.Client(auth=(kid, ksec))
    print(f"Using key: {kid}  (TEST MODE)\n")

    # ---- 1. Plain order: proves we are really hitting Razorpay ----
    print("STEP 1 — create a plain order (connectivity proof)")
    order = client.order.create({
        "amount": 50000, "currency": "INR", "receipt": "spike_connectivity",
    })
    print(f"  ✓ REAL order id: {order['id']}  status={order['status']}\n")

    # ---- 2. Resolve linked accounts ----
    acc_a = os.getenv("RAZORPAY_ACC_A")
    acc_b = os.getenv("RAZORPAY_ACC_B")
    if "--create-accounts" in sys.argv and not (acc_a and acc_b):
        print("STEP 2 — creating two linked accounts via API")
        acc_a = create_linked_account(kid, ksec, "LumenTech Test", "lumentech.test@example.com")
        acc_b = create_linked_account(kid, ksec, "CarryCraft Test", "carrycraft.test@example.com")
        print("  (add these to .env as RAZORPAY_ACC_A / RAZORPAY_ACC_B to reuse)\n")

    if not (acc_a and acc_b):
        print("STEP 2 — SKIPPED: no linked accounts.")
        print("  Create two under Dashboard > Route > Accounts (they activate")
        print("  immediately in test mode), set RAZORPAY_ACC_A / RAZORPAY_ACC_B in")
        print("  .env, then re-run. Connectivity is already proven above.")
        return

    # ---- 3. Order WITH transfers (Route), transfers held ----
    print("STEP 3 — create an order with on-hold Route transfers")
    route_order = client.order.create({
        "amount": 100000, "currency": "INR", "receipt": "spike_route",
        "transfers": [
            {"account": acc_a, "amount": 60000, "currency": "INR", "on_hold": 1},
            {"account": acc_b, "amount": 40000, "currency": "INR", "on_hold": 1},
        ],
    })
    print(f"  ✓ REAL order id: {route_order['id']}")
    transfers = route_order.get("transfers") or []
    if not transfers:
        # fallback: fetch transfers for the order
        resp = requests.get(
            f"{API}/v1/orders/{route_order['id']}/transfers", auth=(kid, ksec)
        )
        transfers = resp.json().get("items", [])
    for t in transfers:
        print(f"    → REAL transfer id: {t['id']}  to {t['recipient']}  "
              f"amount={t['amount']}  on_hold={t.get('on_hold')}")

    # ---- 4. Release one hold (settlement gate) ----
    if transfers:
        tid = transfers[0]["id"]
        print(f"\nSTEP 4 — release hold on {tid}")
        released = client.transfer.edit(tid, {"on_hold": 0})
        print(f"  ✓ on_hold now: {released.get('on_hold')}  "
              f"status={released.get('status')}")

    print("\nDone. Verify these ids in Dashboard > Transactions / Route.")


if __name__ == "__main__":
    main()
