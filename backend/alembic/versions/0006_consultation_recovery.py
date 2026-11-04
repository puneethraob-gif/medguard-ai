"""Persist provider job IDs and bounded transcription recovery state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_consultation_recovery"
down_revision = "0005_consultations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("consultation_recordings")}
    if "provider_job_id" not in columns:
        op.add_column("consultation_recordings", sa.Column("provider_job_id", sa.String(length=100), nullable=True))
    if "audio_deleted_at" not in columns:
        op.add_column("consultation_recordings", sa.Column("audio_deleted_at", sa.DateTime(timezone=True), nullable=True))
    if "provider_job_terminal" not in columns:
        op.add_column("consultation_recordings", sa.Column("provider_job_terminal", sa.Boolean(), server_default=sa.false(), nullable=False))
    if "provider_job_uploaded" not in columns:
        op.add_column("consultation_recordings", sa.Column("provider_job_uploaded", sa.Boolean(), server_default=sa.false(), nullable=False))
    if "provider_job_started" not in columns:
        op.add_column("consultation_recordings", sa.Column("provider_job_started", sa.Boolean(), server_default=sa.false(), nullable=False))
    indexes = {index.get("name") for index in inspector.get_indexes("consultation_recordings")}
    if "uq_consultation_recording_provider_job" not in indexes:
        op.create_index("uq_consultation_recording_provider_job", "consultation_recordings", ["provider_job_id"], unique=True)
    if "transcription_claimed_at" not in columns:
        op.add_column("consultation_recordings", sa.Column("transcription_claimed_at", sa.DateTime(timezone=True), nullable=True))
    if "transcription_queued_at" not in columns:
        op.add_column("consultation_recordings", sa.Column("transcription_queued_at", sa.DateTime(timezone=True), nullable=True))
    if "transcription_attempts" not in columns:
        op.add_column("consultation_recordings", sa.Column("transcription_attempts", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("consultation_recordings")}
    if "transcription_attempts" in columns: op.drop_column("consultation_recordings", "transcription_attempts")
    if "provider_job_terminal" in columns: op.drop_column("consultation_recordings", "provider_job_terminal")
    if "provider_job_started" in columns: op.drop_column("consultation_recordings", "provider_job_started")
    if "provider_job_uploaded" in columns: op.drop_column("consultation_recordings", "provider_job_uploaded")
    if "audio_deleted_at" in columns: op.drop_column("consultation_recordings", "audio_deleted_at")
    if "transcription_claimed_at" in columns: op.drop_column("consultation_recordings", "transcription_claimed_at")
    if "transcription_queued_at" in columns: op.drop_column("consultation_recordings", "transcription_queued_at")
    indexes = {index.get("name") for index in inspect(op.get_bind()).get_indexes("consultation_recordings")}
    if "uq_consultation_recording_provider_job" in indexes:
        op.drop_index("uq_consultation_recording_provider_job", table_name="consultation_recordings")
    if "provider_job_id" in columns: op.drop_column("consultation_recordings", "provider_job_id")
