import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    BigInteger,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    workspaces = relationship("Workspace", back_populates="organization", cascade="all, delete-orphan")
    ai_providers = relationship("AIProvider", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), default="editor", nullable=False)  # owner, admin, editor, viewer
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="users")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(Text, unique=True, nullable=False, index=True)
    csrf_token = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="workspaces")
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_workspace_org_slug"),)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=False)
    design_dials = Column(JSONB, default={"variance": 7, "motion": 4, "density": 4}, nullable=False)
    entry_screen_id = Column(String(36), nullable=True)  # Referência da tela principal para o CEO/Apresentação
    is_archived = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="projects")
    tokens = relationship("DesignTokens", back_populates="project", uselist=False, cascade="all, delete-orphan")
    canvases = relationship("Canvas", back_populates="project", cascade="all, delete-orphan", order_by="Canvas.sort_order")


class DesignTokens(Base):
    __tablename__ = "design_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)
    light_tokens = Column(JSONB, default=dict, nullable=False)
    dark_tokens = Column(JSONB, default=dict, nullable=False)
    shared_tokens = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="tokens")


class Canvas(Base):
    __tablename__ = "canvases"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    entry_screen_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    project = relationship("Project", back_populates="canvases")
    screens = relationship("Screen", back_populates="canvas", cascade="all, delete-orphan")
    scenarios = relationship("DataScenario", back_populates="canvas", cascade="all, delete-orphan")


class Screen(Base):
    __tablename__ = "screens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    canvas_id = Column(String(36), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    is_entry = Column(Boolean, default=False, nullable=False)  # ⭐ Tela Principal
    screen_kind = Column(String(50), default="page", nullable=False)  # page, subpage, modal_overlay
    device_type = Column(String(50), default="desktop", nullable=False)  # desktop, tablet, mobile, custom
    width = Column(Integer, default=1440, nullable=False)
    height = Column(Integer, default=900, nullable=False)
    pos_x = Column(Integer, default=0, nullable=False)
    pos_y = Column(Integer, default=0, nullable=False)
    html_content = Column(Text, default="", nullable=False)
    css_content = Column(Text, default="", nullable=False)
    js_content = Column(Text, default="", nullable=False)
    transition = Column(String(50), default="none", nullable=False)  # none, fade, slide-left
    current_revision = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    canvas = relationship("Canvas", back_populates="screens")
    comments = relationship("Comment", back_populates="screen", cascade="all, delete-orphan")
    revisions = relationship("ScreenRevision", back_populates="screen", cascade="all, delete-orphan")


class ScreenRevision(Base):
    __tablename__ = "screen_revisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    screen_id = Column(String(36), ForeignKey("screens.id", ondelete="CASCADE"), nullable=False, index=True)
    revision_number = Column(Integer, nullable=False)
    html_content = Column(Text, nullable=False)
    css_content = Column(Text, nullable=False)
    js_content = Column(Text, nullable=False)
    change_summary = Column(String(255), default="", nullable=False)
    actor = Column(String(255), default="user", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    screen = relationship("Screen", back_populates="revisions")


class DataScenario(Base):
    __tablename__ = "data_scenarios"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    canvas_id = Column(String(36), ForeignKey("canvases.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # default, vazio, erro, critico
    mock_data = Column(JSONB, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    canvas = relationship("Canvas", back_populates="scenarios")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    screen_id = Column(String(36), ForeignKey("screens.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name = Column(String(255), default="Anônimo", nullable=False)
    element_mb_id = Column(String(255), default="", nullable=False)  # data-mb-id do elemento clicado
    element_snippet = Column(Text, default="", nullable=False)
    pin_x = Column(Float, default=0.0, nullable=False)  # porcentagem relativa X
    pin_y = Column(Float, default=0.0, nullable=False)  # porcentagem relativa Y
    body = Column(Text, nullable=False)
    status = Column(String(50), default="open", nullable=False)  # open, resolved
    replies = Column(JSONB, default=list, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    screen = relationship("Screen", back_populates="comments")


class AIProvider(Base):
    __tablename__ = "ai_providers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_type = Column(String(50), nullable=False)  # mockbird_cloud, openai, anthropic, gemini, openrouter, ollama
    encrypted_api_key = Column(Text, default="", nullable=False)
    default_model = Column(String(100), default="", nullable=False)
    base_url = Column(Text, default="", nullable=False)
    custom_models = Column(JSONB, default=list, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    monthly_token_limit = Column(BigInteger, default=1000000, nullable=False)
    tokens_used_month = Column(BigInteger, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="ai_providers")

