from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, List, Literal
from datetime import datetime

ProjectRole = Literal["viewer", "commenter", "editor", "admin"]


class UserRegister(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr
    password: str = Field(..., min_length=8)
    organization_name: Optional[str] = "Minha Organização"


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str
    organization_id: str
    is_system_admin: bool = False
    email_verified: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class OrganizationOut(BaseModel):
    id: str
    name: str
    slug: str
    created_at: datetime

    class Config:
        from_attributes = True


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    organization_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = ""
    workspace_id: Optional[str] = None
    visibility: Optional[str] = "private"


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[str] = None
    design_dials: Optional[Dict[str, Any]] = None


class ProjectOut(BaseModel):
    id: str
    workspace_id: str
    owner_id: Optional[str] = None
    name: str
    slug: str
    description: str
    visibility: Optional[str] = "private"
    design_dials: Dict[str, Any]
    entry_screen_id: Optional[str]
    is_archived: bool
    is_published: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DesignImportOut(BaseModel):
    project: ProjectOut
    canvases: int
    screens: int
    warnings: List[str] = []


class ProjectMemberCreate(BaseModel):
    user_id: str
    role: ProjectRole = "editor"


class ProjectMemberOut(BaseModel):
    id: str
    project_id: str
    user_id: str
    role: str
    created_at: datetime
    user_name: Optional[str] = ""
    user_email: Optional[str] = ""

    class Config:
        from_attributes = True


class ProjectVisibilityUpdate(BaseModel):
    visibility: str  # private, org


class ShareLinkCreate(BaseModel):
    expires_in_days: Optional[int] = Field(default=90, ge=0, le=3650)
    password: Optional[str] = Field(default="", max_length=128)
    allow_comments: bool = False


class ShareLinkOut(BaseModel):
    id: str
    project_id: str
    slug: str
    allow_comments: bool
    expires_at: Optional[datetime]
    view_count: int
    has_password: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ScreenCreate(BaseModel):
    name: str = Field(..., min_length=1)
    canvas_id: str
    is_entry: Optional[bool] = False
    screen_kind: Optional[str] = "page"
    device_type: Optional[str] = "desktop"
    width: Optional[int] = 1440
    height: Optional[int] = 900
    html_content: Optional[str] = ""
    css_content: Optional[str] = ""
    js_content: Optional[str] = ""


class ScreenUpdate(BaseModel):
    name: Optional[str] = None
    is_entry: Optional[bool] = None
    screen_kind: Optional[str] = None
    device_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    pos_x: Optional[int] = None
    pos_y: Optional[int] = None
    html_content: Optional[str] = None
    css_content: Optional[str] = None
    js_content: Optional[str] = None
    transition: Optional[str] = None


class ScreenOut(BaseModel):
    id: str
    canvas_id: str
    name: str
    is_entry: bool
    screen_kind: str
    device_type: str
    width: int
    height: int
    pos_x: int
    pos_y: int
    html_content: str
    css_content: str
    js_content: str
    transition: str
    current_revision: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserProfileUpdate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)


class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=10)


class ScreenRevisionOut(BaseModel):
    id: str
    screen_id: str
    revision_number: int
    actor: str
    change_summary: str
    created_at: datetime
    html_content: str
    css_content: str
    js_content: str

    class Config:
        from_attributes = True

