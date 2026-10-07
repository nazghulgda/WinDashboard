# App configuration

import os

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.db")

# Tasks archives folder
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive")

# Attachments folder
ATTACHMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "attachments")

# Predefined kanban checkpoints
# type: "check" = simple checkpoint
# type: "counter" = iteration counter (buttons + / -)
CHECKPOINTS = [
  {"order": 1, "name": "Kick-off", "type": "check"},
  {"order": 2, "name": "CheckPoint 1", "type": "check"},
  {"order": 3, "name": "CheckPoint 2", "type": "check"},
  {"order": 4, "name": "CheckPoint 3", "type": "check"},
  {"order": 5, "name": "CheckPoint 4", "type": "check"},
  {"order": 6, "name": "CheckPoint 5", "type": "counter"},
  {"order": 7, "name": "CheckPoint 6", "type": "counter"},
  {"order": 8, "name": "CheckPoint 7", "type": "check"},
  {"order": 9, "name": "CheckPoint 8", "type": "check"},
  {"order": 10, "name": "Closed", "type": "check"},
]

# Checkpoint groups = Task status when all checkpoints of group are completed
# "checkpoints": checkpoints assigned to group (numbers from CHECKPOINTS above)
# Groups are completed one after another, in the order given here.
# First group = initial state, not checkpoints marked.
# Last group = final state, all checkpoints of the task completed.
CHECKPOINT_GROUPS = [
  {"name": "Not started", "checkpoints": []},
  {"name": "Planned", "checkpoints": [1]},
  {"name": "Started", "checkpoints": [2]},
  {"name": "In progress", "checkpoints": [3, 4,5]},
  {"name": "In review", "checkpoints": [7, 8]},
  {"name": "Rework / fixes", "checkpoints": [9]},
  {"name": "Finished", "checkpoints": [10]},
]

# Checkpoint created for a task with "Empty Kanban" — a task always has at least one checkpoint
DEFAULT_CHECKPOINT = {"order": 1, "name": "Task completed", "type": "check"}

# Status of a started task when no checkpoint group is completed yet
# (also used for tasks without checkpoints from the template)
STATUS_IN_PROGRESS = "In progress"

# Main program window settings
APP_TITLE = "WinDashboard"
APP_VERSION = "0.5.0"
MAIN_WINDOW_SIZE = "900x600"

# Database check interval in ms (600 000 ms = 10 minutes)
DB_CHECK_INTERVAL_MS = 600_000

# Task status colours
STATUS_COLORS = {
  "not_started": "#e0ed8c",
  "in_progress": "#d9b4bd",
  "completed": "#00ff00",
}
