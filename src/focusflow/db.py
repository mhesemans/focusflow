from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "FocusFlow"
STATUSES = ["New", "Planned", "Work in Progress", "Overdue", "Complete"]
PRIORITIES = ["No pressure", "Due soon", "Urgent"]
WORK_BLOCK_SECONDS = 30 * 60


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_dt(value: str | None) -> str:
    dt = parse_dt(value)
    if not dt:
        return "Not set"
    return dt.strftime("%d %b %Y, %H:%M")


def format_duration(seconds: int | float | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def safe_filename(name: str) -> str:
    keep = []
    for char in name:
        if char.isalnum() or char in {" ", ".", "_", "-"}:
            keep.append(char)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip()
    return cleaned or "attachment"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        root = Path(base)
    else:
        root = Path.home() / ".local" / "share"
    path = root / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class TaskPatch:
    title: str
    description: str
    priority: str
    due_at: str | None


class TaskStore:
    def __init__(self, db_path: Path | None = None):
        self.root = data_dir()
        self.db_path = db_path or self.root / "focusflow.db"
        self.attachments_dir = self.root / "attachments"
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'No pressure',
                    status TEXT NOT NULL DEFAULT 'New',
                    created_at TEXT NOT NULL,
                    due_at TEXT,
                    completed_at TEXT,
                    total_work_seconds INTEGER NOT NULL DEFAULT 0,
                    current_session_started_at TEXT,
                    paused INTEGER NOT NULL DEFAULT 0,
                    last_updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS task_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                """
            )

    def create_task(self, patch: TaskPatch) -> int:
        created = now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO tasks (title, description, priority, status, created_at, due_at, last_updated_at)
                VALUES (?, ?, ?, 'New', ?, ?, ?)
                """,
                (patch.title.strip(), patch.description.strip(), patch.priority, created, patch.due_at, created),
            )
            return int(cur.lastrowid)

    def update_task(self, task_id: int, patch: TaskPatch) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET title = ?, description = ?, priority = ?, due_at = ?, last_updated_at = ?
                 WHERE id = ?
                """,
                (patch.title.strip(), patch.description.strip(), patch.priority, patch.due_at, now_iso(), task_id),
            )

    def delete_task(self, task_id: int) -> None:
        task_folder = self.attachments_dir / str(task_id)
        with self._connect() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if task_folder.exists():
            shutil.rmtree(task_folder, ignore_errors=True)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, include_complete: bool = False, search: str = "") -> list[dict[str, Any]]:
        self.apply_overdue_rules()
        params: list[Any] = []
        where = []
        if not include_complete:
            where.append("status <> 'Complete'")
        if search.strip():
            where.append(
                """
                (LOWER(title) LIKE ? OR LOWER(description) LIKE ?
                 OR EXISTS (
                    SELECT 1
                      FROM task_notes
                     WHERE task_notes.task_id = tasks.id
                       AND LOWER(task_notes.note) LIKE ?
                 ))
                """
            )
            term = f"%{search.strip().lower()}%"
            params.extend([term, term, term])
        sql = "SELECT * FROM tasks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE priority WHEN 'Urgent' THEN 0 WHEN 'Due soon' THEN 1 ELSE 2 END, COALESCE(due_at, '9999'), created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def add_note(self, task_id: int, note: str) -> int:
        text = note.strip()
        if not text:
            raise ValueError("Note cannot be empty")
        created = now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_notes (task_id, note, created_at)
                VALUES (?, ?, ?)
                """,
                (task_id, text, created),
            )
            conn.execute(
                "UPDATE tasks SET last_updated_at = ? WHERE id = ?",
                (created, task_id),
            )
            return int(cur.lastrowid)

    def list_notes(self, task_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_notes WHERE task_id = ? ORDER BY created_at DESC, id DESC",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_note(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_notes WHERE task_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    def notes_count(self, task_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM task_notes WHERE task_id = ?", (task_id,)).fetchone()
        return int(row["count"])

    def delete_note(self, note_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM task_notes WHERE id = ?", (note_id,))

    def attachment_count(self, task_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM attachments WHERE task_id = ?", (task_id,)).fetchone()
        return int(row["count"])

    def list_attachments(self, task_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM attachments WHERE task_id = ? ORDER BY added_at DESC", (task_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_attachment(self, task_id: int, source_path: str | os.PathLike[str]) -> int:
        source = Path(source_path)
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(str(source))
        task_folder = self.attachments_dir / str(task_id)
        task_folder.mkdir(parents=True, exist_ok=True)
        stored_name = f"{uuid.uuid4().hex}_{safe_filename(source.name)}"
        destination = task_folder / stored_name
        shutil.copy2(source, destination)
        added = now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO attachments (task_id, original_name, stored_path, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, source.name, str(destination), added),
            )
            return int(cur.lastrowid)

    def delete_attachment(self, attachment_id: int) -> None:
        with self._connect() as conn:
            row = conn.execute("SELECT stored_path FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
            conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
        if row:
            try:
                Path(row["stored_path"]).unlink(missing_ok=True)
            except OSError:
                pass

    def move_task(self, task_id: int, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status}")
        if status == "Work in Progress":
            self.start_task(task_id)
            return
        if status == "Complete":
            self.complete_task(task_id)
            return
        # Moving away from active work captures the current work segment first.
        self.pause_task(task_id, mark_paused=False)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = ?, paused = 0, current_session_started_at = NULL,
                       completed_at = NULL, last_updated_at = ?
                 WHERE id = ?
                """,
                (status, now_iso(), task_id),
            )

    def start_task(self, task_id: int) -> None:
        # Keep the app deliberately calm: only one task can actively run at once.
        self.pause_all_active(except_task_id=task_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = 'Work in Progress', paused = 0,
                       current_session_started_at = ?, completed_at = NULL, last_updated_at = ?
                 WHERE id = ?
                """,
                (now_iso(), now_iso(), task_id),
            )

    def pause_task(self, task_id: int, mark_paused: bool = True) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        total = int(task["total_work_seconds"] or 0)
        started = parse_dt(task.get("current_session_started_at"))
        if started and not int(task.get("paused") or 0):
            total += max(0, int((datetime.now() - started).total_seconds()))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET total_work_seconds = ?, current_session_started_at = NULL,
                       paused = ?, last_updated_at = ?
                 WHERE id = ?
                """,
                (total, 1 if mark_paused else 0, now_iso(), task_id),
            )

    def pause_all_active(self, except_task_id: int | None = None) -> None:
        active = self.active_task()
        if active and active["id"] != except_task_id:
            self.pause_task(int(active["id"]), mark_paused=True)

    def unpause_task(self, task_id: int) -> None:
        self.pause_all_active(except_task_id=task_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = 'Work in Progress', paused = 0,
                       current_session_started_at = ?, completed_at = NULL, last_updated_at = ?
                 WHERE id = ?
                """,
                (now_iso(), now_iso(), task_id),
            )

    def park_task(self, task_id: int) -> None:
        self.pause_task(task_id, mark_paused=False)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = 'Planned', paused = 0, current_session_started_at = NULL,
                       last_updated_at = ?
                 WHERE id = ?
                """,
                (now_iso(), task_id),
            )

    def complete_task(self, task_id: int) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        total = int(task["total_work_seconds"] or 0)
        started = parse_dt(task.get("current_session_started_at"))
        if started and not int(task.get("paused") or 0):
            total += max(0, int((datetime.now() - started).total_seconds()))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = 'Complete', completed_at = ?, total_work_seconds = ?,
                       current_session_started_at = NULL, paused = 0, last_updated_at = ?
                 WHERE id = ?
                """,
                (now_iso(), total, now_iso(), task_id),
            )

    def active_task(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tasks
                 WHERE status = 'Work in Progress'
                   AND current_session_started_at IS NOT NULL
                   AND paused = 0
                 ORDER BY last_updated_at DESC
                 LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def apply_overdue_rules(self) -> None:
        current = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE tasks
                   SET status = 'Overdue', last_updated_at = ?
                 WHERE status IN ('New', 'Planned')
                   AND due_at IS NOT NULL
                   AND due_at < ?
                """,
                (current, current),
            )

    def effective_work_seconds(self, task: dict[str, Any]) -> int:
        total = int(task.get("total_work_seconds") or 0)
        started = parse_dt(task.get("current_session_started_at"))
        if started and not int(task.get("paused") or 0):
            total += max(0, int((datetime.now() - started).total_seconds()))
        return total

    def current_segment_seconds(self, task: dict[str, Any]) -> int:
        started = parse_dt(task.get("current_session_started_at"))
        if not started or int(task.get("paused") or 0):
            return 0
        return max(0, int((datetime.now() - started).total_seconds()))
