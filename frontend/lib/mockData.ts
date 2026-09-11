// Realistic mock data matching the exact response shapes in
// contracts/api_contract.md. Passage text/words below are copied verbatim from
// real files under content/passages/ so the reading screen and word-highlight
// logic are exercised against real content, not lorem ipsum.
//
// This file is the *only* place that needs to change if we want richer/more
// varied demo data — lib/api.ts just calls these as its fallback path.

import type {
  EngineeringDashboard,
  MasterySkill,
  MapCategory,
  Passage,
  SessionSummary,
  StoryMap,
  Student,
} from "./types";

// Real gap found from a real screen recording (see docs/BUILD_LOG.md): this
// id used to be a placeholder string that was never a real student ("demo-
// student-1"), while backend/voice independently created and remembered a
// completely different real demo student of its own - the dashboards could
// never show a real voice session's results no matter how many ran, since
// neither side ever asked about the same row. This is now the same
// well-known, shared id both sides get-or-create via GET /students/demo on
// the mastery service, so a real session posted by the voice bot and a
// dashboard load from this frontend are finally talking about one student.
export const MOCK_STUDENT: Student = {
  id: "00000000-0000-0000-0000-000000000001",
  display_name: "Jordan",
  grade: 2,
};

export const MOCK_PASSAGES: Passage[] = [
  {
    id: "g1-short-vowels-001",
    grade: 1,
    title: "Pat and the Big Hat",
    source: "original",
    text: "Pat has a big hat. The hat is red. Pat runs to the pond. A duck sits on a log. Pat pets the duck. The duck likes Pat. Pat and the duck sit in the sun.",
    words: [
      "Pat", "has", "a", "big", "hat", "The", "hat", "is", "red", "Pat",
      "runs", "to", "the", "pond", "A", "duck", "sits", "on", "a", "log",
      "Pat", "pets", "the", "duck", "The", "duck", "likes", "Pat", "Pat",
      "and", "the", "duck", "sit", "in", "the", "sun",
    ],
    skills: ["short_vowels"],
    primary_skill: "short_vowels",
    comprehension_hint_topics: [
      "what color the hat is",
      "why the duck likes Pat",
    ],
    selection_reason: {
      target_skill_id: "short_vowels",
      target_skill_label: "Short Vowel Sounds",
      mode: "priority_weak",
      explanation:
        "This story practices Short Vowel Sounds, a skill that's still developing.",
    },
    // Matches the real backend's pick_challenge_word_index() run against
    // this exact word list, so mock and live modes agree.
    challenge_word_index: 0, // "Pat"
  },
  {
    id: "g2-vowel-teams-001",
    grade: 2,
    title: "The Boat Trip",
    source: "original",
    text: "Dean and his team paddled their boat down the stream. They saw a deer near the trees. Rain began to fall, so they wore their raincoats. Soon they reached the pier and tied up the boat. Dean and his team ate a snack of bread and cheese before heading home.",
    words: [
      "Dean", "and", "his", "team", "paddled", "their", "boat", "down", "the",
      "stream", "They", "saw", "a", "deer", "near", "the", "trees", "Rain",
      "began", "to", "fall", "so", "they", "wore", "their", "raincoats",
      "Soon", "they", "reached", "the", "pier", "and", "tied", "up", "the",
      "boat", "Dean", "and", "his", "team", "ate", "a", "snack", "of",
      "bread", "and", "cheese", "before", "heading", "home",
    ],
    skills: ["vowel_teams", "consonant_blends"],
    primary_skill: "vowel_teams",
    comprehension_hint_topics: [
      "what the team saw near the trees",
      "why they wore raincoats",
    ],
    selection_reason: {
      target_skill_id: "vowel_teams",
      target_skill_label: "Vowel Teams",
      mode: "priority_weak",
      explanation:
        "This story builds on Short Vowel Sounds, which is going well, and practices Vowel Teams next.",
    },
    challenge_word_index: 0, // "Dean" - matches classify_skill_for_word's real output
  },
  {
    id: "g3-inferential-001",
    grade: 3,
    title: "The Fox and the Grapes",
    source: "Adapted from Aesop's Fables (public domain)",
    text: 'A hungry fox spotted a bunch of plump, juicy grapes hanging from a high vine. He leaped again and again, stretching as far as he could, but the grapes stayed just out of reach. After many tries, his legs grew tired and his sides ached. Finally, the fox stepped back, sniffed at the vine, and muttered, "Those grapes are probably sour anyway. I didn\'t want them." He turned and walked away, holding his head high as if nothing had happened.',
    words: [
      "A", "hungry", "fox", "spotted", "a", "bunch", "of", "plump", "juicy",
      "grapes", "hanging", "from", "a", "high", "vine", "He", "leaped",
      "again", "and", "again", "stretching", "as", "far", "as", "he",
      "could", "but", "the", "grapes", "stayed", "just", "out", "of",
      "reach", "After", "many", "tries", "his", "legs", "grew", "tired",
      "and", "his", "sides", "ached", "Finally", "the", "fox", "stepped",
      "back", "sniffed", "at", "the", "vine", "and", "muttered", "Those",
      "grapes", "are", "probably", "sour", "anyway", "I", "didn't", "want",
      "them", "He", "turned", "and", "walked", "away", "holding", "his",
      "head", "high", "as", "if", "nothing", "had", "happened",
    ],
    skills: ["inferential_comprehension", "literal_comprehension"],
    primary_skill: "inferential_comprehension",
    comprehension_hint_topics: [
      "why the fox really said the grapes were sour",
      "how the fox actually felt about not reaching the grapes",
    ],
    selection_reason: {
      target_skill_id: "inferential_comprehension",
      target_skill_label: "Inferential Comprehension",
      mode: "priority_weak",
      explanation:
        "This story practices Inferential Comprehension, a skill that's still developing.",
    },
    // Comprehension skills are never classifier output (phonics-only), so
    // the real backend falls back to the longest word - "stretching".
    challenge_word_index: 20,
  },
];

