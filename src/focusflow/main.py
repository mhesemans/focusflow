from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDateTime, QMimeData, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QDrag, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSystemTrayIcon,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .db import (
    PRIORITIES,
    STATUSES,
    WORK_BLOCK_SECONDS,
    TaskPatch,
    TaskStore,
    format_dt,
    format_duration,
    parse_dt,
)

MIME_TASK_ID = "application/x-focusflow-task-id"


def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative_path


class TaskDialog(QDialog):
    def __init__(self, store: TaskStore, task: dict[str, Any] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.task = task
        self.pending_files: list[Path] = []
        self.setWindowTitle("Edit task" if task else "New task")
        self.setMinimumWidth(620)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Clear, small task title")
        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText(
            "Useful context, links, notes, or the next tiny step")
        self.description_input.setMinimumHeight(120)

        self.priority_input = QComboBox()
        self.priority_input.addItems(PRIORITIES)

        self.due_input = QDateTimeEdit()
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("dd MMM yyyy HH:mm")
        self.due_input.setDateTime(QDateTime.currentDateTime().addDays(1))

        self.attachment_list = QListWidget()
        self.attachment_list.setMinimumHeight(110)
        add_attachment_button = QPushButton("Add attachment")
        remove_attachment_button = QPushButton("Remove selected")
        open_attachment_button = QPushButton("Open selected")
        add_attachment_button.clicked.connect(self.add_attachment)
        remove_attachment_button.clicked.connect(
            self.remove_selected_attachment)
        open_attachment_button.clicked.connect(self.open_selected_attachment)

        form = QGridLayout()
        form.addWidget(QLabel("Title"), 0, 0)
        form.addWidget(self.title_input, 0, 1)
        form.addWidget(QLabel("Priority"), 1, 0)
        form.addWidget(self.priority_input, 1, 1)
        form.addWidget(QLabel("Planned due"), 2, 0)
        form.addWidget(self.due_input, 2, 1)
        form.addWidget(QLabel("Description"), 3, 0, Qt.AlignTop)
        form.addWidget(self.description_input, 3, 1)

        attachment_buttons = QHBoxLayout()
        attachment_buttons.addWidget(add_attachment_button)
        attachment_buttons.addWidget(remove_attachment_button)
        attachment_buttons.addWidget(open_attachment_button)
        attachment_buttons.addStretch(1)

        attachment_group = QGroupBox("Attachments")
        attachment_layout = QVBoxLayout(attachment_group)
        attachment_layout.addWidget(self.attachment_list)
        attachment_layout.addLayout(attachment_buttons)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(attachment_group)
        layout.addWidget(buttons)

        if task:
            self.title_input.setText(task["title"])
            self.description_input.setPlainText(task.get("description") or "")
            self.priority_input.setCurrentText(
                task.get("priority") or PRIORITIES[0])
            due = parse_dt(task.get("due_at"))
            if due:
                self.due_input.setDateTime(
                    QDateTime.fromSecsSinceEpoch(int(due.timestamp())))
            self.reload_attachments()

        self.title_input.setFocus()

    def patch(self) -> TaskPatch:
        return TaskPatch(
            title=self.title_input.text(),
            description=self.description_input.toPlainText(),
            priority=self.priority_input.currentText(),
            due_at=self.due_input.dateTime().toPython().replace(microsecond=0).isoformat(),
        )

    def accept(self) -> None:
        if not self.title_input.text().strip():
            QMessageBox.warning(self, "Missing title",
                                "Give the task a short title first.")
            return
        super().accept()

    def reload_attachments(self) -> None:
        self.attachment_list.clear()
        if self.task:
            for attachment in self.store.list_attachments(int(self.task["id"])):
                item = QListWidgetItem(attachment["original_name"])
                item.setData(Qt.UserRole, attachment)
                self.attachment_list.addItem(item)
        else:
            for file_path in self.pending_files:
                item = QListWidgetItem(file_path.name)
                item.setData(Qt.UserRole, {"pending_path": str(file_path)})
                self.attachment_list.addItem(item)

    def add_attachment(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Add attachments")
        if not paths:
            return
        if self.task:
            errors = []
            for path in paths:
                try:
                    self.store.add_attachment(int(self.task["id"]), path)
                except Exception as exc:  # pragma: no cover - GUI safety net
                    errors.append(f"{Path(path).name}: {exc}")
            self.reload_attachments()
            if errors:
                QMessageBox.warning(
                    self, "Some attachments failed", "\n".join(errors))
        else:
            self.pending_files.extend(Path(path) for path in paths)
            self.reload_attachments()

    def selected_attachment_data(self) -> dict[str, Any] | None:
        item = self.attachment_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)

    def remove_selected_attachment(self) -> None:
        data = self.selected_attachment_data()
        if not data:
            return
        if "pending_path" in data:
            self.pending_files = [path for path in self.pending_files if str(
                path) != data["pending_path"]]
        else:
            self.store.delete_attachment(int(data["id"]))
        self.reload_attachments()

    def open_selected_attachment(self) -> None:
        data = self.selected_attachment_data()
        if not data:
            return
        path = data.get("stored_path") or data.get("pending_path")
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class NotesDialog(QDialog):
    def __init__(
        self,
        store: TaskStore,
        task: dict[str, Any],
        prompt: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.store = store
        self.task = task
        self.setWindowTitle("Task notes")
        self.setMinimumWidth(560)

        title = QLabel(task["title"])
        title.setWordWrap(True)
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))

        self.note_input = QTextEdit()
        self.note_input.setMinimumHeight(90)
        self.note_input.setPlaceholderText(
            prompt or "Add a quick note, handover summary, blocker, or next tiny step"
        )

        add_button = QPushButton("Save note")
        add_button.clicked.connect(self.add_note)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        delete_button = QPushButton("Delete selected note")
        delete_button.clicked.connect(self.delete_selected_note)

        self.note_list = QListWidget()
        self.note_list.setMinimumHeight(180)

        input_buttons = QHBoxLayout()
        input_buttons.addWidget(add_button)
        input_buttons.addStretch(1)

        list_buttons = QHBoxLayout()
        list_buttons.addWidget(delete_button)
        list_buttons.addStretch(1)
        list_buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Task"))
        layout.addWidget(title)
        layout.addWidget(QLabel("New note"))
        layout.addWidget(self.note_input)
        layout.addLayout(input_buttons)
        layout.addWidget(QLabel("Previous notes"))
        layout.addWidget(self.note_list)
        layout.addLayout(list_buttons)

        self.reload_notes()
        self.note_input.setFocus()

    def reload_notes(self) -> None:
        self.note_list.clear()
        notes = self.store.list_notes(int(self.task["id"]))
        if not notes:
            self.note_list.addItem("No notes yet.")
            self.note_list.item(0).setFlags(Qt.NoItemFlags)
            return
        for note in notes:
            item = QListWidgetItem(
                f"{format_dt(note['created_at'])}\n{note['note']}")
            item.setData(Qt.UserRole, note)
            self.note_list.addItem(item)

    def add_note(self) -> None:
        text = self.note_input.toPlainText().strip()
        if not text:
            return
        self.store.add_note(int(self.task["id"]), text)
        self.note_input.clear()
        self.reload_notes()

    def delete_selected_note(self) -> None:
        item = self.note_list.currentItem()
        if not item:
            return
        note = item.data(Qt.UserRole)
        if not note:
            return
        self.store.delete_note(int(note["id"]))
        self.reload_notes()


