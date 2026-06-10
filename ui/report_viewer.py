import os
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class ReportViewerFrame(ttk.Frame):
    def __init__(self, parent, db, on_restart, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_restart = on_restart
        self._summary_path = None
        self._detail_paths = []

        ttk.Label(self, text="Reports Generated", font=("Arial", 13, "bold")).pack(pady=(16, 4))

        self._summary_var = tk.StringVar(value="—")
        ttk.Label(self, text="Summary Report:").pack(anchor=tk.W, padx=20)
        summary_row = ttk.Frame(self)
        summary_row.pack(fill=tk.X, padx=20, pady=2)
        ttk.Entry(summary_row, textvariable=self._summary_var, state="readonly", width=70).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(summary_row, text="Open", command=self._open_summary).pack(side=tk.LEFT, padx=4)

        ttk.Label(self, text="Detail Reports:").pack(anchor=tk.W, padx=20, pady=(10, 2))
        detail_frame = ttk.Frame(self)
        detail_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        self._detail_list = tk.Listbox(detail_frame, height=8)
        self._detail_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self._detail_list.yview)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self._detail_list.config(yscrollcommand=vsb.set)
        ttk.Button(self, text="Open Selected Detail Report", command=self._open_detail).pack(anchor=tk.W, padx=20, pady=4)

        action_row = ttk.Frame(self)
        action_row.pack(fill=tk.X, padx=20, pady=(16, 10))
        ttk.Button(action_row, text="Export Joined Table as CSV…", command=self._export_csv).pack(side=tk.LEFT)
        ttk.Button(action_row, text="Start Over", command=self.on_restart).pack(side=tk.RIGHT)

    def set_reports(self, summary_path: str, detail_paths: list[str]):
        self._summary_path = summary_path
        self._detail_paths = detail_paths
        self._summary_var.set(summary_path)
        self._detail_list.delete(0, tk.END)
        for p in detail_paths:
            self._detail_list.insert(tk.END, p)

    def _open_summary(self):
        if self._summary_path and os.path.isfile(self._summary_path):
            webbrowser.open(f"file:///{self._summary_path.replace(os.sep, '/')}")
        else:
            messagebox.showwarning("Not Found", "Summary report file not found.")

    def _open_detail(self):
        sel = self._detail_list.curselection()
        if not sel:
            messagebox.showinfo("Select a Report", "Please select a detail report from the list.")
            return
        path = self._detail_paths[sel[0]]
        if os.path.isfile(path):
            webbrowser.open(f"file:///{path.replace(os.sep, '/')}")
        else:
            messagebox.showwarning("Not Found", "Detail report file not found.")

    def _export_csv(self):
        path = filedialog.asksaveasfilename(
            title="Save Joined Table as CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            self.db.export_joined_csv(path)
            messagebox.showinfo("Exported", f"Joined table saved to:\n{path}")
        except Exception as exc:
            messagebox.showerror("Export Error", str(exc))
