import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, useReducedMotion } from "framer-motion";
import { api, rupees } from "../api";
import { Reveal, motion } from "./motion.jsx";
import CountUp from "./CountUp.jsx";
import { Badge, ErrorBanner, Skeleton, Icon } from "./ui.jsx";

export default function Negotiation({ correlationId }) {
  const [events, setEvents] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!correlationId) return;
    setLoading(true);
    setError(null);
    api
      .audit(correlationId)
      .then((d) => setEvents(d.events))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [correlationId]);

  const parsed = useMemo(() => parseNegotiation(events), [events]);

  if (!correlationId) return <EmptyState />;

  return (
    <div>
      <Reveal>
        <div className="mb-7">
          <div className="mb-4 flex items-center gap-3">
            <span className="label-caps text-base">Negotiation Session</span>
            <span className="h-px flex-1 bg-line" />
            {parsed && (
              <span className="font-mono text-sm text-ink-faint">
                {correlationId}
              </span>
            )}
          </div>
          <h1 className="h-display text-4xl font-medium tracking-tight">
            Machine-to-Machine Negotiation
          </h1>
        </div>
      </Reveal>

      {error && <ErrorBanner message={error} size="lg" />}
      {loading && <Skeleton className="h-80 w-full" />}

      {parsed && !loading && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
          <div className="space-y-5">
            <PolicyCard side="A" policy={parsed.policyA} />
            <PolicyCard side="B" policy={parsed.policyB} />
          </div>
          <div className="space-y-5">
            <ChatThread parsed={parsed} />
            {parsed.final && <SplitBar parsed={parsed} />}
          </div>
        </div>
      )}
    </div>
  );
}

function PolicyCard({ side, policy }) {
  const isA = side === "A";
  const border = isA ? "border-merchantA/40" : "border-merchantB/40";
  const text = isA ? "text-merchantA" : "text-merchantB";
  const strip = isA ? "before:bg-merchantA" : "before:bg-merchantB";
  const sku = policy.sku;
  return (
    <div
      className={`relative border ${border} bg-surface p-6 before:absolute before:left-0 before:top-0 before:h-full before:w-[3px] before:content-[''] ${strip}`}
    >
      <div className="mb-5 flex items-center gap-3">
        <Icon name={isA ? "smart_toy" : "robot_2"} className={`text-[26px] ${text}`} />
        <span className={`label-caps text-base ${text}`}>Merchant {side} Policy</span>
        {sku?.role && (
          <Badge color={isA ? "merchantA" : "merchantB"} size="lg" className="ml-auto">
            {sku.role}
          </Badge>
        )}
      </div>
      <dl className="space-y-3">
        <Row k="Stance" v={policy.stance || "—"} />
        <Row k="Natural Margin" v={sku ? `${sku.margin_pct.toFixed(1)}%` : "—"} />
        <Row k="Discount Ceiling" v={sku ? `${sku.discount_ceiling_pct.toFixed(1)}%` : "—"} />
        <Row k="Margin Floor" v={sku ? `${sku.margin_floor_pct.toFixed(1)}%` : "—"} />
        <Row
          k="Min Viable (blended)"
          v={policy.minViable != null ? `${policy.minViable.toFixed(1)}%` : "—"}
        />
      </dl>
    </div>
  );
}

function Row({ k, v }) {
  return (
    <div className="flex items-center justify-between border-b border-line/60 pb-2.5">
      <span className="label-caps text-sm">{k}</span>
      <span className="font-mono text-base font-semibold tabular text-ink">{v}</span>
    </div>
  );
}

