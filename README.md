# FocusFlow

FocusFlow is a calm Windows desktop task manager built for quick task capture, Kanban-style planning, and focused work sessions.

It is intentionally local-first. Your tasks are stored in a SQLite database under your Windows user profile, and attachments are copied into the app data folder so they remain linked to the task.

## Update notes

This version includes improved light-theme styling for Windows dark mode, narrower responsive Kanban columns, the Complete column hidden until requested, and task notes. Existing data in `%LOCALAPPDATA%\FocusFlow` is preserved.

## What is included

- Desktop app; no browser required
- Kanban board with these columns:
  - New
  - Planned
  - Work in Progress
  - Overdue
  - Complete
- Drag and drop task cards between statuses
- Quick-add bar for low-friction task capture
- Full task editor with:
  - title
  - description
  - priority
  - planned due date/time
  - attachments
- Priority levels:
  - No pressure
  - Due soon
  - Urgent
- Automatic created date/time
- Automatic completed date/time
- Local attachment copying, opening, and deletion
- Task notes with latest-note preview on cards
- Work timer when a task enters Work in Progress
- One active task at a time; starting a new task pauses the previous active one
- Automatic pause after each 30 minutes of active work
- Break prompt after the 30-minute focus block
- Paused task buttons:
  - Park; moves it back to Planned
  - Unpause; resumes the timer from the previous total
- Total work time saved when the task is completed
- Small always-on-top focus window while a task is active or paused
- Local build script for creating a Windows `.exe`
- Optional installer script for Inno Setup

## ADHD/autism-friendly design choices

The app deliberately avoids busy dashboards and noisy analytics. The design choices are:

- Quick add first; capture the task before overthinking it
- Only one running task at a time; less task-switching chaos
- Gentle 30-minute pause prompt; no punishment language
- Park instead of abandon; stopping a task does not mean failure
- Cards show only the useful next information; due date, priority, work time, attachments, and latest note
- Completed tasks can be hidden by default; less visual clutter
- Attachments stay with the task; less hunting later
- The focus window stays visible over other apps; easier to remember what you started

## Running from source

1. Install Python 3.11 or later from the Microsoft Store or python.org.
2. Open PowerShell in this folder.
3. Run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

## Building a Windows executable

Open PowerShell in this folder and run:

```powershell
.\build_windows.ps1
```

The executable will be created here:

```text
dist\FocusFlow\FocusFlow.exe
```

You can run it directly from there.

## Creating a desktop shortcut

After building the executable, run:

```powershell
.\create_shortcut.ps1
```

This creates a `FocusFlow` shortcut on your desktop. To pin it to the taskbar, right-click the shortcut or the running app icon and choose **Pin to taskbar**.

## Creating a proper installer

The repository includes `FocusFlow.iss`, an Inno Setup script.

1. Build the app first with:

```powershell
.\build_windows.ps1
```

2. Install Inno Setup.
3. Open `FocusFlow.iss` in Inno Setup Compiler.
4. Click **Compile**.

The installer will be created in:

```text
installer\FocusFlowSetup.exe
```

## Where data is stored

On Windows, FocusFlow stores data here:

```text
%LOCALAPPDATA%\FocusFlow
```

Inside that folder you will find:

```text
focusflow.db
attachments\
```

You can also open this location from inside the app using **Open data folder**.

## Current limitations

This is a solid first version, not a commercial-grade release yet.

Known limitations:

- No cloud sync
- No multi-device support
- No recurring tasks yet
- No notification centre integration yet
- No backup/restore screen yet, although the data folder is easy to copy
- The taskbar cannot host a live timer directly; Windows does not allow normal apps to freely embed controls into the taskbar. The always-on-top focus window is the practical replacement.

## Suggested next improvements

Useful next features would be:

- Daily planning mode
- Recurring tasks
- Export to CSV
- Backup and restore button
- Gentle end-of-day review
- Optional task size labels such as 5 min, 15 min, 30 min, deep work
- Optional “next tiny step” field
- Snooze break prompt
- Configurable focus block length
- Optional note prompt settings
- Start with Windows setting

## Development notes

The app is built with:

- Python
- PySide6
- SQLite
- PyInstaller for packaging
- Inno Setup for optional installer creation
