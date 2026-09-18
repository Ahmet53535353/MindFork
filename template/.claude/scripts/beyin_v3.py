"""Local, source-backed memory foundation. No model or network dependencies."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

# Every supported client. "manual" is accepted for receipts only.
HARNESSES = ("codex", "claude", "antigravity", "opencode")


class RevisionConflict(ValueError):
    pass


class ReceiptConflict(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _tokens(text):
    text = unicodedata.normalize("NFKD", str(text).casefold())
    text = "".join(c for c in text if not unicodedata.combining(c)).replace("ı", "i")
    return set(re.findall(r"[a-z0-9]+", text))


STOPWORDS = _tokens("the a an is are was were what which who when where how why of to in on at for from with and or does did do has have latest current please tell about my our this that it its project projects status decision decisions show find get ve veya bir bu su o ne kim neden nasil hangi nedir neydi mi mu icin ile bana benim bizim olarak olan oldu en son guncel proje projesi projesinde karar karari durumu soyle getir bul yok say ignore disregard not no")


class MemoryStore:
    def __init__(self, state_dir, vault_root):
        self.vault_root = Path(vault_root).expanduser().resolve()
        if not self.vault_root.is_dir():
            raise ValueError("vault_root must be an existing directory")
        self.state_dir = Path(state_dir).expanduser().resolve()
        if self.state_dir.is_relative_to(self.vault_root):
            raise ValueError("runtime must be outside vault")
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_dir.chmod(0o700)
        self.database = self.state_dir / "memory.sqlite3"
        if self.database.is_symlink():
            raise ValueError("database must not be a symlink")
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    record TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_record_sequence ON events(record_id,sequence);
            """)
            root = str(self.vault_root)
            binding = db.execute("SELECT value FROM metadata WHERE key='vault_root'").fetchone()
            if binding and binding[0] != root:
                raise ValueError("runtime belongs to another vault")
            if not binding and db.execute("SELECT COUNT(*) FROM records").fetchone()[0]:
                raise ValueError("unbound existing runtime requires explicit migration")
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('vault_root',?)", (root,))
        self.database.chmod(0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        """Connections are scoped to each operation; provided for callers."""

    def context_for(self, harness, query, **kwargs):
        return shared_context(self, harness, query, **kwargs)

    def _source(self, value):
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ValueError("source must be an existing vault-relative file")
        if ".." in Path(value).parts:
            raise ValueError("source traversal rejected")
        target = (self.vault_root / value).resolve()
        if not target.is_relative_to(self.vault_root) or not target.is_file():
            raise ValueError("source missing or outside vault")
        return Path(value).as_posix()

    def _validate(self, record):
        if not isinstance(record, dict):
            raise ValueError("record must be an object")
        record = json.loads(_json(record))
        if not isinstance(record.get("id"), str) or not record["id"].strip():
            raise ValueError("record id required")
        if not isinstance(record.get("text"), str):
            raise ValueError("record text required")
        record["source"] = self._source(record.get("source"))
        record["source_sha256"] = hashlib.sha256((self.vault_root / record["source"]).read_bytes()).hexdigest()
        for field in ("project", "kind", "status", "updated_at"):
            if field in record and not isinstance(record[field], str):
                raise ValueError(field + " must be a string")
        record.setdefault("facts", {})
        if not isinstance(record["facts"], dict):
            raise ValueError("facts must be an object")
        record.setdefault("revision", 1)
        if type(record["revision"]) is not int or record["revision"] < 1:
            raise ValueError("positive revision required")
        record.setdefault("visibility", "internal")
        if record["visibility"] not in ("public", "internal", "private"):
            raise ValueError("invalid visibility")
        supersedes = record.get("supersedes", [])
        if isinstance(supersedes, str):
            supersedes = [supersedes]
        if not isinstance(supersedes, list) or not all(isinstance(v, str) for v in supersedes):
            raise ValueError("supersedes must contain record ids")
        if record["id"] in supersedes:
            raise ValueError("record cannot supersede itself")
        record["supersedes"] = supersedes
        return record

    def ingest(self, record):
        record = self._validate(record)
        payload = _json(record)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM records WHERE id=?", (record["id"],)).fetchone()
            if old:
                if old[0] != payload:
                    raise RevisionConflict("existing id; use update_task with expected revision")
            else:
                db.execute("INSERT INTO records VALUES (?,?)", (record["id"], payload))
                db.execute("INSERT INTO events(event_type,record_id,revision,record) VALUES ('ingest',?,?,?)", (record["id"], record["revision"], payload))
        return record

    def update_task(self, id, expected_revision, changes):
        if not isinstance(changes, dict) or {"id", "revision"} & changes.keys():
            raise ValueError("id and revision cannot be changed")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM records WHERE id=?", (id,)).fetchone()
            if not row:
                raise KeyError(id)
            record = json.loads(row[0])
            if type(expected_revision) is not int or record["revision"] != expected_revision:
                raise RevisionConflict("revision conflict; reread source")
            record.update(changes)
            record["revision"] = expected_revision + 1
            record = self._validate(record)
            db.execute("UPDATE records SET payload=? WHERE id=?", (_json(record), id))
            db.execute("INSERT INTO events(event_type,record_id,revision,record) VALUES ('update',?,?,?)", (id, record["revision"], _json(record)))
        return record

    def history(self, record_id):
        """Committed immutable snapshots, ordered by global event sequence.

        Databases created before events were added have no invented prehistory.
        """
        with self._connect() as db:
            rows = db.execute("SELECT sequence,event_type,record_id,revision,record FROM events WHERE record_id=? ORDER BY sequence", (record_id,)).fetchall()
        return [{"sequence": row[0], "event_type": row[1], "record_id": row[2], "revision": row[3], "record": json.loads(row[4])} for row in rows]

    def submit_receipt(self, event_id, summary, refs, harness):
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id required")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("summary required")
        if harness not in HARNESSES + ("manual",):
            raise ValueError("unsupported harness")
        if not isinstance(refs, list) or not refs:
            raise ValueError("source refs required")
        event = {"event_id": event_id, "summary": summary, "refs": [self._source(ref) for ref in refs], "harness": harness}
        payload = _json(event)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT payload FROM receipts WHERE id=?", (event_id,)).fetchone()
            if old:
                previous = json.loads(old[0])
                if previous["summary"] != summary or previous["refs"] != event["refs"]:
                    raise ReceiptConflict("event_id reused with different payload")
                event = previous
            db.execute("INSERT OR IGNORE INTO receipts VALUES (?,?)", (event_id, payload))
        return dict(event, id=event_id, status="succeeded")

    def retrieve(self, query, project=None, audience="internal", statuses=None, limit=5, budget_chars=8000):
        return self._retrieve(query, project, audience, statuses, limit, budget_chars)

    def snapshot_context(self, audience="internal", budget_chars=6000, limit=5):
        """Explicit bounded current-state snapshot; normal empty queries abstain."""
        return self._retrieve("", audience=audience, statuses=("active", "waiting"),
                              limit=limit, budget_chars=budget_chars, snapshot=True)

    def source_snapshot(self, source_names, audience="internal", budget_chars=3000, source_directory=None, text_transform=None):
        """Return a bounded, source-verified continuity set in requested order."""
        if (not isinstance(source_names, (list, tuple)) or
                not all(isinstance(name, str) and name and "/" not in name and "\\" not in name
                        for name in source_names) or
                type(budget_chars) is not int or budget_chars < 0):
            raise ValueError("invalid source snapshot request")
        if audience not in ("public", "internal", "private"):
            raise ValueError("invalid audience")
        allowed = {"public"} if audience == "public" else {"public", "internal"} if audience == "internal" else {"public", "internal", "private"}
        with self._connect() as db:
            records = [json.loads(row[0]) for row in db.execute("SELECT payload FROM records ORDER BY id")]
        candidates = {name: [] for name in source_names}
        stale_count = 0
        for record in records:
            if (record.get("visibility") not in allowed or record.get("trust") == "untrusted" or
                    record.get("trusted") is False or record.get("status") == "untrusted" or
                    record.get("kind") == "untrusted"):
                continue
            source = record.get("source", "")
            if source_directory is not None and Path(source).parent.as_posix() != source_directory:
                continue
            name = Path(source).name
            if name not in candidates:
                continue
            try:
                self._source(source)
                actual = hashlib.sha256((self.vault_root / source).read_bytes()).hexdigest()
                if actual != record.get("source_sha256"):
                    stale_count += 1
                    continue
            except (ValueError, OSError):
                stale_count += 1
                continue
            preferred = 0 if any(part.casefold().endswith(("companion", "echo")) for part in Path(source).parts[:-1]) else 1
            candidates[name].append((preferred, len(source), source, record))
        chosen = []
        missing = []
        for name in source_names:
            if not candidates[name]:
                missing.append(name)
                continue
            record = min(candidates[name], key=lambda item: item[:3])[3]
            chosen.append({key: record[key] for key in ("id", "source", "title", "kind", "status", "updated_at") if key in record})
            text = record.get("text", "")
            chosen[-1]["text"] = text_transform(name, text) if text_transform else text
        result = {"records": chosen, "citations": [{"id": record["id"], "source": record["source"]} for record in chosen],
                  "requested_sources": list(source_names), "missing_sources": missing,
                  "stale_excluded": stale_count, "truncated": False}
        empty = json.loads(json.dumps(result))
        for record in empty["records"]:
            record["text"] = ""
        available = budget_chars - len(_json(empty))
        if available < 0:
            return {"records": [], "citations": [], "requested_sources": list(source_names),
                    "missing_sources": list(source_names), "stale_excluded": stale_count,
                    "truncated": bool(chosen)}
        share = available // max(1, len(chosen))
        tail_names = {"Journal.md", "Kurallar.md"}
        marker = "[truncated]"
        for record in chosen:
            text = record["text"]
            if len(text) > share:
                keep = max(0, share - len(marker) - 1)
                if not keep:
                    record["text"] = marker
                elif Path(record["source"]).name in tail_names:
                    record["text"] = marker + "\n" + text[-keep:]
                else:
                    record["text"] = text[:keep] + "\n" + marker
                result["truncated"] = True
        while len(_json(result)) > budget_chars and any(record["text"] for record in chosen):
            record = max(chosen, key=lambda item: len(item["text"]))
            text = record["text"]
            prefix = marker + "\n"
            suffix = "\n" + marker
            if text.startswith(prefix) and len(text) > len(prefix):
                record["text"] = prefix + text[len(prefix) + 1:]
            elif text.endswith(suffix) and len(text) > len(suffix):
                record["text"] = text[:-len(suffix) - 1] + suffix
            else:
                record["text"] = text[:-1]
            result["truncated"] = True
        return result

    def _retrieve(self, query, project=None, audience="internal", statuses=None, limit=5, budget_chars=8000, snapshot=False):
        if audience not in ("public", "internal", "private"):
            raise ValueError("invalid audience")
        if not isinstance(query, str) or type(limit) is not int or limit < 0 or type(budget_chars) is not int or budget_chars < 0:
            raise ValueError("invalid query or budget")
        if isinstance(statuses, str):
            statuses = [statuses]
        with self._connect() as db:
            records = [json.loads(row[0]) for row in db.execute("SELECT payload FROM records ORDER BY id")]
        allowed = {"public"} if audience == "public" else {"public", "internal"} if audience == "internal" else {"public", "internal", "private"}
        eligible = []
        stale_count = 0
        for record in records:
            if record["visibility"] not in allowed or record.get("trust") == "untrusted" or record.get("trusted") is False or record.get("status") == "untrusted" or record.get("kind") == "untrusted":
                continue
            if project is not None and record.get("project") != project:
                continue
            try:
                self._source(record["source"])
                actual = hashlib.sha256((self.vault_root / record["source"]).read_bytes()).hexdigest()
                if actual != record.get("source_sha256"):
                    stale_count += 1
                    continue
            except (ValueError, OSError):
                stale_count += 1
                continue
            eligible.append(record)
        superseded = {rid for record in eligible for rid in record["supersedes"]}
        query_tokens = _tokens(query)
        project_tokens = _tokens(project or "")
        terms = query_tokens - STOPWORDS - project_tokens
        scoped_listing = project is not None and bool(query_tokens & project_tokens) and not (query_tokens - STOPWORDS - project_tokens)
        ranked = []
        for record in eligible:
            if record["id"] in superseded:
                continue
            statusless_note = snapshot and "status" not in record and record.get("kind", "note") != "task"
            if statuses is not None and record.get("status") not in statuses and not statusless_note:
                continue
            vocabulary = _tokens(record["text"] + " " + _json(record["facts"]) + " " + str(record.get("title", ""))) - STOPWORDS
            score = len(terms & vocabulary)
            if score or scoped_listing or snapshot:
                ranked.append((score, record))
        ranked.sort(key=lambda item: (item[1].get("updated_at", ""), item[1]["id"]), reverse=True)
        ranked.sort(key=lambda item: -item[0])
        selected, citations = [], []
        used = 0
        clipped_any = False
        for _, record in ranked[:limit]:
            citation = {"id": record["id"], "source": record["source"]}
            size = len(_json(record)) + len(_json(citation))
            if used + size > budget_chars:
                clipped = dict(record, text="", text_truncated=True)
                available = budget_chars - used - len(_json(clipped)) - len(_json(citation))
                marker = " [truncated]"
                if available <= len(marker):
                    continue
                # JSON escaping can cost more than one character per input char.
                text = record["text"][:available - len(marker)]
                clipped["text"] = text + marker
                while text and len(_json(clipped)) + len(_json(citation)) > budget_chars - used:
                    text = text[:-1]
                    clipped["text"] = text + marker
                if not text:
                    continue
                record = clipped
                size = len(_json(record)) + len(_json(citation))
                clipped_any = True
            selected.append(record)
            citations.append(citation)
            used += size
        omitted = len(ranked) - len(selected)
        return {"records": selected, "citations": citations, "abstained": not selected, "truncated": bool(omitted) or clipped_any, "omitted_count": omitted, "used_chars": used, "budget_chars": budget_chars, "stale_count": stale_count}


def shared_context(store, harness, query, **kwargs):
    """Both harnesses call the same source-backed retrieval function."""
    if harness not in HARNESSES:
        raise ValueError("unsupported harness")
    return store.retrieve(query, **kwargs)


def codex_context(store, query, **kwargs):
    return shared_context(store, "codex", query, **kwargs)


def claude_context(store, query, **kwargs):
    return shared_context(store, "claude", query, **kwargs)


def optional_provider(enabled=False, factory=None):
    """No provider code is imported or called unless explicitly enabled."""
    if not enabled:
        return None
    if factory is None or not callable(factory):
        raise ValueError("explicit provider factory required")
    return factory()
