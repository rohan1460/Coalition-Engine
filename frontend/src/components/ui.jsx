import { motion, useReducedMotion } from "framer-motion";

export function Icon({ name, className = "", ...props }) {
  return (
    <span className={`material-symbols-outlined ${className}`} {...props}>
      {name}
    </span>
  );
}

export function Button({
  children,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}) {
  const styles = {
    primary: "bg-ink text-white hover:opacity-90 border border-ink",
    agent: "bg-transparent text-merchantA border border-merchantA hover:bg-merchantA-soft",
    ghost: "border border-lineStrong text-ink hover:border-ink-faint hover:bg-elevated",
    subtle: "border border-line text-ink-muted hover:text-ink hover:border-lineStrong",
    danger: "bg-bad text-white border border-bad hover:opacity-90",
  }[variant];
  const sizes = {
    md: "gap-2 px-5 py-2.5 text-sm",
    lg: "gap-2.5 px-6 py-3.5 text-[15px]",
  }[size];
  return (
    <button
      className={`inline-flex items-center justify-center rounded-full font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${sizes} ${styles} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

// Data card: warm-white surface, hairline border, 4px agent header-strip,
// lifts + border-darkens on hover — no colored glow, that's not this look.
export function HoverCard({
  children,
  className = "",
  accent = "accent",
  strip = true,
}) {
  const reduce = useReducedMotion();
  const stripColor = {
    accent: "before:bg-accent",
    merchantA: "before:bg-merchantA",
    merchantB: "before:bg-merchantB",
  }[accent];
  return (
    <motion.div
      className={`card relative p-5 ${
        strip
          ? `before:absolute before:left-0 before:top-0 before:h-full before:w-[3px] before:rounded-l-2xl before:content-[''] ${stripColor}`
          : ""
      } ${className}`}
      whileHover={
        reduce ? {} : { y: -3, borderColor: "#d6d3d1" }
      }
      transition={{ duration: 0.22, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}

export function Badge({ children, color = "accent", className = "" }) {
  const map = {
    accent: "border-accent/40 text-accent-hover bg-accent-soft",
    merchantA: "border-merchantA/30 text-merchantA bg-merchantA-soft",
    merchantB: "border-merchantB/30 text-merchantB bg-merchantB-soft",
    good: "border-good/30 text-good bg-good/10",
    bad: "border-bad/30 text-bad bg-bad/10",
    warn: "border-warn/30 text-warn bg-warn/10",
    comp: "border-comp/30 text-comp bg-comp/10",
    muted: "border-line text-ink-muted bg-elevated",
  }[color];
  return <span className={`pill ${map} ${className}`}>{children}</span>;
}

export function Spinner({ size = "md", className = "" }) {
  const sizes = {
    md: "h-4 w-4 border-2",
    lg: "h-5 w-5 border-[3px]",
  }[size];
  return (
    <span
      className={`inline-block animate-spin rounded-full border-ink-faint/40 border-t-ink ${sizes} ${className}`}
    />
  );
}

// Rounded switch.
export function Toggle({ checked, onChange, label, sub, color = "accent" }) {
  const on = {
    accent: "bg-accent border-accent",
    bad: "bg-bad border-bad",
    warn: "bg-warn border-warn",
    comp: "bg-comp border-comp",
  }[color];
  return (
    <button
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between rounded-2xl border border-line bg-elevated px-5 py-4 text-left transition-colors hover:border-lineStrong"
    >
      <span>
        <span className="block text-base font-medium text-ink">{label}</span>
        {sub && <span className="mt-0.5 block text-sm text-ink-faint">{sub}</span>}
      </span>
      <span
        className={`relative h-6 w-12 shrink-0 rounded-full border transition-colors ${
          checked ? on : "border-lineStrong bg-white"
        }`}
      >
        <span
          className={`absolute top-[3px] h-3.5 w-3.5 rounded-full transition-transform ${
            checked ? "translate-x-[26px] bg-white" : "translate-x-[3px] bg-ink-faint"
          }`}
        />
      </span>
    </button>
  );
}

export function ErrorBanner({ message, onRetry, size = "md" }) {
  if (!message) return null;
  const cfg = {
    md: { pad: "px-4 py-3", text: "text-sm", icon: "text-[18px]" },
    lg: { pad: "px-5 py-4", text: "text-base", icon: "text-[22px]" },
  }[size];
  return (
    <div
      className={`flex items-center justify-between gap-4 rounded-2xl border border-bad/30 bg-bad/5 text-bad ${cfg.pad} ${cfg.text}`}
    >
      <span className="flex items-center gap-2">
        <Icon name="warning" className={cfg.icon} /> {message}
      </span>
      {onRetry && (
        <button onClick={onRetry} className="font-medium underline">
          Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-2xl border border-line bg-elevated ${className}`} />;
}