export function mockNextPassage(studentId: string): Passage {
  // Stand-in for the mastery-engine's passage-selection rule: just rotate
  // through the sample set deterministically by student id so the demo is
  // reproducible.
  const idx =
    Math.abs(hashString(studentId)) % MOCK_PASSAGES.length;
  return MOCK_PASSAGES[idx];
}

export function mockPassageById(id: string): Passage | undefined {
  return MOCK_PASSAGES.find((p) => p.id === id);
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h << 5) - h + s.charCodeAt(i);
    h |= 0;
  }
  return h;
}

// 12 sessions over the last ~6 weeks with a gentle upward wcpm/accuracy trend
// so the fluency trend line has something meaningful to show.
export function mockSessions(studentId: string): SessionSummary[] {
  const passageIds = MOCK_PASSAGES.map((p) => p.id);
  const now = Date.now();
  const sessions: SessionSummary[] = [];
  for (let i = 11; i >= 0; i--) {
    const daysAgo = i * 4 + Math.round(Math.random() * 2);
    const startedAt = new Date(now - daysAgo * 24 * 60 * 60 * 1000);
    const progress = (11 - i) / 11; // 0 -> 1 across the series
    const wcpm = Math.round(38 + progress * 34 + (Math.random() * 6 - 3));
    const accuracy = Math.min(
      0.99,
      Math.round((0.82 + progress * 0.14 + (Math.random() * 0.04 - 0.02)) * 100) /
        100
    );
    const selfCorrections = Math.round(Math.random() * 4);
    sessions.push({
      id: `${studentId}-session-${i}`,
      passage_id: passageIds[(11 - i) % passageIds.length],
      started_at: startedAt.toISOString(),
      wcpm,
      accuracy,
      self_corrections: selfCorrections,
      // Only the most recent session gets a recap in mock data, matching
      // the real backend (recap is generated going forward, not backfilled
      // for old sessions) - see docs/FEATURE_IDEAS.md's recap idea.
      session_recap:
        i === 0
          ? `Today your child read for ${wcpm} words per minute with ${Math.round(
              accuracy * 100
            )}% accuracy and caught ${selfCorrections} of their own mistakes along the way. Keep up the great practice!`
          : null,
    });
  }
  return sessions;
}

