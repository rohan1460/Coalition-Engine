/** @type {import('tailwindcss').Config} */
// "Mandi" design system — warm neutral, Geist type, rounded-full pills,
// minimal borders instead of shadows. Agent A / Agent B keep their own
// accent so the negotiation stays instantly readable at a glance.
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // surfaces
        base: "#ffffff",
        surface: "#ffffff",
        elevated: "#fafaf9",     // neutral-50
        elevatedHigh: "#f5f5f4", // neutral-100
        cream: "#f6f4f1",        // warm hero/panel wash
        // hairline borders
        line: "#e7e5e4",         // neutral-200 (stone)
        lineStrong: "#d6d3d1",   // neutral-300 (stone)
        // text
        ink: {
          DEFAULT: "#1c1917",    // neutral-900 (stone)
          muted: "#57534e",      // neutral-600 (stone)
          faint: "#a8a29e",      // neutral-400 (stone)
        },
        // brand accent — used sparingly (small dot badges, focus rings),
        // NOT the primary button fill (that's neutral-900, like Mandi).
        accent: {
          DEFAULT: "#f59e0b",
          hover: "#d97706",
          soft: "rgba(245,158,11,0.12)",
        },
        // Agent A = cool blue, Agent B = warm amber — a colorblind-safe
        // pairing that still reads as "two distinct parties" at a glance.
        merchantA: {
          DEFAULT: "#2563eb",
          soft: "rgba(37,99,235,0.08)",
        },
        merchantB: {
          DEFAULT: "#d97706",
          soft: "rgba(217,119,6,0.08)",
        },
        good: "#16a34a",
        bad: "#dc2626",
        warn: "#d97706",
        comp: "#7c3aed",
      },
      fontFamily: {
        display: ['"Geist"', "system-ui", "sans-serif"],
        sans: ['"Geist"', "system-ui", "sans-serif"],
        mono: ['"Geist Mono"', "ui-monospace", "monospace"],
      },
      letterSpacing: {
        caps: "0.06em",
      },
      boxShadow: {
        glowA: "0 0 0 1px rgba(37,99,235,0.35)",
        glowB: "0 0 0 1px rgba(217,119,6,0.35)",
      },
    },
  },
  plugins: [],
};
