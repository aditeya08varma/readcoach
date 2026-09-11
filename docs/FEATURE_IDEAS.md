# ReadCoach Feature Ideas

This is a menu of additional features layered on top of what is already built. It is not
a plan to redesign anything, and it does not assume any of these get built. The stated
priority for the time left before the September 18 deadline is the eval benchmark and
real child testing first, dashboard and reading screen polish second, and new features
only if time remains after that. Every idea below is written with that order in mind.
Nothing here should be read as a reason to delay the eval or the real testing.

Ideas are grouped into three tiers by effort and by how much they would change the
pitch. For each one: what it is, why it specifically fits ReadCoach rather than being a
generic feature any AI app could bolt on, a rough size (small, medium, large) given the
architecture that already exists, and what it would add to the story told to the judges.

A note on what was deliberately left out. Reading streaks, leaderboards, and competitive
mechanics show up in almost every reading app, including ones cited below for
inspiration, but they are built for apps where many kids use the product at once and
compare themselves to each other. ReadCoach is a one child, one AI tutor experience, and
a leaderboard has no one on it. A branching, choose your own adventure story structure
was also considered and rejected, since the whole comprehension engine is built around
asking questions that are strictly grounded in one fixed passage text, and branching
content would either multiply the content authoring work by a lot or reintroduce the
exact hallucination risk the question generation work went out of its way to test
against and rule out. An offline mode was considered and rejected too, since every part
of the live pipeline, Deepgram, Claude, Cartesia, and Daily, requires an internet
connection by design, so there is no real offline path without a completely different
architecture.

## Tier 1: Quick wins

### Auto-generated parent session recap

**What it is.** At the end of a session, use Claude to turn the already-captured session
data, which skills were practiced, how many mistakes and self-corrections happened, how
comprehension questions went, into two or three warm, plain-language sentences a parent
can read at a glance, for example noting that a child worked on vowel teams today, caught
two of their own mistakes, and understood the story well.

**Why it fits.** Every piece of information this needs is already sitting in the
`POST /sessions` payload defined in `contracts/api_contract.md`, since the miscues,
self-corrections, and comprehension results are all captured there already. This is not
a new data pipeline, it is one more small Claude call over data that already exists,
which matches how the project already uses a faster or cheaper model tier for
lower-stakes moments and a stronger one for the questions that matter more.

**Effort.** Small. One templated prompt, one new small field on the session record, and
a short text block on the parent dashboard.

**Pitch value.** Gives judges a second, very different demo moment: not the live voice
loop, but Claude doing something useful with structured data after the fact. It also
directly answers a question any parent evaluating a tutoring product asks first, which
is what did my kid actually do today, in language a busy parent will actually read.

### "Why this story" explanation on the reading screen

**What it is.** A single sentence shown when a new passage loads, explaining in plain
words why the mastery engine picked this one, for example that it builds on short vowels
because that skill is strong now and vowel teams is the next weak prerequisite in line.

**Why it fits.** The `next_passage` selection logic already has everything this needs:
the student's mastery vector, the prerequisite graph from `content/skill_taxonomy.json`,
and the passage's `primary_skill`. This can likely be pure templating off numbers the
mastery engine already computes, with no new AI call required, since the reasoning is
already deterministic.

**Effort.** Small. Mostly a formatting layer on data that already flows through
`GET /students/{id}/next_passage`.

**Pitch value.** This is the single clearest way to make the mastery model, which is
arguably the most technically interesting part of the whole system, visible to a judge
watching a two minute demo instead of buried in a database table only visible on the
engineering dashboard.

### Cold-start mini diagnostic for a brand-new student

**What it is.** Before a student's very first full passage, a short 30 to 60 second
warm-up where the child reads five or six words chosen to span multiple skill
categories, scored by the same alignment and skill-tagging logic already built, to seed
an initial mastery vector instead of starting every skill at zero.

**Why it fits.** Right now a student with no session history has no meaningful mastery
data, so the very first passage pick is close to a guess. This reuses the exact same
alignment engine and rule-based skill tagging already proven on full passages, just on a
shorter list of words instead of a story. It is also directly relevant to the top
priority of real child testing, since every real child tester will be a cold-start user
on day one, and a better first pick means a more representative first impression during
testing.

**Effort.** Small to medium. Needs a short new word list per grade band and a small
seeding rule for `student_skill_mastery`, but no new scoring logic.

**Pitch value.** Strengthens the "real learner impact" story specifically, since it
shows the team thought about the actual first five minutes a real child spends with
this, not just the steady-state loop.

