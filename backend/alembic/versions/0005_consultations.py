"""Add consented consultations, encrypted recordings, transcript, summary and approval history."""
from alembic import op
from app.db.models import Base

revision = "0005_consultations"
down_revision = "0004_healthcare_timeline"
branch_labels = None
depends_on = None

TABLE_NAMES = (
    "consultations", "consultation_consents", "consultation_recordings",
    "consultation_transcript_segments", "consultation_summaries", "consultation_approvals",
)


def upgrade() -> None:
    tables = [Base.metadata.tables[name] for name in TABLE_NAMES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    tables = [Base.metadata.tables[name] for name in reversed(TABLE_NAMES)]
    Base.metadata.drop_all(bind=op.get_bind(), tables=tables)
