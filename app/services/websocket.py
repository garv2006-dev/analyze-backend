import logging
from typing import List
from fastapi import WebSocket

logger = logging.getLogger("WebSocket")
logger.setLevel(logging.INFO)

class ConnectionManager:
    """Manages active client WebSocket connections and facilitates direct broadcasts."""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔌 WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"🔌 WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: dict):
        """Broadcasts a JSON-serializable dictionary to all active sockets."""
        if not self.active_connections:
            return
            
        logger.info(f"📡 Broadcasting new prediction log to {len(self.active_connections)} client(s)...")
        disconnected_sockets = []
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send message over active socket, marking for removal: {e}")
                disconnected_sockets.append(connection)
                
        # Clean up any broken connections
        for conn in disconnected_sockets:
            self.disconnect(conn)

# Singleton WebSocket manager for global route and service usage
ws_manager = ConnectionManager()
