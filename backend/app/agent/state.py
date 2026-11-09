from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: int
    title: str
    target_selector: Optional[str] = None
    description: str
    status: str = "pending"  # "pending", "running", "completed", "failed"


class ToolCallRecord(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[str] = None
    success: bool = True
    error: Optional[str] = None


class QualityAudit(BaseModel):
    passed: bool
    score: int = 100
    issues: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class TargetElementInfo(BaseModel):
    mbId: Optional[str] = None
    tag: Optional[str] = None
    selector: Optional[str] = None
    snippet: Optional[str] = None
    outerHtml: Optional[str] = None
    styles: Optional[Dict[str, Any]] = None


class AgentState(BaseModel):
    prompt: str
    current_html: str
    target_element: Optional[TargetElementInfo] = None
    model_name: str = "bonsai-27b"
    project_id: Optional[str] = None
    screen_id: Optional[str] = None

    # Intenção do agente: "explanation" | "surgical_edit" | "layout_repair" | "full_page"
    intent: str = "surgical_edit"

    # Planejamento (quando aplicável)
    plan: List[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0

    # Ferramentas e Execução
    tools_history: List[ToolCallRecord] = Field(default_factory=list)
    accumulated_patch: Optional[str] = None
    patch_type: str = "none"  # "none", "element", "full"
    target_selector: Optional[str] = None
    target_mb_id: Optional[str] = None
    dom_summary: Optional[str] = None

    # Avaliação de Qualidade
    audit: Optional[QualityAudit] = None
    refinement_attempts: int = 0
    max_refinements: int = 2

    # Status Final
    is_complete: bool = False
    error: Optional[str] = None
    final_summary: str = ""
    reasoning: Optional[str] = None
