from datetime import timezone

class Log:
    def __init__(self, id, user_id, event_type, message, timestamp=None):
        self.id = id
        self.user_id = user_id
        self.event_type = event_type
        self.message = message
        self.timestamp = timestamp

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            id=data.get("id"),
            user_id=data.get("user_id"),
            event_type=data.get("event_type"),
            message=data.get("message"),
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
            "event_type": self.event_type,
            "message": self.message,
            "timestamp": timestamp_str,
        }
