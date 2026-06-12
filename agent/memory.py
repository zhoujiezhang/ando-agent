"""
Conversation history management with sliding window.

Maintains in-memory session store with:
  - Per-session conversation history keyed by UUID
  - Sliding window: keeps first N exchanges (anchor) + most recent M
  - Token budget enforcement
  - Session TTL cleanup
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable


class ConversationManager:
    """Manages multiple conversation sessions with sliding window history."""

    def __init__(
        self,
        max_turns: int = 30,
        max_tokens: int = 8000,
        ttl_seconds: int = 7200,
    ):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.ttl_seconds = ttl_seconds

        # conversation_id -> {"history": [...], "last_active": float}
        self._sessions: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    def create_session(self) -> str:
        """Create a new conversation session and return its ID."""
        conversation_id = str(uuid.uuid4())
        self._sessions[conversation_id] = {
            "history": [],
            "last_active": time.time(),
        }
        return conversation_id

    def ensure_session(self, conversation_id: str | None) -> str:
        """Return existing session ID, or create a new one."""
        if conversation_id and conversation_id in self._sessions:
            self._sessions[conversation_id]["last_active"] = time.time()
            return conversation_id
        return self.create_session()

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Add a message to the conversation history."""
        async with self._lock:
            if conversation_id not in self._sessions:
                return
            self._sessions[conversation_id]["history"].append({
                "role": role,
                "content": content,
            })
            self._sessions[conversation_id]["last_active"] = time.time()

    def get_context_messages(self, conversation_id: str) -> list[dict[str, str]]:
        """
        Get the context messages for a conversation turn.

        Strategy: keep first 2 exchanges (anchor) + last N exchanges (recent).
        The anchor preserves the initial framing; the recent messages keep
        the current thread alive.
        """
        session = self._sessions.get(conversation_id)
        if not session:
            return []

        history = session["history"]
        anchor_pairs = 2  # first 2 user+assistant pairs
        anchor_count = anchor_pairs * 2

        # How many total message pairs can we keep?
        max_messages = self.max_turns * 2
        recent_count = max_messages - anchor_count

        if len(history) <= anchor_count + recent_count:
            return history

        # Keep anchor + recent, drop the middle
        anchor = history[:anchor_count]
        recent = history[-recent_count:]

        # Insert a bridging message to acknowledge the gap
        return anchor + [
            {
                "role": "system",
                "content": "[对话的中间部分已省略，但之前的内容仍然影响着我的思考]",
            },
        ] + recent

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: ~4 chars per token for Chinese/mixed text."""
        return max(1, len(text) // 4)

    def cleanup_expired(self) -> None:
        """Remove sessions that have exceeded their TTL."""
        now = time.time()
        expired = [
            cid
            for cid, session in self._sessions.items()
            if now - session["last_active"] > self.ttl_seconds
        ]
        for cid in expired:
            del self._sessions[cid]

    def get_session_count(self) -> int:
        """Return the number of active sessions."""
        return len(self._sessions)
