from fastapi import HTTPException, Request, Response, Depends, APIRouter, UploadFile, File
from sqlalchemy.exc import SQLAlchemyError
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR

from ingestion.ingestion import Ingestion
from .deps import verify_jwt_token
from db.models import ChatRequest, MessageResponse, OpenChat
from openai import AsyncOpenAI
import os
from sqlalchemy import select, update
from db.engine import session_maker
from db.models import DocumentEmbedding, Document
from pathlib import Path
import asyncio
from sqlalchemy import text

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
    try:
        thread_id = f"{token_data['sub']}:{body.session_id}"
        config = {"configurable": {"thread_id": thread_id, "tenant_id" : token_data.get("tenantId")}}

        result = await request.app.state.graph.ainvoke(
            {"messages": [("user", body.message)]},

            config=config,
        )
        return {"message": result["messages"][-1].content}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/open-chat", )
async def open_chat(body: OpenChat, request: Request, token_data: dict = Depends(verify_jwt_token)):
    thread_id = f"{token_data['sub']}:{body.session_id}"
    config = {"configurable": {"thread_id": thread_id}}

    state = await request.app.state.graph.aget_state(config)

    if not state.values:
        # brand new session — nothing checkpointed yet
        return {"session_id": body.session_id, "messages": []}

    messages = [
        {"role": m.type, "content": m.content}
        for m in state.values.get("messages", [])
        if m.type == 'human' or (m.type == 'ai'and not getattr(m, "tool_calls", None) and m.content) 
    ]
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
    try:
        contents = await audio.read()
        transcript = await get_openai_client().audio.transcriptions.create(
            model="whisper-1",
            file=(audio.filename or "audio.webm", contents, audio.content_type or "audio/webm"),
            # Nudge the transcriber toward domain vocabulary it wouldn't otherwise guess.
            prompt="spores, cultures, spawns, bulks, flushes, batch, strain, tent, inventory",
        )
        return {"text": transcript.text}
    except Exception as e:
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
    try: 
        if file.content_type != "application/pdf": 
            return {"error" : "only pdfs supported for now"}
        
        # declaring ingestion object
        ingester = Ingestion(engine, process)
        

        file_path = UPLOAD_DIR / file.filename
        with file_path.open('wb') as buffer:
            while chunk := await file.read(1024*1024): 
                buffer.write(chunk)

        # ingest, get text, chunks, embeddings and store them
        text, count = await ingester.ingest(file_path)
        chunks = await ingester.chunking(text)
        embeddings = await ingester.get_embeddings(chunks)
        doc_id = await ingester.store_document(
            source = str(file_path), title = file.filename, 
            text = text, page_count = count,
            chunks = chunks, embeddings = embeddings
        )
        
        await file.close()

        return {"document_id" : doc_id, "chunks" : len(chunks), "page_count" : count}, 200

    
    except Exception as e: 
        raise HTTPException(status_code=500, detail = str(e))


@router.get("/api/get-sessions")
async def get_sessions(request : Request, token_data : dict = Depends(verify_jwt_token)):
    prefix = f"{token_data['sub']}:"
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

    seshes = [
        {"session_id": thread_id[len(prefix):], "preview" : preview }
                for (thread_id, _latest), preview in zip(rows, previews)
            ]
    return {"sessions": seshes}