function ChatThread({ parsed }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? parsed.messages.length : 0);
  const [typingSide, setTypingSide] = useState(null);
  const timers = useRef([]);
  const scroller = useRef(null);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    if (reduce) {
      setShown(parsed.messages.length);
      return;
    }
    setShown(0);
    setTypingSide(parsed.messages[0]?.side ?? null);
    let t = 0;
    parsed.messages.forEach((m, i) => {
      t += 850;
      timers.current.push(
        setTimeout(() => {
          setShown(i + 1);
          const next = parsed.messages[i + 1];
          setTypingSide(next ? next.side : null);
        }, t)
      );
    });
    return () => timers.current.forEach(clearTimeout);
  }, [parsed, reduce]);

  useEffect(() => {
    scroller.current?.scrollTo({
      top: scroller.current.scrollHeight,
      behavior: "smooth",
    });
  }, [shown, typingSide]);

  return (
    <div
      ref={scroller}
      className="max-h-[600px] space-y-5 overflow-y-auto border border-line bg-elevated p-6"
    >
      <div className="mb-2 flex items-center justify-center">
        <span className="label-caps border border-line bg-elevated px-4 py-1.5 text-sm">
          Terminal Feed
        </span>
      </div>
      <AnimatePresence initial={false}>
        {parsed.messages.slice(0, shown).map((m) => (
          <Bubble key={m.key} m={m} />
        ))}
      </AnimatePresence>
      {typingSide && shown < parsed.messages.length && <Typing side={typingSide} />}
    </div>
  );
}