### Mastery milestone card

**What it is.** A small visual card that appears on the parent dashboard the first time
a skill's mastery weight crosses a threshold like 0.8, naming the skill in plain
language, for example noting that vowel teams is now mastered.

**Why it fits.** This is a light, presentation-only feature, and it is worth being
honest that it is closer to generic edtech polish than a technical differentiator. But
unlike a generic badge system, it is not decorative on its own, since it visualizes a
real number the mastery engine already computed and already tested, rather than an
arbitrary point count invented just to be rewarding.

**Effort.** Small. A threshold check on existing weight data and one dashboard
component.

**Pitch value.** A small, cheap "aww" moment for a demo video, mostly useful as a nice
frame around the parent dashboard rather than as a technical talking point.

## Tier 2: Strong differentiators

### Mastery-aware adaptive hint pacing

**What it is.** Right now the live tutor gives a spoken hint the moment it notices a
real stumble. This would make that decision sensitive to the child's actual mastery
weight for the skill involved: if the skill is already fairly strong, wait a beat longer
before hinting, on the bet the child will self-correct, since self-correction is already
tracked as a positive signal; if the skill is weak, hint sooner, since a struggling
reader stuck on something genuinely new benefits more from fast support than from being
left to flounder.

**Why it fits.** This is the one idea on this list that actually wires two already-built
pieces together in a way they are not wired together yet. The live tutor and the
mastery engine currently only talk to each other at the start (pick a passage) and the
end (report results) of a session. This would make the mastery vector influence a
moment-to-moment decision inside the live conversation itself, which is a deeper and
more technically interesting integration than either piece has shown on its own so far.

**Effort.** Medium. Needs the student's current mastery vector to be available to the
tutor's in-session decision logic, which it is not today, plus a small policy change to
the hint trigger. No new external service and no change to the contracts' shapes, since
`skill_id` is already on every miscue.

**Pitch value.** This is the strongest technical story on the list, because it
demonstrates something more than "we detect mistakes and we track mastery" as two
separate facts. It shows the system actually behaving differently, live, in response to
what it already knows about a specific child, which is the kind of adaptive behavior a
panel of engineers judging AI product work will specifically be listening for.

