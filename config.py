# App configuration

import os

# Database path
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.db")

# Tasks archives folder
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive")

# Predefined kanban checkpoints
# type: "check" = simple checkpoint
# type: "counter" = iteration counter (buttons + / -)
CHECKPOINTS = [
  {"order": 1, "name": "Kick-off", "type": "check"},
  {"order": 2, "name": "ChekPoint 1", "type": "check"},
  {"order": 3, "name": "ChekPoint 2", "type": "check"},
  {"order": 4, "name": "ChekPoint 3", "type": "check"},
  {"order": 5, "name": "ChekPoint 4", "type": "check"},
  {"order": 6, "name": "ChekPoint 5", "type": "counter"},
  {"order": 7, "name": "ChekPoint 6", "type": "counter"},
  {"order": 8, "name": "ChekPoint 7", "type": "check"},
  {"order": 9, "name": "ChekPoint 8", "type": "check"},
  {"order": 10, "name": "Closed", "type": "check"},
]

# Checkpoint groups aka stages = Task status when all checkpoints of stage are completed
# "checkpoints": checkpoints assigned to stage
# Stage with no checkpoints = initial state, not checkpoints marked.
STAGES = [
  {"name": "Not started", "checkpoints": []},
  {"name": "Planned", "checkpoints": [1]},
  {"name": "Started", "checkpoints": [2]},
  {"name": "In progress", "checkpoints": [3, 4,5]},
  {"name": "In review", "checkpoints": [7, 8]},
  {"name": "Rework / fixes", "checkpoints": [9]},
  {"name": "Finished", "checkpoints": [10]},
]

# Main program window settings
APP_TITLE = "Dashboard"
MAIN_WINDOW_SIZE = "900x600"

# Task status colours
STATUS_COLORS = {
  "not_started": "#e0ed8c",
  "in_progress": "#d9b4bd",
  "completed": "#00ff00",
}
