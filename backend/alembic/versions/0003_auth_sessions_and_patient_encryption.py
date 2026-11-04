"""Add revocable auth sessions and encrypt existing patient fields."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from cryptography.fernet import Fernet
import os
revision="0003_auth_sessions_and_patient_encryption"
down_revision="0002_accounts_and_access"
branch_labels=None
depends_on=None
FIELDS=("date_of_birth","phone","emergency_contact_name","emergency_contact_phone","medical_history","allergies")
def upgrade():
    bind=op.get_bind(); inspector=inspect(bind)
    if "auth_sessions" not in inspector.get_table_names():
        op.create_table("auth_sessions",sa.Column("id",sa.String(36),primary_key=True),sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False,index=True),sa.Column("family_id",sa.String(36),nullable=False,index=True),sa.Column("refresh_hash",sa.String(64),nullable=False,unique=True),sa.Column("expires_at",sa.DateTime(timezone=True),nullable=False),sa.Column("revoked_at",sa.DateTime(timezone=True)),sa.Column("replaced_by",sa.String(36)))
    key=os.environ.get("PATIENT_DATA_ENCRYPTION_KEY")
    if not key: raise RuntimeError("Set PATIENT_DATA_ENCRYPTION_KEY before migrating patient data")
    cipher=Fernet(key.encode())
    columns={c["name"] for c in inspector.get_columns("patient_profiles")}
    for field in FIELDS:
        if field not in columns: continue
        rows=bind.execute(sa.text(f"SELECT user_id, {field} FROM patient_profiles WHERE {field} IS NOT NULL")).all()
        for user_id,value in rows:
            try: cipher.decrypt(str(value).encode())
            except Exception: bind.execute(sa.text(f"UPDATE patient_profiles SET {field}=:value WHERE user_id=:id"),{"value":cipher.encrypt(str(value).encode()).decode(),"id":user_id})
def downgrade():
    raise RuntimeError("Downgrade would require restoring a separately backed-up plaintext copy; not supported")

