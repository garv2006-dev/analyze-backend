class SavedAsset:
    def __init__(self, id, symbol, url, created_at=None):
        self.id = id
        self.symbol = symbol
        self.url = url
        self.created_at = created_at

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            id=data.get("id"),
            symbol=data.get("symbol"),
            url=data.get("url"),
            created_at=data.get("created_at")
        )

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "url": self.url,
            "created_at": self.created_at.isoformat() if hasattr(self.created_at, "isoformat") else self.created_at,
        }
