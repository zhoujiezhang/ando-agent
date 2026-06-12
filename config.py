"""
Configuration for the Tadao Ando Agent.
Loads environment variables and defines constants.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Configuration (Qwen / DashScope) ───────────────────────────
# DashScope (阿里云百炼) OpenAI-compatible endpoint
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
QWEN_BASE_URL: str = os.getenv(
    "QWEN_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
# Default model — qwen-plus is a good balance of quality and cost
DEFAULT_MODEL: str = os.getenv("ANDO_MODEL", "qwen-plus")

# ── Token Budgets ──────────────────────────────────────────────────
MAX_RESPONSE_TOKENS: int = int(os.getenv("MAX_RESPONSE_TOKENS", "2048"))
MAX_HISTORY_TOKENS: int = int(os.getenv("MAX_HISTORY_TOKENS", "8000"))
MAX_KNOWLEDGE_TOKENS: int = int(os.getenv("MAX_KNOWLEDGE_TOKENS", "2000"))

# ── Conversation Settings ──────────────────────────────────────────
MAX_TURNS: int = 30
SESSION_TTL_SECONDS: int = 7200  # 2 hours

# ── Knowledge Base ─────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).parent
KNOWLEDGE_DIR: Path = PROJECT_ROOT / "knowledge"
STATIC_DIR: Path = PROJECT_ROOT / "static"

# ── Server ─────────────────────────────────────────────────────────
HOST: str = os.getenv("ANDO_HOST", "0.0.0.0")
PORT: int = int(os.getenv("ANDO_PORT", "8000"))