**Status: built and verified** (see docs/BUILD_LOG.md's "Building three ideas from the
feature ideation pass"). The gap now is that this only ever happens inside a live
session and leaves no visible trace anywhere else - a parent looking at the dashboard,
or a judge who isn't watching the exact right second of a demo video, has no way to
know it ever happened. The follow-on idea directly below is about closing that gap.

### Making the adaptive hint pacing visible outside the live moment it happens

**What it is.** Three ways to surface the decision above once it's made, instead of
leaving it invisible the instant the live session ends, roughly in order of how cheap
each is given what already exists:

1. **A live, in-session visual cue.** The moment the tutor deliberately holds a hint
   back, show a small, distinct state on the reading screen (different from the plain
   "listening" state) - something like a brief "giving you a moment..." cue - so the
   decision is visible in real time, not just inferable from a slightly longer pause.
   This is the version worth building first specifically because it is the one a demo
   video can actually capture happening live, which is exactly the "make the
   intelligence visible" problem this whole feature exists to solve.
2. **A line in the auto-generated parent recap.** The recap generator
   (`backend/mastery/recap_client.py`) already exists and already turns session facts
   into a warm sentence - this only needs one more fact handed to it (how many times a
   hint was held back this session, and how many of those the child then caught
   themselves) for it to say something like "we gave Jordan a moment to catch two
   tricky words on their own today, and they caught one." Cheap specifically because
   the generation plumbing is already built; the only new work is capturing that fact
   in the first place.
3. **An engineering-dashboard metric.** Something like "adaptive hints held back: X%,
   of which Y% resolved on their own" - aimed squarely at the engineering panel, sitting
   naturally next to the existing eval numbers.

**Why it fits.** All three describe the same real, already-computed decision from a
different vantage point (the child, the parent, the engineer) rather than inventing a
new one - consistent with how every other feature on this list turns real numbers into
something visible instead of decorating with a fake one.

**Effort and the design decision, now settled.** The pacing decision currently lives
only as transient in-memory state inside `TutorSession._pending_hint_candidates` during
a session - it is never written anywhere once the session ends. Decided: this becomes
two new, additive columns on `sessions` in `contracts/db_schema.sql` -
`hints_delayed_count` (how many times a hint was queued for the mastery-aware delay
instead of firing immediately) and `hints_delayed_self_corrected_count` (how many of
those resolved on their own before the delay ran out). Plain aggregate counts, not
per-word detail - enough for both the recap sentence and the engineering metric below,
simpler than threading a new per-miscue field through `contracts/voice_events.md`.

Where it plugs in when built: the tally increments inside `state_machine.py`'s existing
`_maybe_hint`/`_fire_ready_pending_hints` logic (once when a hint is delayed, again when
it's cancelled by a reclassification), gets exposed through `to_session_columns()`,
threads through `backend/voice/mastery_client.py`'s `post_completed_session()`, and
lands via the existing `POST /sessions` endpoint - no new endpoint needed.

**Recommendation for later.** Option 1 (live visual cue) first regardless, since it
needs no persistence at all and is the only one that helps the demo video specifically.
Options 2 (recap line) and 3 (engineering metric) can follow together once the two new
columns exist, since both just read the same two numbers.

**Status: the two columns and the underlying tally are built and tested** (see
docs/BUILD_LOG.md). One honest finding from testing this rather than assuming it: a
delayed hint being cancelled by a genuine self-correction is real, correct, tested
code, but empirically close to unreachable in practice with the current aligner - its
self-correction fold only looks at the word immediately following a misread one (well
before a hint would ever be queued for the extra mastery-aware delay in the first
place), and a live experiment feeding a real "child backtracks several words later"
utterance confirmed it reads as two unrelated substitutions, not a self-correction.
So `hints_delayed_self_corrected_count` should be expected to sit at or near zero in
real sessions. `hints_delayed_count` (how many times extra time was given at all) is
the number actually worth building the recap sentence and any engineering metric
around - phrasing that also claims credit for catches that almost never happen would
be the kind of overclaim this project has otherwise tried hard to avoid.

### Echo reading fallback for repeated stumbles

**What it is.** If a child stumbles on the same word or a similar pattern more than a
couple of times in one passage, instead of giving another hint, the tutor offers to read
the line out loud first and has the child repeat it back, a technique called echo or
choral reading, before continuing. This is a well established, evidence-based strategy
in real reading instruction, not an invented gimmick.

**Why it fits.** It reuses the machinery that already exists, Cartesia TTS to speak the
line, Deepgram to hear the repeat, the same alignment engine to check it, with a new
branch in the tutor's turn-taking logic rather than a new capability. It also gives the
project a stronger claim to being grounded in real reading pedagogy, not just a
technically impressive voice demo, which matters given the project already leans on
that grounding for its comprehension question design.

**Effort.** Medium. Requires a new state in the tutor's conversation logic and a trigger
rule based on repeated miscues on similar patterns, both new logic layered on existing
turn handling rather than new infrastructure.

**Pitch value.** Strengthens the "real learner impact" story by name-dropping and
actually implementing a specific, credible reading intervention technique, which reads
as more serious to a judging panel than a purely AI-flavored feature would.

### Natural-language question and answer over a child's reading history

**What it is.** A text box on the parent or teacher dashboard where a caregiver can ask
a plain question like why is my child struggling with silent e, and Claude answers by
pulling the relevant rows from that student's session and mastery history and
summarizing the pattern in plain language, grounded only in that child's actual data.

**Why it fits.** This is deliberately a different shape of AI use than the live voice
loop, a retrieval and summarization task over structured data that already exists in
`sessions` and `student_skill_mastery`, rather than another real-time conversational
feature. Showing two genuinely different technical patterns, live low-latency voice and
grounded retrieval over stored data, is a stronger signal of range than doing more of
the same pattern twice.

**Effort.** Medium. One new backend endpoint that queries existing tables and passes the
result to Claude with a tight prompt restricting it to that student's real data, plus a
small chat-style component on the dashboard.

**Pitch value.** Broadens the technical story beyond voice, which matters for a panel
evaluating for an AI product engineering role specifically, since it shows the same
grounding discipline already proven in the comprehension question work applied to a
completely different kind of interface.

### Teacher or tutor roster view

**What it is.** A dashboard view listing every student a teacher or tutor is
responsible for, sorted by whoever has the weakest current skill or has not read in the
longest time, so an adult managing many children at once can see at a glance who needs
attention.

**Why it fits.** The single-student parent dashboard already renders mastery and session
data per student. A roster view is mostly the same rendering logic run across multiple
students, aggregated rather than reinvented. It also speaks directly to the host of this
hackathon, since Nerdy's actual business is coordinating many tutors across many
students, so a feature built for that exact scenario, rather than only the single-parent
case, is a more specifically relevant pitch to this particular panel than to a generic
AI hackathon.

**Effort.** Medium. Mostly frontend aggregation over data already served per student,
plus one small new endpoint to list students for a given teacher or tutor.

**Pitch value.** A pitch angle aimed specifically at the judges in the room rather than
a generic feature, since it shows the team thought about how this would actually get
used inside a company that runs tutoring at scale, not just inside one family's home.

## Tier 3: Bigger swings

These are only worth considering if the eval, the real testing, and the UI polish are
all genuinely done early, or for a real future version of this product built after the
hackathon.

### AI-generated passages targeted at a specific weak skill

**What it is.** Instead of picking from the fixed library of 20 stories, generate a new,
short, grade-appropriate passage on demand that specifically exercises whatever skill a
child is currently weakest on, checked against the same word-list and comprehension
grounding standards already used for the hand-checked library.

**Why it fits, and why it is risky.** This would remove the current ceiling of a
20-story library, which is a real limitation for any child who uses this for more than
a couple of weeks. But the project already made a deliberate, considered choice to keep
the story library as a small set of files that a person hand-checked line by line,
specifically because a comprehension question that assumes something not actually in
the story would undermine trust in the system, the same reasoning that led to manually
verifying all 15 sample generated questions against real story text earlier in the
build. Generating the passages themselves reopens exactly that risk at a larger scale,
one level earlier in the pipeline, and would need a real validation step, not just a
generation step, before it could be trusted.

**Effort.** Large. This is closer to a new subsystem than a feature: a generation
prompt, a vocabulary and grade-level control mechanism, and an automated or manual
check step before a generated passage is ever put in front of a real child.

**Pitch value.** If it worked and was demonstrably safe, this is the single biggest
"real product" story on this list, since it turns a fixed 20-story demo into something
that could plausibly scale to real ongoing use. It is also the single easiest idea on
this list to demo badly or unsafely if rushed, so it should not be attempted under
hackathon time pressure without the validation step built alongside it.

### Non-diagnostic reading pattern report for teachers or specialists

**What it is.** Over enough sessions, the miscue data already collected could surface
recurring patterns worth a teacher's attention, for example a child who consistently
struggles with a specific vowel pattern across many different stories rather than just
once. This would be presented as a pattern summary for a teacher to look into, never as
a diagnosis of anything.

**Why it fits, and why it needs real caution.** The underlying data already exists and
is already structured by skill, so the summarization itself is not the hard part.
The hard part is that this sits right next to territory, like screening for reading
disabilities, where overclaiming what a hackathon-built tool can actually determine
would be irresponsible, and a comparable product in this space explicitly markets a
dyslexia screening capability built on much more validation than a 17 day build could
produce. Any version of this built here would need very careful, explicit wording that
it flags patterns for a trained adult to look at, and is not a diagnostic tool, and
would ideally get a second opinion from someone with an actual education background
before being shown to any real parent or teacher.

**Effort.** Large, mostly because of the validation and wording care required, not the
engineering.

**Pitch value.** A meaningful real-world impact story if handled carefully, but also the
idea on this list most likely to raise more questions than it answers in a two minute
demo, so it is probably better mentioned as a future direction in a pitch than actually
built and shown.

### Multi-language support

**What it is.** Extending the same live tutoring loop to another language, most likely
Spanish given how common bilingual reading support is in U.S. elementary schools.

**Why it does not fit this timeline.** The entire skill taxonomy, all 18 skills and
their prerequisite chain, is built around English phonics patterns like silent e and
vowel teams that do not map cleanly onto another language's sound system. This is
realistically closer to a second version of the project than a feature added to this
one, and is called out here mainly so it does not get proposed later as if it were a
small addition. It is a legitimate direction for a real post-hackathon product, not for
the next two weeks.

**Effort.** Large, effectively a second content and taxonomy build.

**Pitch value.** Worth a single sentence in a "future directions" slide, not worth
building.

## Summary

If any new feature work happens after the eval, the real testing, and the UI polish are
genuinely finished, the two ideas most worth the remaining time are the "why this story"
explanation, because it is nearly free and makes the most technically interesting part
of the system visible, and mastery-aware adaptive hint pacing, because it is the one
idea that makes two already-built pieces work together in a way that is currently only
true on paper. Everything else on this list is here to be honest about what exists as
an option, not to suggest it all needs to happen.
