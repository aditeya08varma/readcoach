// Real gap found by audit: zero automated tests existed anywhere in the
// frontend despite this file's own comments documenting real, previously
// confirmed bugs (see lib/confettiPop.ts, lib/voiceEventStream.ts). These
// cover the two behaviors this pass touches: the existing mock-fallback path
// (unreachable backend / non-2xx), and the new zod validation added on top
// of it (a payload that doesn't match contracts/api_contract.md should fall
// back exactly the same way a network failure already does, never crash).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  createStudent,
  getMastery,
  getNextPassage,
  getSessions,
  getStoryMap,
} from "./api";

function mockFetchResolve(body: unknown, ok = true, status = ok ? 200 : 500) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mockFetchReject(err: unknown) {
  const fetchMock = vi.fn().mockRejectedValue(err);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const VALID_SESSION = {
  id: "session-1",
  passage_id: "g1-short-vowels-001",
  started_at: "2026-01-01T00:00:00.000Z",
  wcpm: 82,
  accuracy: 0.91,
  self_corrections: 2,
};

const VALID_PASSAGE = {
  id: "g1-short-vowels-001",
  grade: 1,
  title: "Pat and the Big Hat",
  text: "Pat has a big hat.",
  words: ["Pat", "has", "a", "big", "hat"],
  skills: ["short_vowels"],
};

const VALID_MASTERY = [
  { skill_id: "short_vowels", label: "Short Vowel Sounds", category: "phonics", weight: 0.9 },
];

const VALID_STORY_MAP = {
  categories: [
    {
      category: "phonics",
      skills: [
        {
          skill_id: "short_vowels",
          label: "Short Vowel Sounds",
          category: "phonics",
          weight: 0.9,
          passages: [{ id: "p1", title: "Pat", grade: 1, attempted: true }],
        },
      ],
    },
  ],
};

describe("lib/api.ts mock-fallback behavior", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("returns live data when the backend responds with a contract-shaped payload", async () => {
    mockFetchResolve([VALID_SESSION]);
    const result = await getSessions("student-1");
    expect(result.source).toBe("live");
    expect(result.data).toEqual([VALID_SESSION]);
  });

  it("falls back to mock data when the fetch fails outright (network error)", async () => {
    mockFetchReject(new Error("network down"));
    const result = await getSessions("student-1");
    expect(result.source).toBe("mock");
    expect(result.data.length).toBeGreaterThan(0);
    expect(console.warn).toHaveBeenCalled();
  });

  it("falls back to mock data when the backend responds non-2xx", async () => {
    mockFetchResolve(null, false, 500);
    const result = await getMastery("student-1");
    expect(result.source).toBe("mock");
    expect(result.data.length).toBeGreaterThan(0);
  });

  it("falls back to createStudent's inline mock when the backend is unreachable", async () => {
    mockFetchReject(new Error("connection refused"));
    const result = await createStudent("Ada", 2);
    expect(result.source).toBe("mock");
    expect(result.data.display_name).toBe("Ada");
    expect(result.data.id.startsWith("mock-")).toBe(true);
  });
});

describe("lib/api.ts zod validation (new in this pass)", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("accepts a fully valid passage payload as live data", async () => {
    mockFetchResolve(VALID_PASSAGE);
    const result = await getNextPassage("student-1");
    expect(result.source).toBe("live");
    expect(result.data).toEqual(VALID_PASSAGE);
  });

  it("falls back to mock data instead of crashing when a passage payload fails validation (bad grade)", async () => {
    mockFetchResolve({ ...VALID_PASSAGE, grade: 7 });
    const result = await getNextPassage("student-1");
    expect(result.source).toBe("mock");
    expect(console.error).toHaveBeenCalled();
  });

  it("falls back to mock data when a session list entry is missing required fields", async () => {
    // A real kind of contract drift: wcpm/accuracy silently dropped or
    // renamed server-side. Previously this would have been cast straight
    // through as `SessionSummary[]` with `undefined` numeric fields.
    mockFetchResolve([{ id: "s1", passage_id: "p1", started_at: "2026-01-01" }]);
    const result = await getSessions("student-1");
    expect(result.source).toBe("mock");
    expect(console.error).toHaveBeenCalled();
  });

  it("falls back to mock data when a session list entry has the wrong field types", async () => {
    mockFetchResolve([{ ...VALID_SESSION, wcpm: "eighty-two" }]);
    const result = await getSessions("student-1");
    expect(result.source).toBe("mock");
  });

  it("accepts a fully valid mastery payload as live data", async () => {
    mockFetchResolve(VALID_MASTERY);
    const result = await getMastery("student-1");
    expect(result.source).toBe("live");
    expect(result.data).toEqual(VALID_MASTERY);
  });

  it("falls back to mock data when the mastery payload isn't even an array", async () => {
    mockFetchResolve({ not: "an array" });
    const result = await getMastery("student-1");
    expect(result.source).toBe("mock");
  });

  it("accepts a fully valid story map payload as live data", async () => {
    mockFetchResolve(VALID_STORY_MAP);
    const result = await getStoryMap("student-1");
    expect(result.source).toBe("live");
    expect(result.data).toEqual(VALID_STORY_MAP);
  });

  it("falls back to mock data when a story map's nested skill node is malformed", async () => {
    mockFetchResolve({
      categories: [
        {
          category: "phonics",
          skills: [{ skill_id: "x", label: "X", category: "phonics" /* missing weight/passages */ }],
        },
      ],
    });
    const result = await getStoryMap("student-1");
    expect(result.source).toBe("mock");
  });
});
