"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import PlumpButton from "@/components/ui/PlumpButton";
import PenguinMascot from "@/components/reading/PenguinMascot";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginPageInner />
    </Suspense>
  );
}

function LoginPageInner() {
  const router = useRouter();
  const callbackUrl = useSearchParams().get("callbackUrl") ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    const result = await signIn("credentials", {
      email,
      password,
      redirect: false,
    });
    setSubmitting(false);
    if (result?.error) {
      setError("That email or password doesn't match an account.");
      return;
    }
    router.push(callbackUrl);
  }

  return (
    // Real feedback: this was the very first thing anyone sees, and it was
    // a plain white card with default form fields next to an app that's
    // otherwise fully art-directed everywhere else. Same full-bleed
    // gradient + floaty decorations + tinted-card language as every other
    // screen now, not a generic auth form bolted on the side.
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-b from-sky-400 via-sky-500 to-rose-400 px-4 py-12">
      <div aria-hidden className="pointer-events-none absolute inset-0 hidden sm:block">
        <span className="floaty absolute left-[10%] top-[12%] text-3xl opacity-70">⭐</span>
        <span
          className="floaty absolute right-[12%] top-[18%] text-2xl opacity-60"
          style={{ animationDelay: "1.2s" }}
        >
          ✨
        </span>
        <span
          className="floaty absolute left-[14%] bottom-[16%] text-2xl opacity-50"
          style={{ animationDelay: "2.1s" }}
        >
          ☁️
        </span>
        <span
          className="floaty absolute right-[10%] bottom-[12%] text-3xl opacity-60"
          style={{ animationDelay: "0.6s" }}
        >
          📖
        </span>
      </div>

      <div className="relative w-full max-w-sm rounded-3xl bg-sky-50/95 p-6 shadow-xl ring-2 ring-sky-200 sm:p-8">
        <div className="mb-6 text-center">
          {/* The same penguin every other screen now has, standing in for
              the owl that used to greet a family here - one consistent
              companion across the app, sized to actually anchor this card
              rather than sit as a small icon above the heading. */}
          <div
            className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border-[3px] shadow-lg"
            style={{
              background: "radial-gradient(circle at 34% 28%, #38bdf8a6, #38bdf860)",
              borderColor: "#38bdf8",
            }}
          >
            <PenguinMascot pose="wave" className="h-14 w-14" />
          </div>
          <h1 className="mt-2 font-[family-name:var(--font-kid)] text-2xl font-bold text-slate-800">
            Welcome back
          </h1>
          <p className="mt-1 text-sm text-slate-500">Log in to keep reading.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Email
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-sky-300">
              <span aria-hidden className="text-slate-400">
                ✉️
              </span>
              <input
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full text-base text-slate-800 outline-none"
              />
            </div>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Password
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-sky-300">
              <span aria-hidden className="text-slate-400">
                🔒
              </span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full text-base text-slate-800 outline-none"
              />
            </div>
          </label>

          {error && (
            <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">
              {error}
            </p>
          )}

          <PlumpButton type="submit" variant="secondary" disabled={submitting} className="mt-2 w-full">
            {submitting ? "Logging in..." : "Log in"}
          </PlumpButton>
        </form>

        <p className="mt-5 text-center text-sm text-slate-500">
          New here?{" "}
          <Link href="/signup" className="font-semibold text-sky-600 hover:text-sky-700">
            Create an account
          </Link>
        </p>
      </div>
    </main>
  );
}
