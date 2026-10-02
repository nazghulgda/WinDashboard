# main_window.py

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from database import (
    init_db, backup_db,
    get_all_tasks, get_on_hold_tasks,
    create_task, set_on_hold, get_task_progress,
    get_task_stage_status, get_last_activity
)
from config import APP_TITLE, MAIN_WINDOW_SIZE, STATUS_COLORS, STAGES
from archive import export_task_to_zip, import_task_from_zip, list_archive, remove_archived_task

COLORS = {
    "bg":            "#1a1a2e",
    "panel":         "#16213e",
    "card":          "#0f3460",
    "card_hover":    "#1a4a7a",
    "accent":        "#e94560",
    "accent2":       "#f5a623",
    "text":          "#eaeaea",
    "text_dim":      "#8899aa",
    "progress_bg":   "#0a1628",
    "progress_fg":   "#e94560",
    "btn":           "#e94560",
    "btn_hover":     "#c73652",
    "btn_secondary": "#0f3460",
    "btn_sec_hover": "#1a4a7a",
    "scrollbar":     "#0f3460",
    "border":        "#1e3a5f",
}

FONT_TITLE   = ("Segoe UI", 20, "bold")
FONT_HEADING = ("Segoe UI", 12, "bold")
FONT_BODY    = ("Segoe UI", 10)
FONT_SMALL   = ("Segoe UI", 8)

SORT_OPTIONS = [
    ("Last activity",  "last_activity"),
    ("Creation date",   "created_at"),
    ("Progress",            "progress"),
    ("Title A–Z",         "title"),
]


# ---------------------------------------------------------------------------
# Helper: scroll with a mouse wheel only when the cursor is over the canvas
# ---------------------------------------------------------------------------

