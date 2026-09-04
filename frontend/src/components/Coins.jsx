// Rupee coins drifting behind a hero panel. Rendered as inline SVG (nothing
// fetched at runtime), marked decorative, animated with pure CSS so this
// costs zero JS beyond mounting the markup. See index.css for the keyframe.
const COINS = [
  { left: "6%", top: "18%", size: 44, depth: "mid", driftFrom: "0px", driftTo: "-18px", tiltFrom: "-12deg", tiltTo: "4deg", duration: "7s", delay: "0s" },
  { left: "13%", top: "58%", size: 30, depth: "far", driftFrom: "-6px", driftTo: "12px", tiltFrom: "18deg", tiltTo: "-6deg", duration: "9s", delay: "-2s" },
  { left: "2%", top: "74%", size: 54, depth: "near", driftFrom: "5px", driftTo: "-14px", tiltFrom: "8deg", tiltTo: "-14deg", duration: "6.5s", delay: "-4s" },
  { left: "88%", top: "14%", size: 38, depth: "far", driftFrom: "4px", driftTo: "-16px", tiltFrom: "-20deg", tiltTo: "2deg", duration: "8.5s", delay: "-1s" },
  { left: "80%", top: "46%", size: 58, depth: "near", driftFrom: "-8px", driftTo: "16px", tiltFrom: "10deg", tiltTo: "-10deg", duration: "7.5s", delay: "-3s" },
  { left: "93%", top: "70%", size: 32, depth: "mid", driftFrom: "0px", driftTo: "-16px", tiltFrom: "-6deg", tiltTo: "16deg", duration: "10s", delay: "-5s" },
  { left: "70%", top: "8%", size: 26, depth: "far", driftFrom: "-5px", driftTo: "10px", tiltFrom: "14deg", tiltTo: "-8deg", duration: "11s", delay: "-6s" },
  { left: "24%", top: "6%", size: 28, depth: "far", driftFrom: "2px", driftTo: "-12px", tiltFrom: "-16deg", tiltTo: "6deg", duration: "9.5s", delay: "-7s" },
];

const DEPTH = {
  far: { opacity: 0.25, blur: "1.2px" },
  mid: { opacity: 0.4, blur: "0.4px" },
  near: { opacity: 0.55, blur: "0px" },
};

export default function Coins() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {COINS.map((coin, i) => {
        const d = DEPTH[coin.depth];
        return (
          <span
            key={i}
            className="coin absolute"
            style={{
              left: coin.left,
              top: coin.top,
              width: coin.size,
              height: coin.size,
              opacity: d.opacity,
              filter: d.blur !== "0px" ? `blur(${d.blur})` : undefined,
              "--drift-from": coin.driftFrom,
              "--drift-to": coin.driftTo,
              "--tilt-from": coin.tiltFrom,
              "--tilt-to": coin.tiltTo,
              "--drift-duration": coin.duration,
              "--drift-delay": coin.delay,
            }}
          >
            <svg viewBox="0 0 40 40" width="100%" height="100%">
              <circle cx="20" cy="20" r="19" fill="#eaddc7" stroke="#d3bd94" strokeWidth="1.5" />
              <circle cx="20" cy="20" r="14" fill="none" stroke="#c9ae7c" strokeWidth="1" />
              <text
                x="20" y="26" textAnchor="middle"
                fontSize="16" fontFamily="Geist, system-ui, sans-serif"
                fontWeight="600" fill="#8a6d3f"
              >
                ₹
              </text>
            </svg>
          </span>
        );
      })}
    </div>
  );
}
