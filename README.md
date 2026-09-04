# Coalition Engine

### A Multi-Agent Cross-Merchant Coalition System — built for the Razorpay AI Buildathon

> D2C brands burn money acquiring customers. A customer buying a laptop from
> Merchant A is a *great* customer for Merchant B's bag store — but there's no
> automated, real-time way for two independent merchants to team up and
> cross-sell. Coalition Engine is that missing layer: two merchants' AI agents
> **negotiate a bundle themselves**, a semantic engine finds the right pairing,
> Razorpay Route splits one payment across both merchants, and a saga
> orchestrator makes sure nothing ever goes wrong silently.

> **TEST MODE ONLY.** Every rupee in this project is fake. No real money moves,
> ever — the entire system runs on Razorpay test-mode credentials.

---

## Why this exists

Independent merchants selling complementary, non-competing products (laptops
↔ bags, shoes ↔ socks) have no automated way to discover each other, agree on
a joint discount, or split a single customer payment fairly. Coalition Engine
answers three questions, end to end, with a real payment provider in the loop:

1. **Who should team up?** — semantic matching, not keyword search.
2. **What deal is fair to both sides?** — two AI agents negotiate it themselves,
   bounded by *each merchant's actual unit economics*, not a made-up number.
3. **What happens when something breaks?** — a saga pattern with real
   compensations, so a mid-transaction failure never leaves money stuck.

---

## What's actually in this repo

| Requirement | Where it lives | Proof |
|---|---|---|
| Semantic cross-merchant matching | `app/matching/` | MiniLM embeddings + Neo4j graph, vector fallback if the graph is down |
| Machine-to-machine negotiation | `app/agents/` | Two `MerchantAgent`s, 5-round hard cap, **deterministic** margin math |
| Razorpay Route payment split | `app/payments/`, `app/checkout/` | Real test-mode Orders API, Route transfers, signature-verified Checkout |
| Human safety gate | `app/checkout/service.py` | OTP required before any transfer is released — no exceptions |
| Complete audit trail | `app/audit/` | Every agent decision, with reasoning, persisted to SQLite |
| Failure recovery | `app/saga/` | Saga pattern, 4 steps + compensations, retry with backoff |
| UI | `frontend/` | React + Vite + Tailwind + Framer Motion, 5 screens |

---

## Architecture

```
Customer                                                    Merchant A / B
   │                                                          (Razorpay
   │  1. Browse Merchant A's store                             linked accounts)
   ▼
┌─────────────┐    2. semantic match     ┌──────────────┐
│  Storefront │ ───────────────────────► │  Matching     │
└─────────────┘   (MiniLM + Neo4j graph, │  Engine       │
                    threshold-gated:      └──────┬───────┘
                    no match ⇒ no bundle,         │ companion product
                    never a weak one)             ▼
                                          ┌──────────────────────┐
                                          │  Negotiation Engine   │
                                          │  Agent A  ⇄  Agent B  │
                                          │  (bounded by real     │
                                          │   margin economics)   │
                                          └──────────┬────────────┘
                                                     │ BundleOffer
                                                     ▼
┌─────────────┐   3. OTP confirmation   ┌──────────────────────┐
│  Checkout   │ ───────────────────────► │  Human Safety Gate    │
│  (offer     │                          │  no transfer without  │
│  shown)     │                          │  explicit OTP         │
└─────────────┘                          └──────────┬────────────┘
                                                     │ confirmed
                                                     ▼
                                          ┌──────────────────────┐
                                          │  Saga Orchestrator    │
                                          │  reserve → capture →  │
                                          │  split, with          │
                                          │  compensations on any │
                                          │  step failing         │
                                          └──────────┬────────────┘
                                                     │
                                                     ▼
                                          ┌──────────────────────┐
                                          │  Razorpay (test mode) │
                                          │  Order + Route split  │
                                          └──────────────────────┘

Every arrow above also writes to: app/audit/  (SQLite, queryable via
GET /audit/{correlation_id} — the full story of one transaction)
```

---

## The four hard requirements, and how each is met

**1. Safety & Control — bounded, explainable, human-gated.**
Every discount ceiling an agent can ever propose is derived from that
product's *real* cost price and role (`app/agents/economics.py`) — never a
made-up flat percentage. Settlement is **impossible** without an explicit
customer OTP (`app/checkout/service.py`); Razorpay's `on_hold` transfer
mechanism is the actual enforcement, not just an app-level flag.

**2. Audit trail — what each agent did and why.**
Every matching decision, every negotiation round, every payment step is one
row in `app/audit/trail.py` (SQLite), carrying `actor`, `reasoning`,
`inputs`, and `decision`. `GET /audit/{correlation_id}` replays the entire
story of one transaction, start to finish. It's also what the frontend's
**Negotiation Visualizer** and **Audit Trail** screens read from — nothing
is invented for the UI, it's the same log a judge can query directly.

**3. Failure handling — at least one graceful mode.**
Four are implemented and independently toggleable in the **Failure
Simulation** screen: inventory lock failure (degrades to the fulfillable leg,
customer isn't charged for what failed), Route transfer failure (retries
with exponential backoff, then fully compensates), payment capture failure,
and confirmation timeout. In every case, `stuck_money_inr` is asserted `== 0`
by the test suite (`tests/test_saga.py`).

**4. AI judgment — and knowing when *not* to use AI.**
Two places this is deliberate, not accidental:
- **Matching**: below the affinity threshold, the system returns *nothing* —
  it will not force a weak cross-sell just to show a bundle. Try "LumenView 27
  4K Monitor" in the storefront — it's marked **Out of stock**, not because
  inventory ran out, but because no genuine companion product exists for it.
