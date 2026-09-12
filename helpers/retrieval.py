from db.engine import session_maker
from db.models import DocumentEmbedding
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from helpers.embeddings import embed_query


async def similarity_search(query : str, top_k : int = 5) -> list[dict]: 
    query_embedding = await embed_query(query)
    async with session_maker() as session: 
        stmt = (
            select(DocumentEmbedding)
            .options(selectinload(DocumentEmbedding.document))
            .order_by(DocumentEmbedding.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [
        {
            "chunk_text": row.chunk_text,
            "title": row.document.title,
            "document_id": row.document_id,
        }
        for row in rows
    ]
