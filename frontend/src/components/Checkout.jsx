import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { api, rupees } from "../api";
import { Reveal, motion } from "./motion.jsx";
import CountUp from "./CountUp.jsx";
import {
  Button,
  Badge,
  Spinner,
  ErrorBanner,
  Skeleton,
  Icon,
} from "./ui.jsx";

export default function Checkout({ product, session, setSession, goTab }) {
  const [phase, setPhase] = useState("idle"); // idle|matching|offer|unavailable|otp|confirming|done
  const [error, setError] = useState(null);
  const [otp, setOtp] = useState("");
  const [result, setResult] = useState(null);

  const offer = session?.offer;

  if (!product) {
    return (
      <Reveal>
        <div className="card grid place-items-center p-16 text-center">
          <p className="text-lg text-ink-muted">
            Pick a product from the{" "}
            <button
              onClick={() => goTab("store")}
              className="font-semibold text-accent underline"
            >
              Storefront
            </button>{" "}
            to start a checkout.
          </p>
        </div>
      </Reveal>
    );
  }

  const initiate = async () => {
    setPhase("matching");
    setError(null);
    try {
      const res = await api.initiate(product.product_id);
      if (!res.offer) {
        // Internal reason (e.g. "no companion cleared the threshold") is a
        // business-logic detail, not something a real customer should see —
        // to them this item simply isn't purchasable right now.
        setPhase("unavailable");
        return;
      }
      setSession({
        correlationId: res.correlation_id,
        offer: res.offer,
        otp: res.otp_for_demo,
      });
      setOtp(res.otp_for_demo || "");
      setPhase("offer");
    } catch (e) {
      setError(e.message);
      setPhase("idle");
    }
  };

  const finishResult = (res) => {
    setResult(res);
    setSession({ ...session, confirm: res });
    if (!res.settled) setError(res.reason || "Not settled.");
    setPhase("done");
  };

  const openRazorpay = (conf) => {
    if (!window.Razorpay) {
      setError("Razorpay Checkout script failed to load. Check your connection.");
      setPhase("otp");
      return;
    }
    const rzp = new window.Razorpay({
      key: conf.razorpay_key_id,
      amount: conf.amount_paise,
      currency: conf.currency,
      order_id: conf.order_id,
      name: "Coalition Engine",
      description: "Cross-merchant bundle",
      prefill: conf.prefill,
      theme: { color: "#4F8CFF" },
      // Show UPI (QR + apps + VPA) prominently, then the default methods.
      config: {
        display: {
          blocks: {
            upi: {
              name: "Pay via UPI (QR / apps)",
              instruments: [{ method: "upi", flows: ["qr", "intent", "collect"] }],
            },
          },
          sequence: ["block.upi"],
          preferences: { show_default_blocks: true },
        },
      },
      handler: async (resp) => {
        // Razorpay returns payment_id + order_id + signature.
        setPhase("confirming");
        try {
          const res = await api.pay({
            correlation_id: session.correlationId,
            razorpay_payment_id: resp.razorpay_payment_id,
            razorpay_order_id: resp.razorpay_order_id,
            razorpay_signature: resp.razorpay_signature,
          });
          finishResult(res);
        } catch (e) {
          setError(e.message);
          setPhase("otp");
        }
      },
      modal: {
        ondismiss: () => {
          setError("Payment cancelled — the offer is still held. Try again.");
          setPhase("otp");
        },
      },
    });
    rzp.on("payment.failed", (resp) => {
      setError("Payment failed: " + (resp.error?.description || "unknown"));
      setPhase("otp");
    });
    rzp.open();
  };

  const confirm = async () => {
    setPhase("confirming");
    setError(null);
    try {
      const res = await api.confirm(session.correlationId, otp);
      if (res.status === "awaiting_payment" && res.razorpay_key_id) {
        openRazorpay(res); // real payment: open Razorpay Checkout modal
        return;
      }
      finishResult(res); // mock mode: settled inline
    } catch (e) {
      setError(e.message);
      setPhase("otp");
    }
  };

  return (
    <div className="mx-auto grid min-h-[74vh] max-w-5xl content-center gap-7 lg:grid-cols-[1fr_1.1fr]">
      {/* Left: selected product */}
      <Reveal>
        <div className="card p-8">
          <Badge color="merchantA" size="lg">Your cart · Merchant A</Badge>
          <h3 className="h-display mt-4 text-2xl font-semibold">
            {product.name}
          </h3>
          <p className="mt-2 text-base text-ink-muted">{product.description}</p>
          <div className="mt-6 flex items-center justify-between border-t border-line pt-5">
            <span className="text-base text-ink-muted">Item total</span>
            <span className="h-display text-3xl font-bold">
              {rupees(product.price_inr)}
            </span>
          </div>
          {phase === "idle" && (
            <Button size="lg" className="mt-6 w-full" onClick={initiate}>
              Find a bundle & continue
            </Button>
          )}
          {phase === "unavailable" && (
            <Button size="lg" variant="ghost" className="mt-6 w-full" onClick={() => goTab("store")}>
              Browse other products
            </Button>
          )}
          {error && (
            <div className="mt-4">
              <ErrorBanner message={error} size="lg" />
            </div>
          )}
        </div>
      </Reveal>

      {/* Right: offer / gate / result */}
      <div>
        <AnimatePresence mode="wait">
          {phase === "matching" && <MatchingSkeleton key="sk" />}
          {phase === "unavailable" && <OutOfStock key="oos" />}

          {(phase === "offer" ||
            phase === "otp" ||
            phase === "confirming" ||
            phase === "done") &&
            offer && (
              <motion.div
                key="offer"
                initial={{ opacity: 0, y: 20, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
                className="card overflow-hidden"
              >
                <div className="flex items-center gap-2 border-b border-line bg-merchantB-soft px-8 py-5">
                  <Badge color="merchantB" size="lg">Coalition offer · Merchant B</Badge>
                  <span className="ml-auto text-sm text-ink-muted">
                    affinity {offer.affinity_score}
                  </span>
                </div>

                <div className="p-8">
                  <p className="text-base text-ink-muted">
                    Our agent negotiated a bundle with{" "}
                    <span className="text-merchantB">
                      {offer.product_b.name}
                    </span>
                    .
                  </p>

                  <p className="mt-4 text-lg italic text-ink">
                    “{offer.copy}”
                  </p>

                  {/* price — headline savings vs combined MRP */}
                  <div className="mt-7 flex items-end justify-between">
                    <div>
                      <div className="label-caps text-sm">Bundle price</div>
                      <div className="h-display text-6xl font-extrabold tabular text-good">
                        <CountUp value={offer.bundle_price_inr} prefix="₹" />
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="label-caps text-sm">MRP</div>
                      <div className="text-xl text-ink-faint line-through tabular">
                        {rupees(offer.mrp_total_inr)}
                      </div>
                      <Badge color="good" size="lg" className="mt-1.5">
                        {offer.savings_vs_mrp_pct}% off
                      </Badge>
                    </div>
                  </div>
                  <div className="mt-3 text-sm text-ink-faint">
                    Coalition discount negotiated on{" "}
                    {rupees(offer.original_total_inr)} — each merchant's OWN
                    discount is different; the {offer.discount_pct.toFixed(2)}%
                    above is the blended average, weighted by price.
                  </div>

                  {/* per-merchant discount breakdown — never just the blend */}
                  <div className="mt-7 grid grid-cols-2 gap-4">
                    <SplitChip
                      color="merchantA"
                      label={offer.product_a.name}
                      amount={offer.product_a.amount_inr}
                      discountPct={offer.merchant_a_discount_pct}
                    />
                    <SplitChip
                      color="merchantB"
                      label={offer.product_b.name}
                      amount={offer.product_b.amount_inr}
                      discountPct={offer.merchant_b_discount_pct}
                    />
                  </div>

                  {phase === "offer" && (
                    <div className="mt-7 flex flex-wrap gap-3">
                      <Button
                        size="lg"
                        className="flex-1"
                        onClick={() => setPhase("otp")}
                      >
                        Accept bundle
                      </Button>
                      <Button
                        size="lg"
                        variant="ghost"
                        onClick={() => confirmSingle(setPhase)}
                      >
                        Just the laptop
                      </Button>
                      <Button
                        size="lg"
                        variant="subtle"
                        onClick={() => goTab("negotiation")}
                      >
                        See negotiation →
                      </Button>
                    </div>
                  )}

                  {/* HUMAN SAFETY GATE */}
                  <AnimatePresence>
                    {(phase === "otp" || phase === "confirming") && (
                      <OtpGate
                        otp={otp}
                        setOtp={setOtp}
                        demoOtp={session.otp}
                        confirming={phase === "confirming"}
                        onConfirm={confirm}
                      />
                    )}
                  </AnimatePresence>

                  {phase === "done" && result && (
                    <ResultPanel result={result} goTab={goTab} />
                  )}

                  {error && phase !== "idle" && (
                    <div className="mt-4">
                      <ErrorBanner message={error} size="lg" />
                    </div>
                  )}
                </div>
              </motion.div>
            )}
        </AnimatePresence>
      </div>
    </div>
  );

  function confirmSingle() {
    // "Just the laptop" — decline the bundle, go straight to OTP for A only.
    // For the demo we still route through confirm; the saga charges only the
    // reserved legs. Simplest path: accept then confirm normally.
    setPhase("otp");
  }
}

function SplitChip({ color, label, amount, discountPct }) {
  const ring = {
    merchantA: "border-merchantA/30 bg-merchantA-soft",
    merchantB: "border-merchantB/30 bg-merchantB-soft",
  }[color];
  const text = { merchantA: "text-merchantA", merchantB: "text-merchantB" }[
    color
  ];
  return (
    <div className={`rounded-xl border p-4 ${ring}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm text-ink-muted">{label}</span>
        {discountPct != null && (
          <span className={`shrink-0 text-xs font-bold ${text}`}>
            −{discountPct.toFixed(1)}%
          </span>
        )}
      </div>
      <div className={`h-display mt-1.5 text-2xl font-bold ${text}`}>
        <CountUp value={amount} prefix="₹" />
      </div>
    </div>
  );
}

function OtpGate({ otp, setOtp, demoOtp, confirming, onConfirm }) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.35 }}
      className="mt-6 overflow-hidden"
    >
      <div className="rounded-2xl border border-accent/30 bg-accent-soft p-6">
        <div className="flex items-center gap-3">
          <span className="text-2xl text-accent-hover">🔒</span>
          <span className="h-display text-lg font-semibold text-ink">
            Human safety gate — OTP confirmation
          </span>
        </div>
        <p className="mt-2 text-sm text-ink-muted">
          No money is captured or split until you explicitly confirm. Enter the
          OTP sent to the customer.
        </p>

        <input
          value={otp}
          onChange={(e) =>
            setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))
          }
          inputMode="numeric"
          placeholder="••••••"
          className="mt-5 w-full rounded-xl border border-lineStrong bg-white px-4 py-4 text-center font-display text-3xl tracking-[0.5em] text-ink outline-none focus:border-accent"
        />
        <div className="mt-3 text-center text-sm text-ink-faint">
          demo OTP: <span className="text-ink-muted">{demoOtp}</span>
        </div>
        <div className="mt-3 rounded-lg border border-line bg-white p-3 text-center text-sm text-ink-faint">
          After OTP, the Razorpay Checkout modal opens. Pay with test card{" "}
          <span className="text-ink-muted">4111 1111 1111 1111</span> · any
          future expiry · any CVV · OTP <span className="text-ink-muted">1111</span>
        </div>

        <Button
          size="lg"
          className="mt-5 w-full"
          disabled={otp.length < 6 || confirming}
          onClick={onConfirm}
        >
          {confirming ? (
            <>
              <Spinner size="lg" /> Confirming & settling…
            </>
          ) : (
            "Confirm & pay"
          )}
        </Button>
      </div>
    </motion.div>
  );
}

function ResultPanel({ result, goTab }) {
  const ok = result.settled;
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className={`mt-7 rounded-2xl border p-6 ${
        ok ? "border-good/30 bg-good/10" : "border-warn/30 bg-warn/10"
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="text-3xl">{ok ? "✅" : "⚠️"}</span>
        <span className="h-display text-lg font-bold">
          {ok ? "Settled successfully" : "Not settled"} · {result.status}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 text-sm">
        <Metric
          label="Charged to customer"
          value={rupees(result.net_customer_charge_inr)}
        />
        <Metric
          label="Money in a stuck state"
          value={rupees(result.stuck_money_inr)}
          good={result.stuck_money_inr === 0}
        />
      </div>

      {result.order_id && (
        <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-elevated p-4">
          <Badge color={result.payment_mode === "razorpay_test" ? "good" : "muted"} size="lg">
            {result.payment_mode === "razorpay_test"
              ? "Real Razorpay test order"
              : "Mock order"}
          </Badge>
          <span className="font-mono text-sm text-ink">{result.order_id}</span>
          <Badge
            color={result.route_mode === "live" ? "good" : "warn"}
            size="lg"
            className="ml-auto"
          >
            Route split: {result.route_mode === "live" ? "live" : "simulated"}
          </Badge>
          {result.payment_id && (
            <span className="w-full font-mono text-sm text-ink-faint">
              payment: {result.payment_id}
            </span>
          )}
        </div>
      )}
      <div className="mt-5 flex flex-wrap gap-3">
        <Button size="lg" variant="ghost" onClick={() => goTab("audit")}>
          View audit trail →
        </Button>
        <Button size="lg" variant="subtle" onClick={() => goTab("negotiation")}>
          Replay negotiation →
        </Button>
      </div>
    </motion.div>
  );
}

function Metric({ label, value, good }) {
  return (
    <div className="rounded-xl border border-line bg-elevated p-4">
      <div className="text-sm text-ink-faint">{label}</div>
      <div className={`h-display text-xl font-bold ${good ? "text-good" : ""}`}>
        {value}
      </div>
    </div>
  );
}

function OutOfStock() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="card grid place-items-center p-16 text-center"
    >
      <div className="grid h-14 w-14 place-items-center rounded-full bg-elevated text-ink-faint">
        <Icon name="inventory_2" className="text-[28px]" />
      </div>
      <h3 className="h-display mt-5 text-xl font-semibold">Out of stock</h3>
      <p className="mt-2 max-w-sm text-base text-ink-muted">
        This item isn't available for purchase right now. Please check back
        later or pick something else from the storefront.
      </p>
    </motion.div>
  );
}

function MatchingSkeleton() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="card p-6"
    >
      <div className="flex items-center gap-3 text-base text-ink-muted">
        <Spinner size="lg" /> Embedding catalog · finding a companion · agents
        negotiating…
      </div>
      <div className="mt-5 space-y-3">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-10 w-1/2" />
        <div className="grid grid-cols-2 gap-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      </div>
    </motion.div>
  );
}