function Bubble({ m }) {
  const isA = m.side === "A";
  const border = isA ? "border-merchantA/40" : "border-merchantB/40";
  const text = isA ? "text-merchantA" : "text-merchantB";
  const bg = isA ? "bg-merchantA-soft" : "bg-merchantB-soft";
  const label =
    m.action === "accept" ? "ACCEPTED"
    : m.action === "counter" ? "COUNTER"
    : "PROPOSE";
  const isPropose = m.action === "propose";
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
      className={`flex ${isA ? "justify-start" : "justify-end"}`}
    >
      <div className={`max-w-[88%] border ${border} ${bg} p-4`}>
        <div className="mb-2 flex items-center gap-2.5">
          <span className={`font-mono text-sm font-bold tracking-caps ${text}`}>
            AGENT_{m.side}
          </span>
          <span className="font-mono text-xs text-ink-faint">
            {m.ts} [SYS]
          </span>
          <Badge color={isA ? "merchantA" : "merchantB"} size="lg" className="ml-auto">
            {label}
          </Badge>
        </div>
        <p className="text-base leading-relaxed text-ink-muted">{m.text}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          {isPropose ? (
            <>
              <div className={`inline-flex items-center gap-2.5 border ${border} bg-elevated px-4 py-2`}>
                <span className="label-caps text-sm">MY DISCOUNT:</span>
                <span className={`font-mono text-base font-bold tabular ${text}`}>
                  {m.myPct?.toFixed(1)}%
                </span>
              </div>
              <div className={`inline-flex items-center gap-2.5 border border-line bg-elevated px-4 py-2`}>
                <span className="label-caps text-sm">BLENDED:</span>
                <span className="font-mono text-base font-bold tabular text-ink-muted">
                  {m.blended?.toFixed(2)}%
                </span>
              </div>
            </>
          ) : (
            <div className={`inline-flex items-center gap-2.5 border ${border} bg-elevated px-4 py-2`}>
              <span className="label-caps text-sm">STATUS:</span>
              <span className={`font-mono text-base font-bold tabular ${text}`}>
                {m.action.toUpperCase()}
              </span>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

function Typing({ side }) {
  const isA = side === "A";
  const box = isA
    ? "border-merchantA/40 bg-merchantA-soft"
    : "border-merchantB/40 bg-merchantB-soft";
  const dot = isA ? "bg-merchantA" : "bg-merchantB";
  return (
    <div className={`flex ${isA ? "justify-start" : "justify-end"}`}>
      <div className={`flex items-center gap-1.5 border px-4 py-2.5 ${box}`}>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className={`h-2 w-2 ${dot}`}
            animate={{ opacity: [0.3, 1, 0.3] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
        <span className="label-caps ml-1.5 text-sm">AGENT_{side} COMPUTING</span>
      </div>
    </div>
  );
}

function SplitBar({ parsed }) {
  const { final } = parsed;
  const total = final.a + final.b || 1;
  const aPct = (final.a / total) * 100;
  return (
    <Reveal>
      <div className="border border-line bg-surface p-6">
        <div className="mb-5 flex items-center justify-between">
          <span className="label-caps text-base text-good">Agreement Reached</span>
          <Badge color="good" size="lg">Round {final.round}</Badge>
        </div>
        <div className="flex h-16 w-full border border-line">
          <motion.div
            className="flex items-center justify-start bg-merchantA px-5"
            initial={{ width: 0 }}
            animate={{ width: `${aPct}%` }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
          >
            <span className="h-display text-base font-extrabold tabular text-white">
              A · <CountUp value={final.a} prefix="₹" />
            </span>
          </motion.div>
          <motion.div
            className="flex flex-1 items-center justify-end bg-merchantB px-5"
            initial={{ width: 0 }}
            animate={{ width: `${100 - aPct}%` }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1], delay: 0.15 }}
          >
            <span className="h-display text-base font-extrabold tabular text-white">
              <CountUp value={final.b} prefix="₹" /> · B
            </span>
          </motion.div>
        </div>
        <div className="mt-4 flex items-center justify-between text-sm text-ink-faint">
          <span>A's own discount: {final.discountA.toFixed(1)}%</span>
          <span>Blended: {final.discount.toFixed(2)}%</span>
          <span>B's own discount: {final.discountB.toFixed(1)}%</span>
        </div>
        <div className="mt-3 flex items-center justify-between text-base">
          <span className="label-caps text-sm">Settlement</span>
          <span className="text-ink-muted">
            Customer pays{" "}
            <span className="h-display font-extrabold tabular text-ink">
              {rupees(final.price)}
            </span>{" "}
            · {final.discount.toFixed(2)}% off {rupees(final.original)}
          </span>
        </div>
      </div>
    </Reveal>
  );
}

function EmptyState() {
  return (
    <Reveal>
      <div className="grid place-items-center border border-line bg-elevated p-16 text-center text-lg text-ink-muted">
        Run a checkout first — the negotiation replay will appear here.
      </div>
    </Reveal>
  );
}

function parseNegotiation(events) {
  if (!events) return null;
  const rounds = events.filter((e) => e.event_type === "negotiation_round");
  if (rounds.length === 0) return null;

  const started = events.find((e) => e.event_type === "negotiation_started");
  const firstActor = rounds[0].actor;
  const merchantA = firstActor;
  const merchantB = rounds.find((r) => r.actor !== firstActor)?.actor || "merchant_b";

  const fmtTs = (iso) => {
    try {
      return new Date(iso).toLocaleTimeString("en-GB");
    } catch {
      return "";
    }
  };

  const messages = rounds.map((e, i) => {
    const isA = e.actor === merchantA;
    const action = e.decision?.action || "propose";
    return {
      key: e.event_id || i,
      side: isA ? "A" : "B",
      round: e.inputs?.round ?? Math.floor(i / 2) + 1,
      action,
      // The proposer's OWN SKU discount — never the blended figure, which
      // would misleadingly read as "my discount" when it's a weighted mix.
      myPct: action === "propose"
        ? (isA ? e.decision?.discount_pct_a : e.decision?.discount_pct_b)
        : null,
      blended: e.decision?.discount_pct,
      text: e.reasoning,
      ts: fmtTs(e.timestamp),
    };
  });

  // Read policy data straight from the structured negotiation_started event
  // rather than regexing reasoning text — robust to reasoning wording changes.
  const policyOf = (mid, skuKey) => ({
    stance: mid === merchantA
      ? started?.inputs?.stance_a
      : started?.inputs?.stance_b,
    minViable: mid === merchantA
      ? started?.inputs?.min_viable_a_pct
      : started?.inputs?.min_viable_b_pct,
    sku: started?.inputs?.[skuKey] ?? null,
  });

  const presented = events.find((e) => e.event_type === "offer_presented");
  const final = presented
    ? {
        a: presented.decision?.merchant_a_amount_inr ?? 0,
        b: presented.decision?.merchant_b_amount_inr ?? 0,
        price: presented.decision?.bundle_price_inr ?? 0,
        discount: presented.decision?.discount_pct ?? 0,
        discountA: presented.decision?.discount_pct_a ?? 0,
        discountB: presented.decision?.discount_pct_b ?? 0,
        original:
          (presented.decision?.bundle_price_inr ?? 0) +
          (presented.decision?.discount_amount_inr ?? 0),
        round: presented.inputs?.round ?? messages.at(-1)?.round ?? 0,
      }
    : null;

  return {
    merchantA, merchantB, messages, final,
    policyA: policyOf(merchantA, "sku_a"), policyB: policyOf(merchantB, "sku_b"),
  };
}
