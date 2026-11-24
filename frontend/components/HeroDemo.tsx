"use client";

/**
 * Looping product demo for the sign-in screen (motion graphics, no video):
 * question types in -> sources are scanned -> answer streams -> citations pop -> source card rises.
 * With reduced motion the final frame is shown statically.
 */
import { FileText, Search, Sparkles } from "lucide-react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { EASE_OUT } from "./motion";

const QUESTION = "How many days of annual leave do full-time employees get?";
const ANSWER = ["Full-time", "employees", "receive", "27", "days", "of", "paid", "annual", "leave", "per", "year,", "plus", "public", "holidays."];
const SOURCES = [
  { name: "Employee_Handbook.pdf", meta: "p. 4 · Annual Leave", score: 0.91 },
  { name: "HR_Policies.docx", meta: "§ Time off", score: 0.74 },
  { name: "Benefits_FAQ.md", meta: "Leave & holidays", score: 0.62 },
];

// timeline (ms)
const T = { typeEnd: 1900, scan: 2000, scanEnd: 3600, answer: 3700, perWord: 110, cite: 5400, card: 5900, loop: 9800 };

export function HeroDemo() {
  const reduce = useReducedMotion();
  const [t, setT] = useState(0);
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    if (reduce) {
      // Jump to the final frame after mount; rendering it during hydration would differ from the
      // server-rendered first frame (React hydration mismatch).
      const id = requestAnimationFrame(() => setT(T.loop));
      return () => cancelAnimationFrame(id);
    }
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const elapsed = now - start;
      if (elapsed >= T.loop) {
        setCycle((c) => c + 1);
        return;
      }
      setT(elapsed);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [cycle, reduce]);

  const time = t;
  const typed = QUESTION.slice(0, Math.round((Math.min(time, T.typeEnd) / T.typeEnd) * QUESTION.length));
  const scanning = time >= T.scan && time < T.scanEnd;
  const visibleSources = time >= T.scan ? Math.min(SOURCES.length, Math.floor((time - T.scan) / 450) + 1) : 0;
  const words = time >= T.answer ? Math.min(ANSWER.length, Math.floor((time - T.answer) / T.perWord) + 1) : 0;

  return (
    <div className="relative w-full max-w-md">
      {/* question */}
      <motion.div key={`q-${cycle}`} className="ml-auto w-fit max-w-[85%] rounded-2xl rounded-tr-md bg-white px-4 py-2.5 text-sm text-slate-800 shadow-xl"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE_OUT }}>
        {typed}
        {time < T.typeEnd && <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-pulse bg-brand-500" />}
      </motion.div>

      {/* retrieval */}
      <div className="mt-4 space-y-2">
        <AnimatePresence>
          {SOURCES.slice(0, visibleSources).map((s, i) => (
            <motion.div key={`${cycle}-${s.name}`}
              className="flex items-center gap-3 rounded-xl border border-white/15 bg-white/10 px-3 py-2 text-xs text-white backdrop-blur-md"
              initial={{ opacity: 0, x: -16 }} animate={{ opacity: i === 0 || time < T.answer ? 1 : 0.45, x: 0 }}
              exit={{ opacity: 0 }} transition={{ duration: 0.35, ease: EASE_OUT }}>
              <FileText className="h-3.5 w-3.5 shrink-0 text-brand-100" />
              <span className="min-w-0 flex-1 truncate">{s.name} <span className="text-white/60">· {s.meta}</span></span>
              <span className="h-1 w-14 overflow-hidden rounded-full bg-white/15">
                <motion.span className="block h-full rounded-full bg-gradient-to-r from-cyan-300 to-white"
                  initial={{ width: 0 }} animate={{ width: `${s.score * 100}%` }} transition={{ duration: 0.6, ease: EASE_OUT }} />
              </span>
              <span className="w-8 text-right font-mono tabular-nums text-white/80">{s.score.toFixed(2)}</span>
            </motion.div>
          ))}
        </AnimatePresence>
        {scanning && (
          <motion.div className="flex items-center gap-2 pl-1 text-xs text-white/75" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
            <Search className="h-3.5 w-3.5 animate-pulse" /> Searching 1,284 passages · hybrid + rerank
          </motion.div>
        )}
      </div>

      {/* answer */}
      <AnimatePresence>
        {words > 0 && (
          <motion.div key={`a-${cycle}`} className="mt-4 rounded-2xl rounded-tl-md bg-white/95 p-4 text-sm text-slate-800 shadow-2xl"
            initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.45, ease: EASE_OUT }}>
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-brand-600 uppercase">
              <Sparkles className="h-3.5 w-3.5" /> Answer
            </div>
            <p className="leading-relaxed">
              {ANSWER.slice(0, words).map((w, i) => (
                <motion.span key={i} initial={{ opacity: 0, filter: "blur(4px)" }} animate={{ opacity: 1, filter: "blur(0px)" }}
                  transition={{ duration: 0.3 }}>
                  {w === "27" ? <strong className="text-brand-700">{w}</strong> : w}{" "}
                </motion.span>
              ))}
              {time >= T.cite && (
                <motion.span className="inline-flex h-4 min-w-4 -translate-y-0.5 items-center justify-center rounded bg-brand-600 px-1 text-[10px] font-semibold text-white"
                  initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 600, damping: 18 }}>1</motion.span>
              )}
            </p>
            <AnimatePresence>
              {time >= T.card && (
                <motion.div className="mt-3 rounded-xl border border-brand-100 bg-brand-50/70 p-3"
                  initial={{ opacity: 0, y: 10, height: 0 }} animate={{ opacity: 1, y: 0, height: "auto" }}
                  transition={{ duration: 0.45, ease: EASE_OUT }}>
                  <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
                    <span className="flex h-4 w-4 items-center justify-center rounded bg-brand-600 text-[10px] text-white">1</span>
                    Employee_Handbook.pdf <span className="text-slate-400">· p. 4</span>
                  </div>
                  <p className="mt-1.5 text-xs text-slate-600">
                    “Full-time employees receive{" "}
                    <mark className="rounded bg-yellow-200/80 px-0.5">27 days of paid annual leave</mark> per calendar year…”
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
