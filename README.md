# Tadao Ando Agent — Architecture in Silence

An anthropomorphized web chat agent embodying the Japanese architect [Tadao Ando](https://www.pritzkerprize.com/laureates/tadao-ando). Talk with Ando about architecture, life, light, concrete, and the world.

## Features

- **Conversational AI** — Streamed responses via Qwen (通义千问), displayed in real-time
- **Knowledge Base** — Upload Markdown/TXT files (interviews, articles, bios) to calibrate Ando's answers
- **BM25 Retrieval** — Lightweight in-memory text search injects relevant knowledge into each response
- **Ando-Inspired UI** — Concrete grays, sharp geometry, generous whitespace (ma), light/shadow aesthetics

## Quick Start

### 1. Install Dependencies

```bash
cd ando-agent
pip install -r requirements.txt
```

### 2. Set Your API Key

```bash
cp .env.example .env
# Edit .env and add your DashScope / 阿里云百炼 API key:
# QWEN_API_KEY=sk-...
```

Get a key at [阿里云百炼平台](https://bailian.console.aliyun.com).

### 3. Run

```bash
python main.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

## Adding Knowledge

### Via the UI

1. Click the ☀️ settings icon (top-right)
2. Upload a `.md`, `.txt`, `.pdf`, `.docx`, or `.xlsx` file
3. The knowledge is indexed immediately — no restart needed

### Via the File System

Add Markdown files to the `knowledge/` directory:

```
knowledge/
├── philosophy/     # Architectural philosophy
├── interviews/     # Interview transcripts and Q&A
├── biography/      # Biographical information
└── projects/       # Key architectural works
```

Restart the server to load new files. Each file should include a metadata block:

```markdown
## Metadata
- source: Where this came from
- category: philosophy | interviews | biography | projects
- tags: comma, separated, tags
```

### Knowledge File Guidelines

- Use conversational Q&A format for interviews: `Q: ... A: ...`
- Use descriptive narrative for biography and projects
- Include specific quotes when available, attributed to their source
- Keep files under 10KB for optimal retrieval
- The agent will retrieve and reference these materials when answering

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Main chat page |
| `/api/chat` | POST | Send message, stream response (SSE) |
| `/api/knowledge` | POST | Upload a knowledge file |
| `/api/knowledge/list` | GET | List loaded knowledge sources |
| `/api/knowledge/{id}` | DELETE | Remove a knowledge source |

### Chat Request

```json
{
  "message": "What is your philosophy on light?",
  "conversation_id": null
}
```

Response: Server-Sent Events stream with JSON chunks.

## Configuration

All config is via `.env` or environment variables:

| Variable | Default | Description |
|---|---|---|
| `QWEN_API_KEY` | _(required)_ | 通义千问 API Key |
| `ANDO_MODEL` | `qwen-plus` | 模型（qwen-turbo / qwen-plus / qwen-max） |
| `QWEN_BASE_URL` | 阿里云 DashScope | API 地址（一般不用改） |
| `ANDO_HOST` | `0.0.0.0` | Server bind address |
| `ANDO_PORT` | `8000` | Server port |
| `MAX_RESPONSE_TOKENS` | `2048` | Max tokens per response |
| `MAX_HISTORY_TOKENS` | `8000` | Max tokens for conversation history |
| `MAX_KNOWLEDGE_TOKENS` | `2000` | Max tokens for injected knowledge |

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, 通义千问 (Qwen)
- **Frontend**: Vanilla HTML/CSS/JS, SSE streaming
- **Retrieval**: BM25-lite in-memory text search (no vector DB)
- **Memory**: In-memory conversation store with sliding window

## License

MIT
