from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateStudentRequest(BaseModel):
    display_name: str
    grade: Literal[1, 2, 3]


class StudentResponse(BaseModel):
    id: str
    display_name: str
    grade: int


class MasterySkillResponse(BaseModel):
    skill_id: str
    label: str
    category: str
    weight: float


class Passage(BaseModel):
    id: str
    grade: int
    title: str
    source: Optional[str] = None
    text: str
    words: list[str]
    skills: list[str]
    primary_skill: Optional[str] = None
    comprehension_hint_topics: Optional[list[str]] = None


class SelectionReason(BaseModel):
    """Additive, cosmetic explanation of why passage_selection.py picked
    this passage - see docs/FEATURE_IDEAS.md's "why this story" idea. Never
    influences selection itself, only describes it afterward."""
    target_skill_id: Optional[str] = None
    target_skill_label: Optional[str] = None
    # "chosen" added for the story map's explicit pick-a-story flow
    # (docs/FEATURE_IDEAS.md's gameplay ideation) - a real person picked this
    # passage directly rather than the priority-weak/maintenance/fallback
    # rule choosing it automatically.
    mode: Literal["priority_weak", "maintenance", "fallback", "chosen"]
    explanation: str


class NextPassageResponse(Passage):
    """Same fields as Passage, plus two additive optional fields - see
    contracts/api_contract.md's GET /students/{id}/next_passage entry."""
    selection_reason: Optional[SelectionReason] = None
    # Index into `words` for the reading screen's "challenge word" highlight
    # (docs/FEATURE_IDEAS.md's gameplay ideation). None only if the passage
    # has no words at all, which shouldn't happen with real content.
    challenge_word_index: Optional[int] = None


class MapPassageRef(BaseModel):
    """One passage node under a skill on the story map (docs/FEATURE_IDEAS.md's
    gameplay ideation) - just enough to render a tappable node, not the full
    Passage body."""
    id: str
    title: str
    grade: int
    attempted: bool


class MapSkillNode(BaseModel):
    skill_id: str
    label: str
    category: str
    weight: float
    passages: list[MapPassageRef]


class MapCategory(BaseModel):
    category: str
    skills: list[MapSkillNode]


class StoryMapResponse(BaseModel):
    """GET /students/{id}/map - see contracts/api_contract.md. Pure
    aggregation of already-existing data (topological_skill_order, real
    mastery weights, the passage library, real session history) - no new
    data model, no new AI call."""
    categories: list[MapCategory]


class SessionHistoryItem(BaseModel):
    id: str
    passage_id: str
    started_at: str
    wcpm: Optional[float] = None
    accuracy: Optional[float] = None
    self_corrections: int = 0
    # Additive field, see docs/FEATURE_IDEAS.md's "auto-generated parent
    # session recap" idea. None for sessions ingested before this feature
    # existed, or if the recap call failed (best-effort, non-fatal).
    session_recap: Optional[str] = None


# --- Not part of contracts/api_contract.md. See README note in main.py's module
# docstring: this is a stand-in ingestion endpoint until tutor-logic-engineer's
# service writes session rows itself. ---

class Miscue(BaseModel):
    # word/index were required, but an "insertion" (an extra word the child
    # said that isn't in the passage at all) genuinely has neither a
    # reference word nor a reference index - see alignment.py's Miscue
    # construction for that case. A real recording proved this isn't
    # theoretical: any session containing even one insertion sent word=null/
    # index=null here, which failed this schema and silently dropped the
    # ENTIRE session, every skill update included, with only a 422 in a log
    # file nobody was watching (see docs/BUILD_LOG.md).
    word: Optional[str] = None
    index: Optional[int] = None
    type: Literal["substitution", "omission", "insertion", "self_correction"]
    skill_id: Optional[str] = None
    timestamp_ms: Optional[int] = None


class ComprehensionAnswer(BaseModel):
    question: str
    answer_given: str
    correct: bool
    skill_id: Optional[str] = None


class IngestSessionRequest(BaseModel):
    student_id: str
    passage_id: str
    wcpm: Optional[float] = None
    accuracy: Optional[float] = None
    self_corrections: int = 0
    miscues: list[Miscue] = Field(default_factory=list)
    comprehension: list[ComprehensionAnswer] = Field(default_factory=list)
    pipeline_latency_ms: Optional[dict] = None
    # Additive - see docs/FEATURE_IDEAS.md's hint-pacing surfacing idea and
    # contracts/voice_events.md's hint_pending event. Default 0 so older
    # callers that don't send these keep working.
    hints_delayed_count: int = 0
    hints_delayed_self_corrected_count: int = 0


class SkillUpdateResponse(BaseModel):
    skill_id: str
    session_score: float
    old_weight: float
    new_weight: float
    direct: bool


class IngestSessionResponse(BaseModel):
    session_id: str
    updates: list[SkillUpdateResponse]


class LatencyStages(BaseModel):
    stt_ms: Optional[float] = None
    llm_ms: Optional[float] = None
    tts_ms: Optional[float] = None


class EvalSummary(BaseModel):
    diagnostic_accuracy: float
    question_groundedness: float
    sample_size: int


class EngineeringDashboardResponse(BaseModel):
    latency_p50_ms: LatencyStages
    latency_p95_ms: LatencyStages
    eval: EvalSummary
