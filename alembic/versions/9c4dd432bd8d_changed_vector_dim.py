"""changed vector dim

Revision ID: 9c4dd432bd8d
Revises: 6c189dd45a5e
Create Date: 2026-09-12 10:34:31.243161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '9c4dd432bd8d'
down_revision: Union[str, Sequence[str], None] = '6c189dd45a5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
            'document_embeddings',
            'embedding',
            type_=Vector(2048),
            postgresql_using='embedding::vector(2048)',
        )


def downgrade() -> None:
    op.alter_column(
            'document_embeddings',
            'embedding',
            type_=Vector(1024),
            postgresql_using='embedding::vector(1024)',
        )
    pass
