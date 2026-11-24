import clsx from "clsx";

/** Brand mark: gradient tile with a stylised spark over an open page. */
export function Logo({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const box = { sm: "h-7 w-7 rounded-lg", md: "h-9 w-9 rounded-xl", lg: "h-14 w-14 rounded-2xl" }[size];
  const icon = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-7 w-7" }[size];
  return (
    <span className={clsx("group relative inline-flex shrink-0 items-center justify-center overflow-hidden bg-brand-gradient text-white shadow-glow", box)}>
      <svg viewBox="0 0 24 24" fill="none" className={clsx("relative z-10", icon)} aria-hidden>
        <path d="M4 6.5c2.6-1 5.2-1 8 .6 2.8-1.6 5.4-1.6 8-.6v11c-2.6-1-5.2-1-8 .6-2.8-1.6-5.4-1.6-8-.6v-11Z"
          stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" opacity="0.9" />
        <path d="M12 7.1v11.1" stroke="currentColor" strokeWidth="1.6" opacity="0.6" />
        <path d="M17.5 1.8l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7.7-1.9Z" fill="currentColor" />
      </svg>
      <span className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/40 to-transparent transition-transform duration-700 group-hover:translate-x-full" />
    </span>
  );
}
