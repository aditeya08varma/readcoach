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

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";
const FETCH_TIMEOUT_MS = 2500;

async function tryFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    });
    if (!res.ok) {
      throw new Error(`${path} responded ${res.status}`);
    }
    return (await res.json()) as T;
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
    const data = await tryFetch<Student>("/students", {
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
    const data = await tryFetch<Passage>(`/students/${studentId}/next_passage`);
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
    const data = await tryFetch<Passage>(`/students/${studentId}/passages/${passageId}`);
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
    const data = await tryFetch<VoiceToken>(`/sessions/${studentId}/voice_token`, {
      method: "POST",
      body: JSON.stringify({ student_id: studentId, passage_id: passageId }),
    });
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
      `/students/${studentId}/sessions`
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
    const data = await tryFetch<MasterySkill[]>(`/students/${studentId}/mastery`);
    return { data, source: "live" };
  } catch (err) {
    warnFallback(`GET /students/${studentId}/mastery`, err);
    return { data: mockMastery(studentId), source: "mock" };
  }
}

export async function getStoryMap(studentId: string): Promise<Sourced<StoryMap>> {
  try {
    const data = await tryFetch<StoryMap>(`/students/${studentId}/map`);
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
    const data = await tryFetch<EngineeringDashboard>(
      "/admin/engineering_dashboard"
    );
    return { data, source: "live" };
  } catch (err) {
    warnFallback("GET /admin/engineering_dashboard", err);
    return { data: mockEngineeringDashboard(), source: "mock" };
  }
}
