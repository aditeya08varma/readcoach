# Evaluation details

Full evaluation write-up moved here from the README. The headline numbers and their limits are summarized in the README's Evaluation section.

All numbers below come from real runs of `backend/eval/`. Diagnostic accuracy uses hand-labeled test cases with known injected errors, latency uses scripted sessions timed with real Claude calls, and groundedness uses real Claude-generated questions on the real passages. Speech recognition accuracy on children's voices is the next thing to measure.


Real numbers from the last full run of `backend/eval/run_benchmark.py`
(regenerate anytime with `python3 run_benchmark.py` from `backend/eval/`;
also served live at `GET /admin/eval_report` and summarized on the
engineering dashboard). The skill taxonomy grew from 18 to 27 skills (9 new
vocabulary/comprehension skills: word_categories, synonyms_and_antonyms,
multiple_meaning_words, prefixes_and_suffixes_meaning, figurative_language,
character_traits_and_analysis, compare_and_contrast, predicting_outcomes,
authors_purpose) — the numbers below are a fresh run against that current
27-skill scope, not the frozen pre-expansion numbers from an earlier report.

**A note on methodology before the numbers**: an audit re-ran this exact
benchmark against unchanged code multiple times and found that
skill-tagging accuracy, question groundedness, and hint-generation P95
latency all have real, measured run-to-run variance — they depend on live
Claude calls, which are not perfectly deterministic (skill-tagging accuracy
alone read 66.7%, 73.3%, and 100% across three identical runs). Reporting
any one of those runs as *the* number would have been misleading. Those
three metrics are now each computed from multiple independent trials
(`groundedness_eval.py`: 3 trials; `latency_eval.py`: 2, since a full
latency trial is the most expensive real-API-call unit in the harness) and
reported below as **mean (observed range across N runs)**. Diagnostic
accuracy makes no API calls and is fully deterministic, so it is still a
single run — there is nothing to average.

**Diagnostic accuracy** — 105 synthetic sessions with a known, deliberately
injected error each, run through the real alignment engine (no API calls,
deterministic single run). Still phonics-only by design: `alignment.align()`
classifies word-level miscues, which has no equivalent for the 9 new
vocabulary/comprehension skills (see `backend/eval/benchmark_cases.py`'s
scope note) — those are covered by the new skill-gap-identification check
below instead.

**90.5%** overall (95/105) — unchanged from the pre-expansion run, since none
of the 9 new skills touch this code path.

| Category | Accuracy |
|---|---|
| short_vowels, closed_syllables, silent_e, vowel_teams, r_controlled_vowels, diphthongs, compound_words, multisyllabic_decoding, miscue_type | 100% |
| consonant_blends | 90.0% (9/10) |
| consonant_digraphs | 75.0% (6/8) |
| open_syllables | 66.7% (6/9) |
| inflectional_endings | 60.0% (6/10) |

Two categories were genuinely weak in an earlier pass — multisyllabic_decoding
at 33.3% and compound_words at 66.7% — and both are fixed now: long words
("wonderful", "dinosaur") were getting claimed by an incidental r-controlled
or digraph substring before their real length was ever considered, and the
compound-word dictionary was simply missing common grade-1-3 words like
"popcorn"/"football". The two categories still below 100% are left visible
on purpose, not fixed by relaxing the benchmark: **open_syllables** (tiger,
hero, apron) needs a real syllable-boundary model to resolve without
regressing r_controlled_vowels, and **inflectional_endings** is a genuine,
still-open disagreement between two reasonable design philosophies (does
"jumps" belong to its stem's own decoding pattern, or to the suffix a
curriculum unit would actually be teaching with it) — investigated properly,
not fixed by an arbitrary special case; see `backend/eval/benchmark_cases.py`'s
own docstring for the full reasoning on both.

**Question groundedness** — real Claude-generated comprehension questions,
checked by a separate Claude LLM-judge call for whether each is actually
answerable from the passage text. Sample: **17 passages** (51 questions per
trial), one real passage per new skill from `content/passages/`, run **3
independent trials** (real generation + real judging every time):

**90.2% (range: 90.2–90.2% across 3 runs)** — all three trials happened to
land on the same 46/51 questions grounded this time (groundedness is
noisier in general, per the methodology note above, but this particular
sample landed stable). The 5 ungrounded questions found in the most recent
trial all asked a child to infer a character's/author's unstated internal
motivation or an unstated causal mechanism ("why do you think...", "why did
the ball go over the fence...") from a passage that never states the
reason — a real and specific failure mode, not a vague miss. Full list in
`backend/eval/reports/eval_report.json`'s
`question_groundedness_detail.ungrounded_examples`.

**Skill-gap identification** — for each of the 15 vocabulary/comprehension
skills (all vocabulary + comprehension categories; phonics passages are
excluded as not applicable, see `backend/eval/groundedness_eval.py`'s
docstring for why), did at least one of the 3 real generated questions for
that passage get tagged with the passage's own designed `primary_skill`?

**73.3% (range: 66.7–80.0% across 3 runs)** — most recent trial: 10/15
passages. The specific 5 passages that miss their designed tag vary
somewhat trial to trial (real model non-determinism, not a fixed bug), but
the same handful of vocabulary skills keep recurring across trials:
`vocabulary_in_context`, `word_categories`, `prefixes_and_suffixes_meaning`,
`figurative_language`, and `predicting_outcomes` — every generated question
for those passages still lands on a generic comprehension tag
(literal_comprehension/inferential_comprehension/cause_and_effect/etc.)
instead of the passage's own vocabulary skill. So this isn't a
missing-capability bug (the skill is available to pick), it's a model
behavior issue: Claude just doesn't reach for the specific vocabulary tag
as often as the generic comprehension ones. Flagged to `tutor-logic-engineer`
as a prompting problem, not fixed here (`backend/eval` measures the
pipeline, it doesn't tune it) — see `backend/eval/reports/eval_report.json`'s
`question_groundedness_detail.skill_tagging_misses` for the most recent
trial's full list.

**Latency** — real Claude API calls, timed end-to-end through the real
`TutorSession` pipeline code, **2 independent trials** (10 synthetic
sessions each, 20 total):

| Stage | P50 (mean, range) | P95 (mean, range) | n |
|---|---|---|---|
| hint generation | 1148ms (1117–1179ms) | **15445ms (11183–19707ms)** | 20 |
| question generation | 2154ms (2122–2185ms) | 2705ms (2643–2766ms) | 20 |
| answer grading | 1836ms (1804–1869ms) | 2340ms (2251–2428ms) | 80 (includes the one-retry-on-wrong-answer path) |
| **pooled per-call LLM** | **1831ms (1787–1874ms)** | **2659ms (2412–2906ms)** | 120 |

Hint-generation P95 is the headline example of why this fix mattered: one
trial's P95 was 11183ms, the other's was 19707ms — the same real spread an
earlier audit of this exact code path measured (11.6s–19.7s). A single-run
report would have shown whichever of those two numbers happened to run
last and presented it as precise; reporting mean-plus-range instead makes
that swing visible instead of hiding it.

The pooled per-call figure — not a whole session's calls summed back to
back with none of a real session's own reading/thinking/speaking pauses
between them — is what a child actually waits for at any one moment, and is
the number the engineering dashboard uses as its own real fallback when a
given stage doesn't yet have enough live production samples of its own
(the dashboard reads the mean of this figure, a single float, for backward
compatibility with its existing numeric contract; the full range lives in
`eval_report.json`'s `latency_percentiles_detail`).
