/**
 * Tadao Ando Agent — Chat Frontend
 *
 * Handles message sending, SSE streaming response,
 * and knowledge base management UI.
 */

(function () {
    "use strict";

    // ── State ──────────────────────────────────────────────────────
    let conversationId = null;
    let isStreaming = false;

    // ── DOM Elements ───────────────────────────────────────────────
    const messagesEl     = document.getElementById("messages");
    const chatForm       = document.getElementById("chat-form");
    const messageInput   = document.getElementById("message-input");
    const sendBtn        = document.getElementById("send-btn");
    const settingsToggle = document.getElementById("settings-toggle");
    const settingsPanel  = document.getElementById("settings-panel");
    const settingsClose  = document.getElementById("settings-close");
    const uploadForm     = document.getElementById("upload-form");
    const uploadFile     = document.getElementById("upload-file");
    const uploadStatus   = document.getElementById("upload-status");
    const sourceList     = document.getElementById("source-list");
    const sourceCount    = document.getElementById("source-count");
    const refreshSources = document.getElementById("refresh-sources");

    // ── Chat Logic ─────────────────────────────────────────────────

    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = messageInput.value.trim();
        if (!text || isStreaming) return;

        messageInput.value = "";
        appendMessage("user", text);
        await streamResponse(text);
    });

    async function streamResponse(userMessage) {
        isStreaming = true;
        sendBtn.disabled = true;

        // Show typing indicator
        const typingEl = appendTyping();

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: userMessage,
                    conversation_id: conversationId,
                }),
            });

            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }

            // Capture conversation ID from header
            const newConvId = response.headers.get("X-Conversation-Id");
            if (newConvId) {
                conversationId = newConvId;
            }

            // Remove typing indicator, create assistant bubble
            typingEl.remove();
            const bubbleEl = appendMessage("assistant", "", true);

            // Read SSE stream
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let fullText = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Parse SSE lines
                const lines = buffer.split("\n");
                buffer = lines.pop(); // keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;

                    try {
                        const event = JSON.parse(line.slice(6));

                        if (event.type === "chunk") {
                            fullText += event.content;
                            bubbleEl.textContent = fullText;
                            scrollToBottom();
                        } else if (event.type === "error") {
                            fullText += "\n[Error: " + event.message + "]";
                            bubbleEl.textContent = fullText;
                            bubbleEl.closest(".message").classList.add("error");
                        } else if (event.type === "done") {
                            if (event.conversation_id) {
                                conversationId = event.conversation_id;
                            }
                        }
                    } catch {
                        // Skip malformed JSON
                    }
                }
            }

            // If the response is empty, show a placeholder
            if (!fullText) {
                bubbleEl.textContent = "……";
            }
        } catch (err) {
            typingEl.remove();
            appendMessage("assistant", "Sorry, something went wrong: " + err.message, false, true);
        } finally {
            isStreaming = false;
            sendBtn.disabled = false;
            messageInput.focus();
        }
    }

    // ── Message Rendering ──────────────────────────────────────────

    function appendMessage(role, text, isStreamingBubble = false, isError = false) {
        const div = document.createElement("div");
        div.className = "message" + (role === "user" ? " user" : " assistant") + (isError ? " error" : "");

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.textContent = text;
        if (isStreamingBubble) {
            bubble.classList.add("streaming");
        }

        div.appendChild(bubble);
        messagesEl.appendChild(div);
        scrollToBottom();

        return bubble;
    }

    function appendTyping() {
        const div = document.createElement("div");
        div.className = "message assistant";
        div.innerHTML = `
            <div class="typing-indicator">
                <div class="typing-bar"></div>
                <span>Ando is thinking…</span>
            </div>
        `;
        messagesEl.appendChild(div);
        scrollToBottom();
        return div;
    }

    function scrollToBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // ── Settings Panel ─────────────────────────────────────────────

    settingsToggle.addEventListener("click", () => {
        settingsPanel.classList.toggle("hidden");
        if (!settingsPanel.classList.contains("hidden")) {
            loadKnowledgeSources();
        }
    });

    settingsClose.addEventListener("click", () => {
        settingsPanel.classList.add("hidden");
    });

    // Close settings when clicking outside
    document.addEventListener("click", (e) => {
        if (
            !settingsPanel.classList.contains("hidden") &&
            !settingsPanel.contains(e.target) &&
            !settingsToggle.contains(e.target)
        ) {
            settingsPanel.classList.add("hidden");
        }
    });

    // ── Knowledge Upload ───────────────────────────────────────────

    uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const file = uploadFile.files[0];
        if (!file) return;

        uploadStatus.textContent = "Uploading…";

        const formData = new FormData();
        formData.append("file", file);

        try {
            const res = await fetch("/api/knowledge", {
                method: "POST",
                body: formData,
            });

            const data = await res.json();
            if (data.success) {
                uploadStatus.textContent = `Uploaded: ${data.doc_id} (${data.word_count} words)`;
                uploadStatus.style.color = "#336633";
                loadKnowledgeSources();
            } else {
                uploadStatus.textContent = "Upload failed.";
                uploadStatus.style.color = "#cc3333";
            }
        } catch (err) {
            uploadStatus.textContent = "Error: " + err.message;
            uploadStatus.style.color = "#cc3333";
        }

        uploadFile.value = "";
    });

    // ── Knowledge Source List ──────────────────────────────────────

    refreshSources.addEventListener("click", loadKnowledgeSources);

    async function loadKnowledgeSources() {
        try {
            const res = await fetch("/api/knowledge/list");
            const data = await res.json();
            renderSourceList(data.documents);
        } catch {
            sourceList.innerHTML = '<li class="source-empty">Failed to load sources.</li>';
        }
    }

    function renderSourceList(docs) {
        sourceCount.textContent = docs.length;

        if (docs.length === 0) {
            sourceList.innerHTML = '<li class="source-empty">No knowledge sources loaded.</li>';
            return;
        }

        sourceList.innerHTML = "";
        for (const doc of docs) {
            const li = document.createElement("li");
            li.innerHTML = `
                <div>
                    <div class="source-path">${escapeHtml(doc.doc_id)}</div>
                    <span class="source-meta">${doc.category} · ${doc.word_count} words</span>
                </div>
                <button class="source-delete" data-id="${escapeHtml(doc.doc_id)}">Delete</button>
            `;
            sourceList.appendChild(li);
        }

        // Attach delete handlers
        sourceList.querySelectorAll(".source-delete").forEach((btn) => {
            btn.addEventListener("click", async () => {
                const docId = btn.dataset.id;
                if (!docId) return;

                try {
                    await fetch(`/api/knowledge/${encodeURIComponent(docId)}`, {
                        method: "DELETE",
                    });
                    loadKnowledgeSources();
                } catch (err) {
                    console.error("Delete failed:", err);
                }
            });
        });
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // ── Init ───────────────────────────────────────────────────────
    messageInput.focus();
})();
