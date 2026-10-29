from pgvector import vector
from db.engine import session_maker
from db.models import DocumentEmbedding,Document
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, cast, literal, desc
from sqlalchemy.dialects.postgresql import REGCONFIG
from helpers.embeddings import embed_query
import logging
from pgvector.sqlalchemy import HALFVEC

logger = logging.getLogger(__name__)
LEXICAL_CONFIG = "english"

async def similarity_search(query : str, top_k : int = 5) -> list[dict]:
    """ performs similarity search on straight forward questions """
    query_embedding = await embed_query(query)
    
    async with session_maker() as session:
        emb = cast(DocumentEmbedding.embedding, HALFVEC(2048))
        distance = emb.cosine_distance(query_embedding)
        stmt = (
            select(DocumentEmbedding)
            .options(selectinload(DocumentEmbedding.document))
            .order_by(distance)
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


async def _vector_candidates(session, query_embedding, limit, distance_threshold : float) -> list[dict]:
    """ finds embedding similarity """
    # cast must match the HNSW expression index (embedding::halfvec(2048))
    distance = cast(DocumentEmbedding.embedding, HALFVEC(2048)).cosine_distance(query_embedding)
    # order by distance only + limit in a subquery so the planner can use the HNSW index; join afterwards
    top = (
        select(
            DocumentEmbedding.id,
            DocumentEmbedding.document_id,
            DocumentEmbedding.chunk_index,
            DocumentEmbedding.chunk_text,
            distance.label("distance"),
        )
        .order_by(distance)
        .limit(limit)
        .subquery()
    )
    stmt = (
        select(top.c.id.label("chunk_id"), top.c.chunk_index, top.c.chunk_text, Document.title, top.c.distance)
        .join(Document, Document.id == top.c.document_id)
        .order_by(top.c.distance, top.c.id)
    )

    result = (await session.execute(stmt)).mappings().all()

    return [dict(r) for r in result]


async def _lexical_candidates(session, query, limit) -> list[dict]:
    """ Finds lexical similarity between query and the chunks' ts space"""
    # reusable query object
    ts_query = func.websearch_to_tsquery(cast(literal(LEXICAL_CONFIG), REGCONFIG), query)
    # ranking using the ts_query and actually data in db
    rank = func.ts_rank_cd(DocumentEmbedding.search_vector, ts_query).label('rank')

    stmt = (
        select(DocumentEmbedding.id.label("chunk_id"), DocumentEmbedding.chunk_index, DocumentEmbedding.chunk_text, Document.title, rank)
        .join(Document).where(DocumentEmbedding.document_id == Document.id)
        .where(DocumentEmbedding.search_vector.op("@@")(ts_query))
        .order_by(desc(rank), DocumentEmbedding.id)
        .limit(limit)
    )

    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]

async def _rrf(vector_list, lexical_list, k : int = 60) -> list[dict]:
    scores : dict[int, float] = {}
    payload : dict[int, dict] = {}

    for rank, row in enumerate(vector_list, start = 1):
        cid = row['chunk_id']
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        payload[cid] = row

    for rank, row in enumerate(lexical_list, start=1):
        cid = row["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        payload.setdefault(cid, row)

    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
    return [{**payload[cid], "rrf_score": scores[cid]} for cid in ranked_ids]


async def _mmr(vector_list : list[dict], relevane_threshold : float, diversity_threshold : float) -> list[dict]:
   pass 
    
    

async def hybrid_retrieval(query: str, top_k : int, distance_threshold : float, alpha : float,  lambda_mult : float) -> list[dict]:
    """ Hybrid retrieval with text search as well as embedding search using HNSW index declard in Postgres"""
    async with session_maker() as session:

        query = query.strip()
        query_embedding = await embed_query(query)

        vector_list = await _vector_candidates(session, query_embedding, top_k)
        lexical_list = await _lexical_candidates(session, query, top_k)

        best_retrieved = await _rrf(vector_list, lexical_list)

    return best_retrieved[:top_k]




# TODO : to implement HNSW or IVFF for the vector search




