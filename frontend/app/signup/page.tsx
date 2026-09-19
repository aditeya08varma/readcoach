"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { toast } from "sonner";
import PlumpButton from "@/components/ui/PlumpButton";
import PenguinMascot from "@/components/reading/PenguinMascot";
import Logo from "@/components/ui/Logo";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

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
      const message = body.error ?? "Something went wrong. Please try again.";
      setError(message);
      toast.error(message);
      setSubmitting(false);
      return;
    }

    // Log straight in - no separate manual login step after a fresh signup.
    const result = await signIn("credentials", { email, password, redirect: false });
    setSubmitting(false);
    if (result?.error) {
      const message = "Account created, but logging in failed. Please log in manually.";
      setError(message);
      toast.error(message);
      router.push("/login");
      return;
    }
    toast.success("Account created! Welcome to ReadCoach.");
    router.push("/");
  }

  return (
    // Calmed toward the dashboard's adult register, same fix and reasoning
    // as /login: this is a parent filling out a signup form, not a child,
    // so the full-saturation gradient and floating decorative emoji are
    // gone. Amber stays this page's soft identity accent (matching the
    // "Create account" button), just concentrated into the card and
    // penguin circle instead of the whole background.
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-b from-amber-50 via-white to-amber-50 px-4 py-12">
      <div className="relative flex w-full max-w-sm flex-col items-center">
        <Logo size="lg" tone="dark" href={null} className="mb-6" />
        <div className="w-full rounded-3xl bg-white p-6 shadow-xl ring-2 ring-amber-100 sm:p-8">
        <div className="mb-6 text-center">
          {/* The same penguin every other screen now has, celebrating a
              brand new account before there's even a first story to
              celebrate yet. */}
          <div
            className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border-[3px] shadow-lg"
            style={{
              background: "radial-gradient(circle at 34% 28%, #fde68a, #fef3c7)",
              borderColor: "#fcd34d",
            }}
          >
            <PenguinMascot pose="dance" className="h-14 w-14" />
          </div>
          <h1 className="mt-2 font-[family-name:var(--font-classy)] text-2xl font-bold text-slate-800">
            Create your account
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            One account, one reader - let&apos;s get your child set up.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1 text-sm font-medium text-slate-700">
            Your email
            {/* Real gap found auditing keyboard focus: the input inside has
                outline-none (a native ring clipped by this rounded pill
                looked broken) but nothing had ever replaced it - tabbing
                through this form left no visible focus indicator at all.
                This wrapper is the real one now: a border color change plus
                a genuinely visible ring, same pattern as /login. */}
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-amber-300 focus-within:ring-2 focus-within:ring-amber-400/70 focus-within:ring-offset-1">
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
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-amber-300 focus-within:ring-2 focus-within:ring-amber-400/70 focus-within:ring-offset-1">
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
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-amber-300 focus-within:ring-2 focus-within:ring-amber-400/70 focus-within:ring-offset-1">
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
            <div className="flex items-center gap-2 rounded-2xl border-2 border-white bg-white px-3 py-2 shadow-sm transition-shadow focus-within:border-amber-300 focus-within:ring-2 focus-within:ring-amber-400/70 focus-within:ring-offset-1">
              <span aria-hidden className="text-slate-400">
                🎓
              </span>
              <Select
                value={String(grade)}
                onValueChange={(v) => setGrade(Number(v) as 1 | 2 | 3)}
              >
                <SelectTrigger className="h-auto w-full justify-between border-0 bg-transparent p-0 text-base text-slate-800 shadow-none focus-visible:ring-0">
                  {/* Base UI's Select.Value renders the raw value as-is
                      unless given a formatter - it doesn't infer a label
                      from the matching SelectItem's children the way some
                      other libraries do. */}
                  <SelectValue>{(v: string | null) => (v ? `Grade ${v}` : "Grade")}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">Grade 1</SelectItem>
                  <SelectItem value="2">Grade 2</SelectItem>
                  <SelectItem value="3">Grade 3</SelectItem>
                </SelectContent>
              </Select>
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
      </div>
    </main>
  );
}
