import tkinter as tk
from tkinter import ttk

import persistence.workflow_store as workflow_store


class WorkflowLauncher(tk.Toplevel):
    def __init__(self, parent, workflows_dir, on_new, on_run, on_edit):
        super().__init__(parent)
        self.title("DQ with AI — Workflows")
        self.geometry("600x440")
        self.resizable(True, True)
        self.grab_set()

        self._on_new = on_new
        self._on_run = on_run
        self._on_edit = on_edit
        self._workflows = workflow_store.load_all(workflows_dir)

        ttk.Label(self, text="DQ with AI", font=("TkDefaultFont", 14, "bold")).pack(pady=(24, 4))
        ttk.Label(self, text="Data Quality Checker", foreground="gray").pack()

        ttk.Button(self, text="+ New Workflow", width=20, command=self._new).pack(pady=14)

        if self._workflows:
            ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=24, pady=(0, 8))
            ttk.Label(self, text="Saved Workflows", font=("TkDefaultFont", 9, "bold")).pack(
                anchor=tk.W, padx=24)

            outer = ttk.Frame(self)
            outer.pack(fill=tk.BOTH, expand=True, padx=24, pady=(4, 24))

            canvas = tk.Canvas(outer, highlightthickness=0)
            vsb = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
            canvas.configure(yscrollcommand=vsb.set)
            vsb.pack(side=tk.RIGHT, fill=tk.Y)
            canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            inner = ttk.Frame(canvas)
            cw = canvas.create_window((0, 0), window=inner, anchor="nw")
            inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

            for wf in self._workflows:
                row = ttk.Frame(inner)
                row.pack(fill=tk.X, pady=4, padx=4)

                ttk.Label(row, text=wf["name"], width=28, anchor=tk.W,
                          font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT)
                updated = wf.get("updated_at", "")[:10]
                ttk.Label(row, text=updated, foreground="gray", width=12).pack(side=tk.LEFT, padx=6)
                n_rules = len(wf.get("rules", []))
                ttk.Label(row, text=f"{n_rules} rule(s)", foreground="gray", width=10).pack(side=tk.LEFT)
                ttk.Button(row, text="Run", width=6,
                           command=lambda w=wf: self._run(w)).pack(side=tk.RIGHT, padx=(4, 0))
                ttk.Button(row, text="Edit", width=6,
                           command=lambda w=wf: self._edit(w)).pack(side=tk.RIGHT, padx=4)
        else:
            ttk.Label(self, text="No saved workflows yet. Click '+ New Workflow' to get started.",
                      foreground="gray").pack(pady=20)

        self.protocol("WM_DELETE_WINDOW", self._new)

    def _new(self):
        self.destroy()
        self._on_new()

    def _run(self, workflow):
        self.destroy()
        self._on_run(workflow)

    def _edit(self, workflow):
        self.destroy()
        self._on_edit(workflow)
