"use client";

/**
 * Motion primitives. All animation goes through MotionProvider with reducedMotion="user", so people
 * who ask their OS for reduced motion get instant transitions (plus the CSS fallback in globals.css).
 * Animations use transform/opacity only, so they stay on the compositor and never shift layout.
 */
import { animate, motion, MotionConfig, useInView, useMotionValue, useReducedMotion, type Variants } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";

export const EASE_OUT = [0.22, 1, 0.36, 1] as const;

export function MotionProvider({ children }: { children: ReactNode }) {
  return (
    <MotionConfig reducedMotion="user" transition={{ duration: 0.45, ease: EASE_OUT }}>
      {children}
    </MotionConfig>
  );
}

export function FadeIn({ children, delay = 0, y = 12, className }: { children: ReactNode; delay?: number; y?: number; className?: string }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: EASE_OUT }}>
      {children}
    </motion.div>
  );
}

const container: Variants = { hidden: {}, show: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } } };
const item: Variants = {
  hidden: { opacity: 0, y: 14, scale: 0.98 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.5, ease: EASE_OUT } },
};

export function Stagger({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={container} initial="hidden" animate="show">
      {children}
    </motion.div>
  );
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return <motion.div className={className} variants={item}>{children}</motion.div>;
}

/** Counts up to ``value`` when it scrolls into view (instant with reduced motion). */
export function AnimatedNumber({ value, format = (n: number) => Math.round(n).toLocaleString() }:
  { value: number; format?: (n: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });
  const reduce = useReducedMotion();
  const mv = useMotionValue(0);
  const [text, setText] = useState(format(0));

  useEffect(() => mv.on("change", (v) => setText(format(v))), [mv, format]);
  useEffect(() => {
    if (!inView) return;
    if (reduce) {
      mv.set(value);
      return;
    }
    const controls = animate(mv, value, { duration: 1.1, ease: EASE_OUT });
    return () => controls.stop();
  }, [inView, value, reduce, mv]);

  return <span ref={ref} className="tabular-nums">{text}</span>;
}

/** Route-level enter transition (rendered by app/(app)/template.tsx, which remounts per navigation). */
export function PageTransition({ children }: { children: ReactNode }) {
  return (
    <motion.div className="h-full" initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }} transition={{ duration: 0.45, ease: EASE_OUT }}>
      {children}
    </motion.div>
  );
}
