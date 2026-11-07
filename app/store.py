"""In-memory store for proposed entries. Swap for a database before real use."""
import threading

from .models import JournalEntry


class EntryStore:
    def __init__(self) -> None:
        self._entries: dict[str, JournalEntry] = {}
        self._lock = threading.Lock()

    def add(self, entry: JournalEntry) -> JournalEntry:
        with self._lock:
            self._entries[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> JournalEntry | None:
        return self._entries.get(entry_id)

    def all(self) -> list[JournalEntry]:
        return list(self._entries.values())
