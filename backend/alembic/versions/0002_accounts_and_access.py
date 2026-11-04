"""Create identity, patient access, consent, hospital and audit tables."""
from alembic import op
from app.db.models import Base
revision = "0002_accounts_and_access"
down_revision = "0001_initial"
branch_labels = None
depends_on = None
def upgrade() -> None:
    # This revision predates timeline_events. Keep it stable when current ORM
    # metadata grows; the dedicated 0004 migration owns that table.
    tables = [table for table in Base.metadata.sorted_tables if table.name not in {
        "timeline_events", "consultations", "consultation_consents", "consultation_recordings",
        "consultation_transcript_segments", "consultation_summaries", "consultation_approvals",
    }]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)
def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
