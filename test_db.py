# Database structure verification

from database import (
    init_db, create_task, get_all_tasks, get_task,
    get_checkpoints, set_checkpoint_completed, get_task_progress,
    create_note, get_notes,
    create_link, get_links,
    delete_task
)

print("=== Database structure test ===\n")

# Initialization
init_db()
print(" Database initialized (tasks.db)")

# Task creation
task_id = create_task("Test task", "Test task description")
print(f"Task created, id={task_id}")

# Checkpoints test
checkpoints = get_checkpoints(task_id)
print(f"Checkpoints created: {len(checkpoints)} (waiting: 20)")
print(f"  First: '{checkpoints[0]['name']}', Last: '{checkpoints[-1]['name']}'")

# Marking of a few checkpints
set_checkpoint_completed(checkpoints[0]["id"], True)
set_checkpoint_completed(checkpoints[1]["id"], True)
set_checkpoint_completed(checkpoints[2]["id"], True)
done, total = get_task_progress(task_id)
print(f"Task progress: {done} / {total}")

# Note
note_id = create_note(task_id, "First meeting", "Project scope discussed")
notes = get_notes(task_id)
print(f"Note created: '{notes[0]['title']}' ({notes[0]['created_at'][:10]})")

# File and folder link
create_link(task_id, "Project folder", r"C:\projects\TestProject", "folder")
create_link(task_id, "Specification", r"C:\projects\TestProject\spec.docs", "file")
links = get_links(task_id)
print(f"Links added: {len(links)} pcs.")
for l in links:
    print(f" [{l['link_type']}] {l['label']} -> {l['path']}")

# List of all tasks
all_tasks = get_all_tasks()
print(f"\n All tasks in database: {len(all_tasks)}")
for t in all_tasks:
    d, tot = get_task_progress(t["id"])
    print(f" #{t['id']} '{t['title']}' - progress {d}/{tot}")

# Task deletion
delete_task(task_id)
print(f"Task #{task_id} deleted (including checkpoints, notes and links)")
print(f"Remaining tasks: {len(get_all_tasks())}")

print(f"\n=== All tests finished succesfully. ===")
