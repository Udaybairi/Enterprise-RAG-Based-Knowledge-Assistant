"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/hooks/useAuth";
import { AnimatePresence, motion } from "motion/react";
import { HeroDemo } from "./HeroDemo";
import { Logo } from "./Logo";
import { EASE_OUT, FadeIn } from "./motion";
import { Spinner } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { login, register, user } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const nextPath = () => {
    const n = new URLSearchParams(window.location.search).get("next");
    return n && n.startsWith("/") && !n.startsWith("//") ? n : "/";
  };

  useEffect(() => {
    if (user) router.replace(nextPath());
  }, [user, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, name);
      router.replace(nextPath());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* left: brand + live product demo */}
      <div className="relative hidden flex-1 overflow-hidden bg-[#0b0b1a] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute -top-1/4 -left-1/4 h-[70%] w-[70%] rounded-full bg-brand-600/50 blur-[120px] animate-aurora" />
          <div className="absolute -right-1/4 -bottom-1/4 h-[70%] w-[70%] rounded-full bg-accent-600/40 blur-[120px] animate-aurora [animation-delay:-6s]" />
          <div className="absolute top-1/3 left-1/3 h-[40%] w-[40%] rounded-full bg-cyan-500/20 blur-[100px] animate-aurora [animation-delay:-11s]" />
          <div className="absolute inset-0 bg-[linear-gradient(to_right,rgb(255_255_255/0.05)_1px,transparent_1px),linear-gradient(to_bottom,rgb(255_255_255/0.05)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />
        </div>
        <FadeIn className="relative flex items-center gap-3">
          <Logo />
          <span className="font-semibold tracking-tight">Knowledge Assistant</span>
        </FadeIn>
        <div className="relative flex flex-col gap-9">
          <FadeIn delay={0.1} className="max-w-xl">
            <h2 className="text-[2.5rem] leading-[1.08] font-semibold tracking-tight">
              Answers from your documents,{" "}
              <span className="bg-gradient-to-r from-cyan-200 via-white to-violet-200 bg-clip-text text-transparent">with sources you can check.</span>
            </h2>
            <p className="mt-4 max-w-lg text-base text-white/70 [@media(max-height:820px)]:hidden">
              Upload policies, manuals and reports. Ask in plain language and get grounded answers, each claim
              linked to the exact document, page and passage.
            </p>
          </FadeIn>
          <FadeIn delay={0.25} className="[@media(max-height:700px)]:hidden">
            <HeroDemo />
          </FadeIn>
        </div>
        <p className="relative text-xs text-white/50">Retrieval-augmented generation · Google Gemini · PostgreSQL + pgvector</p>
      </div>

      {/* right: form */}
      <div className="relative flex flex-1 items-center justify-center p-6">
        <div aria-hidden className="page-backdrop pointer-events-none absolute inset-0" />
        <motion.form onSubmit={submit} className="relative w-full max-w-sm space-y-5"
          initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.55, ease: EASE_OUT }}>
          <div className="lg:hidden"><Logo size="lg" /></div>
          <div>
            <h1 className="text-[1.75rem] font-semibold tracking-tight">{mode === "login" ? "Sign in" : "Create your account"}</h1>
            <p className="mt-1.5 text-sm text-slate-500 dark:text-slate-400">
              {mode === "login" ? "Sign in to your knowledge workspace." : "Start asking questions about your documents."}
            </p>
          </div>
          <AnimatePresence>
            {error && (
              <motion.div className="rounded-xl border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm text-rose-700 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300"
                role="alert" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto", x: [0, -6, 6, -3, 3, 0] }}
                exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.4 }}>
                {error}
              </motion.div>
            )}
          </AnimatePresence>
          {mode === "register" && (
            <div>
              <label className="label" htmlFor="name">Full name</label>
              <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </div>
          )}
          <div>
            <label className="label" htmlFor="email">Work email</label>
            <input id="email" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@company.com" />
          </div>
          <div>
            <label className="label" htmlFor="password">Password</label>
            <input id="password" type="password" required minLength={mode === "register" ? 8 : 1} className="input"
              value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"} />
            {mode === "register" && <p className="mt-1.5 text-xs text-slate-500">At least 8 characters, including a letter and a digit.</p>}
          </div>
          <button className="btn-primary w-full py-2.5" disabled={busy}>
            {busy && <Spinner />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <p className="text-center text-sm text-slate-500">
            {mode === "login" ? (
              <>No account? <Link className="font-medium text-brand-600 hover:underline dark:text-brand-300" href="/register">Create one</Link></>
            ) : (
              <>Already registered? <Link className="font-medium text-brand-600 hover:underline dark:text-brand-300" href="/login">Sign in</Link></>
            )}
          </p>
        </motion.form>
      </div>
    </div>
  );
}
