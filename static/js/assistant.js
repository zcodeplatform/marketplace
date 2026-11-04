(() => {
  const widget = document.querySelector("[data-shopping-assistant]");
  if (!widget) return;

  const toggle = widget.querySelector("[data-assistant-toggle]");
  const panel = widget.querySelector("[data-assistant-panel]");
  const closeButton = widget.querySelector("[data-assistant-close]");
  const newButton = widget.querySelector("[data-assistant-new]");
  const messagesElement = widget.querySelector("[data-assistant-messages]");
  const form = widget.querySelector("[data-assistant-form]");
  const input = form?.elements.message;
  const sendButton = widget.querySelector("[data-assistant-send]");
  const historyKey = `marketplace-shopping-chat:${widget.dataset.userId}`;
  let history = form ? loadHistory() : [];
  let activeRequest;

  function loadHistory() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(historyKey) || "[]");
      if (!Array.isArray(saved)) return [];
      return saved.filter((message) => (
        message && ["user", "assistant"].includes(message.role)
        && typeof message.content === "string"
      )).slice(-30);
    } catch {
      return [];
    }
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(historyKey, JSON.stringify(history.slice(-30)));
    } catch {
      showMessage("Chat history could not be saved in this browser.", "error");
    }
  }

  function scrollToLatest() {
    messagesElement.scrollTop = messagesElement.scrollHeight;
  }

  function showMessage(content, role, container = messagesElement) {
    const bubble = document.createElement("div");
    bubble.className = `assistant-message assistant-message-${role}`;
    if (role === "assistant") renderAssistantText(bubble, content);
    else bubble.textContent = content;
    container.append(bubble);
    scrollToLatest();
    return bubble;
  }

  function renderAssistantText(element, content) {
    const productPath = /\/p\/[a-z0-9][a-z0-9-]*/gi;
    let start = 0;
    element.replaceChildren();
    for (const match of content.matchAll(productPath)) {
      element.append(document.createTextNode(content.slice(start, match.index)));
      const link = document.createElement("a");
      link.href = match[0];
      link.textContent = match[0];
      element.append(link);
      start = match.index + match[0].length;
    }
    element.append(document.createTextNode(content.slice(start)));
  }

  function renderHistory() {
    messagesElement.replaceChildren();
    if (!history.length) {
      showMessage("Hi! Tell me what you’re looking for, and I’ll help you explore available products.", "assistant");
      return;
    }
    history.forEach(({ role, content }) => showMessage(content, role));
  }

  function setOpen(open) {
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) input?.focus();
  }

  function parseEvent(block) {
    let type = "message";
    const data = [];
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("event:")) type = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (!data.length) return null;
    try {
      return { type, payload: JSON.parse(data.join("\n")) };
    } catch {
      return null;
    }
  }

  async function sendMessage(message) {
    history.push({ role: "user", content: message });
    history = history.slice(-30);
    saveHistory();
    renderHistory();
    const reply = showMessage("", "assistant");
    let replyText = "";
    const controller = new AbortController();
    activeRequest = controller;
    input.disabled = true;
    sendButton.disabled = true;

    try {
      const response = await fetch(widget.dataset.chatUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.body.dataset.csrfToken,
        },
        body: JSON.stringify({ messages: history.slice(-12) }),
        signal: controller.signal,
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error || "The assistant could not reply. Please try again.");
      }
      if (!response.body) throw new Error("Streaming replies are unavailable in this browser.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      const handleEvent = (block) => {
        const event = parseEvent(block);
        if (event?.type === "token") {
          replyText += event.payload.content || "";
          renderAssistantText(reply, replyText);
          scrollToLatest();
        } else if (event?.type === "error") {
          throw new Error(event.payload.error || "The assistant could not reply. Please try again.");
        } else if (event?.type === "done") {
          completed = true;
        }
      };
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        let separator = /\r?\n\r?\n/.exec(buffer);
        while (separator) {
          handleEvent(buffer.slice(0, separator.index));
          buffer = buffer.slice(separator.index + separator[0].length);
          separator = /\r?\n\r?\n/.exec(buffer);
        }
        if (done) break;
      }
      if (buffer) handleEvent(buffer);
      if (replyText && completed) {
        history.push({ role: "assistant", content: replyText });
        history = history.slice(-30);
        saveHistory();
      } else if (!completed) {
        throw new Error("The connection ended before the assistant finished. Please try again.");
      } else {
        throw new Error("The assistant returned an empty reply. Please try again.");
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        reply.remove();
        showMessage(error.message || "The assistant could not reply. Please try again.", "error");
      }
    } finally {
      if (activeRequest === controller) activeRequest = null;
      input.disabled = false;
      sendButton.disabled = false;
      input.focus();
    }
  }

  toggle.addEventListener("click", () => setOpen(panel.hidden));
  closeButton.addEventListener("click", () => setOpen(false));
  if (newButton) {
    newButton.addEventListener("click", () => {
      activeRequest?.abort();
      activeRequest = null;
      history = [];
      saveHistory();
      renderHistory();
      input.focus();
    });
  }
  if (form) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const message = input.value.trim();
      if (!message || input.disabled) return;
      input.value = "";
      sendMessage(message);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    renderHistory();
  }

})();
