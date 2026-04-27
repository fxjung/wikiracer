from __future__ import annotations

import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from wikiracer.progress import (
    reset_game,
    reset_round,
    set_participant_name,
    snapshot,
    subscribe,
    unsubscribe,
)
from wikiracer.storage import clear_visited_pages


MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 9999
CYTOSCAPE_PATH = Path(__file__).with_name("cytoscape.min.js")
CYTOSCAPE_DAGRE_DEPENDENCY_PATH = Path(__file__).with_name("dagre.min.js")
CYTOSCAPE_DAGRE_PATH = Path(__file__).with_name("cytoscape-dagre.min.js")

app = FastAPI(title="Wikiracer Monitor")
_server_started = False
_server_lock = threading.Lock()


AUDIENCE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wikiracer</title>
  <script src="/assets/cytoscape.min.js"></script>
  <script src="/assets/dagre.min.js"></script>
  <script src="/assets/cytoscape-dagre.min.js"></script>
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
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 16px;
    }
    .participant {
      padding: 18px;
      border: 1px solid #d5dce6;
      border-left: 7px solid var(--accent);
      background: #ffffff;
      box-shadow: 0 12px 28px rgba(27, 37, 51, .08);
      box-sizing: border-box;
      min-width: 0;
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
    .summary {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    .steps {
      padding: 4px 8px;
      border: 1px solid color-mix(in srgb, var(--accent) 35%, transparent);
      background: color-mix(in srgb, var(--accent) 12%, transparent);
      color: #26313f;
      font-size: 13px;
      font-weight: 750;
      white-space: nowrap;
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
      margin-bottom: 14px;
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
    .participant-graph {
      height: clamp(240px, 32vh, 380px);
      border: 1px solid #d5dce6;
      background: #f8fafc;
      position: relative;
      overflow: hidden;
    }
    .graph {
      position: absolute;
      inset: 0;
    }
    .graph-empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      color: #6a7280;
      pointer-events: none;
    }
    .graph-panel[hidden] {
      display: none;
    }
    .graph-empty[hidden] {
      display: none;
    }
    @media (max-width: 760px) {
      body {
        padding: 16px;
      }
      .grid {
        grid-template-columns: 1fr;
      }
      .participant-graph {
        height: 280px;
      }
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
      .participant-graph {
        background: #171b21;
        border-color: #36404d;
      }
      .path, .status {
        color: #b8c0cc;
      }
      .current-label {
        color: #9da8b6;
      }
      .steps {
        color: #eef1f5;
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
    const graphs = new Map();
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
            <div class="summary">
              <h2 class="name">${escapeHtml(participant.displayName)}</h2>
              <span class="steps">${escapeHtml(participant.steps || 0)} steps</span>
            </div>
            <p class="current-label">Current page</p>
            <p class="current">${escapeHtml(participant.currentTitle || "")}</p>
            <div class="path">${renderPath(participant.path || [])}</div>
            <div class="participant-graph">
              <div class="graph" data-address="${escapeHtml(participant.address)}"></div>
              <div class="graph-empty">No graph yet.</div>
            </div>
          </section>
        `).join("")}
      `;
      renderGraphs(participants, state.graph || { nodes: [], edges: [], currentNodeIds: {} });
    }

    function renderGraphs(participants, graphState) {
      const activeAddresses = new Set(participants.map((participant) => participant.address));
      graphs.forEach((entry, address) => {
        if (!activeAddresses.has(address)) {
          entry.cy.destroy();
          graphs.delete(address);
        }
      });

      participants.forEach((participant) => {
        renderParticipantGraph(participant.address, graphState);
      });
    }

    function renderParticipantGraph(address, graphState) {
      const container = participantsEl.querySelector(`.graph[data-address="${cssEscape(address)}"]`);
      if (!container) {
        return;
      }
      const panel = container.closest(".participant-graph");
      const emptyEl = panel.querySelector(".graph-empty");
      const allNodes = graphState.nodes || [];
      const allEdges = graphState.edges || [];
      const currentNodeId = (graphState.currentNodeIds || {})[address] || null;
      const nodes = allNodes.filter((node) => node.address === address);
      const nodeIds = new Set(nodes.map((node) => node.id));
      const edges = allEdges.filter(
        (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
      );
      const signature = JSON.stringify({
        nodes: nodes.map((node) => [node.id, node.title]),
        edges: edges.map((edge) => [edge.id, edge.source, edge.target]),
        current: currentNodeId,
      });
      const existing = graphs.get(address);
      if (existing?.signature === signature && existing.container === container) {
        existing.cy.resize();
        existing.cy.fit(undefined, 18);
        return;
      }
      emptyEl.hidden = nodes.length > 0;
      if (!window.cytoscape || nodes.length === 0) {
        existing?.cy.destroy();
        graphs.delete(address);
        return;
      }

      const elements = [
        ...nodes.map((node) => ({
          classes: node.id === currentNodeId ? "current" : "",
          data: {
            id: node.id,
            label: node.title,
            participant: node.participant,
          },
        })),
        ...edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
          },
        })),
      ];

      let cy = existing?.cy;
      if (!cy || existing.container !== container) {
        existing?.cy.destroy();
        cy = cytoscape({
          container,
          elements,
          userZoomingEnabled: false,
          userPanningEnabled: false,
          boxSelectionEnabled: false,
          autoungrabify: true,
          wheelSensitivity: 0.2,
          style: [
            {
              selector: "node",
              style: {
                "background-color": "#4f7ec8",
                "border-color": "#d9e2ef",
                "border-width": 1,
                "color": "#1f2933",
                "font-size": 12,
                "font-weight": 650,
                "label": "data(label)",
                "text-background-color": "#ffffff",
                "text-background-opacity": 0.92,
                "text-background-padding": 3,
                "text-margin-y": -13,
                "text-wrap": "wrap",
                "text-max-width": 95,
                "width": 12,
                "height": 12,
              },
            },
            {
              selector: "node.current",
              style: {
                "background-color": "#27ae60",
                "border-color": "#0b6b36",
                "border-width": 3,
                "width": 20,
                "height": 20,
                "z-index": 20,
              },
            },
            {
              selector: "edge",
              style: {
                "curve-style": "bezier",
                "line-color": "#9aa7b7",
                "target-arrow-color": "#9aa7b7",
                "target-arrow-shape": "triangle",
                "arrow-scale": 0.75,
                "width": 1.4,
              },
            },
          ],
        });
      } else {
        cy.elements().remove();
        cy.add(elements);
      }

      cy.layout({
        name: window.cytoscapeDagre ? "dagre" : "breadthfirst",
        rankDir: "LR",
        nodeSep: 80,
        rankSep: 64,
        edgeSep: 28,
        fit: false,
        padding: 16,
        directed: true,
        spacingFactor: 0.9,
        animate: false,
      }).run();
      cy.resize();
      cy.fit(undefined, 18);
      graphs.set(address, { cy, signature, container });
    }

    function cssEscape(value) {
      if (window.CSS?.escape) {
        return window.CSS.escape(value);
      }
      return String(value).replace(/["\\\\]/g, "\\\\$&");
    }

    function renderPath(path) {
      if (path.length === 0) {
        return "";
      }
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
    .toolbar {
      display: flex;
      gap: 8px;
      margin-bottom: 14px;
    }
    button {
      padding: 7px 10px;
      border: 1px solid #c9d0da;
      background: white;
      color: inherit;
      font: inherit;
      cursor: pointer;
    }
    button:hover {
      background: #eef2f7;
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
    .steps {
      width: 90px;
      text-align: right;
      white-space: nowrap;
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
      button {
        background: #1d2025;
        border-color: #444b56;
      }
      button:hover {
        background: #252a31;
      }
      .path, .status {
        color: #b8c0cc;
      }
    }
  </style>
</head>
<body>
  <h1>Wikiracer Admin</h1>
  <div class="toolbar">
    <button id="new-round" type="button">New round</button>
    <button id="new-game" type="button">New game</button>
  </div>
  <div id="status" class="status">Connecting...</div>
  <main id="participants" class="empty">No participants yet.</main>
  <script>
    const statusEl = document.querySelector("#status");
    const participantsEl = document.querySelector("#participants");
    const newRoundButton = document.querySelector("#new-round");
    const newGameButton = document.querySelector("#new-game");
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
              <th>Steps</th>
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
                <td class="steps">${escapeHtml(participant.steps || 0)}</td>
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

    async function postAction(path) {
      const response = await fetch(path, { method: "POST" });
      render(await response.json());
    }

    newRoundButton.addEventListener("click", () => {
      postAction("/api/new-round");
    });

    newGameButton.addEventListener("click", () => {
      if (confirm("Reset globally visited pages and clear current paths?")) {
        postAction("/api/new-game");
      }
    });

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


@app.get("/assets/cytoscape.min.js")
def cytoscape_js() -> FileResponse:
    return FileResponse(CYTOSCAPE_PATH, media_type="text/javascript")


@app.get("/assets/dagre.min.js")
def dagre_js() -> FileResponse:
    return FileResponse(CYTOSCAPE_DAGRE_DEPENDENCY_PATH, media_type="text/javascript")


@app.get("/assets/cytoscape-dagre.min.js")
def cytoscape_dagre_js() -> FileResponse:
    return FileResponse(CYTOSCAPE_DAGRE_PATH, media_type="text/javascript")


@app.post("/api/participant-name")
def participant_name(update: ParticipantNameUpdate) -> dict[str, object]:
    return set_participant_name(update.address, update.name)


@app.post("/api/new-round")
def new_round() -> dict[str, object]:
    return reset_round()


@app.post("/api/new-game")
def new_game() -> dict[str, object]:
    clear_visited_pages()
    return reset_game()


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
