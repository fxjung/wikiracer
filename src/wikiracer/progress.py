import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from wikiracer.urls import display_title_from_path


@dataclass
class ParticipantProgress:
    address: str
    name: str | None = None
    path: list[str] = field(default_factory=list)

    @property
    def current_title(self) -> str | None:
        return self.path[-1] if self.path else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "name": self.name,
            "displayName": self.name or self.address,
            "currentTitle": self.current_title,
            "path": self.path,
            "steps": len(self.path),
        }


_lock = threading.RLock()
_participants: dict[str, ParticipantProgress] = {}
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
    return {"participants": participants}


def record_page(address: str, page: tuple[str, str]) -> dict[str, Any]:
    """Record a fetched page for one participant and notify subscribers."""
    title = display_title_from_path(page[1])
    with _lock:
        progress = _participants.setdefault(
            address,
            ParticipantProgress(address=address),
        )
        if progress.current_title != title:
            progress.path.append(title)
        state = snapshot()

    publish(state)
    return state


def set_participant_name(address: str, name: str) -> dict[str, Any]:
    """Set a display name for a participant and notify subscribers."""
    with _lock:
        progress = _participants.get(address)
        if progress is None:
            return snapshot()
        cleaned_name = name.strip()
        progress.name = cleaned_name or None
        state = snapshot()

    publish(state)
    return state


def reset_round() -> dict[str, Any]:
    """Clear participant paths while keeping known participants and names."""
    with _lock:
        for progress in _participants.values():
            progress.path.clear()
        state = snapshot()

    publish(state)
    return state


def reset_game() -> dict[str, Any]:
    """Clear participant paths while keeping known participants and names."""
    return reset_round()


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
