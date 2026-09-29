from dataclasses import dataclass, asdict
from queue import Queue

@dataclass
class ActionEvent:
    action: str
    source: str = "gesture"
    confidence: float = 1.0
    x: float | None = None
    y: float | None = None
    def to_dict(self):
        return asdict(self)

class ActionQueue:
    def __init__(self):
        self.queue = Queue()
    def put(self, event):
        self.queue.put(event)
    def get_nowait(self):
        return self.queue.get_nowait()
