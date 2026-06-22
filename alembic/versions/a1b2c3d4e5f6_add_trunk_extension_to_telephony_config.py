"""add trunk_extension to telephony_config

Revision ID: a1b2c3d4e5f6
Revises: 30f34ea96eda
Create Date: 2026-06-22

Adds trunk_extension column — the short Ozonetel SIP trunk ID (e.g. "525836")
that goes inside the <stream> body XML.  Separate from did_numbers which stores
full E.164 phone numbers used for inbound DID routing.
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "30f34ea96eda"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telephony_config",
        sa.Column("trunk_extension", sa.String(), nullable=True, server_default="525836"),
    )


def downgrade() -> None:
    op.drop_column("telephony_config", "trunk_extension")
