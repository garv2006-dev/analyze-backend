from datetime import timezone
from backend.app.config import BACKEND_URL

class Screenshot:
    def __init__(self, id, user_id, url_id, image_path, highlighted_image_path=None, timestamp=None):
        self.id = id
        self.user_id = user_id
        self.url_id = url_id
        self.image_path = image_path
        self.highlighted_image_path = highlighted_image_path
        self.timestamp = timestamp

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            id=data.get("id"),
            user_id=data.get("user_id"),
            url_id=data.get("url_id"),
            image_path=data.get("image_path"),
            highlighted_image_path=data.get("highlighted_image_path"),
            timestamp=data.get("timestamp")
        )

    def to_dict(self):
        ts = self.timestamp
        if ts:
            if hasattr(ts, "tzinfo"):
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                timestamp_str = ts.isoformat()
            else:
                timestamp_str = str(ts)
        else:
            timestamp_str = None

        return {
            "id": self.id,
            "user_id": self.user_id,
            "url_id": self.url_id,
            "image_path": self.image_path,
            "image_url": self.image_path if (self.image_path and (self.image_path.startswith("http://") or self.image_path.startswith("https://"))) else f"{BACKEND_URL}/screenshots/{self.image_path}",
            "highlighted_image_path": self.highlighted_image_path,
            "highlighted_image_url": self.highlighted_image_path if (self.highlighted_image_path and (self.highlighted_image_path.startswith("http://") or self.highlighted_image_path.startswith("https://"))) else (f"{BACKEND_URL}/screenshots/{self.highlighted_image_path}" if self.highlighted_image_path else None),
            "timestamp": timestamp_str,
        }
