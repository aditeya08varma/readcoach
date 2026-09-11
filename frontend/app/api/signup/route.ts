import { NextResponse } from "next/server";
import bcrypt from "bcryptjs";
import { pool } from "@/lib/db";
import { createStudent } from "@/lib/api";

export async function POST(request: Request) {
  const body = await request.json();
  const { email, password, displayName, grade } = body ?? {};
  if (!email || !password || !displayName || !grade) {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }
  if (![1, 2, 3].includes(Number(grade))) {
    return NextResponse.json({ error: "Grade must be 1, 2, or 3" }, { status: 400 });
  }
  const normalizedEmail = String(email).toLowerCase().trim();

  const existing = await pool.query("select id from app_users where email = $1", [
    normalizedEmail,
  ]);
  if (existing.rows.length > 0) {
    return NextResponse.json(
      { error: "An account with that email already exists" },
      { status: 409 }
    );
  }

  // Reuse lib/api.ts's existing createStudent() as-is - it already POSTs to
  // the real /students endpoint on the Python backend and returns a real
  // uuid. Not reinventing student creation here.
  const studentResult = await createStudent(displayName, Number(grade) as 1 | 2 | 3);

  // createStudent() silently falls back to a fake "mock-<timestamp>" id (not
  // a real uuid) if the backend is unreachable - that id would fail the
  // students(id) FK on insert below anyway, so surface a real error instead
  // of half-creating an account with no real student behind it.
  if (studentResult.source !== "live") {
    return NextResponse.json(
      { error: "Could not reach the backend service. Make sure it's running and try again." },
      { status: 502 }
    );
  }

  const passwordHash = await bcrypt.hash(password, 10);
  await pool.query(
    `insert into app_users (email, password_hash, student_id, display_name, grade)
     values ($1, $2, $3, $4, $5)`,
    [normalizedEmail, passwordHash, studentResult.data.id, displayName, grade]
  );

  return NextResponse.json({ ok: true });
}
