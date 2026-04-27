from __future__ import annotations

import threading

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from wikiracer.progress import set_participant_name, snapshot, subscribe, unsubscribe


MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 9999

app = FastAPI(title="Wikiracer Monitor")
_server_started = False
_server_lock = threading.Lock()


AUDIENCE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wikiracer</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #eef2f7;
      color: #1f2933;
    }
    body {
      margin: 0;
      min-height: 100vh;
      padding: 28px;
      box-sizing: border-box;
    }
    h1 {
      margin: 0;
      font-size: 32px;
      font-weight: 750;
    }
    header {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 24px;
    }
    .status {
      color: #536171;
      font-size: 15px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .participant {
      min-height: 170px;
      padding: 18px;
      border: 1px solid #d5dce6;
      border-left: 7px solid var(--accent);
      background: #ffffff;
      box-shadow: 0 12px 28px rgba(27, 37, 51, .08);
      box-sizing: border-box;
    }
    .participant:nth-child(6n+1) { --accent: #2f80ed; }
    .participant:nth-child(6n+2) { --accent: #27ae60; }
    .participant:nth-child(6n+3) { --accent: #eb5757; }
    .participant:nth-child(6n+4) { --accent: #f2994a; }
    .participant:nth-child(6n+5) { --accent: #9b51e0; }
    .participant:nth-child(6n) { --accent: #00a6a6; }
    .name {
      margin: 0 0 10px;
      font-size: 21px;
      font-weight: 750;
      overflow-wrap: anywhere;
    }
    .current-label {
      margin: 0 0 4px;
      color: #647284;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }
    .current {
      margin: 0 0 14px;
      font-size: 18px;
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .path {
      color: #4a5563;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .separator {
      color: var(--accent);
      font-weight: 750;
      padding: 0 5px;
    }
    .empty {
      padding: 18px 12px;
      color: #6a7280;
      background: white;
      border: 1px solid #d9dde3;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        background: #15191f;
        color: #eef1f5;
      }
      .participant, .empty {
        background: #20262e;
        border-color: #36404d;
        box-shadow: none;
      }
      .path, .status {
        color: #b8c0cc;
      }
      .current-label {
        color: #9da8b6;
      }
    }
  </style>
</head>
<body>
  <header>
    <h1>Wikiracer</h1>
    <div id="status" class="status">Connecting...</div>
  </header>
  <main id="participants" class="empty">No participants yet.</main>
  <script>
    const statusEl = document.querySelector("#status");
    const participantsEl = document.querySelector("#participants");
    let lastRenderAt = 0;

    function render(state) {
      lastRenderAt = Date.now();
      const participants = state.participants || [];
      statusEl.textContent = `${participants.length} participant${participants.length === 1 ? "" : "s"}`;
      if (participants.length === 0) {
        participantsEl.className = "empty";
        participantsEl.textContent = "No participants yet.";
        return;
      }

      participantsEl.className = "grid";
      participantsEl.innerHTML = `
        ${participants.map((participant) => `
          <section class="participant">
            <h2 class="name">${escapeHtml(participant.displayName)}</h2>
            <p class="current-label">Current page</p>
            <p class="current">${escapeHtml(participant.currentTitle || "")}</p>
            <div class="path">${renderPath(participant.path || [])}</div>
          </section>
        `).join("")}
      `;
    }

    function renderPath(path) {
      return path.map((title) => escapeHtml(title)).join('<span class="separator">&gt;</span>');
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[char]));
    }

    async function loadInitialState() {
      const response = await fetch("/api/progress");
      render(await response.json());
    }

    async function poll() {
      try {
        await loadInitialState();
      } finally {
        setTimeout(poll, 1000);
      }
    }

    function connect() {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${protocol}://${location.host}/ws`);
      socket.addEventListener("open", () => { statusEl.textContent = "Connected"; });
      socket.addEventListener("message", (event) => { render(JSON.parse(event.data)); });
      socket.addEventListener("close", () => {
        if (Date.now() - lastRenderAt > 1500) {
          statusEl.textContent = "Disconnected. Reconnecting...";
        }
        setTimeout(connect, 1000);
      });
    }

    poll();
    connect();
  </script>
</body>
</html>
"""


ADMIN_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wikiracer Admin</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #20242a;
    }
    body {
      margin: 0;
      padding: 24px;
    }
    h1 {
      margin: 0 0 18px;
      font-size: 24px;
      font-weight: 650;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      background: white;
      border: 1px solid #d9dde3;
    }
    th, td {
      padding: 10px 12px;
      border-bottom: 1px solid #e7e9ee;
      text-align: left;
      vertical-align: top;
    }
    th {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: #596271;
      background: #f1f3f6;
    }
    input {
      width: 100%;
      max-width: 220px;
      box-sizing: border-box;
      padding: 7px 8px;
      border: 1px solid #c9d0da;
      background: white;
      color: inherit;
      font: inherit;
    }
    input:focus {
      outline: 2px solid #8ab4f8;
      outline-offset: 1px;
    }
    .address {
      width: 180px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: nowrap;
    }
    .name-cell {
      width: 250px;
    }
    .current {
      width: 260px;
      font-weight: 600;
    }
    .path {
      color: #3f4752;
      overflow-wrap: anywhere;
    }
    .empty {
      padding: 18px 12px;
      color: #6a7280;
      background: white;
      border: 1px solid #d9dde3;
    }
    .status {
      margin-bottom: 12px;
      color: #596271;
      font-size: 14px;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        background: #15171a;
        color: #eef1f5;
      }
      table, .empty {
        background: #1d2025;
        border-color: #343942;
      }
      th {
        background: #252a31;
        color: #b2bbc8;
      }
      th, td {
        border-bottom-color: #30353d;
      }
      input {
        background: #15171a;
        border-color: #444b56;
      }
      .path, .status {
        color: #b8c0cc;
      }
    }
  </style>
</head>
<body>
  <h1>Wikiracer Admin</h1>
  <div id="status" class="status">Connecting...</div>
  <main id="participants" class="empty">No participants yet.</main>
  <script>
    const statusEl = document.querySelector("#status");
    const participantsEl = document.querySelector("#participants");
    const pendingNames = new Map();
    const saveTimers = new Map();
    let lastRenderAt = 0;

    function render(state) {
      lastRenderAt = Date.now();
      const active = document.activeElement;
      const activeAddress = active?.dataset?.address;
      const activeValue = active?.value;
      const participants = state.participants || [];
      statusEl.textContent = `${participants.length} participant${participants.length === 1 ? "" : "s"}`;
      if (participants.length === 0) {
        participantsEl.className = "empty";
        participantsEl.textContent = "No participants yet.";
        return;
      }

      participantsEl.className = "";
      participantsEl.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Participant</th>
              <th>Name</th>
              <th>Current Page</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            ${participants.map((participant) => `
              <tr>
                <td class="address">${escapeHtml(participant.address)}</td>
                <td class="name-cell">
                  <input
                    data-address="${escapeHtml(participant.address)}"
                    value="${escapeHtml(nameValue(participant, activeAddress, activeValue))}"
                    placeholder="${escapeHtml(participant.address)}"
                    aria-label="Participant name for ${escapeHtml(participant.address)}"
                  >
                </td>
                <td class="current">${escapeHtml(participant.currentTitle || "")}</td>
                <td class="path">${escapeHtml((participant.path || []).join(" > "))}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
      bindInputs();
      if (activeAddress) {
        const replacement = participantsEl.querySelector(`input[data-address="${cssEscape(activeAddress)}"]`);
        replacement?.focus();
      }
    }

    function nameValue(participant, activeAddress, activeValue) {
      if (participant.address === activeAddress) {
        return activeValue;
      }
      if (pendingNames.has(participant.address)) {
        return pendingNames.get(participant.address);
      }
      return participant.name || "";
    }

    function bindInputs() {
      participantsEl.querySelectorAll("input[data-address]").forEach((input) => {
        input.addEventListener("input", () => {
          const address = input.dataset.address;
          pendingNames.set(address, input.value);
          clearTimeout(saveTimers.get(address));
          saveTimers.set(address, setTimeout(() => saveName(address, input.value), 350));
        });
        input.addEventListener("blur", () => {
          const address = input.dataset.address;
          clearTimeout(saveTimers.get(address));
          saveName(address, input.value);
        });
      });
    }

    async function saveName(address, name) {
      await fetch("/api/participant-name", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ address, name }),
      });
      pendingNames.delete(address);
      saveTimers.delete(address);
    }

    function cssEscape(value) {
      if (window.CSS?.escape) {
        return window.CSS.escape(value);
      }
      return String(value).replace(/["\\\\]/g, "\\\\$&");
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[char]));
    }

    async function loadInitialState() {
      const response = await fetch("/api/progress");
      render(await response.json());
    }

    async function poll() {
      try {
        await loadInitialState();
      } finally {
        setTimeout(poll, 1000);
      }
    }

    function connect() {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${protocol}://${location.host}/ws`);
      socket.addEventListener("open", () => { statusEl.textContent = "Connected"; });
      socket.addEventListener("message", (event) => { render(JSON.parse(event.data)); });
      socket.addEventListener("close", () => {
        if (Date.now() - lastRenderAt > 1500) {
          statusEl.textContent = "Disconnected. Reconnecting...";
        }
        setTimeout(connect, 1000);
      });
    }

    poll();
    connect();
  </script>
</body>
</html>
"""


class ParticipantNameUpdate(BaseModel):
    address: str
    name: str = ""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return AUDIENCE_HTML


@app.get("/admin", response_class=HTMLResponse)
def admin() -> str:
    return ADMIN_HTML


@app.get("/api/progress")
def progress() -> dict[str, object]:
    return snapshot()


@app.post("/api/participant-name")
def participant_name(update: ParticipantNameUpdate) -> dict[str, object]:
    return set_participant_name(update.address, update.name)


@app.websocket("/ws")
async def websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = subscribe()
    try:
        await websocket.send_json(snapshot())
        while True:
            await websocket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)


def start_monitor() -> None:
    global _server_started
    with _server_lock:
        if _server_started:
            return
        _server_started = True

    config = uvicorn.Config(
        app,
        host=MONITOR_HOST,
        port=MONITOR_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="wikiracer-monitor", daemon=True)
    thread.start()