class TaskCard(QFrame):
    editRequested = Signal(int)
    deleteRequested = Signal(int)
    startRequested = Signal(int)
    pauseRequested = Signal(int)
    unpauseRequested = Signal(int)
    parkRequested = Signal(int)
    completeRequested = Signal(int)
    notesRequested = Signal(int)

    def __init__(self, store: TaskStore, task: dict[str, Any], parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.task = task
        self.drag_start_position = QPoint()
        self.setObjectName("TaskCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.OpenHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.build_ui()

    def build_ui(self) -> None:
        priority = self.task.get("priority", "No pressure")
        priority_class = priority.lower().replace(" ", "-")
        status = self.task.get("status")
        paused = bool(self.task.get("paused"))

        self.setProperty("priority", priority_class)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        title = QLabel(self.task["title"])
        title.setWordWrap(True)
        title.setFont(QFont("Segoe UI", 10, QFont.Bold))
        layout.addWidget(title)

        meta = QLabel(f"{priority} • Due {format_dt(self.task.get('due_at'))}")
        meta.setObjectName("MetaLabel")
        meta.setWordWrap(True)
        layout.addWidget(meta)

        description = (self.task.get("description") or "").strip()
        if description:
            short_description = description[:130] + \
                ("…" if len(description) > 130 else "")
            desc = QLabel(short_description)
            desc.setObjectName("DescriptionLabel")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        latest_note = self.store.latest_note(int(self.task["id"]))
        if latest_note:
            note_text = latest_note["note"].replace("\n", " ").strip()
            short_note = note_text[:110] + \
                ("…" if len(note_text) > 110 else "")
            note = QLabel(f"Latest note: {short_note}")
            note.setObjectName("NoteLabel")
            note.setWordWrap(True)
            layout.addWidget(note)

        work_seconds = self.store.effective_work_seconds(self.task)
        segment_seconds = self.store.current_segment_seconds(self.task)
        remaining = max(0, WORK_BLOCK_SECONDS - segment_seconds)
        attachment_count = self.store.attachment_count(int(self.task["id"]))
        note_count = self.store.notes_count(int(self.task["id"]))
        details = [f"Worked: {format_duration(work_seconds)}"]
        if status == "Work in Progress" and not paused:
            details.append(f"Break in: {format_duration(remaining)}")
        if paused:
            details.append("Paused")
        if attachment_count:
            details.append(
                f"{attachment_count} attachment{'s' if attachment_count != 1 else ''}")
        if note_count:
            details.append(
                f"{note_count} note{'s' if note_count != 1 else ''}")
        detail_label = QLabel(" • ".join(details))
        detail_label.setObjectName("MetaLabel")
        detail_label.setWordWrap(True)
        layout.addWidget(detail_label)

        primary_buttons = QHBoxLayout()
        primary_buttons.setSpacing(4)

        if status != "Complete":
            if status == "Work in Progress" and paused:
                unpause = QPushButton("Unpause")
                unpause.clicked.connect(
                    lambda: self.unpauseRequested.emit(int(self.task["id"])))
                park = QPushButton("Park")
                park.clicked.connect(
                    lambda: self.parkRequested.emit(int(self.task["id"])))
                primary_buttons.addWidget(unpause)
                primary_buttons.addWidget(park)
            elif status == "Work in Progress":
                pause = QPushButton("Pause")
                pause.clicked.connect(
                    lambda: self.pauseRequested.emit(int(self.task["id"])))
                primary_buttons.addWidget(pause)
            else:
                start = QPushButton("Start")
                start.clicked.connect(
                    lambda: self.startRequested.emit(int(self.task["id"])))
                primary_buttons.addWidget(start)

            complete = QPushButton("Done")
            complete.clicked.connect(
                lambda: self.completeRequested.emit(int(self.task["id"])))
            primary_buttons.addWidget(complete)
            primary_buttons.addStretch(1)
            layout.addLayout(primary_buttons)

        secondary_buttons = QHBoxLayout()
        secondary_buttons.setSpacing(4)
        note_button = QPushButton("Note")
        note_button.clicked.connect(
            lambda: self.notesRequested.emit(int(self.task["id"])))
        secondary_buttons.addWidget(note_button)

        edit = QPushButton("Edit")
        edit.clicked.connect(
            lambda: self.editRequested.emit(int(self.task["id"])))
        secondary_buttons.addWidget(edit)

        delete = QPushButton("⋯")
        delete.setToolTip("Delete task")
        delete.clicked.connect(
            lambda: self.deleteRequested.emit(int(self.task["id"])))
        secondary_buttons.addWidget(delete)
        secondary_buttons.addStretch(1)
        layout.addLayout(secondary_buttons)

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if not (event.buttons() & Qt.LeftButton):
            return
        if (event.position().toPoint() - self.drag_start_position).manhattanLength() < QApplication.startDragDistance():
            return
        mime_data = QMimeData()
        mime_data.setData(MIME_TASK_ID, str(self.task["id"]).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.exec(Qt.MoveAction)


class KanbanColumn(QFrame):
    taskDropped = Signal(int, str)

    def __init__(self, status: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.status = status
        self.setAcceptDrops(True)
        self.setObjectName("KanbanColumn")
        self.setMinimumWidth(185)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.layout.setSpacing(8)
        self.header = QLabel(status)
        self.header.setObjectName("ColumnHeader")
        self.header.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.header)
        self.cards_layout = QVBoxLayout()
        self.cards_layout.setSpacing(8)
        self.layout.addLayout(self.cards_layout)
        self.layout.addStretch(1)

    def set_count(self, count: int) -> None:
        self.header.setText(f"{self.status} ({count})")

    def clear_cards(self) -> None:
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_card(self, card: TaskCard) -> None:
        self.cards_layout.addWidget(card)

    def dragEnterEvent(self, event):  # type: ignore[override]
        if event.mimeData().hasFormat(MIME_TASK_ID):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):  # type: ignore[override]
        if event.mimeData().hasFormat(MIME_TASK_ID):
            event.acceptProposedAction()

    def dropEvent(self, event):  # type: ignore[override]
        if event.mimeData().hasFormat(MIME_TASK_ID):
            task_id = int(bytes(event.mimeData().data(
                MIME_TASK_ID)).decode("utf-8"))
            self.taskDropped.emit(task_id, self.status)
            event.acceptProposedAction()


class FocusWindow(QWidget):
    pauseRequested = Signal(int)
    unpauseRequested = Signal(int)
    parkRequested = Signal(int)
    completeRequested = Signal(int)
    notesRequested = Signal(int)

    def __init__(self):
        super().__init__()
        self.task_id: int | None = None
        self.setWindowTitle("Focus task")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setMinimumWidth(310)
        self.setObjectName("FocusWindow")

        self.title_label = QLabel("No task running")
        self.title_label.setWordWrap(True)
        self.title_label.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.time_label = QLabel("Worked: 0m 00s")
        self.break_label = QLabel("Break in: 30m 00s")

        self.pause_button = QPushButton("Pause")
        self.unpause_button = QPushButton("Unpause")
        self.park_button = QPushButton("Park")
        self.done_button = QPushButton("Done")
        self.pause_button.clicked.connect(self._pause)
        self.unpause_button.clicked.connect(self._unpause)
        self.park_button.clicked.connect(self._park)
        self.done_button.clicked.connect(self._complete)

        buttons = QHBoxLayout()
        buttons.addWidget(self.pause_button)
        buttons.addWidget(self.unpause_button)
        buttons.addWidget(self.park_button)
        buttons.addWidget(self.done_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.time_label)
        layout.addWidget(self.break_label)
        layout.addLayout(buttons)

    def update_task(self, store: TaskStore, task: dict[str, Any] | None) -> None:
        if not task:
            self.task_id = None
            self.hide()
            return
        self.task_id = int(task["id"])
        paused = bool(task.get("paused"))
        work_seconds = store.effective_work_seconds(task)
        segment_seconds = store.current_segment_seconds(task)
        remaining = max(0, WORK_BLOCK_SECONDS - segment_seconds)
        self.title_label.setText(task["title"])
        self.time_label.setText(f"Worked: {format_duration(work_seconds)}")
        self.break_label.setText(
            "Paused" if paused else f"Break in: {format_duration(remaining)}")
        self.pause_button.setVisible(not paused)
        self.unpause_button.setVisible(paused)
        self.park_button.setVisible(paused)
        if not self.isVisible():
            self.show()
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 24, screen.top() + 80)

    def _pause(self) -> None:
        if self.task_id:
            self.pauseRequested.emit(self.task_id)

    def _unpause(self) -> None:
        if self.task_id:
            self.unpauseRequested.emit(self.task_id)

    def _park(self) -> None:
        if self.task_id:
            self.parkRequested.emit(self.task_id)

    def _complete(self) -> None:
        if self.task_id:
            self.completeRequested.emit(self.task_id)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store = TaskStore()
        self.columns: dict[str, KanbanColumn] = {}
        self.setWindowTitle("FocusFlow")
        self.setMinimumSize(1050, 720)
        self.focus_window = FocusWindow()
        self.focus_window.pauseRequested.connect(self.pause_task)
        self.focus_window.unpauseRequested.connect(self.unpause_task)
        self.focus_window.parkRequested.connect(self.park_task)
        self.focus_window.completeRequested.connect(self.complete_task)

        self._build_toolbar()
        self._build_main_ui()
        self._build_timer()
        self.refresh_board()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        new_action = QAction("New full task", self)
        new_action.triggered.connect(self.new_full_task)
        toolbar.addAction(new_action)

        data_action = QAction("Open data folder", self)
        data_action.triggered.connect(self.open_data_folder)
        toolbar.addAction(data_action)

        focus_action = QAction("Show focus window", self)
        focus_action.triggered.connect(self.show_focus_for_current)
        toolbar.addAction(focus_action)

    def _build_main_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        quick = QFrame()
        quick.setObjectName("QuickAdd")
        quick_layout = QHBoxLayout(quick)
        quick_layout.setContentsMargins(10, 8, 10, 8)
        self.quick_title = QLineEdit()
        self.quick_title.setPlaceholderText(
            "Quick add: what is the next concrete task?")
        self.quick_priority = QComboBox()
        self.quick_priority.addItems(PRIORITIES)
        self.quick_due = QDateTimeEdit()
        self.quick_due.setCalendarPopup(True)
        self.quick_due.setDisplayFormat("dd MMM HH:mm")
        self.quick_due.setDateTime(QDateTime.currentDateTime().addDays(1))
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.quick_add_task)
        self.quick_title.returnPressed.connect(self.quick_add_task)
        quick_layout.addWidget(self.quick_title, 4)
        quick_layout.addWidget(self.quick_priority, 1)
        quick_layout.addWidget(self.quick_due, 1)
        quick_layout.addWidget(add_button)

        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter tasks")
        self.search_input.textChanged.connect(self.refresh_board)
        self.show_completed = QCheckBox("Show completed")
        self.show_completed.stateChanged.connect(self.refresh_board)
        controls.addWidget(QLabel("Search"))
        controls.addWidget(self.search_input, 1)
        controls.addWidget(self.show_completed)
        controls.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        board = QWidget()
        board.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        board_layout = QHBoxLayout(board)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(8)
        for status in STATUSES:
            column = KanbanColumn(status)
            column.taskDropped.connect(self.handle_task_drop)
            self.columns[status] = column
            board_layout.addWidget(column)
        scroll.setWidget(board)

        outer.addWidget(quick)
        outer.addLayout(controls)
        outer.addWidget(scroll, 1)
        self.setCentralWidget(central)

    def _build_timer(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def quick_add_task(self) -> None:
        title = self.quick_title.text().strip()
        if not title:
            return
        patch = TaskPatch(
            title=title,
            description="",
            priority=self.quick_priority.currentText(),
            due_at=self.quick_due.dateTime().toPython().replace(microsecond=0).isoformat(),
        )
        self.store.create_task(patch)
        self.quick_title.clear()
        self.refresh_board()

    def new_full_task(self) -> None:
        dialog = TaskDialog(self.store, parent=self)
        if dialog.exec() == QDialog.Accepted:
            task_id = self.store.create_task(dialog.patch())
            errors = []
            for file_path in dialog.pending_files:
                try:
                    self.store.add_attachment(task_id, file_path)
                except Exception as exc:
                    errors.append(f"{file_path.name}: {exc}")
            self.refresh_board()
            if errors:
                QMessageBox.warning(
                    self, "Some attachments failed", "\n".join(errors))

    def edit_task(self, task_id: int) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        dialog = TaskDialog(self.store, task, self)
        if dialog.exec() == QDialog.Accepted:
            self.store.update_task(task_id, dialog.patch())
            self.refresh_board()

    def delete_task(self, task_id: int) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        reply = QMessageBox.question(
            self,
            "Delete task",
            f"Delete '{task['title']}' and its copied attachments?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.store.delete_task(task_id)
            self.refresh_board()

    def handle_task_drop(self, task_id: int, status: str) -> None:
        self.store.move_task(task_id, status)
        self.refresh_board()
        self.show_focus_for_current()

    def start_task(self, task_id: int) -> None:
        self.store.start_task(task_id)
        self.refresh_board()
        self.show_focus_for_current()

    def pause_task(self, task_id: int) -> None:
        self.store.pause_task(task_id, mark_paused=True)
        self.refresh_board()
        self.show_focus_for_current()

    def unpause_task(self, task_id: int) -> None:
        self.store.unpause_task(task_id)
        self.refresh_board()
        self.show_focus_for_current()

    def park_task(self, task_id: int) -> None:
        self.store.park_task(task_id)
        self.refresh_board()
        self.show_focus_for_current()
        self.open_notes(
            task_id, "Optional parking note: what was done, what is blocking it, or the next tiny step")

    def complete_task(self, task_id: int) -> None:
        self.store.complete_task(task_id)
        self.refresh_board()
        self.show_focus_for_current()

    def open_notes(self, task_id: int, prompt: str = "") -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        dialog = NotesDialog(self.store, task, prompt, self)
        dialog.exec()
        self.refresh_board()

    def refresh_board(self) -> None:
        tasks = self.store.list_tasks(
            include_complete=self.show_completed.isChecked(), search=self.search_input.text()
        )
        grouped = {status: [] for status in STATUSES}
        for task in tasks:
            grouped.setdefault(task["status"], []).append(task)
        for status, column in self.columns.items():
            column.clear_cards()
            for task in grouped.get(status, []):
                card = TaskCard(self.store, task)
                card.editRequested.connect(self.edit_task)
                card.deleteRequested.connect(self.delete_task)
                card.startRequested.connect(self.start_task)
                card.pauseRequested.connect(self.pause_task)
                card.unpauseRequested.connect(self.unpause_task)
                card.parkRequested.connect(self.park_task)
                card.completeRequested.connect(self.complete_task)
                card.notesRequested.connect(self.open_notes)
                column.add_card(card)
            column.set_count(len(grouped.get(status, [])))
            column.setVisible(
                status != "Complete" or self.show_completed.isChecked())

    def tick(self) -> None:
        active = self.store.active_task()
        if active:
            segment_seconds = self.store.current_segment_seconds(active)
            if segment_seconds >= WORK_BLOCK_SECONDS:
                self.store.pause_task(int(active["id"]), mark_paused=True)
                self.refresh_board()
                paused_task = self.store.get_task(int(active["id"]))
                self.focus_window.update_task(self.store, paused_task)
                msg = QMessageBox(self)
                msg.setWindowTitle("Break time")
                msg.setText(
                    "30 minutes of focused work logged. Take a short break, then choose Unpause or Park.")
                add_note_button = msg.addButton(
                    "Add note", QMessageBox.ActionRole)
                msg.addButton("Take break", QMessageBox.AcceptRole)
                msg.exec()
                if msg.clickedButton() == add_note_button:
                    self.open_notes(
                        int(active["id"]),
                        "Optional break note: what did you just finish, and what is the next tiny step?",
                    )
                return
        focus_task = active
        if not focus_task:
            # If there is a paused work-in-progress task, keep it visible so the next choice is obvious.
            for task in self.store.list_tasks(include_complete=False):
                if task["status"] == "Work in Progress" and task.get("paused"):
                    focus_task = task
                    break
        self.focus_window.update_task(self.store, focus_task)
        # Refresh cards every 10 seconds while work is running so timers stay readable without flicker.
        if active and datetime.now().second % 10 == 0:
            self.refresh_board()

    def show_focus_for_current(self) -> None:
        task = self.store.active_task()
        if not task:
            for candidate in self.store.list_tasks(include_complete=False):
                if candidate["status"] == "Work in Progress" and candidate.get("paused"):
                    task = candidate
                    break
        self.focus_window.update_task(self.store, task)

    def open_data_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    def closeEvent(self, event):  # type: ignore[override]
        active = self.store.active_task()
        if active:
            reply = QMessageBox.question(
                self,
                "Work timer is running",
                "A task timer is still running. Pause it before closing?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Yes:
                self.store.pause_task(int(active["id"]), mark_paused=True)
        self.focus_window.close()
        event.accept()


def apply_styles(app: QApplication) -> None:
    app.setStyleSheet(
        """
        QWidget {
            font-family: 'Segoe UI';
            font-size: 10pt;
            color: #20242a;
        }
        QMainWindow, QDialog, QMessageBox {
            background: #f4f5f7;
        }
        QToolBar {
            background: #ffffff;
            border: 0;
            border-bottom: 1px solid #d6d9de;
            spacing: 8px;
            padding: 6px;
        }
        QToolButton {
            color: #20242a;
            background: transparent;
            border: 1px solid transparent;
            border-radius: 6px;
            padding: 5px 8px;
        }
        QToolButton:hover {
            background: #eef2f7;
            border-color: #d6d9de;
        }
        QScrollArea, QScrollArea > QWidget > QWidget {
            background: #f4f5f7;
            border: 0;
        }
        #QuickAdd {
            background: #ffffff;
            border: 1px solid #d6d9de;
            border-radius: 10px;
        }
        #KanbanColumn {
            background: #eef0f3;
            border: 1px solid #d8dce2;
            border-radius: 12px;
        }
        #ColumnHeader {
            color: #20242a;
            font-weight: 700;
            padding: 6px;
        }
        #TaskCard {
            background: #ffffff;
            border: 1px solid #d7dce2;
            border-left: 5px solid #8e9aaf;
            border-radius: 10px;
        }
        #TaskCard[priority="due-soon"] {
            border-left-color: #d89a2b;
        }
        #TaskCard[priority="urgent"] {
            border-left-color: #c94f4f;
        }
        #MetaLabel {
            color: #5c6470;
            font-size: 9pt;
        }
        #DescriptionLabel {
            color: #343a40;
        }
        #NoteLabel {
            color: #3c4858;
            background: #f6f8fb;
            border: 1px solid #e0e5ec;
            border-radius: 6px;
            padding: 5px;
        }
        #FocusWindow {
            background: #ffffff;
            border: 1px solid #d7dce2;
        }
        QLabel, QCheckBox, QGroupBox {
            color: #20242a;
        }
        QPushButton {
            color: #20242a;
            padding: 5px 8px;
            border-radius: 6px;
            border: 1px solid #bcc4cf;
            background: #ffffff;
        }
        QPushButton:hover {
            background: #f0f3f7;
        }
        QLineEdit, QTextEdit, QDateTimeEdit, QComboBox, QListWidget {
            color: #20242a;
            border: 1px solid #c5ccd6;
            border-radius: 6px;
            padding: 5px;
            background: #ffffff;
            selection-background-color: #d7e7ff;
            selection-color: #20242a;
        }
        QComboBox QAbstractItemView {
            color: #20242a;
            background: #ffffff;
            selection-background-color: #eef2f7;
        }
                QDateTimeEdit::drop-down {
            background: #ffffff;
            border-left: 1px solid #c5ccd6;
            width: 24px;
        }

        QCalendarWidget {
            color: #20242a;
            background-color: #ffffff;
        }

        QCalendarWidget QWidget {
            color: #20242a;
            background-color: #ffffff;
            alternate-background-color: #f4f5f7;
        }

        QCalendarWidget QWidget#qt_calendar_navigationbar {
            background-color: #eef2f7;
        }

        QCalendarWidget QToolButton {
            color: #20242a;
            background-color: #ffffff;
            border: 1px solid #c5ccd6;
            border-radius: 5px;
            padding: 4px;
            margin: 2px;
        }

        QCalendarWidget QToolButton:hover {
            background-color: #f0f3f7;
        }

        QCalendarWidget QToolButton::menu-indicator {
            image: none;
        }

        QCalendarWidget QMenu {
            color: #20242a;
            background-color: #ffffff;
            border: 1px solid #c5ccd6;
        }

        QCalendarWidget QSpinBox {
            color: #20242a;
            background-color: #ffffff;
            selection-background-color: #d7e7ff;
            selection-color: #20242a;
        }

        QCalendarWidget QAbstractItemView {
            color: #20242a;
            background-color: #ffffff;
            selection-background-color: #d7e7ff;
            selection-color: #20242a;
            alternate-background-color: #f4f5f7;
        }

        QCalendarWidget QAbstractItemView:disabled {
            color: #9aa1aa;
        }

        QDateTimeEdit {
            color: #111827;
            background-color: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 6px;
            padding-right: 34px;
        }

        QDateTimeEdit::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            background-color: #475569;
            border-left: 1px solid #94a3b8;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }

        QDateTimeEdit::down-arrow {
            image: none;
        }
        """
    )


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("FocusFlow")
    app.setOrganizationName("FocusFlowLocal")
    icon_path = resource_path("assets/focusflow.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_styles(app)
    window = MainWindow()
    if not app.windowIcon().isNull():
        window.setWindowIcon(app.windowIcon())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
