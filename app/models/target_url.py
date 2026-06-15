class TargetURL:
    def __init__(self, id, user_id, url, status="inactive", interval_minutes=5, created_at=None, updated_at=None):
        self.id = id
        self.user_id = user_id
        self.url = url
        self.status = status
        self.interval_minutes = interval_minutes
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            id=data.get("id"),
            user_id=data.get("user_id"),
            url=data.get("url"),
            status=data.get("status", "inactive"),
            interval_minutes=data.get("interval_minutes", 5),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at")
        )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "url": self.url,
            "status": self.status,
            "interval_minutes": self.interval_minutes,
            "created_at": self.created_at.isoformat() if hasattr(self.created_at, "isoformat") else self.created_at,
            "updated_at": self.updated_at.isoformat() if hasattr(self.updated_at, "isoformat") else self.updated_at,
        }
