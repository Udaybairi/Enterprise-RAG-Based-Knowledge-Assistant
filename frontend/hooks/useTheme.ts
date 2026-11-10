"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

export type Theme = "light" | "dark" | "system";
const KEY = "rag.theme";
const listeners = new Set<() => void>();

function read(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme) || "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Theme preference shared by every component (single source of truth in localStorage). */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, read, () => "system" as Theme);

  useEffect(() => {
    apply(read());
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply(read());
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* storage unavailable: still apply for this session */
    }
    apply(t);
    listeners.forEach((l) => l());
  }, []);

  return { theme, setTheme };
}
