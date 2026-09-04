import { useEffect, useRef, useState } from "react";
import { AnimatePresence, useReducedMotion } from "framer-motion";
import { api, rupees } from "../api";
import { Reveal, motion } from "./motion.jsx";
import { Button, Badge, Toggle, Spinner, ErrorBanner } from "./ui.jsx";

const MODES = [
  {
    key: "inventory_fail",
    label: "Inventory lock fails (Merchant B)",
    sub: "Bag out of stock — bundle should degrade to laptop-only",
    color: "warn",
  },
  {
    key: "transfer_fail",
    label: "Route split transfer fails",
    sub: "Retries with backoff, then refunds + reverses",
    color: "bad",
  },
  {
    key: "capture_fail",
    label: "Payment capture fails",
    sub: "Reservations released; nothing charged",
    color: "bad",
  },
  {
    key: "confirmation_timeout",
    label: "Confirmation times out",
    sub: "Held reservations released; no settlement",
    color: "comp",
  },
];

const STEP_META = {
  customer_confirmation: { color: "good", icon: "✔" },
  saga_started: { color: "accent", icon: "▶" },
  saga_step_completed: { color: "good", icon: "✔" },
  payment_initiated: { color: "good", icon: "✔" },
  split_executed: { color: "good", icon: "✔" },
  saga_step_failed: { color: "bad", icon: "✕" },
  failure: { color: "bad", icon: "✕" },
  compensation_executed: { color: "comp", icon: "⟲" },
  saga_completed: { color: "good", icon: "★" },
  saga_failed: { color: "comp", icon: "⟲" },
};
const EXEC_TYPES = new Set(Object.keys(STEP_META));

const DOT = {
  accent: "bg-accent",
  good: "bg-good",
  bad: "bg-bad",
  comp: "bg-comp",
};

export default function FailureSim() {
  const [flags, setFlags] = useState({
    inventory_fail: false,
    transfer_fail: false,
    capture_fail: false,
    confirmation_timeout: false,
  });
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [steps, setSteps] = useState([]);
  const [shown, setShown] = useState(0);
  const reduce = useReducedMotion();
  const timers = useRef([]);

  const anyOn = Object.values(flags).some(Boolean);

  const run = async () => {
    timers.current.forEach(clearTimeout);
    setRunning(true);
    setError(null);
    setResult(null);
    setSteps([]);
    setShown(0);
    try {
      const res = await api.simulate("a_lap_15biz", flags);
      if (res.status === "failed" && !res.correlation_id) {
        setError(res.reason || "Could not run simulation.");
        setRunning(false);
        return;
      }
      setResult(res);
      const audit = await api.audit(res.correlation_id);
      const exec = audit.events.filter((e) => EXEC_TYPES.has(e.event_type));
      setSteps(exec);

      if (reduce) {
        setShown(exec.length);
      } else {
        exec.forEach((_, i) => {
          timers.current.push(
            setTimeout(() => setShown(i + 1), 400 + i * 600)
          );
        });
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  return (
    <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
      <Reveal>
        <div className="card p-7">
          <div className="mb-4 flex items-center gap-2.5">
            <Badge color="bad" size="lg">Resilience</Badge>
          </div>
          <h1 className="h-display text-3xl font-medium tracking-tight">
            Failure Simulation
          </h1>
          <p className="mt-3 text-base text-ink-muted">
            Force a failure and watch the saga compensate. No matter which one
            you pick, no money is ever left in a stuck state.
          </p>

          <div className="mt-6 space-y-3.5">
            {MODES.map((m) => (
              <Toggle
                key={m.key}
                checked={flags[m.key]}
                onChange={(v) => setFlags((f) => ({ ...f, [m.key]: v }))}
                label={m.label}
                sub={m.sub}
                color={m.color}
              />
            ))}
          </div>

          <Button
            size="lg"
            className="mt-7 w-full"
            onClick={run}
            disabled={running}
          >
            {running ? (
              <>
                <Spinner size="lg" /> Running checkout…
              </>
            ) : anyOn ? (
              "Run checkout with failure active"
            ) : (
              "Run checkout (happy path)"
            )}
          </Button>

          {error && (
            <div className="mt-4">
              <ErrorBanner message={error} size="lg" />
            </div>
          )}
        </div>
      </Reveal>

      <div>
        {result && <ResultBanner result={result} />}

        <div className="card mt-4 p-7">
          <h3 className="h-display mb-5 text-xl font-semibold">Saga execution</h3>
          {steps.length === 0 ? (
            <p className="text-base text-ink-muted">
              Run a simulation to see the saga steps and compensations roll in.
            </p>
          ) : (
            <div className="relative pl-10">
              <div className="absolute bottom-2 left-[13px] top-2 w-[2px] bg-line" />
              <div className="space-y-4">
                <AnimatePresence initial={false}>
                  {steps.slice(0, shown).map((e, i) => {
                    const meta = STEP_META[e.event_type] || {
                      color: "accent",
                      icon: "•",
                    };
                    return (
                      <motion.div
                        key={e.event_id || i}
                        layout
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.35, ease: "easeOut" }}
                        className="relative"
                      >
                        <span
                          className={`absolute -left-[32px] top-3.5 grid h-6 w-6 place-items-center rounded-full text-sm text-base ring-4 ring-surface ${
                            DOT[meta.color]
                          }`}
                        >
                          {meta.icon}
                        </span>
                        <div
                          className={`rounded-xl border p-4 ${
                            meta.color === "comp"
                              ? "border-comp/30 bg-comp/10"
                              : meta.color === "bad"
                              ? "border-bad/30 bg-bad/10"
                              : "border-line bg-elevated/50"
                          }`}
                        >
                          <div className="mb-1.5 flex items-center gap-2.5">
                            <span className="font-mono text-sm text-ink-faint">
                              {e.event_type}
                            </span>
                            <span className="ml-auto text-sm text-ink-faint">
                              {e.actor}
                            </span>
                          </div>
                          <p className="text-base text-ink">{e.reasoning}</p>
                        </div>
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ResultBanner({ result }) {
  const settled = result.settled;
  const noStuck = result.stuck_money_inr === 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="card p-6"
    >
      <div className="flex items-center gap-2.5">
        <Badge color={settled ? "good" : "comp"} size="lg">
          {result.status.replaceAll("_", " ")}
        </Badge>
        <span className="ml-auto text-sm text-ink-faint">
          saga {result.saga_id}
        </span>
      </div>
      <div className="mt-5 grid grid-cols-3 gap-4 text-center">
        <Stat label="Charged" value={rupees(result.net_customer_charge_inr)} />
        <Stat
          label="Stuck money"
          value={rupees(result.stuck_money_inr)}
          good={noStuck}
        />
        <Stat
          label="Outcome"
          value={settled ? "Fulfilled" : "Rolled back"}
        />
      </div>
      {noStuck && (
        <div className="mt-4 text-center text-sm text-good">
          ✓ No money left in a stuck state
        </div>
      )}
    </motion.div>
  );
}

function Stat({ label, value, good }) {
  return (
    <div className="rounded-xl border border-line bg-elevated p-4">
      <div className="text-sm text-ink-faint">{label}</div>
      <div className={`h-display mt-1 text-xl font-bold ${good ? "text-good" : ""}`}>
        {value}
      </div>
    </div>
  );
}
