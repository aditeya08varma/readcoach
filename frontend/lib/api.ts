// Data-access layer for contracts/api_contract.md.
//
// Every function here has the exact request/response shape of the real
// endpoint. Components only ever call these functions and never fetch()
// directly, so swapping mock data for the real backend is a one-file change.
//
// Swap strategy: each function tries a real HTTP call against
// NEXT_PUBLIC_API_BASE_URL first (short timeout so a missing/unstarted
// backend fails fast instead of hanging the UI). If that call fails for any
// reason - backend not running yet, network error, non-2xx, timeout - it
// falls back to the matching mock generator in ./mockData and tags the
// result `source: "mock"`. Once the real backend is reachable and returns a
// 2xx with the contract shape, every screen picks it up automatically with
// zero component changes; `source` flips to "live" and the UI's data-source
// badge reflects that.

import type { z } from "zod";
import type {
  EngineeringDashboard,
  MasterySkill,
  Passage,
  SessionSummary,
  Sourced,
  StoryMap,
  Student,
  VoiceToken,
} from "./types";
import {
  mockEngineeringDashboard,
  mockMastery,
  mockNextPassage,
  mockPassageById,
  mockSessions,
  mockStoryMap,
} from "./mockData";
import {
  EngineeringDashboardSchema,
  MasterySkillListSchema,
  PassageSchema,
  SessionSummaryListSchema,
  StoryMapSchema,
  StudentSchema,
  VoiceTokenSchema,
} from "./schemas";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";
const FETCH_TIMEOUT_MS = 2500;

// Every call site below hands this a zod schema matching the exact
// contract shape (lib/schemas.ts) instead of just a `<T>` type parameter to
// blindly cast onto whatever JSON came back. Real gap found by audit: `zod`
// was already a listed dependency nothing in the app actually used, so a
// backend response that drifted from the contract (a renamed field, a
// server-side bug, a stale deploy) would previously flow straight into
// components as if it were the real shape, only to blow up unpredictably
// deeper in rendering. A schema failure here is treated exactly like a
// network failure - it throws, and every caller's existing catch block
// falls back to the matching mock generator, same as an unreachable
// backend always has.
async function tryFetch<T>(
  path: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
  timeoutMs: number = FETCH_TIMEOUT_MS
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!res.ok) {
      throw new Error(`${path} responded ${res.status}`);
    }
    const json = await res.json();
    const parsed = schema.safeParse(json);
    if (!parsed.success) {
      console.error(
        `[api] ${path} returned a payload that failed validation:`,
        parsed.error.issues
      );
      throw new Error(`${path} returned a payload that didn't match the contract`);
    }
    return parsed.data;
  } finally {
    clearTimeout(timeout);
  }
}

function warnFallback(path: string, err: unknown) {
  if (typeof window !== "undefined") {
    console.warn(
      `[api] ${path} unreachable, using mock data (${
        err instanceof Error ? err.message : String(err)
      })`
    );
  }
}

export async function createStudent(
  displayName: string,
  grade: 1 | 2 | 3
): Promise<Sourced<Student>> {
  try {
    const data = await tryFetch<Student>("/students", StudentSchema, {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, grade }),
    });
    return { data, source: "live" };
  } catch (err) {
    warnFallback("POST /students", err);
    return {
      data: { id: "mock-" + Date.now(), display_name: displayName, grade },
      source: "mock",
    };
  }
}

export async function getNextPassage(
  studentId: string
): Promise<Sourced<Passage>> {
  try {
    const data = await tryFetch<Passage>(
      `/students/${studentId}/next_passage`,
      PassageSchema
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/next_passage`, err);
    return { data: mockNextPassage(studentId), source: "mock" };
  }
}

export async function getPassageById(
  studentId: string,
  passageId: string
): Promise<Sourced<Passage>> {
  try {
    const data = await tryFetch<Passage>(
      `/students/${studentId}/passages/${passageId}`,
      PassageSchema
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/passages/${passageId}`, err);
    const mock = mockPassageById(passageId);
    return {
      data: mock ?? mockNextPassage(studentId),
      source: "mock",
    };
  }
}

export async function createVoiceToken(
  studentId: string,
  passageId: string
): Promise<Sourced<VoiceToken>> {
  try {
    const data = await tryFetch<VoiceToken>(
      `/sessions/${studentId}/voice_token`,
      VoiceTokenSchema,
      {
        method: "POST",
        body: JSON.stringify({ student_id: studentId, passage_id: passageId }),
      }
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`POST /sessions/${studentId}/voice_token`, err);
    return {
      data: {
        session_id: "mock-session-" + Date.now(),
        daily_room_url: "https://mock.daily.co/readcoach-demo",
        daily_token: "mock-token",
      },
      source: "mock",
    };
  }
}

export async function getSessions(
  studentId: string
): Promise<Sourced<SessionSummary[]>> {
  try {
    const data = await tryFetch<SessionSummary[]>(
      `/students/${studentId}/sessions`,
      SessionSummaryListSchema
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/sessions`, err);
    return { data: mockSessions(studentId), source: "mock" };
  }
}

export async function getMastery(
  studentId: string
): Promise<Sourced<MasterySkill[]>> {
  try {
    const data = await tryFetch<MasterySkill[]>(
      `/students/${studentId}/mastery`,
      MasterySkillListSchema
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/mastery`, err);
    return { data: mockMastery(studentId), source: "mock" };
  }
}

export async function getStoryMap(studentId: string): Promise<Sourced<StoryMap>> {
  try {
    const data = await tryFetch<StoryMap>(
      `/students/${studentId}/map`,
      StoryMapSchema
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/map`, err);
    return { data: mockStoryMap(), source: "mock" };
  }
}

export async function getEngineeringDashboard(): Promise<
  Sourced<EngineeringDashboard>
> {
  try {
    // Real bug found live (see docs/BUILD_LOG.md): this endpoint's own
    // backend hop to the eval service has up to a 3.0s internal timeout
    // (backend/mastery/main.py's engineering_dashboard), which is already
    // longer than this file's normal 2.5s fetch budget before any network
    // time or the mastery service's own DB work is even added on top - a
    // backend that's merely slow, not down, would always lose that race
    // and get mislabeled "Mock data" even though it was about to return
    // genuine live data. This is the one endpoint in this file with a real
    // nested downstream call, so it's the one that needs real headroom
    // over the backend's own worst case, not the shared default.
    const data = await tryFetch<EngineeringDashboard>(
      "/admin/engineering_dashboard",
      EngineeringDashboardSchema,
      undefined,
      6000
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback("GET /admin/engineering_dashboard", err);
    return { data: mockEngineeringDashboard(), source: "mock" };
  }
}
