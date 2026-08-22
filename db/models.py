from pydantic import BaseModel 
from sqlalchemy.orm import DeclarativeBase, declarative_base, foreign, mapped_column, Mapped, relationship, foreign
from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime, Boolean, JSON
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone

class ChatRequest(BaseModel):
    message : str
    session_id : str


class MessageResponse(BaseModel):
    response : str
    session_id : str
    user_id : str

class OpenChat(BaseModel):
    session_id : str


Base = declarative_base()

class Document(Base):
    """A source document ingested for retrieval (e.g. via ingestion.py's
    PDF pipeline). One row per document; chunked/embedded pieces live in
    DocumentEmbedding, linked by document_id.
    """
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(length=500))          # file path or URL it came from
    title = Column(String(length=200), nullable=True)
    content = Column(Text)                     # full extracted text
    doc_metadata = Column(JSON, nullable=True)     # page count, ocr engine, etc.
    page_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    embeddings = relationship("DocumentEmbedding", back_populates="document", cascade="all, delete-orphan")


class DocumentEmbedding(Base):
    """One chunk of a Document plus its vector embedding, for similarity
    search. chunk_index preserves ordering within the source document.
    """
    __tablename__ = "document_embeddings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_index = Column(Integer)
    chunk_text = Column(Text)
    embedding = Column(Vector(1024))            # dim must match your embedding model
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document = relationship("Document", back_populates="embeddings")


class QueryChecks(Base):
    """Audit log for helpers.query_checker.QueryCheck — one row per SQL
    query the agent's db_query_tool attempted to run, and the verdict.
    """
    __tablename__ = "query_check"
    id = Column(Integer, primary_key=True, autoincrement=True)
    query = Column(String(length=200))
    check_method = Column(String(length=20))        # "llm" or "manual"
    answer = Column(Boolean)                         # True = safe, False = rejected
    raw_response = Column(Text, nullable=True)        # LLM's raw reply, for debugging false positives/negatives
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))