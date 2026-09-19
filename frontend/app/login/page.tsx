"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { toast } from "sonner";
import PlumpButton from "@/components/ui/PlumpButton";
import PenguinMascot from "@/components/reading/PenguinMascot";
import Logo from "@/components/ui/Logo";

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
      const message = "That email or password doesn't match an account.";
      setError(message);
      toast.error(message);
      return;
    }
    router.push(callbackUrl);
  }

  return (
    // Calmed toward the dashboard's adult register: this is a parent
    // filling out a login form, not a child on the reading screen, so it
    // no longer gets the kid-facing full-saturation gradient and floating
    // decorative emoji. Sky stays as this page's soft identity accent
    // (matching the "Log in" button), just concentrated into the card and
    // penguin circle instead of the whole background - same logic as
    // /dashboard and /admin/engineering.
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-b from-sky-50 via-white to-sky-50 px-4 py-12">
      <div className="relative flex w-full max-w-sm flex-col items-center">
        <Logo size="lg" tone="dark" href={null} className="mb-6" />
        <div className="w-full rounded-3xl bg-white p-6 shadow-xl ring-2 ring-sky-100 sm:p-8">
        <div className="mb-6 text-center">
          {/* The same penguin every other screen now has, standing in for
              the owl that used to greet a family here - one consistent
              companion across the app, sized to actually anchor this card
              rather than sit as a small icon above the heading. */}
          <div
            className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border-[3px] shadow-lg"
            style={{
              background: "radial-gradient(circle at 34% 28%, #bae6fd, #e0f2fe)",
              borderColor: "#7dd3fc",
            }}
          >
            <PenguinMascot pose="wave" className="h-14 w-14" />
          </div>
          <h1 className="mt-2 font-[family-name:var(--font-classy)] text-2xl font-bold text-slate-800">
            Welcome back
          </h1>
          <p className="mt-1 text-sm text-slate-500">Log in to keep reading.</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Email
            {/* The real input inside has outline-none (see below) since a
                native focus outline clipped by this rounded pill looked
                broken - this wrapper is the real focus indicator instead: a
                border color change plus a genuinely visible ring, not just
                the browser default that was suppressed. */}
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-sky-300 focus-within:ring-2 focus-within:ring-sky-400/70 focus-within:ring-offset-1">
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
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-sky-300 focus-within:ring-2 focus-within:ring-sky-400/70 focus-within:ring-offset-1">
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
      </div>
    </main>
  );
}
