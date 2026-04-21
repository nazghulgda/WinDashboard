# Database structure verification

from database import (
    init_db, create_task, get_all_tasks, get_task,
    get_stages, set_stage_completed, get_task_progress,
    create_note, get_notes,
    create_link, get_links,
    delete_task
)

print("==== Database structure test === ")

# Initialization
init_db()
print(" Database initialized (tasks.db)")

# Task creation
task_id = create_task("Test task", "Test task description")
print(f"Task created, id={task_id}")

# Checkpoints test