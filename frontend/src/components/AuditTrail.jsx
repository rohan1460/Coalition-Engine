import { useEffect, useState } from "react";
import { api } from "../api";
import { Reveal, motion } from "./motion.jsx";
import { Badge, Spinner, ErrorBanner, Skeleton } from "./ui.jsx";

const META = {
  affinity_scored: { cat: "Matching", color: "accent" },
  matching_performed: { cat: "Matching", color: "accent" },
  negotiation_started: { cat: "Negotiation", color: "warn" },
  negotiation_round: { cat: "Negotiation", color: "warn" },
  offer_presented: { cat: "Negotiation", color: "warn" },
  negotiation_failed: { cat: "Failure", color: "bad" },
  customer_confirmation: { cat: "Confirmation", color: "good" },
  payment_initiated: { cat: "Payment", color: "good" },
  split_executed: { cat: "Payment", color: "good" },
  saga_started: { cat: "Saga", color: "accent" },
  saga_step_completed: { cat: "Saga", color: "accent" },
  saga_completed: { cat: "Saga", color: "good" },
  saga_step_failed: { cat: "Failure", color: "bad" },
  failure: { cat: "Failure", color: "bad" },
  saga_failed: { cat: "Failure", color: "bad" },
  compensation_executed: { cat: "Compensation", color: "comp" },
  rollback: { cat: "Compensation", color: "comp" },
};

const DOT = {
  accent: "bg-accent",
  warn: "bg-warn",
  good: "bg-good",
  bad: "bg-bad",
  comp: "bg-comp",
  muted: "bg-ink-faint",
};

export default function AuditTrail({ correlationId }) {
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

  if (!correlationId) {
    return (
      <Reveal>
        <div className="card grid place-items-center p-16 text-center text-lg text-ink-muted">
          Run a checkout to generate an audit trail.
        </div>
      </Reveal>
    );
  }

  return (
    <div>
      <Reveal>
        <div className="mb-7">
          <div className="mb-4 flex items-center gap-3">
            <span className="label-caps text-base">Transaction Ledger</span>
            <span className="h-px flex-1 bg-line" />
          </div>
          <h1 className="h-display text-4xl font-medium tracking-tight">Audit Trail</h1>
          <p className="mt-3 text-lg text-ink-muted">
            Every agent decision — with the reasoning behind it — tied to one
            correlation id:{" "}
            <span className="font-mono text-sm text-ink">
              {correlationId}
            </span>
          </p>
        </div>
      </Reveal>

      {error && <ErrorBanner message={error} size="lg" />}
      {loading && (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-16" />
          ))}
        </div>
      )}

      {events && (
        <div className="relative pl-10">
          {/* connecting line */}
          <div className="absolute bottom-2 left-[13px] top-2 w-[2px] bg-line" />
          <div className="space-y-5">
            {events.map((e, i) => {
              const meta = META[e.event_type] || { cat: "Event", color: "muted" };
              return (
                <Reveal key={e.event_id || i} y={12}>
                  <div className="relative">
                    <span
                      className={`absolute -left-[32px] top-4 h-4 w-4 rounded-full ring-4 ring-base ${
                        DOT[meta.color]
                      }`}
                    />
                    <div className="card p-5">
                      <div className="mb-2 flex flex-wrap items-center gap-2.5">
                        <Badge color={meta.color} size="lg">{meta.cat}</Badge>
                        <span className="font-mono text-sm text-ink-faint">
                          {e.event_type}
                        </span>
                        <span className="ml-auto text-sm text-ink-faint">
                          {fmtTime(e.timestamp)} · {e.actor}
                        </span>
                      </div>
                      <p className="text-base leading-relaxed text-ink">
                        {e.reasoning}
                      </p>
                    </div>
                  </div>
                </Reveal>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function fmtTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString("en-GB");
  } catch {
    return "";
  }
}
