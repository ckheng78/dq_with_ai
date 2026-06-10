import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from core.db import Database
from core.llm import LLMClient
import core.reporter as reporter
import persistence.join_store as join_store
import persistence.rule_store as rule_store
from ui.file_loader import FileLoaderFrame
from ui.join_editor import JoinEditorFrame
from ui.rule_editor import RuleEditorFrame
from ui.report_viewer import ReportViewerFrame


class App(tk.Tk):
    def __init__(self, config: dict):
        super().__init__()
        self.title("DQ with AI — Data Quality Checker")
        self.geometry("1100x700")
        self.resizable(True, True)

        self._config = config
        self._db = Database()
        self._llm = LLMClient(config["ollama"])
        self._base_dir = os.path.dirname(os.path.abspath(__file__))
        self._paths = {k: os.path.join(self._base_dir, v) for k, v in config["paths"].items()}
        self._templates_dir = os.path.join(self._base_dir, "templates")
        self._max_detail_rows = config["ui"]["report_max_detail_rows"]

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True)

        self._file_loader = FileLoaderFrame(self._nb, self._db, self._on_files_loaded)
        self._join_editor = JoinEditorFrame(self._nb, self._db, self._llm, self._on_joined)
        self._rule_editor = RuleEditorFrame(self._nb, self._db, self._llm, self._on_rules_run)
        self._report_viewer = ReportViewerFrame(self._nb, self._db, self._restart)

        self._nb.add(self._file_loader, text="1. Load Files")
        self._nb.add(self._join_editor, text="2. Define Join")
        self._nb.add(self._rule_editor, text="3. Define Rules")
        self._nb.add(self._report_viewer, text="4. Reports")

        for i in range(1, 4):
            self._nb.tab(i, state="disabled")

        self.after(200, self._check_recurring)

    def _check_recurring(self):
        saved_join = join_store.load_latest(self._paths["joins_dir"])
        saved_rules = rule_store.load_latest(self._paths["rules_dir"])
        if saved_join and saved_rules:
            answer = messagebox.askyesno(
                "Saved Rules Found",
                "Saved join rules and data quality rules were found.\n\n"
                "Would you like to automatically run them on the CSV files in the data folder?",
            )
            if answer:
                self._run_recurring(saved_join, saved_rules)
                return
        # Fall through to manual workflow
        self._nb.tab(0, state="normal")
        self._nb.select(0)

    def _run_recurring(self, saved_join: dict, saved_rules: list[dict]):
        progress_win = tk.Toplevel(self)
        progress_win.title("Running…")
        progress_win.geometry("360x100")
        progress_win.grab_set()
        ttk.Label(progress_win, text="Running saved rules, please wait…").pack(pady=14)
        bar = ttk.Progressbar(progress_win, mode="indeterminate", length=300)
        bar.pack(padx=20)
        bar.start(10)

        def worker():
            try:
                # Load all CSVs from data dir
                data_dir = self._paths["data_dir"]
                csv_files = [f for f in os.listdir(data_dir) if f.lower().endswith(".csv")]
                if not csv_files:
                    self.after(0, lambda: (progress_win.destroy(), messagebox.showwarning(
                        "No CSVs Found", f"No CSV files found in {data_dir}.")))
                    return
                for fname in csv_files:
                    name = "".join(c if c.isalnum() else "_" for c in os.path.splitext(fname)[0])
                    self._db.register_csv(name, os.path.join(data_dir, fname))

                # Execute saved join
                self._db.execute_join(saved_join["sql"])

                # Run rules
                from core.rules import run_all_rules
                results = run_all_rules(saved_rules, self._db)
                self.after(0, lambda: self._finish_recurring(results, saved_join, saved_rules, progress_win))
            except Exception as exc:
                self.after(0, lambda: (progress_win.destroy(), messagebox.showerror("Error", str(exc))))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_recurring(self, results, saved_join, saved_rules, progress_win):
        progress_win.destroy()
        self._generate_and_show_reports(results)

        if messagebox.askyesno("Save Rules?", "Would you like to overwrite saved rules with the current set?"):
            rule_store.save(saved_rules, self._paths["rules_dir"])
        if messagebox.askyesno("Save Join?", "Would you like to overwrite the saved join with the current join?"):
            join_store.save(saved_join, self._paths["joins_dir"])

    # ---- Manual workflow callbacks ----

    def _on_files_loaded(self, table_names: list[str]):
        self._join_editor.set_tables(table_names)
        self._nb.tab(1, state="normal")
        self._nb.select(1)

    def _on_joined(self, join_config: dict):
        self._nb.tab(2, state="normal")
        self._nb.select(2)
        if messagebox.askyesno("Save Join Rules?", "Would you like to save this join rule for future use?"):
            path = join_store.save(join_config, self._paths["joins_dir"])
            messagebox.showinfo("Saved", f"Join rule saved to:\n{path}")

    def _on_rules_run(self, results, rules: list[dict]):
        if messagebox.askyesno("Save Rules?", "Would you like to save these data quality rules for future use?"):
            path = rule_store.save(rules, self._paths["rules_dir"])
            messagebox.showinfo("Saved", f"Rules saved to:\n{path}")
        self._generate_and_show_reports(results)

    def _generate_and_show_reports(self, results):
        try:
            total_rows = self._db.get_joined_row_count()
            reports_dir = self._paths["reports_dir"]
            summary_path = reporter.generate_summary(results, total_rows, reports_dir, self._templates_dir)
            detail_paths = [
                reporter.generate_detail(r, self._max_detail_rows, reports_dir, self._templates_dir)
                for r in results
            ]
            self._nb.tab(3, state="normal")
            self._nb.select(3)
            self._report_viewer.set_reports(summary_path, detail_paths)
        except Exception as exc:
            messagebox.showerror("Report Error", str(exc))

    def _restart(self):
        self._db.close()
        self._db = Database()
        self._join_editor.db = self._db
        self._rule_editor.db = self._db
        self._report_viewer.db = self._db
        for i in range(1, 4):
            self._nb.tab(i, state="disabled")
        self._nb.tab(0, state="normal")
        self._nb.select(0)
