"""Thread-safe in-memory store standing in for a database.

Deliberate scope decision (see docs/DESIGN.md): the assignment explicitly
allows an in-memory store for this prototype instead of a real database, so
link data lives only for the lifetime of the process.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LinkRecord:
    long_url: str
    created_at: float
    clicks: int = 0
    last_accessed_at: Optional[float] = None
    recent_hits: List[float] = field(default_factory=list)


class InMemoryStore:
    _MAX_RECENT_HITS = 20

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._links: Dict[str, LinkRecord] = {}
        self._counter = 0

    def next_counter(self) -> int:
        with self._lock:
            self._counter += 1
            return self._counter

    def exists(self, code: str) -> bool:
        with self._lock:
            return code in self._links

    def create(self, code: str, long_url: str) -> LinkRecord:
        with self._lock:
            record = LinkRecord(long_url=long_url, created_at=time.time())
            self._links[code] = record
            return record

    def get(self, code: str) -> Optional[LinkRecord]:
        with self._lock:
            return self._links.get(code)

    def record_hit(self, code: str) -> Optional[LinkRecord]:
        with self._lock:
            record = self._links.get(code)
            if record is None:
                return None
            record.clicks += 1
            record.last_accessed_at = time.time()
            record.recent_hits.append(record.last_accessed_at)
            if len(record.recent_hits) > self._MAX_RECENT_HITS:
                record.recent_hits = record.recent_hits[-self._MAX_RECENT_HITS:]
            return record
