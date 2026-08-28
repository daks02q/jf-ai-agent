from fastapi import HTTPException, Request, Response, Depends, APIRouter, UploadFile, File
from sqlalchemy.exc import SQLAlchemyError
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR

from ingestion.ingestion import Ingestion
from .deps import verify_jwt_token
from db.models import ChatRequest, MessageResponse, OpenChat
from openai import AsyncOpenAI
import os
import time
import logging
from sqlalchemy import select, update
from db.engine import session_maker
from db.models import DocumentEmbedding, Document
from pathlib import Path
import asyncio
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = Path("pdfs")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
engine = os.getenv("INGESTION_ENGINE")
process = os.getenv("INGESTION_PROCESS")

def get_openai_client() -> AsyncOpenAI:
    # Lazy so the module (and the whole app) can still import when
    # OPENAI_API_KEY isn't set for deployments that don't use voice input.
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client

@router.post('/api/chat/')
async def chat_request( body : ChatRequest, request : Request, token_data: dict = Depends(verify_jwt_token)):
    thread_id = f"{token_data['sub']}:{body.session_id}"
    logger.info("chat_request start thread_id=%s message_len=%d", thread_id, len(body.message))
    start = time.monotonic()
    try:
        config = {"configurable": {"thread_id": thread_id, "tenant_id" : token_data.get("tenantId")}}

        result = await request.app.state.graph.ainvoke(
            {"messages": [("user", body.message)]},
            config=config,
        )
        reply = result["messages"][-1].content
        logger.info(
            "chat_request done thread_id=%s in %.2fs reply_len=%d",
            thread_id, time.monotonic() - start, len(reply or ""),
        )
        return {"message": reply}

    except Exception as e:
        logger.exception("chat_request failed thread_id=%s", thread_id)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/open-chat", )
async def open_chat(body: OpenChat, request: Request, token_data: dict = Depends(verify_jwt_token)):
    thread_id = f"{token_data['sub']}:{body.session_id}"
    logger.info("open_chat thread_id=%s", thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    state = await request.app.state.graph.aget_state(config)

    if not state.values:
        # brand new session — nothing checkpointed yet
        logger.info("open_chat thread_id=%s has no checkpoint yet", thread_id)
        return {"session_id": body.session_id, "messages": []}

    messages = [
        {"role": m.type, "content": m.content}
        for m in state.values.get("messages", [])
        if m.type == 'human' or (m.type == 'ai'and not getattr(m, "tool_calls", None) and m.content)
    ]
    logger.info("open_chat thread_id=%s returning %d messages", thread_id, len(messages))
    return {"session_id": body.session_id, "messages": messages}


@router.post("/api/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    token_data: dict = Depends(verify_jwt_token),
):
    """Transcribe a recorded voice note to text for entry work.

    The client uploads raw audio; the transcript is returned as plain text
    for the user to review/edit before it's sent as a chat message — batch
    IDs and strain names are easy for a transcriber to mangle, so this is
    a draft, not an auto-submit.
    """
    logger.info("transcribe_audio start filename=%s content_type=%s", audio.filename, audio.content_type)
    start = time.monotonic()
    try:
        contents = await audio.read()
        transcript = await get_openai_client().audio.transcriptions.create(
            model="whisper-1",
            file=(audio.filename or "audio.webm", contents, audio.content_type or "audio/webm"),
            # Nudge the transcriber toward domain vocabulary it wouldn't otherwise guess.
            prompt="spores, cultures, spawns, bulks, flushes, batch, strain, tent, inventory",
        )
        logger.info(
            "transcribe_audio done in %.2fs transcript_len=%d",
            time.monotonic() - start, len(transcript.text or ""),
        )
        return {"text": transcript.text}
    except Exception as e:
        logger.exception("transcribe_audio failed filename=%s", audio.filename)
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/upload")
async def upload_document(
    file : UploadFile = File(...),
    token_data : dict = Depends(verify_jwt_token),
    upload_data : dict = {}
):
    """ 
    Enables the user to upload files for ingestion and embedding to be used by the retriever and response model 
    """
    logger.info("upload_document start filename=%s content_type=%s", file.filename, file.content_type)
    start = time.monotonic()
    try:
        if file.content_type != "application/pdf":
            logger.warning("upload_document rejected non-pdf filename=%s type=%s", file.filename, file.content_type)
            return {"error" : "only pdfs supported for now"}

        # declaring ingestion object
        ingester = Ingestion(engine, process)


        file_path = UPLOAD_DIR / file.filename
        with file_path.open('wb') as buffer:
            while chunk := await file.read(1024*1024):
                buffer.write(chunk)

        # ingest, get text, chunks, embeddings and store them
        text, count = await ingester.ingest(file_path)
        logger.info("upload_document ingested filename=%s pages=%d", file.filename, count)
        chunks = await ingester.chunking(text)
        logger.info("upload_document chunked filename=%s chunks=%d", file.filename, len(chunks))
        embeddings = await ingester.get_embeddings(chunks)
        doc_id = await ingester.store_document(
            source = str(file_path), title = file.filename,
            text = text, page_count = count,
            chunks = chunks, embeddings = embeddings
        )

        await file.close()

        logger.info(
            "upload_document done filename=%s doc_id=%s chunks=%d in %.2fs",
            file.filename, doc_id, len(chunks), time.monotonic() - start,
        )
        return {"document_id" : doc_id, "chunks" : len(chunks), "page_count" : count}, 200


    except Exception as e:
        logger.exception("upload_document failed filename=%s", file.filename)
        raise HTTPException(status_code=500, detail = str(e))


@router.get("/api/get-sessions")
async def get_sessions(request : Request, token_data : dict = Depends(verify_jwt_token)):
    prefix = f"{token_data['sub']}:"
    logger.info("get_sessions user=%s", token_data['sub'])
    async with session_maker() as session:
        sesh =  await session.execute(
            text("""
                SELECT thread_id, MAX(checkpoint_id) AS latest
                FROM checkpoints
                WHERE thread_id LIKE :prefix
                GROUP BY thread_id
                ORDER BY latest DESC
            """),
            {"prefix": f"{prefix}%"},
        )
        rows = sesh.fetchall()

    async def preview_for(thread_id : str) -> str: 
        config  = { "configurable" : {'thread_id' : thread_id}}
        state = await request.app.state.graph.aget_state(config)
        messages = state.values.get("messages", []) if state.values else []
        if not messages:
            return ""
        return messages[0].content[:80]

    previews = await asyncio.gather(*(preview_for(thread_id) for thread_id, _ in rows))
    logger.info("get_sessions user=%s found %d sessions", token_data['sub'], len(rows))

    seshes = [
        {"session_id": thread_id[len(prefix):], "preview" : preview }
                for (thread_id, _latest), preview in zip(rows, previews)
            ]
    return {"sessions": seshes}