def _setup_mousewheel_scroll(canvas):
    def _scroll(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind():
        canvas.bind_all("<MouseWheel>", _scroll)

    def _check_and_unbind():
        try:
            if not canvas.winfo_exists():
                return
            cx, cy = canvas.winfo_rootx(), canvas.winfo_rooty()
            cw, ch = canvas.winfo_width(), canvas.winfo_height()
            px, py = canvas.winfo_pointerx(), canvas.winfo_pointery()
            if cx <= px <= cx + cw and cy <= py <= cy + ch:
                _bind()
            else:
                canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    canvas.bind("<Enter>", lambda e: _bind())
    canvas.bind("<Leave>", lambda e: canvas.after(10, _check_and_unbind))


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry(MAIN_WINDOW_SIZE)
        self.root.configure(bg=COLORS["bg"])
        self.root.minsize(700, 450)

        self._task_windows = {}   # task_id -> TaskWindow
        init_db()
        backup_db()
        self._build_ui()
        self._load_tasks()
        self._start_auto_refresh()

    def _build_ui(self):
        header = tk.Frame(self.root, bg=COLORS["panel"])
        header.pack(fill="x", side="top")

        tk.Label(
            header, text="◈  TASK DASHBOARD",
            font=FONT_TITLE, bg=COLORS["panel"],
            fg=COLORS["accent"], padx=20, pady=14
        ).pack(side="left")

        self._make_button(header, "+ Nowy task",  lambda: self._new_task(),
                          side="right", padx=20, pady=12)
        self._make_button(header, "📦 Archiwum",  lambda: self._open_archive(),
                          side="right", padx=(0, 4), pady=12, secondary=True)
        self._make_button(header, "⏸ On Hold",    lambda: self._open_on_hold(),
                          side="right", padx=(0, 4), pady=12, secondary=True)

        tk.Frame(self.root, bg=COLORS["accent"], height=2).pack(fill="x")

        filter_bar = tk.Frame(self.root, bg=COLORS["bg"], padx=16, pady=10)
        filter_bar.pack(fill="x")

        tk.Label(filter_bar, text="Szukaj:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._load_tasks())
        tk.Entry(
            filter_bar, textvariable=self.search_var,
            font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat", width=28
        ).pack(side="left", padx=(6, 20), ipady=4)

        # Sorting
        tk.Label(filter_bar, text="Sortuj:", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text_dim"]).pack(side="left")

        self.sort_var = tk.StringVar(value="last_activity")
        sort_cb = ttk.Combobox(
            filter_bar, textvariable=self.sort_var,
            values=[opt[0] for opt in SORT_OPTIONS],
            state="readonly", width=18, font=FONT_BODY
        )
        sort_cb.set(SORT_OPTIONS[0][0])
        sort_cb.pack(side="left", padx=(6, 0), ipady=2)
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self._load_tasks())

        # Combobox style for dark theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
            fieldbackground=COLORS["card"],
            background=COLORS["card"],
            foreground=COLORS["text"],
            selectbackground=COLORS["card_hover"],
            selectforeground=COLORS["text"],
            bordercolor=COLORS["border"],
            arrowcolor=COLORS["text_dim"],
        )

        self.count_label = tk.Label(filter_bar, text="", font=FONT_SMALL,
                                    bg=COLORS["bg"], fg=COLORS["text_dim"])
        self.count_label.pack(side="right")

        list_frame = tk.Frame(self.root, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.cards_frame, anchor="nw"
        )
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.cards_frame.bind("<Configure>", self._on_frame_configure)
        _setup_mousewheel_scroll(self.canvas)

    # -----------------------------------------------------------------------
    # Loading tasks
    # -----------------------------------------------------------------------

    def _get_sort_key(self) -> str:
        label = self.sort_var.get()
        for opt_label, opt_key in SORT_OPTIONS:
            if opt_label == label:
                return opt_key
        return "last_activity"

    def _load_tasks(self):
        query    = self.search_var.get().lower() if hasattr(self, "search_var") else ""
        sort_key = self._get_sort_key() if hasattr(self, "sort_var") else "last_activity"

        tasks = get_all_tasks()   # default: created_at DESC

        if query:
            tasks = [t for t in tasks if query in t["title"].lower()
                     or query in (t["description"] or "").lower()]

        if sort_key == "last_activity":
            tasks.sort(key=lambda t: get_last_activity(t["id"]), reverse=True)
        elif sort_key == "created_at":
            tasks.sort(key=lambda t: t["created_at"], reverse=True)
        elif sort_key == "progress":
            def _prog(t):
                done, total = get_task_progress(t["id"])
                return done / total if total else 0.0
            tasks.sort(key=_prog, reverse=True)
        elif sort_key == "title":
            tasks.sort(key=lambda t: t["title"].lower())

        for w in self.cards_frame.winfo_children():
            w.destroy()

        self.count_label.config(text=f"{len(tasks)} task{'ów' if len(tasks) != 1 else ''}")

        if not tasks:
            tk.Label(
                self.cards_frame,
                text="No tasks available. Click '+ New task' to add the first one.",
                font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"], pady=40
            ).pack()
            return

        for task in tasks:
            self._make_task_card(task)

    def _make_task_card(self, task: dict):
        done, total  = get_task_progress(task["id"])
        progress_pct = done / total if total else 0
        is_finished  = (done == total and total > 0)

        if done == 0:
            status_color = STATUS_COLORS["not_started"]
        elif is_finished:
            status_color = STATUS_COLORS["completed"]
        else:
            status_color = STATUS_COLORS["in_progress"]

        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=12, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        tk.Frame(card, bg=status_color, width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=FONT_HEADING,
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=task["created_at"][:10], font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        if task["description"]:
            desc = task["description"]
            if len(desc) > 80:
                desc = desc[:77] + "..."
            tk.Label(info, text=desc, font=FONT_SMALL,
                     bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(fill="x", pady=(2, 4))

        progress_frame = tk.Frame(info, bg=COLORS["progress_bg"], height=4)
        progress_frame.pack(fill="x", pady=(4, 2))
        progress_frame.pack_propagate(False)
        if progress_pct > 0:
            tk.Frame(progress_frame, bg=COLORS["progress_fg"]).place(
                relwidth=progress_pct, relheight=1.0)

        bottom_row = tk.Frame(info, bg=COLORS["card"])
        bottom_row.pack(fill="x", pady=(2, 0))

        stage_status = get_task_stage_status(task["id"])
        tk.Label(bottom_row, text=stage_status,
                 font=("Segoe UI", 8, "bold"), bg=COLORS["card"],
                 fg=COLORS["accent2"], anchor="w").pack(side="left")

        last_act = get_last_activity(task["id"])
        last_act_str = last_act[:16].replace("T", "  ") if last_act else ""
        tk.Label(bottom_row, text=f"last activity: {last_act_str}",
                 font=FONT_SMALL, bg=COLORS["card"],
                 fg=COLORS["text_dim"], anchor="e").pack(side="right")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        self._make_button(
            actions, "⏸ Put on hold",
            lambda tid=task["id"]: self._hold_task(tid),
            small=True, secondary=True, side="top", padx=2, pady=2
        )
        if is_finished:
            self._make_button(
                actions, "📦 Archive",
                lambda tid=task["id"], ttl=task["title"]: self._archive_task(tid, ttl, "active"),
                small=True, secondary=True, side="top", padx=2, pady=2
            )

        def open_on_click(e, tid=task["id"]):
            self._open_task(tid)

        for widget in [card, info, row1, bottom_row, progress_frame]:
            widget.bind("<Button-1>", open_on_click)
            widget.configure(cursor="hand2")

        for lbl in info.winfo_children() + row1.winfo_children() + bottom_row.winfo_children():
            try:
                lbl.bind("<Button-1>", open_on_click)
                lbl.configure(cursor="hand2")
            except Exception:
                pass

        self._bind_hover(card, COLORS["card"], COLORS["card_hover"], deep=True,
                         exclude=actions)

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _new_task(self):
        dialog = NewTaskDialog(self.root)
        self.root.wait_window(dialog.window)
        if dialog.result:
            stages = None if dialog.result.get("use_template") else []
            create_task(dialog.result["title"], dialog.result["description"], stages=stages)
            self._load_tasks()

    def _open_task(self, task_id: int):
        from task_window import TaskWindow

        # If the task is already open — give it focus
        if task_id in self._task_windows:
            try:
                tw = self._task_windows[task_id]
                if tw.window.winfo_exists():
                    tw.window.lift()
                    tw.window.focus_force()
                    return
            except Exception:
                pass
            del self._task_windows[task_id]

        def on_task_close(tid=task_id):
            self._task_windows.pop(tid, None)
            self._load_tasks()

        tw = TaskWindow(self.root, task_id, on_close=on_task_close)
        self._task_windows[task_id] = tw

    def _hold_task(self, task_id: int):
        set_on_hold(task_id, True)
        self._load_tasks()

    def _archive_task(self, task_id: int, title: str, source: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
           f"The task will be removed from the database and saved as a ZIP file in the archive folder.",
            parent=self.root
        ):
            return
        try:
            zip_path = export_task_to_zip(task_id, source)
            self._load_tasks()
            messagebox.showinfo(
                "Archived",
                f"Task has been archived:\n{zip_path}",
                parent=self.root
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}", parent=self.root)

    def _open_on_hold(self):
        OnHoldWindow(self.root, on_restore=self._load_tasks, on_archive=self._load_tasks)

    def _open_archive(self):
        ArchiveWindow(self.root, on_restore=self._load_tasks)

    def _start_auto_refresh(self):
        # Clear expired references
        dead = [tid for tid, tw in self._task_windows.items()
                if not self._window_alive(tw)]
        for tid in dead:
            del self._task_windows[tid]
        self._load_tasks()
        self.root.after(5000, self._start_auto_refresh)

    def _window_alive(self, tw) -> bool:
        try:
            return tw.window.winfo_exists()
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Helpery UI
    # -----------------------------------------------------------------------

    def _make_button(self, parent, text, command,
                     side="left", padx=4, pady=4,
                     small=False, secondary=False):
        font     = FONT_SMALL if small else FONT_BODY
        bg       = COLORS["btn_secondary"] if secondary else COLORS["btn"]
        fg       = COLORS["text_dim"]      if secondary else "white"
        hover_bg = COLORS["btn_sec_hover"] if secondary else COLORS["btn_hover"]

        btn = tk.Label(parent, text=text, font=font, bg=bg, fg=fg,
                       padx=8 if small else 14, pady=4 if small else 6,
                       cursor="hand2", relief="flat")
        btn.pack(side=side, padx=padx, pady=pady)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=hover_bg))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _bind_hover(self, widget, color_normal, color_hover,
                    deep=False, exclude=None):
        def on_enter(e):
            widget.config(bg=color_hover)
            if deep:
                for child in widget.winfo_children():
                    if child is not exclude:
                        try: child.config(bg=color_hover)
                        except Exception: pass
        def on_leave(e):
            widget.config(bg=color_normal)
            if deep:
                for child in widget.winfo_children():
                    if child is not exclude:
                        try: child.config(bg=color_normal)
                        except Exception: pass
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


# ---------------------------------------------------------------------------
# Dialog: New task
# ---------------------------------------------------------------------------

class NewTaskDialog:
    def __init__(self, parent):
        self.result = None
        self.window = tk.Toplevel(parent)
        self.window.title("New Task")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("460x360")
        self.window.resizable(False, False)
        self.window.grab_set()

        tk.Label(self.window, text="New Task", font=("Segoe UI", 12, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"], pady=12).pack()
        tk.Frame(self.window, bg=COLORS["accent"], height=1).pack(fill="x")

        form = tk.Frame(self.window, bg=COLORS["bg"], padx=24, pady=16)
        form.pack(fill="both", expand=True)

        tk.Label(form, text="Title *", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.title_var = tk.StringVar()
        title_entry = tk.Entry(form, textvariable=self.title_var,
                               font=FONT_BODY, bg=COLORS["card"], fg=COLORS["text"],
                               insertbackground=COLORS["text"], relief="flat")
        title_entry.pack(fill="x", ipady=5, pady=(2, 12))
        title_entry.focus_set()

        tk.Label(form, text="Short Description (Optional)", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.desc_text = tk.Text(form, height=3, font=FONT_BODY,
                                 bg=COLORS["card"], fg=COLORS["text"],
                                 insertbackground=COLORS["text"], relief="flat", wrap="word")
        self.desc_text.pack(fill="x", pady=(2, 12))

        tk.Label(form, text="Kanban", font=FONT_BODY,
                 bg=COLORS["bg"], fg=COLORS["text"]).pack(anchor="w")
        self.template_var = tk.StringVar(value="template")
        tmpl_frame = tk.Frame(form, bg=COLORS["bg"])
        tmpl_frame.pack(anchor="w", pady=(2, 14))
        radio_style = dict(
            bg=COLORS["bg"], fg=COLORS["text"],
            activebackground=COLORS["bg"], activeforeground=COLORS["text"],
            selectcolor=COLORS["card"], font=FONT_BODY
        )
        tk.Radiobutton(
            tmpl_frame, text=f"Use Default Template  ({len(STAGES)} Stages)",
            variable=self.template_var, value="template", **radio_style
        ).pack(anchor="w")
        tk.Radiobutton(
            tmpl_frame, text="Empty Kanban",
            variable=self.template_var, value="empty", **radio_style
        ).pack(anchor="w")

        btn_row = tk.Frame(form, bg=COLORS["bg"])
        btn_row.pack(fill="x")
        confirm = tk.Label(btn_row, text="Create Task",
                           font=("Segoe UI", 10, "bold"),
                           bg=COLORS["btn"], fg="white",
                           padx=14, pady=6, cursor="hand2")
        confirm.pack(side="right")
        confirm.bind("<Button-1>", lambda e: self._confirm())
        confirm.bind("<Enter>", lambda e: confirm.config(bg=COLORS["btn_hover"]))
        confirm.bind("<Leave>", lambda e: confirm.config(bg=COLORS["btn"]))
        self.window.bind("<Return>", lambda e: self._confirm())
        self.window.bind("<Escape>", lambda e: self.window.destroy())

    def _confirm(self):
        title = self.title_var.get().strip()
        if not title:
            return
        self.result = {
            "title":        title,
            "description":  self.desc_text.get("1.0", "end").strip(),
            "use_template": self.template_var.get() == "template",
        }
        self.window.destroy()


# ---------------------------------------------------------------------------
# Okno: On Hold
# ---------------------------------------------------------------------------

class OnHoldWindow:
    def __init__(self, parent, on_restore=None, on_archive=None):
        self.on_restore = on_restore
        self.on_archive = on_archive

        self.window = tk.Toplevel(parent)
        self.window.title("On Hold")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("700x480")
        self.window.minsize(500, 300)

        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="⏸  ON HOLD", font=FONT_TITLE,
                 bg=COLORS["panel"], fg=COLORS["text_dim"],
                 padx=20, pady=14).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        list_frame = tk.Frame(self.window, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        cw = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(cw, width=e.width))
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        _setup_mousewheel_scroll(self.canvas)

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        tasks = get_on_hold_tasks()
        if not tasks:
            tk.Label(self.cards_frame, text="No tasks on hold.",
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        for task in tasks:
            self._make_card(task)

    def _make_card(self, task: dict):
        done, total = get_task_progress(task["id"])

        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=10, padx=14)
        card.pack(fill="x", pady=4, padx=2)

        tk.Frame(card, bg=COLORS["text_dim"], width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=task["title"], font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(side="left")
        hold_date = (task["on_hold_at"] or "")[:10]
        tk.Label(row1, text=f"on hold: {hold_date}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        tk.Label(info, text=f"{done} from {total} stages completed", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"], anchor="w").pack(anchor="w", pady=(2, 0))

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        self._make_btn(actions, "▶ Restore",   COLORS["btn"],
                       lambda tid=task["id"]: self._restore(tid))
        self._make_btn(actions, "📦 Archive", COLORS["btn_secondary"],
                       lambda tid=task["id"], ttl=task["title"]: self._archive(tid, ttl))

    def _make_btn(self, parent, text, bg, command):
        btn = tk.Label(parent, text=text, font=FONT_SMALL, bg=bg, fg="white",
                       padx=8, pady=4, cursor="hand2")
        btn.pack(side="top", pady=2)
        btn.bind("<Button-1>", lambda e: command())
        hover = COLORS["btn_hover"] if bg == COLORS["btn"] else COLORS["btn_sec_hover"]
        btn.bind("<Enter>", lambda e: btn.config(bg=hover))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))

    def _restore(self, task_id: int):
        set_on_hold(task_id, False)
        if self.on_restore:
            self.on_restore()
        self._load()

    def _archive(self, task_id: int, title: str):
        if not messagebox.askyesno(
            "Archive Task",
            f"Are you sure you want to archive the task:\n\n\"{title}\"\n\n"
           f"The task will be deleted from the database and saved as a ZIP file.",
            parent=self.window
        ):
            return
        try:
            zip_path = export_task_to_zip(task_id, "onhold")
            if self.on_archive:
                self.on_archive()
            self._load()
            messagebox.showinfo("Task Archived",
                                f"Task has been archived:\n{zip_path}",
                                parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to archive task:\n{e}",
                                 parent=self.window)


# ---------------------------------------------------------------------------
# Okno: Archive
# ---------------------------------------------------------------------------

class ArchiveWindow:
    def __init__(self, parent, on_restore=None):
        self.on_restore = on_restore

        self.window = tk.Toplevel(parent)
        self.window.title("Archive")
        self.window.configure(bg=COLORS["bg"])
        self.window.geometry("800x520")
        self.window.minsize(600, 350)

        header = tk.Frame(self.window, bg=COLORS["panel"])
        header.pack(fill="x")
        tk.Label(header, text="📦  ARCHIVE", font=FONT_TITLE,
                 bg=COLORS["panel"], fg=COLORS["text_dim"],
                 padx=20, pady=14).pack(side="left")
        tk.Frame(self.window, bg=COLORS["accent"], height=2).pack(fill="x")

        list_frame = tk.Frame(self.window, bg=COLORS["bg"])
        list_frame.pack(fill="both", expand=True, padx=16, pady=12)

        self.canvas = tk.Canvas(list_frame, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = tk.Scrollbar(list_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.cards_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        cw = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(cw, width=e.width))
        self.cards_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        _setup_mousewheel_scroll(self.canvas)

        self._load()

    def _load(self):
        for w in self.cards_frame.winfo_children():
            w.destroy()

        archives = list_archive()
        onhold   = [a for a in archives if a["source"] == "onhold"]
        finished = [a for a in archives if a["source"] != "onhold"]

        if not archives:
            tk.Label(self.cards_frame, text="Archive is empty.",
                     font=FONT_BODY, bg=COLORS["bg"], fg=COLORS["text_dim"],
                     pady=40).pack()
            return

        if onhold:
            self._section_header("⏸  On Hold")
            for a in onhold:
                self._make_card(a)

        if finished:
            self._section_header("✅  Finished")
            for a in finished:
                self._make_card(a)

    def _section_header(self, text: str):
        frm = tk.Frame(self.cards_frame, bg=COLORS["bg"])
        frm.pack(fill="x", pady=(12, 4))
        tk.Label(frm, text=text, font=("Segoe UI", 11, "bold"),
                 bg=COLORS["bg"], fg=COLORS["accent"], padx=4).pack(side="left")
        tk.Frame(frm, bg=COLORS["border"], height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0), pady=6)

    def _make_card(self, a: dict):
        card = tk.Frame(self.cards_frame, bg=COLORS["card"], pady=8, padx=14)
        card.pack(fill="x", pady=3, padx=2)

        src_color = COLORS["text_dim"] if a["source"] == "onhold" else STATUS_COLORS["completed"]
        tk.Frame(card, bg=src_color, width=4).pack(side="left", fill="y", padx=(0, 12))

        info = tk.Frame(card, bg=COLORS["card"])
        info.pack(side="left", fill="both", expand=True)

        row1 = tk.Frame(info, bg=COLORS["card"])
        row1.pack(fill="x")
        tk.Label(row1, text=a["title"], font=("Segoe UI", 11, "bold"),
                 bg=COLORS["card"], fg=COLORS["text"], anchor="w").pack(side="left")
        tk.Label(row1, text=f"arch: {a['export_date']}", font=FONT_SMALL,
                 bg=COLORS["card"], fg=COLORS["text_dim"]).pack(side="right")

        row2 = tk.Frame(info, bg=COLORS["card"])
        row2.pack(fill="x")
        tk.Label(row2,
                 text=f"Postęp: {a['progress']}  |  utworzony: {a['created_at']}",
                 font=FONT_SMALL, bg=COLORS["card"], fg=COLORS["text_dim"],
                 anchor="w").pack(side="left")

        actions = tk.Frame(card, bg=COLORS["card"])
        actions.pack(side="right", padx=(12, 0))

        restore_btn = tk.Label(actions, text="▶ Restore", font=FONT_SMALL,
                               bg=COLORS["btn"], fg="white", padx=8, pady=4, cursor="hand2")
        restore_btn.pack(pady=(0, 2))
        restore_btn.bind("<Button-1>",
            lambda e, zp=a["zip_path"], fn=a["filename"]: self._restore(zp, fn))
        restore_btn.bind("<Enter>", lambda e: restore_btn.config(bg=COLORS["btn_hover"]))
        restore_btn.bind("<Leave>", lambda e: restore_btn.config(bg=COLORS["btn"]))

        del_btn = tk.Label(actions, text="🗑 Delete", font=FONT_SMALL,
                           bg="#3a1515", fg="#ff9999", padx=8, pady=4, cursor="hand2")
        del_btn.pack()
        del_btn.bind("<Button-1>",
            lambda e, zp=a["zip_path"], ttl=a["title"]: self._remove(zp, ttl))
        del_btn.bind("<Enter>", lambda e: del_btn.config(bg="#5a2020"))
        del_btn.bind("<Leave>", lambda e: del_btn.config(bg="#3a1515"))

    def _restore(self, zip_path: str, filename: str):
        source_label = "On Hold" if "onhold" in filename else "aktywnych"
        if not messagebox.askyesno(
            "Restore Task",
            f"Restore task to the {source_label} list?\n\n{filename}",
            parent=self.window
        ):
            return
        try:
            new_id = import_task_from_zip(zip_path)
            try:
                os.remove(zip_path)
            except Exception:
                pass
            if self.on_restore:
                self.on_restore()
            self._load()
            messagebox.showinfo("Task Restored",
                                f"Task has been restored (id={new_id}).",
                                parent=self.window)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to restore task:\n{e}",
                                 parent=self.window)

    def _remove(self, zip_path: str, title: str):
        if not messagebox.askyesno(
            "Delete from Archive",
            f"Delete task from archive?\n\n\"{title}\"\n\n"
            f"The ZIP file will be moved to the 'archive/removed' folder.\n"
            f"You can manually recover it from there.",
            parent=self.window
        ):
            return
        try:
            remove_archived_task(zip_path)
            self._load()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to delete task:\n{e}",
                                 parent=self.window)


# ---------------------------------------------------------------------------
# Run Application
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()
