"""SQLAlchemy ORM mappings for the tables created in migrations/versions/0001.

The migration is the source of truth for constraints; these classes only map columns
so Python code can use typed, parameterised queries instead of string SQL.
"""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

ACTIVE_BOOKING_STATUSES = ("confirmed", "en_route", "in_progress", "completed")
CANCELLED_STATUSES = ("cancelled_by_customer", "cancelled_by_provider")
EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB().with_variant(JSON(), "sqlite")}


class ServiceCategory(Base):
    __tablename__ = "service_categories"
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")


class Locality(Base):
    __tablename__ = "localities"
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)


class Technician(Base):
    __tablename__ = "technicians"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    bio: Mapped[str] = mapped_column(Text, default="")
    years_experience: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Numeric(2, 1), default=4.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")

    categories: Mapped[list["TechnicianCategory"]] = relationship(
        back_populates="technician", cascade="all, delete-orphan", lazy="selectin"
    )
    areas: Mapped[list["TechnicianServiceArea"]] = relationship(
        back_populates="technician", cascade="all, delete-orphan", lazy="selectin"
    )


class TechnicianCategory(Base):
    __tablename__ = "technician_categories"
    technician_id: Mapped[int] = mapped_column(ForeignKey("technicians.id"), primary_key=True)
    category_code: Mapped[str] = mapped_column(ForeignKey("service_categories.code"), primary_key=True)
    visiting_charge_inr: Mapped[int] = mapped_column(Integer)
    technician: Mapped[Technician] = relationship(back_populates="categories")


class TechnicianServiceArea(Base):
    __tablename__ = "technician_service_areas"
    technician_id: Mapped[int] = mapped_column(ForeignKey("technicians.id"), primary_key=True)
    locality_code: Mapped[str] = mapped_column(ForeignKey("localities.code"), primary_key=True)
    technician: Mapped[Technician] = relationship(back_populates="areas")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    technician_id: Mapped[int | None] = mapped_column(ForeignKey("technicians.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class AvailabilitySlot(Base):
    __tablename__ = "availability_slots"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    technician_id: Mapped[int] = mapped_column(ForeignKey("technicians.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class Booking(Base):
    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reference: Mapped[str] = mapped_column(Text, unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    technician_id: Mapped[int] = mapped_column(Integer)
    slot_id: Mapped[int] = mapped_column(BigInteger)
    category_code: Mapped[str] = mapped_column(Text)
    locality_code: Mapped[str] = mapped_column(Text)
    issue_description: Mapped[str] = mapped_column(Text)
    visiting_charge_inr: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text)
    request_fingerprint: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class BookingStatusEvent(Base):
    __tablename__ = "booking_status_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"))
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class PolicyDocument(Base):
    __tablename__ = "policy_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, default="draft")
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str] = mapped_column(Text, default="")
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(Text, default="pending")
    ingestion_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("policy_documents.id", ondelete="CASCADE"))
    chunk_index: Mapped[int] = mapped_column(Integer)
    section_title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str] = mapped_column(Text)
    is_quarantined: Mapped[bool] = mapped_column(Boolean, default=False)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    dataset_version: Mapped[str] = mapped_column(Text, default="")
    artifact_path: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    suite: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    failures: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(Text)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text, default="")
    entity_id: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
