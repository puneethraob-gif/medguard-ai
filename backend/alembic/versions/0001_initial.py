"""Initial empty schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # No product tables yet. The migration chain is ready for future schema changes.
    pass

def downgrade() -> None:
    pass
