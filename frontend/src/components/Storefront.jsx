import { useEffect, useState } from "react";
import { api, rupees } from "../api";
import { Reveal, Stagger, StaggerItem } from "./motion.jsx";
import { Button, HoverCard, Badge, Skeleton, ErrorBanner, Icon } from "./ui.jsx";
import Coins from "./Coins.jsx";

// Soft pastel product-art washes — same idea as Mandi's product-art tiles: a
// flat icon on a gentle tinted square, no photography. Matched by keyword in
// the product's own name/category/tags, NOT by list position — cycling by
// index silently drifts out of sync the moment the catalog size doesn't
// divide evenly into the pattern count (a monitor showing headphones, etc).
const ART_RULES = [
  { test: /webcam|camera/, icon: "videocam", bg: "#fdf0ef", tint: "#c3665c" },
  { test: /mouse/, icon: "mouse", bg: "#eef2ff", tint: "#5b6fd6" },
  { test: /keyboard/, icon: "keyboard", bg: "#f1f8f0", tint: "#5c9c66" },
  { test: /headphone|audio|sound/, icon: "headphones", bg: "#fbf3ff", tint: "#9a63c9" },
  { test: /monitor|display/, icon: "desktop_windows", bg: "#eefbf7", tint: "#3f9d84" },
  { test: /ssd|storage|drive/, icon: "save", bg: "#fdf3e7", tint: "#c8935a" },
  { test: /hub|usb|dock|cable/, icon: "usb", bg: "#f5f5f4", tint: "#78716c" },
  { test: /laptop|book|notebook/, icon: "laptop_mac", bg: "#fdf3e7", tint: "#c8935a" },
];
const DEFAULT_ART = { icon: "inventory_2", bg: "#f5f5f4", tint: "#78716c" };

function artFor(product) {
  const haystack = [product.name, product.category, ...(product.tags || [])]
    .join(" ")
    .toLowerCase();
  return ART_RULES.find((r) => r.test.test(haystack)) || DEFAULT_ART;
}

export default function Storefront({ onBuy }) {
  const [merchant, setMerchant] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    api
      .catalog()
      .then((d) => setMerchant(d.merchants[0]))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  return (
    <div>
      <Reveal>
        <div className="hero-panel px-6 pb-10 pt-12 text-center sm:pb-14 sm:pt-16">
          <Coins />
          <div className="relative z-10 flex flex-col items-center">
            <span className="rise inline-flex items-center gap-2 rounded-full border border-line bg-white px-4 py-1.5 text-[13px] shadow-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              Merchant A Storefront
            </span>
            <h1
              className="rise mt-6 max-w-2xl font-medium tracking-tight text-balance"
              style={{ animationDelay: "110ms", fontSize: "clamp(28px, 5vw, 44px)", lineHeight: 1.08, letterSpacing: "-0.02em" }}
            >
              {merchant ? merchant.name : "LumenTech Electronics"}
            </h1>
            <p
              className="rise mt-4 max-w-xl text-ink-muted text-pretty"
              style={{ animationDelay: "220ms", fontSize: "15px", lineHeight: 1.6 }}
            >
              Buy a product and watch our AI agent team up with a non-competing
              merchant to build a better bundle — negotiated in real time.
            </p>
          </div>
        </div>
      </Reveal>

      {error && <ErrorBanner message={error} onRetry={load} />}

      {loading ? (
        <div className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      ) : (
        <Stagger className="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {merchant?.products.map((p) => {
            const art = artFor(p);
            return (
              <StaggerItem key={p.product_id}>
                <HoverCard
                  accent="merchantA"
                  strip={false}
                  className={`flex h-full flex-col p-0 ${
                    p.has_companion === false ? "opacity-60" : ""
                  }`}
                >
                  <div
                    className="flex h-32 items-center justify-center rounded-t-2xl"
                    style={{ background: art.bg }}
                  >
                    <Icon
                      name={art.icon}
                      className="text-[40px]"
                      style={{
                        color: p.has_companion === false ? "#a8a29e" : art.tint,
                      }}
                    />
                  </div>

                  <div className="flex flex-1 flex-col p-5">
                    <div className="mb-3 flex items-center gap-2">
                      <Badge color="muted">{p.category}</Badge>
                      {p.has_companion === false ? (
                        <Badge color="bad" className="ml-auto">Out of stock</Badge>
                      ) : (
                        <span className="ml-auto text-xs text-ink-faint">
                          {p.stock_qty} in stock
                        </span>
                      )}
                    </div>
                    <h3 className="h-display text-lg font-semibold leading-snug">
                      {p.name}
                    </h3>
                    <p className="mt-1.5 line-clamp-2 text-sm text-ink-muted">
                      {p.description}
                    </p>
                    <div className="mt-auto flex items-end justify-between gap-3 border-t border-line pt-4">
                      <div className="flex flex-col leading-tight">
                        <span className="h-display text-xl font-semibold tabular">
                          {rupees(p.price_inr)}
                        </span>
                        {p.mrp_inr > p.price_inr && (
                          <span className="mt-0.5 text-xs">
                            <span className="text-ink-faint line-through tabular">
                              {rupees(p.mrp_inr)}
                            </span>{" "}
                            <span className="font-medium text-good">
                              {p.discount_pct}% off
                            </span>
                          </span>
                        )}
                      </div>
                      {p.has_companion === false ? (
                        <Button variant="subtle" disabled>
                          Out of stock
                        </Button>
                      ) : (
                        <Button variant="primary" onClick={() => onBuy(p)}>
                          Buy Now
                        </Button>
                      )}
                    </div>
                  </div>
                </HoverCard>
              </StaggerItem>
            );
          })}
        </Stagger>
      )}
    </div>
  );
}
