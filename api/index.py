"""
Vercel serverless function entry point for Tadao Ando Agent.

Wraps the FastAPI app for Vercel's Python runtime.
"""

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Import our agent modules
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.chat import ChatError, stream_chat
from agent.knowledge import KnowledgeIndex
from agent.memory import ConversationManager
from agent.prompt import build_system_prompt

import config

# ─ Global State (per-function instance) ────────────────────────────
knowledge_index = KnowledgeIndex()
conversation_manager = ConversationManager(
    max_turns=config.MAX_TURNS,
    max_tokens=config.MAX_HISTORY_TOKENS,
    ttl_seconds=config.SESSION_TTL_SECONDS,
)

# Load knowledge on import
knowledge_index.load_directory()

# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(title="Tadao Ando Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/chat")
async def chat(request: ChatRequest):
    from fastapi import HTTPException

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    conversation_id = conversation_manager.ensure_session(request.conversation_id)
    await conversation_manager.add_message(conversation_id, "user", request.message)

    excerpts = knowledge_index.retrieve(request.message)
    system_prompt = build_system_prompt(excerpts)
    context_messages = conversation_manager.get_context_messages(conversation_id)

    messages = [m for m in context_messages if m["role"] in ("user", "assistant")]
    messages.append({"role": "user", "content": request.message})

    async def event_generator():
        import json
        assistant_response = ""
        try:
            async for chunk in stream_chat(messages, system_prompt):
                assistant_response += chunk
                data = json.dumps({"type": "chunk", "content": chunk})
                yield f"data: {data}\n\n"
        except ChatError as exc:
            error_data = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {error_data}\n\n"
        except Exception as exc:
            error_data = json.dumps({"type": "error", "message": f"Internal error: {exc}"})
            yield f"data: {error_data}\n\n"
        finally:
            if assistant_response:
                await conversation_manager.add_message(conversation_id, "assistant", assistant_response)
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


@app.post("/api/knowledge")
async def upload_knowledge(file: UploadFile):
    from fastapi import HTTPException

    SUPPORTED_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".xlsx")

    if not file.filename or not file.filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Only {', '.join(SUPPORTED_EXTENSIONS)} files are accepted",
        )

    try:
        from agent.extract import extract_text_from_bytes
        content = await file.read()
        text = extract_text_from_bytes(content, file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to extract text: {exc}")

    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text found in file")

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
    knowledge_index.remove_document(doc_id)
    knowledge_index.add_document(doc_id, text, category, source=doc_id)

    return KnowledgeUploadResponse(
        success=True,
        doc_id=doc_id,
        category=category,
        word_count=len(text.split()),
    )


@app.get("/api/knowledge/list")
async def list_knowledge():
    docs = knowledge_index.get_document_list()
    return {"documents": docs, "total": len(docs)}


@app.delete("/api/knowledge/{doc_id:path}")
async def delete_knowledge(doc_id: str):
    from fastapi import HTTPException

    if doc_id not in knowledge_index.documents:
        raise HTTPException(status_code=404, detail="Knowledge document not found")

    knowledge_index.remove_document(doc_id)
    return {"success": True, "doc_id": doc_id}


# ── Vercel Handler ──────────────────────────────────────────────────

from mangum import Mangum

handler = Mangum(app)
