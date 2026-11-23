"""Private, per-destination crash journal. Each operator has one active writer."""

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path


def recovery_directory() -> Path:
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "TaskBot" / "quota-recovery"
    state = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(state) / "taskbot" / "quota-recovery"


def _make_private_directory(path: Path) -> None:
    if path.is_dir():
        return
    _make_private_directory(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    if os.name == "posix":
        # Make the new directory entry durable on first use, before any sale.
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


class QuotaJournal:
    def __init__(self, directory: Path, destination: tuple, operator_id: str):
        key = hashlib.sha256(json.dumps(destination).encode()).hexdigest()
        folder = directory / key
        _make_private_directory(folder)
        self.operator_id = operator_id
        self.active_id: str | None = None
        # SQLite's OS lock is released even if the owning process is killed.
        self._lease = sqlite3.connect(folder / "owner.sqlite3", timeout=0)
        try:
            self._lease.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            self._lease.close()
            raise RuntimeError("Quota journal is locked or unavailable for this operator") from exc
        try:
            self._db = sqlite3.connect(folder / "pending.sqlite3")
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA synchronous=EXTRA")
            self._db.execute("PRAGMA secure_delete=ON")
            with self._db:
                self._db.execute("""
                    CREATE TABLE IF NOT EXISTS events (
                        sequence INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
                        ready INTEGER NOT NULL CHECK (ready IN (0, 1, 2)),
                        source TEXT NOT NULL, payload TEXT NOT NULL
                    )
                """)
                self._db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS one_open_item ON events(ready) WHERE ready=0"
                )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        try:
            if db := getattr(self, "_db", None):
                db.close()
        finally:
            self._lease.close()

    def begin(self, nik: str, started_at: str, source: str) -> None:
        self.require_resolved()
        event_id = str(uuid.uuid4())
        payload = {"nik": nik, "operator_id": self.operator_id, "started_at": started_at}
        with self._db:
            self._db.execute(
                "INSERT INTO events(id, ready, source, payload) VALUES (?, 0, ?, ?)",
                (event_id, source, json.dumps(payload)),
            )
        self.active_id = event_id

    def require_resolved(self) -> None:
        row = self._db.execute("SELECT id FROM events WHERE ready=0").fetchone()
        if row:
            raise RuntimeError(
                f"Quota event {row['id']} has no recorded outcome. "
                "Check the shop receipt and use the quota recovery command."
            )

    def confirm(self, nik: str, finished_at: str, name: str, customer_type: str) -> None:
        with self._db:
            payload = self.open_item(self.active_id)
            if payload["nik"] != nik:
                raise ValueError("Shop confirmation does not match the open quota event")
            payload.update(status="completed", finished_at=finished_at,
                           nama_pengguna=name, jenis_pengguna=customer_type)
            self._db.execute("UPDATE events SET ready=2, payload=? WHERE id=?",
                             (json.dumps(payload), self.active_id))

    def stage(self, payload: dict, source: str) -> None:
        if payload["operator_id"] != self.operator_id:
            raise ValueError("Terminal row belongs to a different operator")
        with self._db:
            if self.active_id is None:
                self.require_resolved()
                self._db.execute(
                    "INSERT INTO events(id, ready, source, payload) VALUES (?, 1, ?, ?)",
                    (str(uuid.uuid4()), source, json.dumps(payload)),
                )
            else:
                original = self._db.execute(
                    "SELECT ready, payload FROM events WHERE id=?", (self.active_id,)
                ).fetchone()
                if original is None:
                    raise ValueError("Missing open quota event")
                checkpoint = json.loads(original["payload"])
                if checkpoint["nik"] != payload["nik"]:
                    raise ValueError("Terminal row does not match the open quota event")
                if original["ready"] == 2 and payload["status"] != "completed":
                    raise ValueError("A confirmed quota event must stay completed")
                # Keep the full terminal row's timestamp identical to the public
                # report. The earlier confirmation covers a crash before this point.
                self._db.execute("UPDATE events SET ready=1, payload=? WHERE id=?",
                                 (json.dumps(payload), self.active_id))
        self.active_id = None

    def open_item(self, event_id: str) -> dict:
        row = self._db.execute("SELECT payload FROM events WHERE ready=0 AND id=?", (event_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown or already resolved quota event")
        return json.loads(row["payload"])

    def finish_without_quota(self, nik: str) -> None:
        if self.active_id is not None:
            with self._db:
                if self.open_item(self.active_id)["nik"] != nik:
                    raise ValueError("Terminal row does not match the open quota event")
                self._db.execute("DELETE FROM events WHERE id=? AND ready=0", (self.active_id,))
            self.active_id = None

    def reconcile(self, event_id: str, *, confirmed_at: str | None) -> None:
        with self._db:
            payload = self.open_item(event_id)
            if confirmed_at is None:
                self._db.execute("DELETE FROM events WHERE id=? AND ready=0", (event_id,))
            else:
                payload.update(finished_at=confirmed_at, status="completed")
                self._db.execute("UPDATE events SET ready=1, payload=? WHERE id=?",
                                 (json.dumps(payload), event_id))

    def entries(self):
        return self._db.execute("SELECT id, ready, source, payload FROM events ORDER BY sequence")

    def drain(self, deliver) -> int:
        delivered = 0
        while row := self._db.execute(
            "SELECT id, source, payload FROM events WHERE ready IN (1, 2) ORDER BY sequence LIMIT 1"
        ).fetchone():
            deliver(row["id"], row["source"], json.loads(row["payload"]))
            # deliver returns only after PostgreSQL commits the receipt and quota.
            with self._db:
                self._db.execute("DELETE FROM events WHERE id=?", (row["id"],))
            delivered += 1
        return delivered
