"use client";

import { Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/hooks/useAuth";
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
      <div className="hidden flex-1 flex-col justify-between bg-gradient-to-br from-brand-700 via-brand-600 to-indigo-500 p-12 text-white lg:flex">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-white/15"><Sparkles className="h-5 w-5" /></div>
          <span className="font-semibold">Knowledge Assistant</span>
        </div>
        <div className="max-w-md">
          <h2 className="text-3xl font-semibold leading-tight">Answers from your documents, with sources you can check.</h2>
          <p className="mt-4 text-brand-100">
            Upload policies, manuals and reports. Ask questions in plain language and get grounded answers with
            citations to the exact document, page and passage.
          </p>
        </div>
        <p className="text-xs text-brand-200">Retrieval-augmented generation · Google Gemini · Hybrid search</p>
      </div>
      <div className="flex flex-1 items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm space-y-4">
          <div>
            <h1 className="text-2xl font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {mode === "login" ? "Welcome back. Sign in to your workspace." : "The first account becomes the administrator."}
            </p>
          </div>
          {error && <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300" role="alert">{error}</div>}
          {mode === "register" && (
            <div>
              <label className="label" htmlFor="name">Full name</label>
              <input id="name" className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </div>
          )}
          <div>
            <label className="label" htmlFor="email">Work email</label>
            <input id="email" type="email" required className="input" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
          <div>
            <label className="label" htmlFor="password">Password</label>
            <input id="password" type="password" required minLength={mode === "register" ? 8 : 1} className="input"
              value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"} />
            {mode === "register" && <p className="mt-1 text-xs text-slate-500">At least 8 characters, including a letter and a digit.</p>}
          </div>
          <button className="btn-primary w-full" disabled={busy}>
            {busy && <Spinner />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>
          <p className="text-center text-sm text-slate-500">
            {mode === "login" ? (
              <>No account? <Link className="font-medium text-brand-600" href="/register">Create one</Link></>
            ) : (
              <>Already registered? <Link className="font-medium text-brand-600" href="/login">Sign in</Link></>
            )}
          </p>
        </form>
      </div>
    </div>
  );
}
