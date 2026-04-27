from __future__ import annotations

import threading

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from wikiracer.progress import snapshot, subscribe, unsubscribe


MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 9999

app = FastAPI(title="Wikiracer Monitor")
_server_started = False
_server_lock = threading.Lock()


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wikiracer Monitor</title>
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
    .address {
      width: 180px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: nowrap;
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
      .path, .status {
        color: #b8c0cc;
      }
    }
  </style>
</head>
<body>
  <h1>Wikiracer Monitor</h1>
  <div id="status" class="status">Connecting...</div>
  <main id="participants" class="empty">No participants yet.</main>
  <script>
    const statusEl = document.querySelector("#status");
    const participantsEl = document.querySelector("#participants");

    function render(state) {
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
              <th>Current Page</th>
              <th>Path</th>
            </tr>
          </thead>
          <tbody>
            ${participants.map((participant) => `
              <tr>
                <td class="address">${escapeHtml(participant.address)}</td>
                <td class="current">${escapeHtml(participant.currentTitle || "")}</td>
                <td class="path">${escapeHtml((participant.path || []).join(" > "))}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
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

    function connect() {
      const protocol = location.protocol === "https:" ? "wss" : "ws";
      const socket = new WebSocket(`${protocol}://${location.host}/ws`);
      socket.addEventListener("open", () => { statusEl.textContent = "Connected"; });
      socket.addEventListener("message", (event) => { render(JSON.parse(event.data)); });
      socket.addEventListener("close", () => {
        statusEl.textContent = "Disconnected. Reconnecting...";
        setTimeout(connect, 1000);
      });
    }

    loadInitialState().catch(() => {});
    connect();
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/api/progress")
def progress() -> dict[str, object]:
    return snapshot()


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
