"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import PlumpButton from "@/components/ui/PlumpButton";
import PenguinMascot from "@/components/reading/PenguinMascot";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [grade, setGrade] = useState<1 | 2 | 3>(1);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const res = await fetch("/api/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, displayName, grade }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      setError(body.error ?? "Something went wrong. Please try again.");
      setSubmitting(false);
      return;
    }

    // Log straight in - no separate manual login step after a fresh signup.
    const result = await signIn("credentials", { email, password, redirect: false });
    setSubmitting(false);
    if (result?.error) {
      setError("Account created, but logging in failed. Please log in manually.");
      router.push("/login");
      return;
    }
    router.push("/");
  }

  return (
    // Same real feedback and fix as the login screen: full-bleed gradient +
    // floaty decorations + a tinted, ringed card instead of a plain white
    // one bolted onto an otherwise fully art-directed app. Amber identity
    // here specifically, matching the amber "Create account" button.
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-b from-sky-400 via-sky-500 to-rose-400 px-4 py-12">
      <div aria-hidden className="pointer-events-none absolute inset-0 hidden sm:block">
        <span className="floaty absolute left-[10%] top-[12%] text-3xl opacity-70">🌟</span>
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
          🔤
        </span>
        {/* Same companion as every other screen, celebrating a brand new
            account before there's even a first story to celebrate yet. */}
        <div
          className="floaty absolute bottom-[4%] left-[3%] flex h-24 w-24 items-center justify-center rounded-full border-4 shadow-xl sm:h-28 sm:w-28"
          style={{
            background: "radial-gradient(circle at 34% 28%, #f59746a6, #f5974660)",
            borderColor: "#f59746",
            animationDelay: "0.4s",
          }}
        >
          <PenguinMascot pose="dance" className="h-16 w-16 sm:h-20 sm:w-20" />
        </div>
      </div>

      <div className="relative w-full max-w-sm rounded-3xl bg-amber-50/95 p-6 shadow-xl ring-2 ring-amber-200 sm:p-8">
        <div className="mb-6 text-center">
          <span className="text-4xl drop-shadow-sm" aria-hidden>
            🎉
          </span>
          <h1 className="mt-2 font-[family-name:var(--font-kid)] text-2xl font-bold text-slate-800">
            Create your account
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            One account, one reader - let&apos;s get your child set up.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Your email
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-amber-300">
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
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-amber-300">
              <span aria-hidden className="text-slate-400">
                🔒
              </span>
              <input
                type="password"
                required
                minLength={8}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full text-base text-slate-800 outline-none"
              />
            </div>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Child&apos;s name
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-amber-300">
              <span aria-hidden className="text-slate-400">
                🧒
              </span>
              <input
                type="text"
                required
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full text-base text-slate-800 outline-none"
              />
            </div>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Grade
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm focus-within:border-amber-300">
              <span aria-hidden className="text-slate-400">
                🎓
              </span>
              <select
                value={grade}
                onChange={(e) => setGrade(Number(e.target.value) as 1 | 2 | 3)}
                className="w-full bg-transparent text-base text-slate-800 outline-none"
              >
                <option value={1}>Grade 1</option>
                <option value={2}>Grade 2</option>
                <option value={3}>Grade 3</option>
              </select>
            </div>
          </label>

          {error && (
            <p className="rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-800 ring-1 ring-rose-200">
              {error}
            </p>
          )}

          <PlumpButton type="submit" variant="primary" disabled={submitting} className="mt-2 w-full">
            {submitting ? "Creating account..." : "Create account"}
          </PlumpButton>
        </form>

        <p className="mt-5 text-center text-sm text-slate-500">
          Already have an account?{" "}
          <Link href="/login" className="font-semibold text-sky-600 hover:text-sky-700">
            Log in
          </Link>
        </p>
      </div>
    </main>
  );
}
