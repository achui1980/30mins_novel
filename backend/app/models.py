"""Pydantic data models for the novel knowledge-graph pipeline.

Two families of models live here:

1. Extraction models  — what the LLM returns per chunk (ChunkExtraction and its
   members). These feed the merge/dedup layer.
2. Reader-output models — the packaged results served to the frontend
   (SettingCard, LayeredSummary, WorkPackage) plus API status models.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Relationship taxonomy
# ---------------------------------------------------------------------------


class RelationCategory(str, Enum):
    """Fixed relationship categories used for graph coloring / legend."""

    FAMILY = "家人"
    LOVER = "爱人"
    FRIEND = "朋友"
    ENEMY = "敌人"
    MASTER_APPRENTICE = "师徒"
    MASTER_SERVANT = "主仆"
    ALLY = "同盟"
    OTHER = "其他"


# Only these categories carry a meaningful source->target direction (arrow).
DIRECTED_CATEGORIES = {RelationCategory.MASTER_APPRENTICE, RelationCategory.MASTER_SERVANT}


def confidence_label(confidence: float) -> str:
    """Map a confidence score to a provenance label (design §5.3)."""
    if confidence >= 0.9:
        return "EXTRACTED"
    if confidence >= 0.4:
        return "INFERRED"
    return "AMBIGUOUS"


# ---------------------------------------------------------------------------
# Extraction models (LLM structured output, per chunk)
# ---------------------------------------------------------------------------


class Character(BaseModel):
    name: str = Field(description="角色的规范姓名（最常用/最正式的称呼）")
    aliases: list[str] = Field(default_factory=list, description="别名、绰号、代称")
    role: str = Field(default="", description="角色定位，如 主角/反派/配角")
    description: str = Field(default="", description="一句话身份描述")


class Place(BaseModel):
    name: str = Field(description="地点的规范名称")
    description: str = Field(default="", description="地点简介")


class Event(BaseModel):
    summary: str = Field(description="事件的一句话概述")
    chapter: Optional[str] = Field(default=None, description="所属章节标识")
    participants: list[str] = Field(default_factory=list, description="参与角色姓名")
    order_hint: Optional[int] = Field(
        default=None, description="事件在全书中的粗略先后顺序，用于未来时间线"
    )

    @field_validator("chapter", mode="before")
    @classmethod
    def _coerce_chapter_to_str(cls, v):
        # The LLM occasionally emits the chapter id/number as an int (e.g. 2)
        # while the schema declares a string. Coerce rather than skip the block.
        if isinstance(v, (int, float)):
            return str(int(v))
        return v


class Relationship(BaseModel):
    source: str = Field(description="关系源角色姓名")
    target: str = Field(description="关系目标角色姓名")
    category: RelationCategory = Field(description="固定关系类别")
    detail: str = Field(default="", description="关系的自由文本描述")
    evidence: str = Field(default="", description="支持该关系的原文证据/摘录")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="置信度 0-1")


class ChunkExtraction(BaseModel):
    """The structured payload the LLM returns for a single text block."""

    characters: list[Character] = Field(default_factory=list)
    places: list[Place] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)

    @field_validator("characters", "places", "events", "relationships", mode="before")
    @classmethod
    def _coerce_null_to_empty(cls, v):
        # The LLM occasionally returns null (or omits) a list field instead of
        # an empty array. Coerce those to [] so a single block isn't skipped
        # over a benign validation error.
        if v is None:
            return []
        return v


# ---------------------------------------------------------------------------
# Reader-output models (packaged for the frontend)
# ---------------------------------------------------------------------------


class SettingCard(BaseModel):
    title: str
    content: str


class ChapterSummary(BaseModel):
    chapter: str
    title: str = ""
    summary: str


class ArcSummary(BaseModel):
    """A story arc == a graph community/cluster."""

    title: str
    summary: str
    community_id: int
    member_characters: list[str] = Field(default_factory=list)


class LayeredSummary(BaseModel):
    one_liner: str = ""
    story_hook: str = Field(default="", description="30-50字：这本书为什么值得读的钩子")
    overview: str = ""
    arcs: list[ArcSummary] = Field(default_factory=list)
    chapters: list[ChapterSummary] = Field(default_factory=list)


class MainCharacter(BaseModel):
    id: str
    label: str
    description: str = ""
    score: float = 0.0
    mention_count: int = 0


class SuggestedQuestion(BaseModel):
    question: str
    rationale: str = ""


class TimelineEvent(BaseModel):
    """One flattened, chapter-tagged plot event for the interactive timeline (design §4.3)."""

    seq: int
    chapter_id: str
    chapter_title: str
    summary: str
    participants: list[str] = Field(default_factory=list)


class WorkPackage(BaseModel):
    work_id: str
    title: str
    granularity: Literal["quick", "complete"] = "quick"
    layered_summary: LayeredSummary = Field(default_factory=LayeredSummary)
    setting_cards: list[SettingCard] = Field(default_factory=list)
    graph_ref: str = "graph.json"
    main_characters: list[MainCharacter] = Field(default_factory=list)
    suggested_questions: list[SuggestedQuestion] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# API / status models
# ---------------------------------------------------------------------------

Phase = Literal["queued", "parsing", "extracting", "building", "summarizing", "done", "failed"]


class WorkStatus(BaseModel):
    work_id: str
    title: str = ""
    granularity: Literal["quick", "complete"] = "quick"
    phase: Phase = "queued"
    progress: float = 0.0  # 0..1, meaningful mainly during "extracting"
    message: str = ""
    error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class WorkListItem(BaseModel):
    work_id: str
    title: str
    phase: Phase
    granularity: Literal["quick", "complete"] = "quick"


class CreateWorkResponse(BaseModel):
    work_id: str
    status: Literal["queued"] = "queued"