- **Negotiation**: an LLM never computes a rupee. `app/agents/money.py` and
  `app/agents/economics.py` are pure, unit-tested arithmetic. The only LLM
  call in the entire money path is `app/agents/copy.py`, which writes the
  customer-facing marketing sentence *after* the deal is already fully
  decided — it narrates a number the rules engine produced, never invents one.

---

## Bundle economics — deterministic, margin-based, and can walk away

Every discount ceiling is derived from a product's real `price_inr` /
`cost_price_inr` and its `product_role`:

- **`anchor`** — the high-value item driving the purchase (laptops). Thin,
  competitive retail margins (~6–15%) → realistic **1–3%** discount ceiling.
- **`companion`** — the attach item riding the anchor's traffic (bags,
  accessories). Fat accessory-category margins (~40–60%) → **20–40%**
  discount ceiling.

A laptop and a bag **never** share a discount ceiling — their margins aren't
remotely comparable, so treating them the same was the bug this design fixes.
See `app/agents/economics.py` for the exact retention-fraction formula.

Because the ceilings are real, some pairings **genuinely cannot converge**:
if both sides at their absolute maximum discount still can't clear the
coalition's minimum viability bar, the negotiation fails cleanly and no offer
is shown — not a scripted demo failure, the same formula that makes most
pairings succeed. See Scenario 2 in `scripts/negotiate_demo.py` for a
pairing engineered to hit exactly this wall.

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python, FastAPI, Pydantic v2 |
| Matching | `sentence-transformers` (all-MiniLM-L6-v2), Neo4j (optional, vector fallback) |
| Payments | `razorpay` SDK, Razorpay Orders + Checkout + Route (test mode) |
| Persistence | SQLite (audit log, saga state) |
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion |
| LLM (copy only) | Anthropic `claude-opus-4-8`, with a deterministic offline fallback |

---

## Project layout

```
app/
  agents/       # MerchantAgent, negotiation engine, deterministic economics
  matching/     # semantic embedding, Neo4j graph, catalog loading
  payments/     # Razorpay client, bounds validation, human-gated settlement
  checkout/     # end-to-end orchestration: inventory, saga adapter, service
  saga/         # saga pattern: steps, compensations, retry with backoff
  audit/        # structured, persistent audit trail
  models/       # Pydantic schemas (Product, Merchant, BundleOffer)
  api/          # FastAPI routes (checkout, catalog, audit, health, webhooks)
data/           # mock merchant catalogs (real Flipkart-derived prices + margins)
frontend/       # React + Vite + Tailwind + Framer Motion UI
scripts/        # negotiate_demo, matching_sanity, load_graph, route_spike
tests/          # 38 tests across economics, negotiation, saga, payments, API
demo.py                    # scripted happy-path walkthrough (no server needed)
demo_inventory_failure.py  # scripted failure walkthrough (no server needed)
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your test credentials (optional for demo)
```

## Run — backend + frontend together

Open two terminals.

**Terminal 1 — API (port 8000):**
```bash
source .venv/bin/activate
uvicorn app.main:app --reload
```

To create **real Razorpay test-mode Orders** (real `order_...` ids), put your
`rzp_test_` keys in `.env` and start with the flag:
```bash
USE_REAL_RAZORPAY=true uvicorn app.main:app --reload
```
The Route split stays simulated over the real order until the Route feature
is activated on the account (KYC) and `ROUTE_ENABLED=true` is set. Verify a
real transaction anytime:
```bash
python -m scripts.route_spike   # prints a real order_ id from Razorpay
```

**Terminal 2 — frontend (port 5173):**
```bash
cd frontend
npm install      # first time only
npm run dev
```

Open **http://localhost:5173**. The frontend calls the API at
`http://localhost:8000` (override with `VITE_API_URL`). Interactive API docs
(Swagger) are at `http://localhost:8000/docs`.

## API surface

| Method | Path | What it does |
|---|---|---|
| `GET` | `/health` | Service + dependency status (Neo4j, Razorpay) |
| `GET` | `/catalog` | Merchant A's storefront catalog, with `has_companion` per product |
| `POST` | `/checkout/initiate` | Match → negotiate → return the bundle offer (or none) |
| `POST` | `/checkout/confirm` | Validate OTP → reserve inventory → create the Razorpay order |
| `POST` | `/checkout/pay` | Verify the Razorpay signature server-side → release the split |
| `POST` | `/checkout/simulate` | Run a full checkout with a forced failure mode (demo panel) |
| `GET` | `/audit/{correlation_id}` | The complete, ordered story of one transaction |
| `POST` | `/webhooks/razorpay` | Signature-verified server-side payment source of truth |

## Demo scripts (no server needed)

```bash
python demo.py                    # full happy path, printed stage by stage
python demo_inventory_failure.py  # Merchant B inventory fails -> graceful degrade
python -m scripts.negotiate_demo  # two real pairings: one converges, one walks away
```

## Test

```bash
pytest    # 38 tests: economics, negotiation, saga, payments, checkout API
```

---

## What's honestly still pending

- **Route transfers are simulated over a real order**, not yet live — the
  merchant account's Route feature needs KYC activation on Razorpay's side.
  The code path for real transfers (`on_hold` + `PATCH` release) is fully
  implemented and tested against the mock client; flipping `ROUTE_ENABLED=true`
  once KYC clears requires no code changes.
- **Neo4j is optional, not required** — if it's down, matching transparently
  falls back to the in-memory vector matcher with a logged warning. This is
  a deliberate resilience feature, not a workaround.
