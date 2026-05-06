"""api/routes/ws.py — WebSocket endpoint."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from core.events import manager

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive / accept pings
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
