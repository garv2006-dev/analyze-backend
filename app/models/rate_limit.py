class RateLimit:
    def __init__(self, id, user_id, request_count=0, time_window="", last_request_time=None):
        self.id = id
        self.user_id = user_id
        self.request_count = request_count
        self.time_window = time_window
        self.last_request_time = last_request_time

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            id=data.get("id"),
            user_id=data.get("user_id"),
            request_count=data.get("request_count", 0),
            time_window=data.get("time_window", ""),
            last_request_time=data.get("last_request_time")
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "request_count": self.request_count,
            "time_window": self.time_window,
            "last_request_time": self.last_request_time.isoformat() if hasattr(self.last_request_time, "isoformat") else self.last_request_time,
        }
