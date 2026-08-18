from fastapi import HTTPException, Request, Response, Depends, APIRouter, UploadFile, File
from sqlalchemy.exc import SQLAlchemyError
from starlette.status import HTTP_200_OK, HTTP_500_INTERNAL_SERVER_ERROR
from .deps import verify_jwt_token
from ..db.models import ChatRequest, MessageResponse, OpenChat
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
import json
import os


router = APIRouter()
_openai_client = None


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
        text = body.message
        thread_id = f"{token_data['sub']}:{body.session_id}"
        config = {"configurable": {"thread_id": thread_id}}

        async def event_generator():
            async for event in request.app.state.graph.astream_events(
                {"messages": [("user", text)]},
                config=config,
                version='v2'
            ):
                if event['event'] == 'on_chat_model_stream':
                    chunk = event['data']['chunk']
                    if chunk.content:
                        yield f"data: {json.dumps({'token': chunk.content})}\n\n"
                elif event["event"] == "on_chain_end" and event['name'] == "LangGraph":
                    yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(event_generator(), media_type = "text/event-stream")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/open-chat")
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








    

