"""
Tadao Ando Anthropomorphized Web Agent — FastAPI Application.

Runs the chat interface with SSE streaming and knowledge management.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent.chat import ChatError, stream_chat
from agent.extract import extract_text_from_bytes
from agent.knowledge import KnowledgeIndex
from agent.memory import ConversationManager
from agent.prompt import KnowledgeExcerpt, build_system_prompt

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ando-agent")


# ── Global State ────────────────────────────────────────────────────

knowledge_index = KnowledgeIndex()
conversation_manager = ConversationManager(
    max_turns=config.MAX_TURNS,
    max_tokens=config.MAX_HISTORY_TOKENS,
    ttl_seconds=config.SESSION_TTL_SECONDS,
)


# ── Lifespan ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load knowledge base on startup, cleanup sessions periodically."""
    # Load knowledge files
    count = knowledge_index.load_directory()
    logger.info(f"Loaded {count} knowledge documents from {config.KNOWLEDGE_DIR}")

    # Periodic session cleanup (every 5 minutes)
    async def cleanup_loop():
        import asyncio
        while True:
            await asyncio.sleep(300)
            conversation_manager.cleanup_expired()

    import asyncio
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


# ── App Setup ───────────────────────────────────────────────────────

app = FastAPI(
    title="Tadao Ando Agent",
    description="An anthropomorphized chat agent embodying architect Tadao Ando.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


# ── Request Models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class KnowledgeUploadResponse(BaseModel):
    success: bool
    doc_id: str
    category: str
    word_count: int


# ── Routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main chat page."""
    return (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    """
    Send a message and receive a streamed response via SSE.

    The agent retrieves relevant knowledge excerpts, builds the system
    prompt, and streams the Qwen (通义千问) API response.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Ensure or create session
    conversation_id = conversation_manager.ensure_session(request.conversation_id)

    # Add user message to history
    await conversation_manager.add_message(conversation_id, "user", request.message)

    # Retrieve relevant knowledge
    excerpts = knowledge_index.retrieve(request.message)

    # Build system prompt with knowledge injection
    system_prompt = build_system_prompt(excerpts)

    # Get context messages (sliding window)
    context_messages = conversation_manager.get_context_messages(conversation_id)

    # Build messages list for Claude API
    messages = [m for m in context_messages if m["role"] in ("user", "assistant")]
    messages.append({"role": "user", "content": request.message})

    async def event_generator():
        """Stream the response as SSE events."""
        assistant_response = ""
        try:
            async for chunk in stream_chat(messages, system_prompt):
                assistant_response += chunk
                # SSE format
                data = json.dumps({"type": "chunk", "content": chunk})
                yield f"data: {data}\n\n"
        except ChatError as exc:
            error_data = json.dumps({
                "type": "error",
                "message": str(exc),
            })
            yield f"data: {error_data}\n\n"
        except Exception as exc:
            error_data = json.dumps({
                "type": "error",
                "message": f"Internal error: {exc}",
            })
            yield f"data: {error_data}\n\n"
        finally:
            # Add assistant response to history after streaming completes
            if assistant_response:
                await conversation_manager.add_message(
                    conversation_id, "assistant", assistant_response,
                )
            # Send done signal
            done_data = json.dumps({
                "type": "done",
                "conversation_id": conversation_id,
            })
            yield f"data: {done_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Conversation-Id": conversation_id,
        },
    )


SUPPORTED_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".xlsx")


@app.post("/api/knowledge")
async def upload_knowledge(file: UploadFile):
    """Upload a new knowledge file (.md, .txt, .pdf, .docx, .xlsx)."""
    if not file.filename or not file.filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Only {', '.join(SUPPORTED_EXTENSIONS)} files are accepted",
        )

    try:
        content = await file.read()
        text = extract_text_from_bytes(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract text: {exc}",
        )

    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text found in file")

    # Determine category from filename or default to interviews
    filename_lower = file.filename.lower()
    if any(kw in filename_lower for kw in ["philosophy", "理念", "哲学"]):
        category = "philosophy"
    elif any(kw in filename_lower for kw in ["project", "作品", "建筑"]):
        category = "projects"
    elif any(kw in filename_lower for kw in ["bio", "生平", "传记"]):
        category = "biography"
    else:
        category = "interviews"

    doc_id = f"uploaded/{file.filename}"

    # Remove existing doc with same ID if present
    knowledge_index.remove_document(doc_id)

    # Add to index
    knowledge_index.add_document(doc_id, text, category, source=doc_id)

    word_count = len(text.split())

    return KnowledgeUploadResponse(
        success=True,
        doc_id=doc_id,
        category=category,
        word_count=word_count,
    )


@app.get("/api/knowledge/list")
async def list_knowledge():
    """List all currently loaded knowledge sources."""
    docs = knowledge_index.get_document_list()
    return {"documents": docs, "total": len(docs)}


@app.delete("/api/knowledge/{doc_id:path}")
async def delete_knowledge(doc_id: str):
    """Remove a knowledge source from the index."""
    if doc_id not in knowledge_index.documents:
        raise HTTPException(status_code=404, detail="Knowledge document not found")

    knowledge_index.remove_document(doc_id)
    return {"success": True, "doc_id": doc_id}


# ── Entry Point ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
    )
