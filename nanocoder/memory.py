"""Long-term memory - persist key facts across sessions.

Two layers:
  Short-term = self.messages (already in agent.py)
  Long-term  = this module: JSON-backed store with keyword search

Inspired by CrewAI's unified Memory (remember/recall/forget) and
OpenAI Agents SDK's Session protocol.
"""

import json
import time
import re
from pathlib import Path
from dataclasses import dataclass, field, asdict


MEMORY_DIR = Path.home() / ".nanocoder" / "memory"


@dataclass
class MemoryEntry:
    id: str
    text: str
    scope: str = "global"
    importance: float = 1.0
    created_at: float = 0.0
    tags: list[str] = field(default_factory=list)


class Memory:
    """Simple keyword-based long-term memory backed by a single JSON file."""

    def __init__(self, store_path: Path | None = None):
        self._path = store_path or (MEMORY_DIR / "memories.json")
        self._entries: list[MemoryEntry] = []
        self._load()

    # -- public API --

    def remember(self, text: str, scope: str = "global",
                 importance: float = 1.0, tags: list[str] | None = None) -> str:
        """Store a new memory entry. Returns the entry id."""
        entry = MemoryEntry(
            id=f"mem_{int(time.time() * 1000)}",
            text=text,
            scope=scope,
            importance=importance,
            created_at=time.time(),
            tags=tags or [],
        )
        self._entries.append(entry)
        self._save()
        return entry.id

    def recall(self, query: str, top_k: int = 5, scope: str | None = None) -> list[MemoryEntry]:
        """Retrieve the most relevant memories for a query.

        Scoring: keyword overlap * importance * recency decay.
        """
        query_words = set(_tokenize(query))
        if not query_words:
            return []

        scored: list[tuple[float, MemoryEntry]] = []
        now = time.time()

        for entry in self._entries:
            if scope and entry.scope != scope:
                continue
            entry_words = set(_tokenize(entry.text)) | set(entry.tags)
            overlap = len(query_words & entry_words)
            if overlap == 0:
                continue
            keyword_score = overlap / max(len(query_words), 1)
            age_days = (now - entry.created_at) / 86400
            recency = 1.0 / (1.0 + age_days * 0.1)
            score = keyword_score * entry.importance * recency
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def forget(self, entry_id: str) -> bool:
        """Remove a memory entry by id."""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.id != entry_id]
        if len(self._entries) < before:
            self._save()
            return True
        return False

    def list_all(self, scope: str | None = None) -> list[MemoryEntry]:
        if scope:
            return [e for e in self._entries if e.scope == scope]
        return list(self._entries)

    def format_for_prompt(self, entries: list[MemoryEntry]) -> str:
        """Format recalled memories as a string to inject into system prompt."""
        if not entries:
            return ""
        lines = ["# Recalled memories (from previous sessions)"]
        for e in entries:
            lines.append(f"- {e.text}")
        return "\n".join(lines)

    # -- extraction helper --

    @staticmethod
    def extract_from_conversation(messages: list[dict]) -> list[str]:
        """Extract memorable facts from a conversation: file paths, decisions, errors, preferences."""
        facts: list[str] = []
        files_seen: set[str] = set()

        for m in messages:
            text = m.get("content", "") or ""
            role = m.get("role", "")

            for match in re.finditer(r'[\w./\\-]+\.\w{1,5}', text):
                files_seen.add(match.group())

            if role == "user":
                for pattern in [
                    r"(?:prefer|always|never|use|don't use)\s+.{5,60}",
                    r"(?:style|convention|format)\s*[:=]\s*.{5,40}",
                ]:
                    for match in re.finditer(pattern, text, re.IGNORECASE):
                        facts.append(f"User preference: {match.group().strip()}")

        if files_seen:
            facts.append(f"Files worked on: {', '.join(sorted(files_seen)[:15])}")

        return facts

    # -- persistence --

    def _load(self):
        if not self._path.exists():
            self._entries = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [MemoryEntry(**e) for e in data]
        except (json.JSONDecodeError, TypeError, KeyError):
            self._entries = []

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(e) for e in self._entries]
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase words for keyword matching."""
    return [w.lower() for w in re.findall(r'\w{2,}', text)]
