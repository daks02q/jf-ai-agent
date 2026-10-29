"""add block_type and label to document_embeddings

Revision ID: 21a72e2ad92d
Revises: 3d64d8d72129
Create Date: 2026-09-17 18:10:06.751713

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21a72e2ad92d'
down_revision: Union[str, Sequence[str], None] = '3d64d8d72129'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('document_embeddings', sa.Column('block_type', sa.String(length=50), nullable=True))
    op.add_column('document_embeddings', sa.Column('label', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('document_embeddings', 'label')
    op.drop_column('document_embeddings', 'block_type')
