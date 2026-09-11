# ReadCoach demo video — script and shot list

Target length: 2:30-3:00, matching the original build plan's own Stage 8 target.
Structure: live interaction carries the video; narration is minimal text
overlays, not a voiceover talking over everything — the coach's real voice
and the reader's real voice are the actual proof this works.

## Before you hit record

1. Run `./dev.sh` from the repo root, wait for all four services to report
   ready, open `http://localhost:3000` in a clean browser window (log in as
   a real account, not the demo/mock fallback — the badge in the top corner
   should say "Live data", not "Mock data").
2. Pick the passage now, not live: **"Pat and the Big Hat"** (grade 1,
   36 words, short_vowels) is short enough to read in full on camera without
   dragging, and simple enough that a deliberate stumble reads as natural,
   not staged. If you want a slightly longer beat, **"Brad and the Frog"**
   (39 words) works the same way.
3. Decide your one deliberate stumble in advance and rehearse it once so it
   sounds like a genuine misread, not a performance — e.g. read "Pat" as
   "Path" or skip a word entirely. The alignment engine will catch it either
   way; you don't need to oversell it.
4. Clear your dashboard/map screens of any earlier test data if you want a
   clean "Not started yet" story, or leave real history in if you want the
   demo to show an established mastery trend — both are honest, pick based
   on which beat you want act 4 to tell.

## Recording setup (Mac)

Screen + mic + the coach's own TTS audio all need to end up in one file.
QuickTime's screen recording alone won't do this cleanly (it captures
either system audio or mic, not both mixed together). Two real options:

- **OBS Studio** (free): add a Display Capture source for the screen, an
  Audio Input Capture source for your mic, and an Audio Output Capture
  source for system audio (the coach's TTS). Mix levels so your voice and
  the coach's voice are both clearly audible — test one full exchange
  before recording for real.
- **QuickTime + a virtual audio device** (BlackHole or Loopback): route
  system audio into BlackHole, aggregate it with your mic into one input
  device in Audio MIDI Setup, then record screen with that aggregate device
  as the audio source in QuickTime.

Record at 1080p minimum. Do one full silent dry run first to confirm mic
levels, browser zoom level (125-150% often reads better on camera than
100%), and that no other tab/notification can interrupt.

## The script

**[0:00-0:12] Cold open — no narration, just the product**

Show the home screen. The penguin waves. Click "Start Reading" for real —
let the confetti/pop happen, let the transition to the reading screen play
out at its own natural speed. Don't cut this short; a beat of genuine polish
up front sets the tone before anything technical happens.

> On-screen text only, no voiceover yet: *"ReadCoach — a live voice AI
> reading tutor. Not a recording. A real conversation."*

**[0:12-0:55] The actual read — this is the whole pitch**

Read "Pat and the Big Hat" out loud into the mic, at a natural pace. Let the
live word highlighting run exactly as it happens — don't narrate over it,
let the audience watch words light up in real time as you say them. Hit
your one rehearsed stumble partway through. Keep reading through it exactly
like a real kid would — don't stop, don't apologize to the camera, just
finish the passage. This is the single most important 40 seconds of the
whole video: it's the only thing a recorded, edited demo can't fake.

> Text overlay, appears briefly and fades, doesn't block the UI: *"Deepgram
> streaming STT + a custom word-alignment engine — tagging every miscue by
> skill, live, as it happens."*

**[0:55-1:20] The review — the coach teaches, warmly, once**

Passage finishes. Let the coach's own real spoken review play — it will
name the word you stumbled on and ask you to say it again. Say it back
correctly. Don't rush this; the point being made here is specifically that
the tutor teaches once, in a calm pass, instead of interrupting mid-read —
that pacing decision only reads as real if you let a real silence happen
around it.

> Text overlay: *"Every real stumble taught once, after the full passage —
> not interrupted mid-sentence."*

**[1:20-1:55] Comprehension, spoken and graded, out loud**

Let the first comprehension question play. Answer it out loud, genuinely,
including a natural pause mid-sentence like you're actually thinking (this
is what lets the video honestly show the completion-gating feature working —
the coach should NOT jump in while you're still mid-thought). Let the
spoken grading feedback play in full before cutting.

> Text overlay: *"A fast Claude call judges when an answer is actually
> finished — not a fixed silence timeout, so a thinking pause never gets
> cut off."*

**[1:55-2:15] The map — what happens next, and why**

Cut to the story map. Show the winding path, the "up next" node with its
own waving penguin, and narrate ONE sentence live (this is the one place a
short voiceover earns its keep, since the adaptive-selection logic isn't
otherwise visible):

> Spoken or on-screen: *"The next story isn't random — it's picked from a
> real per-skill mastery model, always targeting the weakest foundational
> skill first."*

**[2:15-2:40] The dashboards — proof, not just polish**

Two quick cuts, 8-10 seconds each:
1. Parent dashboard: fluency trend chart, skill mastery bars, the day's
   recap sentence.
2. Engineering dashboard: the real per-stage latency chart, and the eval
   scores tile. Let the real numbers sit on screen long enough to read:

> On-screen text, numbers pulled live from the actual dashboard, not typed
> in post: **90.5% diagnostic accuracy · 91.7% question groundedness ·
> ~2s median LLM response time.**
>
> Spoken or on-screen: *"Measured, not claimed — an automated benchmark
> checks this pipeline against known errors and re-runs itself."*

**[2:40-2:55] Close**

Cut back to the home screen or a simple title card.

> On-screen text: *"ReadCoach — built for the Nerdy AI Hackathon. Full
> writeup, architecture, and these exact numbers: [your repo URL]."*

## What NOT to do

- Don't voiceover-narrate the entire video top to bottom — it makes a real
  live product feel like a slideshow. Let the coach's real TTS voice and
  your real reading voice carry the middle two acts entirely.
- Don't cut out every pause. A little real latency and a little real
  silence is what makes the rest of it credible as live, not scripted.
- Don't reset to a perfect, error-free read. The one deliberate stumble is
  the whole point — it's the only way to actually show the diagnostic and
  teaching loop working, not just described.
- Don't show the eval numbers as a screenshot pasted in after the fact —
  record the actual dashboard rendering them live, in the same take style
  as everything else, so it reads as the same real product, not a separate
  slide deck bolted onto the end.

## After recording

Trim dead air at the very start/end only. Keep the two feature callouts
(review pacing, completion-gating) as real text overlays layered on top of
the live footage, not as separate cutaway slides — the goal is one
continuous, credible take of a real session, not a highlight reel of
disconnected clips.
