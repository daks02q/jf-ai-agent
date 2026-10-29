"""adding hnsw index

Revision ID: 3d64d8d72129
Revises: 906b0c5dfd8e
Create Date: 2026-09-15 13:31:00.930505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d64d8d72129'
down_revision: Union[str, Sequence[str], None] = '906b0c5dfd8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "CREATE INDEX document_embeddings_embedding_hnsw_idx "
        "ON document_embeddings USING hnsw ((embedding::halfvec(2048)) halfvec_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX document_embeddings_embedding_hnsw_idx")
