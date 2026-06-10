import threading
import tkinter as tk
from tkinter import ttk, messagebox


class JoinEditorFrame(ttk.Frame):
    def __init__(self, parent, db, llm, on_joined, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.llm = llm
        self.on_joined = on_joined
        self._table_names = []
        self._generated_sql = tk.StringVar()

        ttk.Label(self, text="Describe how to join the tables (in plain English):").pack(anchor=tk.W, padx=10, pady=(10, 2))
        self._nl_input = tk.Text(self, height=4, wrap=tk.WORD)
        self._nl_input.pack(fill=tk.X, padx=10)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, padx=10, pady=6)
        ttk.Button(btn_row, text="Translate to SQL", command=self._translate).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="Regenerate", command=self._translate).pack(side=tk.LEFT, padx=6)
        self._progress = ttk.Progressbar(btn_row, mode="indeterminate", length=120)
        self._progress.pack(side=tk.LEFT, padx=6)

        ttk.Label(self, text="Generated SQL (review before executing):").pack(anchor=tk.W, padx=10, pady=(4, 2))
        sql_frame = ttk.Frame(self)
        sql_frame.pack(fill=tk.X, padx=10)
        self._sql_box = tk.Text(sql_frame, height=5, wrap=tk.WORD, state=tk.DISABLED, background="#f0f0f0")
        self._sql_box.pack(fill=tk.X)

        btn_row2 = ttk.Frame(self)
        btn_row2.pack(fill=tk.X, padx=10, pady=6)
        self._exec_btn = ttk.Button(btn_row2, text="Execute Join & Preview", command=self._execute_join, state=tk.DISABLED)
        self._exec_btn.pack(side=tk.LEFT)

        ttk.Label(self, text="Preview of joined table (first 100 rows):").pack(anchor=tk.W, padx=10, pady=(4, 2))
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=10)

        self._tree = ttk.Treeview(preview_frame, show="headings", height=10)
        vsb = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(preview_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)

        btn_row3 = ttk.Frame(self)
        btn_row3.pack(fill=tk.X, padx=10, pady=(6, 10))
        self._next_btn = ttk.Button(btn_row3, text="Next: Define Rules →", command=self._proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

    def set_tables(self, table_names: list[str]):
        self._table_names = table_names

    def _translate(self):
        nl = self._nl_input.get("1.0", tk.END).strip()
        if not nl:
            messagebox.showwarning("Input Required", "Please describe the join in plain English first.")
            return
        self._progress.start(10)
        self._exec_btn.config(state=tk.DISABLED)

        def worker():
            try:
                col_hints = {t: self.db.get_columns(t) for t in self._table_names}
                sql = self.llm.translate_join(nl, self._table_names, col_hints)
                self.after(0, lambda: self._show_sql(sql))
            except Exception as exc:
                self.after(0, lambda: self._on_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _show_sql(self, sql: str):
        self._progress.stop()
        self._sql_box.config(state=tk.NORMAL)
        self._sql_box.delete("1.0", tk.END)
        self._sql_box.insert("1.0", sql)
        self._sql_box.config(state=tk.DISABLED)
        self._exec_btn.config(state=tk.NORMAL)

    def _on_error(self, msg: str):
        self._progress.stop()
        messagebox.showerror("Error", msg)

    def _execute_join(self):
        sql = self._sql_box.get("1.0", tk.END).strip()
        if not sql:
            return
        self._progress.start(10)

        def worker():
            try:
                self.db.execute_join(sql)
                cols, rows = self.db.get_joined_preview()
                self.after(0, lambda: self._show_preview(cols, rows))
            except Exception as exc:
                self.after(0, lambda: self._on_error(f"Join failed:\n{exc}\n\nSQL:\n{sql}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_preview(self, cols: list[str], rows: list[tuple]):
        self._progress.stop()
        self._tree.config(columns=cols)
        for col in cols:
            self._tree.heading(col, text=col)
            self._tree.column(col, width=110, stretch=True)
        for item in self._tree.get_children():
            self._tree.delete(item)
        for row in rows:
            self._tree.insert("", tk.END, values=[str(v) if v is not None else "" for v in row])
        self._next_btn.config(state=tk.NORMAL)

    def get_join_config(self) -> dict:
        return {
            "tables": self._table_names,
            "nl_instruction": self._nl_input.get("1.0", tk.END).strip(),
            "sql": self._sql_box.get("1.0", tk.END).strip(),
        }

    def _proceed(self):
        self.on_joined(self.get_join_config())