// Mastery vector across the real skill taxonomy (content/skill_taxonomy.json),
// weighted so early phonics skills are further along than later comprehension
// skills — a plausible profile for a grade-2 reader.
export function mockMastery(_studentId: string): MasterySkill[] {
  const skills: Array<[string, string, MasterySkill["category"], number]> = [
    ["short_vowels", "Short Vowel Sounds", "phonics", 0.92],
    ["consonant_blends", "Consonant Blends", "phonics", 0.85],
    ["consonant_digraphs", "Consonant Digraphs", "phonics", 0.8],
    ["closed_syllables", "Closed Syllables", "phonics", 0.78],
    ["silent_e", "Silent-E (VCe) Pattern", "phonics", 0.7],
    ["vowel_teams", "Vowel Teams", "phonics", 0.55],
    ["r_controlled_vowels", "R-Controlled Vowels", "phonics", 0.48],
    ["diphthongs", "Diphthongs", "phonics", 0.4],
    ["open_syllables", "Open Syllables", "phonics", 0.5],
    ["inflectional_endings", "Inflectional Endings (-s, -ed, -ing)", "phonics", 0.66],
    ["compound_words", "Compound Words", "phonics", 0.6],
    ["multisyllabic_decoding", "Multisyllabic Word Decoding", "phonics", 0.3],
    ["vocabulary_in_context", "Vocabulary in Context", "vocabulary", 0.42],
    ["literal_comprehension", "Literal Comprehension", "comprehension", 0.58],
    ["sequencing", "Sequencing Events", "comprehension", 0.35],
    ["cause_and_effect", "Cause and Effect", "comprehension", 0.3],
    ["inferential_comprehension", "Inferential Comprehension", "comprehension", 0.22],
    ["main_idea_and_summarizing", "Main Idea and Summarizing", "comprehension", 0.15],
  ];
  return skills.map(([skill_id, label, category, weight]) => ({
    skill_id,
    label,
    category,
    weight,
  }));
}

// Story map (docs/FEATURE_IDEAS.md's gameplay ideation) - derived from the
// same mockMastery() weights and MOCK_PASSAGES above, in the same order
// mockMastery() already lists them (foundational skills first), so mock and
// live modes tell a consistent story rather than showing different numbers
// in different screens.
export function mockStoryMap(): StoryMap {
  const skills = mockMastery("mock");
  const categoryOrder: MapCategory["category"][] = [
    "phonics",
    "vocabulary",
    "comprehension",
  ];
  const categories = categoryOrder
    .map((category) => ({
      category,
      skills: skills
        .filter((s) => s.category === category)
        .map((s) => ({
          skill_id: s.skill_id,
          label: s.label,
          category: s.category,
          weight: s.weight,
          passages: MOCK_PASSAGES.filter((p) => p.primary_skill === s.skill_id).map(
            (p) => ({
              id: p.id,
              title: p.title,
              grade: p.grade,
              // Deterministic stand-in for "has this student read it before":
              // the mock fluency trend already has 12 past sessions, so
              // treat any passage that appears in that rotation as attempted.
              attempted: MOCK_PASSAGES.indexOf(p) < 2,
            })
          ),
        })),
    }))
    .filter((c) => c.skills.length > 0);
  return { categories };
}

export function mockEngineeringDashboard(): EngineeringDashboard {
  return {
    latency_p50_ms: { stt_ms: 210, llm_ms: 480, tts_ms: 140 },
    latency_p95_ms: { stt_ms: 410, llm_ms: 890, tts_ms: 260 },
    eval: {
      diagnostic_accuracy: 0.87,
      question_groundedness: 0.91,
      sample_size: 64,
    },
  };
}
