from __future__ import annotations

import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from wikiracer.options import monitor_host, monitor_port
from wikiracer.progress import (
    reset_game,
    reset_round,
    set_participant_name,
    snapshot,
    subscribe,
    unsubscribe,
)
from wikiracer.storage import clear_visited_pages


CYTOSCAPE_PATH = Path(__file__).with_name("cytoscape.min.js")
LAYOUT_BASE_PATH = Path(__file__).with_name("layout-base.min.js")
COSE_BASE_PATH = Path(__file__).with_name("cose-base.min.js")
CYTOSCAPE_FCOSE_PATH = Path(__file__).with_name("cytoscape-fcose.min.js")

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
  <script src="/assets/layout-base.min.js"></script>
  <script src="/assets/cose-base.min.js"></script>
  <script src="/assets/cytoscape-fcose.min.js"></script>
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
      margin-bottom: 18px;
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
    .graph-empty {
      position: absolute;
      inset: 0;
      display: grid;
      place-items: center;
      color: #6a7280;
      pointer-events: none;
    }
    .graph-panel {
      height: clamp(360px, 56vh, 760px);
      border: 1px solid #d5dce6;
      background: #ffffff;
      box-shadow: 0 12px 28px rgba(27, 37, 51, .08);
      position: relative;
      overflow: hidden;
    }
    #graph {
      position: absolute;
      inset: 0;
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
      .graph-panel {
        height: 420px;
      }
    }
    @media (prefers-color-scheme: dark) {
      :root {
        background: #15191f;
        color: #eef1f5;
      }
      .participant, .empty, .graph-panel {
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
  <section id="graph-panel" class="graph-panel" hidden>
    <div id="graph"></div>
    <div id="graph-empty" class="graph-empty">No graph yet.</div>
  </section>
  <script>
    const statusEl = document.querySelector("#status");
    const participantsEl = document.querySelector("#participants");
    const graphPanelEl = document.querySelector("#graph-panel");
    const graphEmptyEl = document.querySelector("#graph-empty");
    let graph = null;
    let graphSignature = "";
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
          <section class="participant" style="--accent: ${escapeHtml(participant.color || "#2f80ed")}">
            <div class="summary">
              <h2 class="name">${escapeHtml(participant.displayName)}</h2>
              <span class="steps">${escapeHtml(participant.steps || 0)} steps</span>
            </div>
            <p class="current-label">Current page</p>
            <p class="current">${escapeHtml(participant.currentTitle || "")}</p>
            <!-- <div class="path">${renderPath(participant.path || [])}</div>  -->
          </section>
        `).join("")}
      `;
      renderGraph(state.graph || { nodes: [], edges: [] });
    }

    function renderGraph(graphState) {
      const nodes = graphState.nodes || [];
      const edges = graphState.edges || [];
      const signature = JSON.stringify({
        nodes: nodes.map((node) => [
          node.id,
          node.title,
          (node.currentParticipants || []).map((participant) => participant.color).join(","),
        ]),
        edges: edges.map((edge) => [
          edge.id,
          edge.source,
          edge.target,
          edge.color,
          edge.active,
        ]),
      });
      if (signature === graphSignature) {
        graph?.resize();
        return;
      }
      graphSignature = signature;
      graphPanelEl.hidden = false;
      graphEmptyEl.hidden = nodes.length > 0;
      if (!window.cytoscape || nodes.length === 0) {
        graph?.elements().remove();
        return;
      }

      const elements = [
        ...nodes.map((node) => ({
          classes: (node.currentParticipants || []).length > 0 ? "current" : "",
          position: organicPosition(node.id, nodes, edges),
          data: {
            id: node.id,
            label: node.title,
            currentCount: (node.currentParticipants || []).length,
            ...pieData(node.currentParticipants || []),
          },
        })),
        ...edges.map((edge) => ({
          classes: edge.active ? "active-edge" : "inactive-edge",
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            color: edge.color,
          },
        })),
      ];

      if (!graph) {
        graph = cytoscape({
          container: document.querySelector("#graph"),
          elements,
          boxSelectionEnabled: false,
          autoungrabify: false,
          minZoom: 0.15,
          maxZoom: 4,
          wheelSensitivity: 5,
          textureOnViewport: false,
          style: [
            {
              selector: "node",
              style: {
                "background-color": "#c8ced7",
                "border-color": "#8f9aaa",
                "border-width": 1,
                "color": "#1f2933",
                "font-size": 13,
                "font-weight": 650,
                "label": "data(label)",
                "text-background-color": "#ffffff",
                "text-background-opacity": 0.92,
                "text-background-padding": 3,
                "text-margin-y": -12,
                "text-wrap": "wrap",
                "text-max-width": 125,
                "width": 14,
                "height": 14,
              },
            },
            {
              selector: "node.current",
              style: {
                "background-color": "#ffffff",
                "border-color": "#111827",
                "border-width": 3,
                "pie-size": "100%",
                "pie-1-background-color": "data(pieColor1)",
                "pie-1-background-size": "data(pieSize1)",
                "pie-2-background-color": "data(pieColor2)",
                "pie-2-background-size": "data(pieSize2)",
                "pie-3-background-color": "data(pieColor3)",
                "pie-3-background-size": "data(pieSize3)",
                "pie-4-background-color": "data(pieColor4)",
                "pie-4-background-size": "data(pieSize4)",
                "pie-5-background-color": "data(pieColor5)",
                "pie-5-background-size": "data(pieSize5)",
                "pie-6-background-color": "data(pieColor6)",
                "pie-6-background-size": "data(pieSize6)",
                "width": 24,
                "height": 24,
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
                "arrow-scale": 0.8,
                "width": 1.6,
                "control-point-step-size": 48,
              },
            },
            {
              selector: "edge.active-edge",
              style: {
                "line-color": "data(color)",
                "target-arrow-color": "data(color)",
                "opacity": 0.92,
                "width": 2.4,
              },
            },
            {
              selector: "edge.inactive-edge",
              style: {
                "line-color": "#a8b0bb",
                "target-arrow-color": "#a8b0bb",
                "opacity": 0.38,
                "width": 1.4,
              },
            },
          ],
        });
      } else {
        graph.elements().remove();
        graph.add(elements);
      }

      graph.layout({
        name: window.cytoscapeFcose ? "fcose" : "cose",
        quality: "proof",
        randomize: false,
        nodeDimensionsIncludeLabels: true,
        uniformNodeDimensions: false,
        packComponents: false,
        tile: false,
        nodeRepulsion: 74000,
        idealEdgeLength: 185,
        edgeElasticity: 0.28,
        nestingFactor: 0.1,
        gravity: 0.03,
        gravityRange: 2.4,
        nodeSeparation: 190,
        numIter: 3400,
        fit: true,
        padding: 64,
        animate: true,
        animationDuration: 650,
        stop: () => {
          softenLayoutArtifacts();
          graph.fit(undefined, 54);
        },
      }).run();
      graph.resize();
    }

    function softenLayoutArtifacts() {
      const cyNodes = graph.nodes();
      if (cyNodes.length < 4 || !organicPosition.layout) {
        return;
      }

      const box = cyNodes.boundingBox({ includeLabels: false });
      const width = Math.max(box.w, 1);
      const height = Math.max(box.h, 1);
      const aspect = width / height;
      const gridLike = binnedPositionCount(cyNodes, "x") <= Math.ceil(Math.sqrt(cyNodes.length))
        || binnedPositionCount(cyNodes, "y") <= Math.ceil(Math.sqrt(cyNodes.length));
      const lineLike = aspect > 4.2 || aspect < 0.24;
      if (!lineLike && !gridLike) {
        return;
      }

      const seedBox = boundingBoxForPositions(organicPosition.layout.positions);
      const scale = Math.max(width, height) / Math.max(seedBox.w, seedBox.h, 1);
      const center = { x: box.x1 + width / 2, y: box.y1 + height / 2 };
      const seedCenter = { x: seedBox.x1 + seedBox.w / 2, y: seedBox.y1 + seedBox.h / 2 };
      cyNodes.forEach((node) => {
        const seed = organicPosition.layout.positions.get(node.id());
        if (!seed) {
          return;
        }
        const current = node.position();
        const target = {
          x: center.x + (seed.x - seedCenter.x) * scale,
          y: center.y + (seed.y - seedCenter.y) * scale,
        };
        node.position({
          x: current.x * 0.48 + target.x * 0.52,
          y: current.y * 0.48 + target.y * 0.52,
        });
      });
    }

    function binnedPositionCount(cyNodes, axis) {
      const bins = new Set();
      cyNodes.forEach((node) => {
        bins.add(Math.round(node.position(axis) / 36));
      });
      return bins.size;
    }

    function boundingBoxForPositions(positions) {
      let x1 = Infinity;
      let y1 = Infinity;
      let x2 = -Infinity;
      let y2 = -Infinity;
      for (const position of positions.values()) {
        x1 = Math.min(x1, position.x);
        y1 = Math.min(y1, position.y);
        x2 = Math.max(x2, position.x);
        y2 = Math.max(y2, position.y);
      }
      return { x1, y1, w: x2 - x1, h: y2 - y1 };
    }

    function organicPosition(nodeId, nodes, edges) {
      const layout = organicPosition.layout;
      const signature = JSON.stringify({
        nodes: nodes.map((node) => node.id),
        edges: edges.map((edge) => [edge.source, edge.target]),
      });
      if (!layout || layout.signature !== signature) {
        organicPosition.layout = buildOrganicPositions(nodes, edges, signature);
      }
      return organicPosition.layout.positions.get(nodeId) || { x: 0, y: 0 };
    }

    function buildOrganicPositions(nodes, edges, signature) {
      const nodeIds = nodes.map((node) => node.id);
      const adjacency = new Map(nodeIds.map((id) => [id, []]));
      const indegree = new Map(nodeIds.map((id) => [id, 0]));
      for (const edge of edges) {
        if (!adjacency.has(edge.source) || !adjacency.has(edge.target)) {
          continue;
        }
        adjacency.get(edge.source).push(edge.target);
        adjacency.get(edge.target).push(edge.source);
        indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1);
      }

      const positions = new Map();
      const seen = new Set();
      let componentIndex = 0;
      const componentGap = 820;
      for (const start of nodeIds) {
        if (seen.has(start)) {
          continue;
        }

        const component = [];
        const queue = [start];
        seen.add(start);
        for (let index = 0; index < queue.length; index += 1) {
          const current = queue[index];
          component.push(current);
          for (const next of adjacency.get(current) || []) {
            if (!seen.has(next)) {
              seen.add(next);
              queue.push(next);
            }
          }
        }

        const roots = component.filter((id) => (indegree.get(id) || 0) === 0);
        const root = roots[0] || component[0];
        const depth = new Map([[root, 0]]);
        const order = new Map([[root, 0]]);
        const walk = [root];
        for (let index = 0; index < walk.length; index += 1) {
          const current = walk[index];
          const neighbors = [...(adjacency.get(current) || [])].sort(compareNodeIds);
          for (const next of neighbors) {
            if (!depth.has(next)) {
              depth.set(next, depth.get(current) + 1);
              order.set(next, walk.length);
              walk.push(next);
            }
          }
        }

        component.forEach((id, index) => {
          if (!depth.has(id)) {
            depth.set(id, 0);
            order.set(id, index);
          }
        });

        const maxDepth = Math.max(...component.map((id) => depth.get(id)));
        const centerDepth = maxDepth / 2;
        const phase = stableNoise(`${signature}:${componentIndex}`) * Math.PI * 2;
        for (const id of component) {
          const d = depth.get(id);
          const rank = order.get(id);
          const bow = Math.sin((d + 1) * 1.28 + phase) * 138;
          const branchSpread = (rank - (component.length - 1) / 2) * 36;
          const loosen = stableNoise(`${id}:loosen`) - 0.5;
          positions.set(id, {
            x: componentIndex * componentGap + (d - centerDepth) * 210 + loosen * 70,
            y: bow + branchSpread + (stableNoise(`${id}:lift`) - 0.5) * 96,
          });
        }

        componentIndex += 1;
      }

      return { signature, positions };
    }

    function stableNoise(value) {
      let hash = 2166136261;
      for (let index = 0; index < value.length; index += 1) {
        hash ^= value.charCodeAt(index);
        hash = Math.imul(hash, 16777619);
      }
      return (hash >>> 0) / 4294967295;
    }

    function compareNodeIds(left, right) {
      return Number(left.replace(/\\D/g, "")) - Number(right.replace(/\\D/g, ""));
    }

    function pieData(currentParticipants) {
      const data = {};
      const size = currentParticipants.length > 0 ? 100 / Math.min(currentParticipants.length, 6) : 0;
      for (let index = 1; index <= 6; index += 1) {
        data[`pieColor${index}`] = currentParticipants[index - 1]?.color || "#ffffff";
        data[`pieSize${index}`] = currentParticipants[index - 1] ? size : 0;
      }
      return data;
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


@app.get("/assets/layout-base.min.js")
def layout_base_js() -> FileResponse:
    return FileResponse(LAYOUT_BASE_PATH, media_type="text/javascript")


@app.get("/assets/cose-base.min.js")
def cose_base_js() -> FileResponse:
    return FileResponse(COSE_BASE_PATH, media_type="text/javascript")


@app.get("/assets/cytoscape-fcose.min.js")
def cytoscape_fcose_js() -> FileResponse:
    return FileResponse(CYTOSCAPE_FCOSE_PATH, media_type="text/javascript")


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
        host=monitor_host(),
        port=monitor_port(),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="wikiracer-monitor", daemon=True)
    thread.start()
