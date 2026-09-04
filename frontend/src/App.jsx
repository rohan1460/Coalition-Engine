import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "./api";
import { Icon } from "./components/ui.jsx";
import Storefront from "./components/Storefront.jsx";
import Checkout from "./components/Checkout.jsx";
import Negotiation from "./components/Negotiation.jsx";
import AuditTrail from "./components/AuditTrail.jsx";
import FailureSim from "./components/FailureSim.jsx";

const TABS = [
  { id: "store", label: "Storefront" },
  { id: "checkout", label: "Checkout" },
  { id: "negotiation", label: "Negotiation" },
  { id: "audit", label: "Audit Trail" },
  { id: "failure", label: "Failure Sim" },
];

export default function App() {
  const [tab, setTab] = useState("store");
  const [selected, setSelected] = useState(null);
  const [session, setSession] = useState(null);
  const [health, setHealth] = useState(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const buyNow = (product) => {
    setSelected(product);
    setSession(null);
    setTab("checkout");
  };

  const settled = session?.confirm?.settled;

  return (
    <div className="flex min-h-full flex-col bg-white text-ink">
      <Header tab={tab} setTab={setTab} health={health} />

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 pb-16 pt-10">
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
          >
            {tab === "store" && <Storefront onBuy={buyNow} />}
            {tab === "checkout" && (
              <Checkout
                product={selected}
                session={session}
                setSession={setSession}
                goTab={setTab}
              />
            )}
            {tab === "negotiation" && (
              <Negotiation correlationId={session?.correlationId} />
            )}
            {tab === "audit" && (
              <AuditTrail correlationId={session?.correlationId} />
            )}
            {tab === "failure" && <FailureSim />}
          </motion.div>
        </AnimatePresence>
      </main>

      <StatusBar health={health} settled={settled} />
    </div>
  );
}

function Header({ tab, setTab, health }) {
  const ok = health?.status === "ok";
  const live = health?.dependencies?.razorpay?.live_orders;
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-white/80 backdrop-blur-xl">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4">
        <button
          onClick={() => setTab("store")}
          className="flex items-center gap-3 rounded-xl transition-opacity hover:opacity-80"
        >
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-ink text-white">
            <Icon name="hub" className="text-[20px]" />
          </div>
          <div className="leading-none">
            <div className="h-display text-lg font-semibold tracking-tight">
              Coalition Engine
            </div>
          </div>
        </button>

        <nav className="ml-auto hidden items-center gap-1 lg:flex">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                tab === t.id
                  ? "bg-elevated text-ink"
                  : "text-ink-muted hover:text-ink"
              }`}
            >
              {t.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 text-xs text-ink-muted lg:ml-0">
          <span
            className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-good" : "bg-bad"}`}
          />
          {live ? "Razorpay Live-Test" : ok ? "API Online" : "Offline"}
        </div>
      </div>

      {/* mobile tabs */}
      <div className="flex gap-1 overflow-x-auto border-t border-line px-4 pb-3 pt-2 lg:hidden">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm font-medium ${
              tab === t.id ? "bg-elevated text-ink" : "text-ink-muted"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
    </header>
  );
}

function StatusBar({ health, settled }) {
  const secure = health?.status === "ok";
  const items = [
    { k: "Mode", v: "Test", tone: "text-accent-hover" },
    { k: "Secure", v: secure ? "On" : "Off", tone: secure ? "text-good" : "text-bad" },
    { k: "Agent A", v: "Ready", tone: "text-merchantA" },
    { k: "Agent B", v: "Ready", tone: "text-merchantB" },
    { k: "Settlement gate", v: settled ? "Open" : "Locked",
      tone: settled ? "text-good" : "text-ink-faint" },
  ];
  return (
    <footer className="border-t border-line mt-8">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-6 py-5 text-xs text-ink-faint">
        <span>Razorpay test mode. No real money moves.</span>
        <span className="hidden text-line sm:inline">|</span>
        {items.map((it, i) => (
          <span key={i} className="inline-flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full bg-current ${it.tone}`} />
            <span className="text-ink-muted">{it.k}:</span>{" "}
            <span className={it.tone}>{it.v}</span>
          </span>
        ))}
      </div>
    </footer>
  );
}
