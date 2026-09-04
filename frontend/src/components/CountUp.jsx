import { useEffect, useState } from "react";
import { animate, useReducedMotion } from "framer-motion";

// Animates a number counting up. Respects reduced-motion (jumps to value).
export default function CountUp({
  value,
  duration = 0.9,
  prefix = "",
  suffix = "",
  decimals = 0,
  format,
}) {
  const reduce = useReducedMotion();
  const [display, setDisplay] = useState(reduce ? value : 0);

  useEffect(() => {
    if (reduce) {
      setDisplay(value);
      return;
    }
    const controls = animate(0, value, {
      duration,
      ease: "easeOut",
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [value, reduce, duration]);

  const num =
    decimals > 0
      ? Number(display).toFixed(decimals)
      : Math.round(display).toLocaleString("en-IN");
  return (
    <span>
      {prefix}
      {format ? format(display) : num}
      {suffix}
    </span>
  );
}
