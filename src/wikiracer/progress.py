import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from wikiracer.urls import display_title_from_path

PARTICIPANT_COLORS = [
    "#2f80ed",
    "#27ae60",
    "#eb5757",
    "#f2994a",
    "#9b51e0",
    "#00a6a6",
    "#d946ef",
    "#64748b",
]


@dataclass
class ParticipantProgress:
    address: str
    color: str
    name: str | None = None
    path: list[str] = field(default_factory=list)
    current_node_id: str | None = None

    @property
    def current_title(self) -> str | None:
        return self.path[-1] if self.path else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "displayName": self.name or self.address,
            "color": self.color,
            "currentTitle": self.current_title,
            "path": self.path,
            "steps": len(self.path),
        }


_lock = threading.RLock()
_participants: dict[str, ParticipantProgress] = {}
_graph_nodes: dict[str, dict[str, Any]] = {}
_page_node_ids: dict[tuple[str, str], str] = {}
_graph_edges: list[dict[str, Any]] = []
_next_node_id = 1
_subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]] = set()


def snapshot() -> dict[str, Any]:
    with _lock:
        participants = [
            progress.as_dict()
            for progress in sorted(
                _participants.values(),
                key=lambda item: item.address,
            )
        ]
        current_by_node: dict[str, list[dict[str, str]]] = {}
        for progress in _participants.values():
            if progress.current_node_id is None:
                continue
            current_by_node.setdefault(progress.current_node_id, []).append(
                {
                    "address": progress.address,
                    "name": progress.name or progress.address,
                    "color": progress.color,
                }
            )
        graph = {
            "nodes": [
                {
                    **node,
                    "currentParticipants": current_by_node.get(node["id"], []),
                }
                for node in _graph_nodes.values()
            ],
            "edges": list(_graph_edges),
        }
    return {"participants": participants, "graph": graph}


def record_page(address: str, page: tuple[str, str]) -> dict[str, Any]:
    """Record a fetched page for one participant and notify subscribers."""
    title = display_title_from_path(page[1])
    with _lock:
        progress = participant(address)
        if progress.current_title != title:
            progress.path.append(title)

            node_id = page_node_id(page, title)
            if progress.current_node_id is not None and progress.current_node_id != node_id:
                _graph_edges.append(
                    {
                        "id": f"e{len(_graph_edges) + 1}",
                        "source": progress.current_node_id,
                        "target": node_id,
                        "address": address,
                        "participant": progress.name or address,
                        "color": progress.color,
                        "active": True,
                    }
                )
            progress.current_node_id = node_id
        state = snapshot()

    publish(state)
    return state


def set_participant_name(address: str, name: str) -> dict[str, Any]:
    """Set a display name for a participant and notify subscribers."""
    with _lock:
        progress = participant(address)
        cleaned_name = name.strip()
        progress.name = cleaned_name or None
        state = snapshot()

    publish(state)
    return state


def reset_round() -> dict[str, Any]:
    """Clear participant paths while keeping known participants, names, and graph."""
    with _lock:
        for progress in _participants.values():
            progress.path.clear()
            progress.current_node_id = None
        for edge in _graph_edges:
            edge["active"] = False
        state = snapshot()

    publish(state)
    return state


def reset_game() -> dict[str, Any]:
    """Clear participant paths and graph while keeping known participants and names."""
    global _next_node_id
    with _lock:
        for progress in _participants.values():
            progress.path.clear()
            progress.current_node_id = None
        _graph_nodes.clear()
        _page_node_ids.clear()
        _graph_edges.clear()
        _next_node_id = 1
        state = snapshot()

    publish(state)
    return state


def participant(address: str) -> ParticipantProgress:
    progress = _participants.get(address)
    if progress is None:
        progress = ParticipantProgress(
            address=address,
            color=participant_color(len(_participants)),
        )
        _participants[address] = progress
    return progress


def participant_color(index: int) -> str:
    if index < len(PARTICIPANT_COLORS):
        return PARTICIPANT_COLORS[index]
    hue = (index * 137) % 360
    return f"hsl({hue} 72% 50%)"


def page_node_id(page: tuple[str, str], title: str) -> str:
    global _next_node_id
    existing = _page_node_ids.get(page)
    if existing is not None:
        return existing

    node_id = f"n{_next_node_id}"
    _next_node_id += 1
    _page_node_ids[page] = node_id
    _graph_nodes[node_id] = {
        "id": node_id,
        "title": title,
        "host": page[0],
        "path": page[1],
    }
    return node_id


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    loop = asyncio.get_running_loop()
    with _lock:
        _subscribers.add((loop, queue))
    return queue


def unsubscribe(queue: asyncio.Queue[dict[str, Any]]) -> None:
    with _lock:
        for subscriber in list(_subscribers):
            if subscriber[1] is queue:
                _subscribers.discard(subscriber)


def publish(state: dict[str, Any]) -> None:
    with _lock:
        subscribers = list(_subscribers)

    for loop, queue in subscribers:
        try:
            loop.call_soon_threadsafe(_publish_to_queue, queue, state)
        except RuntimeError:
            unsubscribe(queue)


def _publish_to_queue(
    queue: asyncio.Queue[dict[str, Any]],
    state: dict[str, Any],
) -> None:
    try:
        queue.put_nowait(state)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        queue.put_nowait(state)
