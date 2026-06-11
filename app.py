import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from core.db import Database
from core.llm import LLMClient
import core.reporter as reporter
import persistence.workflow_store as workflow_store
from ui.file_loader import FileLoaderFrame
from ui.filter_editor import FilterEditorFrame, PostJoinFilterFrame
from ui.join_editor import JoinEditorFrame
from ui.derived_fields_editor import DerivedFieldsEditorFrame
from ui.rule_editor import RuleEditorFrame
from ui.report_viewer import ReportViewerFrame
from ui.workflow_launcher import WorkflowLauncher


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

        # Accumulated workflow state — populated as tabs are completed
        self._wf_pre_filters: list[dict] = []
        self._wf_join: dict = {}
        self._wf_post_filters: list[dict] = []
        self._wf_derived: list[dict] = []
        self._wf_rules: list[dict] = []
        self._current_workflow_name: str = ""

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True)

        self._file_loader              = FileLoaderFrame(self._nb, self._db, self._on_files_loaded)
        self._filter_editor            = FilterEditorFrame(self._nb, self._db, self._on_filters_applied)
        self._join_editor              = JoinEditorFrame(self._nb, self._db, self._on_joined)
        self._postjoin_filter_editor   = PostJoinFilterFrame(self._nb, self._db, self._on_postjoin_filtered)
        self._derived_fields_editor    = DerivedFieldsEditorFrame(self._nb, self._db, self._on_derived_fields_applied)
        self._rule_editor              = RuleEditorFrame(self._nb, self._db, self._llm, self._on_rules_run)
        self._report_viewer            = ReportViewerFrame(self._nb, self._db, self._restart)

        self._nb.add(self._file_loader,            text="1. Load Files")
        self._nb.add(self._filter_editor,          text="2. Pre-Join Filters")
        self._nb.add(self._join_editor,            text="3. Define Join")
        self._nb.add(self._postjoin_filter_editor, text="4. Post-Join Filters")
        self._nb.add(self._derived_fields_editor,  text="5. Derived Fields")
        self._nb.add(self._rule_editor,            text="6. Define Rules")
        self._nb.add(self._report_viewer,          text="7. Reports")

        for i in range(7):
            self._nb.tab(i, state="disabled")

        self.after(200, self._show_launcher)

    # ---- Launcher ----

    def _show_launcher(self):
        WorkflowLauncher(
            self,
            self._paths["workflows_dir"],
            on_new=self._on_new_workflow,
            on_run=self._run_workflow,
            on_edit=self._edit_workflow,
        )

    def _on_new_workflow(self):
        self._nb.tab(0, state="normal")
        self._nb.select(0)

    # ---- Manual workflow tab callbacks ----

    def _on_files_loaded(self, table_names: list[str]):
        self._filter_editor.set_tables(table_names)
        self._join_editor.set_tables(table_names)
        self._nb.tab(1, state="normal")
        self._nb.select(1)

    def _on_filters_applied(self, filters: list[dict]):
        self._wf_pre_filters = filters
        self._nb.tab(2, state="normal")
        self._nb.select(2)

    def _on_joined(self, join_config: dict):
        self._wf_join = join_config
        self._postjoin_filter_editor.set_joined_table(self._db.get_table_names())
        self._nb.tab(3, state="normal")
        self._nb.select(3)

    def _on_postjoin_filtered(self, filters: list[dict]):
        self._wf_post_filters = filters
        self._derived_fields_editor.set_columns(self._db.get_columns("joined_table"))
        self._nb.tab(4, state="normal")
        self._nb.select(4)

    def _on_derived_fields_applied(self, derived: list[dict]):
        self._wf_derived = derived
        self._nb.tab(5, state="normal")
        self._nb.select(5)
        try:
            self._rule_editor.set_fields(
                self._db.get_columns("joined_table"),
                self._db.get_table_names(),
            )
        except Exception:
            pass

    def _on_rules_run(self, results, rules: list[dict]):
        self._wf_rules = rules
        self._generate_and_show_reports(results)
        name = simpledialog.askstring(
            "Save Workflow",
            "Enter a name to save this workflow\n(or Cancel to skip):",
            initialvalue=self._current_workflow_name or "",
            parent=self,
        )
        if name and name.strip():
            self._save_workflow(name.strip())

    def _save_workflow(self, name: str):
        workflow = {
            "name": name,
            "files": self._file_loader.get_file_configs(self._base_dir),
            "pre_join_filters": self._wf_pre_filters,
            "join": self._wf_join,
            "post_join_filters": self._wf_post_filters,
            "derived_fields": self._wf_derived,
            "rules": self._wf_rules,
        }
        if self._current_workflow_name:
            workflow["created_at"] = ""  # will be set by store if missing
        path = workflow_store.save(workflow, self._paths["workflows_dir"])
        self._current_workflow_name = name
        messagebox.showinfo("Saved", f"Workflow '{name}' saved to:\n{path}")

    def _generate_and_show_reports(self, results):
        try:
            total_rows = self._db.get_joined_row_count()
            reports_dir = self._paths["reports_dir"]
            summary_path = reporter.generate_summary(results, total_rows, reports_dir, self._templates_dir)
            detail_paths = []
            csv_paths = []
            for r in results:
                detail_paths.append(
                    reporter.generate_detail(r, self._max_detail_rows, reports_dir, self._templates_dir)
                )
                csv_paths.append(reporter.generate_violation_csv(r, reports_dir))
            self._nb.tab(6, state="normal")
            self._nb.select(6)
            self._report_viewer.set_reports(summary_path, detail_paths, csv_paths)
        except Exception as exc:
            messagebox.showerror("Report Error", str(exc))

    # ---- Re-run saved workflow (headless) ----

    def _run_workflow(self, workflow: dict):
        progress_win = tk.Toplevel(self)
        progress_win.title("Running Workflow…")
        progress_win.geometry("420x120")
        progress_win.grab_set()
        status_lbl = ttk.Label(progress_win, text="Starting…")
        status_lbl.pack(pady=14)
        bar = ttk.Progressbar(progress_win, mode="indeterminate", length=360)
        bar.pack(padx=30)
        bar.start(10)

        def set_status(msg):
            self.after(0, lambda m=msg: status_lbl.config(text=m))

        def worker():
            try:
                set_status("Loading files…")
                for fc in workflow["files"]:
                    abs_path = os.path.normpath(os.path.join(self._base_dir, fc["path"]))
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(f"File not found: {abs_path}")
                    self._db.register_csv(
                        fc["name"], abs_path,
                        encoding=fc["encoding"], delimiter=fc["delimiter"],
                        engine=fc["engine"], selected_columns=fc["selected_columns"],
                    )

                if workflow.get("pre_join_filters"):
                    set_status("Applying pre-join filters…")
                    self._db.apply_filters(workflow["pre_join_filters"])

                set_status("Executing join…")
                self._db.execute_join(workflow["join"]["sql"])

                if workflow.get("post_join_filters"):
                    set_status("Applying post-join filters…")
                    self._db.apply_join_filters(workflow["post_join_filters"])

                if workflow.get("derived_fields"):
                    set_status("Applying derived fields…")
                    self._db.apply_derived_fields(workflow["derived_fields"])

                set_status("Running rules…")
                from core.rules import run_all_rules
                results = run_all_rules(workflow["rules"], self._db)

                self.after(0, lambda: self._finish_workflow_run(results, workflow, progress_win))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    progress_win.destroy(),
                    messagebox.showerror("Workflow Error", str(e)),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_workflow_run(self, results, workflow, progress_win):
        progress_win.destroy()
        self._wf_rules = workflow.get("rules", [])
        self._current_workflow_name = workflow.get("name", "")
        self._generate_and_show_reports(results)

    # ---- Edit saved workflow (pre-populate all tabs) ----

    def _edit_workflow(self, workflow: dict):
        progress_win = tk.Toplevel(self)
        progress_win.title("Loading Workflow…")
        progress_win.geometry("420x120")
        progress_win.grab_set()
        status_lbl = ttk.Label(progress_win, text="Loading files…")
        status_lbl.pack(pady=14)
        bar = ttk.Progressbar(progress_win, mode="indeterminate", length=360)
        bar.pack(padx=30)
        bar.start(10)

        def set_status(msg):
            self.after(0, lambda m=msg: status_lbl.config(text=m))

        def worker():
            try:
                for fc in workflow["files"]:
                    abs_path = os.path.normpath(os.path.join(self._base_dir, fc["path"]))
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(f"File not found: {abs_path}")
                    self._db.register_csv(
                        fc["name"], abs_path,
                        encoding=fc["encoding"], delimiter=fc["delimiter"],
                        engine=fc["engine"], selected_columns=fc["selected_columns"],
                    )

                if workflow.get("pre_join_filters"):
                    set_status("Applying filters…")
                    self._db.apply_filters(workflow["pre_join_filters"])

                set_status("Executing join…")
                self._db.execute_join(workflow["join"]["sql"])

                if workflow.get("post_join_filters"):
                    self._db.apply_join_filters(workflow["post_join_filters"])

                if workflow.get("derived_fields"):
                    set_status("Applying derived fields…")
                    self._db.apply_derived_fields(workflow["derived_fields"])

                self.after(0, lambda: self._finish_edit_workflow(workflow, progress_win))
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    progress_win.destroy(),
                    messagebox.showerror("Load Error", str(e)),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_edit_workflow(self, workflow: dict, progress_win):
        progress_win.destroy()
        table_names = [fc["name"] for fc in workflow["files"]]

        self._file_loader.populate_from_workflow(workflow["files"], self._base_dir)

        self._filter_editor.set_tables(table_names)
        if workflow.get("pre_join_filters"):
            self._filter_editor.load_filters(workflow["pre_join_filters"])

        self._join_editor.set_tables(table_names)
        self._join_editor.load_join_config(workflow.get("join", {}))

        self._postjoin_filter_editor.set_joined_table(self._db.get_table_names())
        if workflow.get("post_join_filters"):
            self._postjoin_filter_editor.load_filters(workflow["post_join_filters"])

        self._derived_fields_editor.set_columns(self._db.get_columns("joined_table"))
        if workflow.get("derived_fields"):
            self._derived_fields_editor.load_derived_fields(workflow["derived_fields"])

        self._rule_editor.set_fields(
            self._db.get_columns("joined_table"),
            self._db.get_table_names(),
        )
        self._rule_editor.load_rules(workflow.get("rules", []))

        # Store state so "Save Workflow" at the end captures everything
        self._wf_pre_filters = workflow.get("pre_join_filters", [])
        self._wf_join = workflow.get("join", {})
        self._wf_post_filters = workflow.get("post_join_filters", [])
        self._wf_derived = workflow.get("derived_fields", [])
        self._wf_rules = workflow.get("rules", [])
        self._current_workflow_name = workflow.get("name", "")

        for i in range(6):
            self._nb.tab(i, state="normal")
        self._nb.select(5)

    # ---- Restart ----

    def _restart(self):
        self._db.close()
        self._db = Database()
        self._filter_editor.db = self._db
        self._join_editor.db = self._db
        self._postjoin_filter_editor.db = self._db
        self._derived_fields_editor.db = self._db
        self._rule_editor.db = self._db
        self._report_viewer.db = self._db

        self._wf_pre_filters = []
        self._wf_join = {}
        self._wf_post_filters = []
        self._wf_derived = []
        self._wf_rules = []
        self._current_workflow_name = ""

        for i in range(7):
            self._nb.tab(i, state="disabled")
        self.after(100, self._show_launcher)
