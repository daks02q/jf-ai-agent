"""add fts search vector

Revision ID: 906b0c5dfd8e
Revises: 9c4dd432bd8d
Create Date: 2026-09-15 13:01:26.886101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql



# revision identifiers, used by Alembic.
revision: str = '906b0c5dfd8e'
down_revision: Union[str, Sequence[str], None] = '9c4dd432bd8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "document_embeddings",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', coalesce(chunk_text, ''))", persisted=True),
            nullable=True,
        )
    )
    op.create_index(
           "ix_document_embeddings_search_vector",
           "document_embeddings",
           ["search_vector"],
           postgresql_using="gin",
       )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_document_embeddings_search_vector", table_name="document_embeddings")
    op.drop_column("document_embeddings", "search_vector")
