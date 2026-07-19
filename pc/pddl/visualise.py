#!/usr/bin/env python3
import os
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Option 1: hard-code your folder:
# DEFAULT_PDDL_DIR = Path("/home/pi/pi/pddl")

# Option 2: use a pddl folder beside this script.
DEFAULT_PDDL_DIR = Path(__file__).resolve().parent / "pddl"

# Folder scan interval in milliseconds.
REFRESH_MS = 2000

# Facts obtained from sensors or external/environment telemetry.
SENSOR_PREDICATES = {
    "motion-detected",
    "light-low",
    "light-normal",
    "light-high",
    "humidity-low",
    "outdoor-temp-hot",
    "outdoor-temp-cold",
    "outdoor-raining",
    "indoor-temp-hot",
    "indoor-temp-cold",
    "indoor-temp-ideal",
    "product-available",
}

# Facts representing known physical actuator/device states.
ACTUATOR_PREDICATES = {
    "led-on",
    "humidifier-on",
    "window-open",
    "window-closed",
    "fan-on",
    "fan-off",
    "heater-on",
    "heater-off",
    "gate-open",
    "delivered-left",
    "delivered-right",
    "delivery-unavailable-notified",
    "delivery-requested-left",
    "delivery-requested-right",
    "delivery-request-handled",
}

# Structural facts that should not be displayed.
IGNORED_INIT_PREDICATES = {
    "zone-in-building",
}

# Planner-only / derived actions.
DERIVED_ACTIONS = {
    "confirm-lights-off",
    "confirm-lights-on",
    "confirm-humid-normal",
    "confirm-humid-low",
}

DIFF_BACKGROUND = "#FFF3BF"   # pale yellow
DIFF_FOREGROUND = "#8A4B00"   # dark amber
NORMAL_FONT = ("Cascadia Mono", 9)
CHANGED_FONT = ("Cascadia Mono", 9, "bold")

INIT_GOAL_BACKGROUND = "#EAF4FF"   # light blue
PLAN_BACKGROUND = "#F4EEFF"        # light lavender

# ---------------------------------------------------------------------------
# PDDL parsing helpers
# ---------------------------------------------------------------------------

def clean_fact(text: str) -> str:
    """Normalize whitespace in one PDDL fact/action."""
    return re.sub(r"\s+", " ", text.strip())


def predicate_name(fact: str) -> str:
    """Return the predicate name from '(predicate argument ...)'. """
    match = re.match(r"\(\s*([^\s()]+)", fact.strip())
    return match.group(1) if match else ""


def action_name(action_line: str) -> str:
    """Return the action name from 'action-name(zone1)'."""
    return action_line.split("(", 1)[0].strip()


def extract_balanced_block(text: str, marker: str) -> str:
    """
    Extract a complete PDDL section starting with marker, for example:
    marker='(:init' or marker='(:goal'.
    """
    start = text.lower().find(marker.lower())

    if start < 0:
        return ""

    depth = 0
    started = False

    for index in range(start, len(text)):
        char = text[index]

        if char == "(":
            depth += 1
            started = True

        elif char == ")" and started:
            depth -= 1

            if depth == 0:
                return text[start:index + 1]

    return ""


def top_level_expressions(section: str) -> list:
    """
    Get direct expressions from a PDDL section.

    Examples:
      (:init (fan-on zone1) (window-open zone1))
      -> ['(fan-on zone1)', '(window-open zone1)']

      (:goal (and (comfortable zone1) (control-lights zone1)))
      -> ['(comfortable zone1)', '(control-lights zone1)']
    """
    if not section:
        return []

    expressions = []
    depth = 0
    start = None

    for index, char in enumerate(section):
        if char == "(":
            depth += 1

            # Section root: depth 1
            # Direct :init children: depth 2
            # :goal -> (and ...) children: depth 3
            if depth in (2, 3):
                candidate = section[index:]

                if not re.match(
                    r"\(\s*:(init|goal|objects|domain)\b",
                    candidate,
                    flags=re.IGNORECASE,
                ) and not re.match(
                    r"\(\s*and\b",
                    candidate,
                    flags=re.IGNORECASE,
                ):
                    start = index

        elif char == ")":
            if start is not None and depth in (2, 3):
                expression = clean_fact(section[start:index + 1])

                if expression not in expressions:
                    expressions.append(expression)

                start = None

            depth -= 1

    return expressions


