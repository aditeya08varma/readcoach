"""Real per-stage pipeline latency, captured from Pipecat's own metrics
system instead of guessed from frame arrival order.

Real gap found and already documented in backend/mastery/main.py and
backend/eval/latency_eval.py: `pipeline_latency_ms` has never once been
populated on a real session, because nothing in this bot measured stt_ms
or tts_ms at all - only llm_ms, and only offline in the eval harness's own
benchmark, never on an actual live session. `TutorProcessor` sits AFTER
Deepgram STT and BEFORE Cartesia TTS in the pipeline (see bot.py), so it
never directly observes either service's own request/response timing -
by the time a `TranscriptionFrame` reaches it, STT has already finished.

`PipelineParams(enable_metrics=True)` (already set in bot.py) already
makes `DeepgramSTTService` and `CartesiaTTSService` emit real
`TTFBMetricsData` (time-to-first-byte) for every request they make.
`LatencyObserver` is a Pipecat `BaseObserver` - it watches every frame
pushed anywhere in the pipeline, regardless of which processor sits where
- so it can see those real TTFB samples without needing to sit between
the transport and either service itself.

LLM timing is captured separately, since TutorProcessor calls Claude
directly (`TutorLLMClient`) rather than through a Pipecat-native LLM
service, invisible to Pipecat's own metrics. `TimingLLMClient` reuses the
exact same wrap-and-stopwatch pattern already proven in
backend/eval/latency_eval.py's `TimingLLMClient` (not reimplemented, just
reused here for the live pipeline instead of an offline benchmark).
"""

from __future__ import annotations

import time
from statistics import median

from pipecat.frames.frames import MetricsFrame
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed


class LatencyObserver(BaseObserver):
    """Buckets real STT/TTS TTFB samples (milliseconds) for one session.

    One instance is created per bot session (see bot.py) - samples are not
    reset between sessions because a fresh instance is used for each.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.stt_samples_ms: list[float] = []
        self.tts_samples_ms: list[float] = []

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if not isinstance(frame, MetricsFrame):
            return
        for metrics_data in frame.data:
            if not isinstance(metrics_data, TTFBMetricsData):
                continue
            # Matched by class name substring rather than an exact class
            # reference, so this doesn't need its own import of the two
            # service classes just to do an isinstance-style check - the
            # `processor` field is always the service's own class name
            # (see pipecat.metrics.metrics.MetricsData).
            name = metrics_data.processor or ""
            if "Deepgram" in name or "STT" in name:
                self.stt_samples_ms.append(metrics_data.value * 1000)
            elif "Cartesia" in name or "TTS" in name:
                self.tts_samples_ms.append(metrics_data.value * 1000)

    def stt_ms(self) -> float | None:
        return round(median(self.stt_samples_ms), 1) if self.stt_samples_ms else None

    def tts_ms(self) -> float | None:
        return round(median(self.tts_samples_ms), 1) if self.tts_samples_ms else None


class TimingLLMClient:
    """Wraps a real `TutorLLMClient`, delegating every call to it unchanged,
    while recording real wall-clock latency for each call. Same
    wrap-and-stopwatch shape as backend/eval/latency_eval.py's
    TimingLLMClient (hint/question-generation/grading all folded into one
    `llm_samples_ms` list here, since the engineering dashboard's chart has
    one LLM column, not three - the eval harness's own report is still the
    place to look for the finer per-call-kind breakdown).
    """

    def __init__(self, real_client) -> None:
        self._real = real_client
        self.llm_samples_ms: list[float] = []

    async def generate_hint(self, **kwargs):
        return await self._timed(self._real.generate_hint, **kwargs)

    async def generate_questions(self, **kwargs):
        return await self._timed(self._real.generate_questions, **kwargs)

    async def grade_answer(self, **kwargs):
        return await self._timed(self._real.grade_answer, **kwargs)

    async def is_answer_complete(self, **kwargs):
        return await self._timed(self._real.is_answer_complete, **kwargs)

    async def _timed(self, fn, **kwargs):
        t0 = time.perf_counter()
        result = await fn(**kwargs)
        self.llm_samples_ms.append((time.perf_counter() - t0) * 1000)
        return result

    def llm_ms(self) -> float | None:
        return round(median(self.llm_samples_ms), 1) if self.llm_samples_ms else None
