from datetime import datetime
from typing import Any

from fastapi import WebSocket


class LogBroadcaster:
    def __init__(self) -> None:
        self.clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for client in self.clients[:]:
            try:
                await client.send_json(message)
            except Exception:
                self.disconnect(client)


broadcaster = LogBroadcaster()


async def emit(level: str, message: str, **extra: Any) -> None:
    payload = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level.upper(),
        "message": message,
        **extra,
    }
    await broadcaster.broadcast(payload)