def parse_problem(problem_path: Path) -> dict:
    """Read and classify init facts and goal facts from a problem PDDL file."""
    text = problem_path.read_text(encoding="utf-8", errors="replace")

    init_block = extract_balanced_block(text, "(:init")
    goal_block = extract_balanced_block(text, "(:goal")

    init_facts = top_level_expressions(init_block)
    goal_facts = top_level_expressions(goal_block)

    sensor_init = []
    actuator_init = []
    other_init = []

    for fact in init_facts:
        name = predicate_name(fact)

        # Do not show structural mapping facts.
        if name in IGNORED_INIT_PREDICATES:
            continue

        if name in SENSOR_PREDICATES:
            sensor_init.append(fact)

        elif name in ACTUATOR_PREDICATES:
            actuator_init.append(fact)

        else:
            other_init.append(fact)

    return {
        "sensor_init": sensor_init,
        "actuator_init": actuator_init,
        "other_init": other_init,
        "goals": goal_facts,
    }


def matching_plan_path(problem_path: Path) -> Path:
    """
    problem_42.pddl -> plan_problem_42.pddl.txt
    """
    return problem_path.parent / f"plan_{problem_path.name}.txt"


def parse_plan(plan_path: Path) -> list:
    """Read one action per line from a plan file."""
    if not plan_path.exists():
        return ["Waiting for plan file..."]

    content = plan_path.read_text(encoding="utf-8", errors="replace").strip()

    if not content:
        return ["Plan file is empty."]

    if content.lower() == "no plan found.":
        return ["No plan found."]

    return [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]


def split_plan_actions(plan_actions: list) -> tuple:
    """
    Split into:
      1. Real physical/planner commands: Plans
      2. Confirmation/rule actions: Derived plans
    """
    plans = []
    derived_plans = []

    for action in plan_actions:
        name = action_name(action)

        if name in DERIVED_ACTIONS or name.startswith("rule-"):
            derived_plans.append(action)
        else:
            plans.append(action)

    return plans, derived_plans


# ---------------------------------------------------------------------------
# Viewer application
# ---------------------------------------------------------------------------

