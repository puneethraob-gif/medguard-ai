"""Add the patient healthcare timeline event index."""
from alembic import op
import sqlalchemy as sa

revision = "0004_healthcare_timeline"
down_revision = "0003_auth_sessions_and_patient_encryption"
branch_labels = None
depends_on = None

EVENT_TYPES = (
    "consultation_scheduled", "consultation_completed", "summary_generated", "summary_approved",
    "prescription_uploaded", "prescription_approved", "medication_schedule_activated", "prescription_updated",
    "medication_course_completed", "medication_started", "medication_completed", "medication_schedule_changed",
    "refill_required", "test_recommended", "test_scheduled", "test_completed", "report_uploaded", "report_reviewed",
    "follow_up_scheduled", "appointment_updated", "appointment_completed", "appointment_cancelled",
)
STATUSES = (
    "scheduled", "pending", "recommended", "pending_review", "active", "updated",
    "completed", "approved", "reviewed", "cancelled", "rejected", "in_progress",
)
MODULES = ("consultation", "prescription", "medicine", "laboratory", "appointment")


def upgrade() -> None:
    op.create_table(
        "timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patient_profiles.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_module", sa.String(length=40), nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"event_type IN ({','.join(repr(value) for value in EVENT_TYPES)})", name="ck_timeline_event_type"),
        sa.CheckConstraint(f"status IN ({','.join(repr(value) for value in STATUSES)})", name="ck_timeline_status"),
        sa.CheckConstraint(f"source_module IN ({','.join(repr(value) for value in MODULES)})", name="ck_timeline_source_module"),
        sa.UniqueConstraint("patient_id", "event_type", "source_module", "source_record_id", name="uq_timeline_source_event"),
    )
    op.create_index("ix_timeline_patient_date", "timeline_events", ["patient_id", "event_date"])
    op.create_index("ix_timeline_patient_type_date", "timeline_events", ["patient_id", "event_type", "event_date"])
    op.create_index("ix_timeline_patient_status_date", "timeline_events", ["patient_id", "status", "event_date"])


def downgrade() -> None:
    op.drop_index("ix_timeline_patient_status_date", table_name="timeline_events")
    op.drop_index("ix_timeline_patient_type_date", table_name="timeline_events")
    op.drop_index("ix_timeline_patient_date", table_name="timeline_events")
    op.drop_table("timeline_events")
