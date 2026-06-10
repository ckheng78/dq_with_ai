import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class FileLoaderFrame(ttk.Frame):
    def __init__(self, parent, db, on_loaded, **kwargs):
        super().__init__(parent, **kwargs)
        self.db = db
        self.on_loaded = on_loaded
        self._loaded_files = {}  # name -> path

        top = ttk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(top, text="Add CSV File(s)", command=self._pick_files).pack(side=tk.LEFT)
        ttk.Button(top, text="Remove Selected", command=self._remove_selected).pack(side=tk.LEFT, padx=6)
        self._next_btn = ttk.Button(top, text="Next: Define Join →", command=self._proceed, state=tk.DISABLED)
        self._next_btn.pack(side=tk.RIGHT)

        list_frame = ttk.LabelFrame(self, text="Loaded Files")
        list_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        self._file_list = tk.Listbox(list_frame, height=4, selectmode=tk.SINGLE)
        self._file_list.pack(fill=tk.X, padx=6, pady=6)

        self._preview_nb = ttk.Notebook(self)
        self._preview_nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

    def _pick_files(self):
        paths = filedialog.askopenfilenames(
            title="Select CSV Files",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            # Make table name safe for DuckDB
            safe_name = "".join(c if c.isalnum() else "_" for c in name)
            if safe_name in self._loaded_files:
                messagebox.showwarning("Duplicate", f"A table named '{safe_name}' is already loaded.")
                continue
            try:
                self.db.register_csv(safe_name, path)
                self._loaded_files[safe_name] = path
                self._file_list.insert(tk.END, f"{safe_name}  ({path})")
                self._add_preview_tab(safe_name)
            except Exception as exc:
                messagebox.showerror("Load Error", f"Failed to load {path}:\n{exc}")
        self._next_btn.config(state=tk.NORMAL if self._loaded_files else tk.DISABLED)

    def _remove_selected(self):
        sel = self._file_list.curselection()
        if not sel:
            return
        idx = sel[0]
        entry = self._file_list.get(idx)
        name = entry.split("  (")[0]
        self._file_list.delete(idx)
        self._loaded_files.pop(name, None)
        # Remove preview tab
        for tab_id in self._preview_nb.tabs():
            if self._preview_nb.tab(tab_id, "text") == name:
                self._preview_nb.forget(tab_id)
                break
        self._next_btn.config(state=tk.NORMAL if self._loaded_files else tk.DISABLED)

    def _add_preview_tab(self, table_name: str):
        frame = ttk.Frame(self._preview_nb)
        self._preview_nb.add(frame, text=table_name)
        try:
            cols, rows = self.db.get_preview(table_name)
        except Exception as exc:
            ttk.Label(frame, text=f"Preview error: {exc}").pack(padx=10, pady=10)
            return

        tree = ttk.Treeview(frame, columns=cols, show="headings", height=12)
        for col in cols:
            tree.heading(col, text=col)
            tree.column(col, width=120, stretch=True)
        for row in rows:
            tree.insert("", tk.END, values=[str(v) if v is not None else "" for v in row])

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _proceed(self):
        if len(self._loaded_files) < 2:
            messagebox.showinfo("Two Tables Required", "Please load at least 2 CSV files to define a join.")
            return
        self.on_loaded(list(self._loaded_files.keys()))