class PDDLHistoryViewer(tk.Tk):
    def __init__(self, pddl_dir: Path):
        super().__init__()

        self.pddl_dir = pddl_dir
        self.last_signature = None

        self.title("PDDL Planning History")
        self.geometry("1450x800")
        self.minsize(950, 550)

        self._build_ui()
        self._refresh_if_changed()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(
            "Header.TLabel",
            font=("Segoe UI", 16, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            foreground="#667085",
        )
        style.configure(
            "Card.TFrame",
            background="#FFFFFF",
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "CardHeader.TLabel",
            background="#1479B8",
            foreground="white",
            font=("Segoe UI", 12, "bold"),
        )
        style.configure(
            "Section.TLabel",
            background="#EEF3F8",
            foreground="#172033",
            font=("Segoe UI", 10, "bold"),
        )

        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 10))

        ttk.Label(
            header,
            text="PDDL Planning History",
            style="Header.TLabel",
        ).pack(side="left")

        self.status_label = ttk.Label(
            header,
            text="",
            style="Muted.TLabel",
        )
        self.status_label.pack(side="right")

        ttk.Label(
            root,
            text=(
                "Use the mouse wheel to slide through instances. "
                "If you are at the latest instance, new instances follow automatically."
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        self.canvas = tk.Canvas(
            root,
            background="#F5F7FA",
            highlightthickness=0,
        )
        self.canvas.pack(side="top", fill="both", expand=True)

        self.horizontal_scrollbar = ttk.Scrollbar(
            root,
            orient="horizontal",
            command=self.canvas.xview,
        )
        self.horizontal_scrollbar.pack(side="bottom", fill="x")

        self.canvas.configure(
            xscrollcommand=self.horizontal_scrollbar.set,
        )

        self.cards_frame = ttk.Frame(self.canvas)

        self.cards_window = self.canvas.create_window(
            (0, 0),
            window=self.cards_frame,
            anchor="nw",
        )

        self.cards_frame.bind(
            "<Configure>",
            self._update_scroll_region,
        )

        self.canvas.bind(
            "<Configure>",
            self._resize_cards_area,
        )

        # Scroll horizontally with normal wheel movement.
        self.canvas.bind_all(
            "<MouseWheel>",
            self._horizontal_mousewheel,
        )
        self.canvas.bind_all(
            "<Button-4>",
            self._horizontal_mousewheel_linux,
        )
        self.canvas.bind_all(
            "<Button-5>",
            self._horizontal_mousewheel_linux,
        )

    def _update_scroll_region(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _resize_cards_area(self, event):
        self.canvas.itemconfigure(
            self.cards_window,
            height=event.height,
        )

    def _horizontal_mousewheel(self, event):
        direction = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(direction * 3, "units")


    def _horizontal_mousewheel_linux(self, event):
        direction = -1 if event.num == 4 else 1
        self.canvas.xview_scroll(direction * 3, "units")

    @staticmethod
    def _add_section(
        parent,
        title: str,
        values: list,
        color: str,
        background: str,
    ) -> bool:
        """
        Add a visible card section only when values exist.

        The complete section is omitted when values are empty.
        """
        if not values:
            return False

        header = tk.Label(
            parent,
            text=title,
            background=background,
            foreground="#172033",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=9,
            pady=5,
        )
        header.pack(fill="x", pady=(10, 4))

        body = tk.Text(
            parent,
            height=max(2, min(len(values) + 1, 8)),
            wrap="word",
            background=background,
            foreground=color,
            relief="flat",
            font=("Cascadia Mono", 9),
            padx=8,
            pady=5,
        )
        body.pack(fill="x")

        body.insert(
            "1.0",
            "\n".join(f"• {value}" for value in values),
        )
        body.configure(state="disabled")

        return True

    def _problem_files(self) -> list:
        """Return problem_N.pddl files in numeric order."""
        if not self.pddl_dir.exists():
            return []

        problems = []

        try:
            paths = list(self.pddl_dir.iterdir())
        except OSError:
            return []

        for path in paths:
            match = re.fullmatch(r"problem_(\d+)\.pddl", path.name)

            if match and path.is_file():
                problems.append((int(match.group(1)), path))

        return sorted(problems, key=lambda item: item[0])

    def _folder_signature(self) -> tuple:
        """
        Signature changes when a matching problem or plan file is added,
        changed, or removed.
        """
        if not self.pddl_dir.exists():
            return ()

        signature = []

        try:
            paths = list(self.pddl_dir.iterdir())
        except OSError:
            return ()

        for path in paths:
            is_problem = re.fullmatch(r"problem_\d+\.pddl", path.name)
            is_plan = re.fullmatch(
                r"plan_problem_\d+\.pddl\.txt",
                path.name,
            )

            if not (is_problem or is_plan):
                continue

            try:
                stat = path.stat()
                signature.append(
                    (path.name, stat.st_mtime_ns, stat.st_size)
                )
            except OSError:
                pass

        return tuple(sorted(signature))

    def _refresh_if_changed(self):
        signature = self._folder_signature()

        if signature != self.last_signature:
            self.last_signature = signature
            self._rebuild_cards()

        self.after(REFRESH_MS, self._refresh_if_changed)

    @staticmethod
    def _changed_values(current_values: list, previous_values: list) -> set:
        """
        Marks entries that did not exist in the immediately preceding instance.

        A changed state such as:
        (fan-on zone1) -> (fan-off zone1)

        appears as a newly added, highlighted fact because the new fact differs
        from the prior instance.
        """
        return set(current_values) - set(previous_values)

    def _rebuild_cards(self):
        """
        Refresh cards while preserving horizontal position.

        - If the slider was at the right edge, follow new instances.
        - Otherwise, remain at exactly the same viewing location.
        - Changed entries versus the previous instance are bold/highlighted.
        """
        left_fraction, right_fraction = self.canvas.xview()
        was_at_right_edge = right_fraction >= 0.99

        for child in self.cards_frame.winfo_children():
            child.destroy()

        problems = self._problem_files()

        if not problems:
            ttk.Label(
                self.cards_frame,
                text=(
                    "No problem_N.pddl files found in:\n"
                    f"{self.pddl_dir}"
                ),
                style="Muted.TLabel",
                padding=20,
            ).pack()

            self.status_label.config(text="0 instances")
            self.after_idle(self._update_scroll_region)
            return

        previous_data = {
            "sensor_init": [],
            "actuator_init": [],
            "other_init": [],
            "goals": [],
            "plans": [],
            "derived_plans": [],
        }

        for column, (number, problem_path) in enumerate(problems):
            card = ttk.Frame(
                self.cards_frame,
                style="Card.TFrame",
                padding=10,
                width=380,
                height=700,
            )
            card.grid(
                row=0,
                column=column,
                padx=(0, 12),
                pady=4,
                sticky="ns",
            )
            card.grid_propagate(False)

            ttk.Label(
                card,
                text=f"Instance {number}",
                style="CardHeader.TLabel",
                padding=(10, 8),
            ).pack(fill="x")

            ttk.Label(
                card,
                text=problem_path.name,
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(7, 0))

            try:
                parsed = parse_problem(problem_path)

                plan_actions = parse_plan(
                    matching_plan_path(problem_path)
                )

                plans, derived_plans = split_plan_actions(plan_actions)

                current_data = {
                    "sensor_init": parsed["sensor_init"],
                    "actuator_init": parsed["actuator_init"],
                    "other_init": parsed["other_init"],
                    "goals": parsed["goals"],
                    "plans": plans,
                    "derived_plans": derived_plans,
                }

                self._add_section(
                    card,
                    "SENSOR INIT",
                    parsed["sensor_init"],
                    "#0E639A",
                    INIT_GOAL_BACKGROUND,
                )

                self._add_section(
                    card,
                    "ACTUATOR INIT",
                    parsed["actuator_init"],
                    "#8A3B12",
                    INIT_GOAL_BACKGROUND,
                )

                self._add_section(
                    card,
                    "OTHER INIT",
                    parsed["other_init"],
                    "#667085",
                    INIT_GOAL_BACKGROUND,
                )

                self._add_section(
                    card,
                    "GOAL",
                    parsed["goals"],
                    "#16865B",
                    INIT_GOAL_BACKGROUND,
                )

                self._add_section(
                    card,
                    "PLANS",
                    plans,
                    "#6F42C1",
                    PLAN_BACKGROUND,
                )

                self._add_section(
                    card,
                    "DERIVED PLANS",
                    derived_plans,
                    "#4B5563",
                    PLAN_BACKGROUND,
                )

                previous_data = current_data

            except Exception as exc:
                self._add_section(
                    card,
                    "READ ERROR",
                    [str(exc)],
                    "#C33B3B",
                    "#FFF1F1",
                )

        self.status_label.config(
            text=(
                f"{len(problems)} instance(s) · "
                f"refreshing every {REFRESH_MS // 1000}s"
            )
        )

        def restore_horizontal_position():
            self._update_scroll_region()

            if was_at_right_edge:
                # Auto-follow newly created instance only at the right edge.
                self.canvas.xview_moveto(1.0)
            else:
                # Freeze current horizontal reading position.
                self.canvas.xview_moveto(left_fraction)

        self.after_idle(restore_horizontal_position)


def main():
    """
    Usage:
        python3 pddl_history_viewer.py
        python3 pddl_history_viewer.py /home/pi/pi/pddl
    """
    if len(sys.argv) > 1:
        pddl_dir = Path(sys.argv[1]).expanduser().resolve()
    else:
        pddl_dir = DEFAULT_PDDL_DIR

    app = PDDLHistoryViewer(pddl_dir)
    app.mainloop()


if __name__ == "__main__":
    main()