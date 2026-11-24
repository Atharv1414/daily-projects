"""Tkinter screens. They display state and pass input on; all rules live elsewhere."""

import time
import tkinter as tk
from collections.abc import Callable
from datetime import date
from tkinter import messagebox, simpledialog, ttk

from .lesson import LanguagePack, Lesson
from .progress import ProgressTracker
from .session import Session
from .storage import Storage
from .user import User

PAD = 12
ACCENTS = list("éèêëàâçîïôùûüœñáíóú¿")


class App(tk.Tk):
    def __init__(
        self,
        storage: Storage,
        packs: dict[str, LanguagePack],
        today: Callable[[], date] = date.today,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self.storage, self.packs, self.today, self.clock = storage, packs, today, clock
        self.user: User | None = None
        self.pack = packs.get("french") or next(iter(packs.values()))
        self.title("French Lingo")
        self.geometry("760x580")
        self.minsize(560, 460)
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Helvetica", 22, "bold"))
        style.configure("Prompt.TLabel", font=("Helvetica", 26))
        self._screen: ttk.Frame | None = None
        self.show(LearnerScreen)

    def show(self, screen: type[ttk.Frame], *args) -> None:
        if self._screen is not None:
            self._screen.destroy()
        self._screen = screen(self, *args)
        self._screen.pack(fill="both", expand=True, padx=PAD * 2, pady=PAD * 2)

    @property
    def screen(self):
        return self._screen


class LearnerScreen(ttk.Frame):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        ttk.Label(self, text="Who is learning?", style="Title.TLabel").pack(anchor="w", pady=PAD)
        for user in app.storage.users():
            ttk.Button(self, text=user.name, command=lambda u=user: self.choose(u)).pack(
                fill="x", pady=3
            )
        ttk.Button(self, text="Add a learner…", command=self.ask).pack(anchor="w", pady=PAD)

    def choose(self, user: User) -> None:
        self.app.user = user
        self.app.show(HomeScreen)

    def ask(self) -> None:
        name = simpledialog.askstring("New learner", "Name:", parent=self)
        if name is not None:
            self.add(name)

    def add(self, name: str) -> None:
        try:
            self.choose(self.app.storage.add_user(name))
        except ValueError as exc:
            messagebox.showerror("Could not add learner", str(exc), parent=self)


class HomeScreen(ttk.Frame):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        self.app = app
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text=f"Bonjour, {app.user.name}", style="Title.TLabel").pack(side="left")
        names = {p.name: p for p in app.packs.values()}
        picker = ttk.Combobox(top, values=list(names), state="readonly", width=14)
        picker.set(app.pack.name)
        picker.bind("<<ComboboxSelected>>", lambda _e: self.change(names[picker.get()]))
        picker.pack(side="right")
        tracker = ProgressTracker(app.user, app.pack, app.storage, app.today())
        c = tracker.counts()
        summary = f"{c['due']} due · {c['new']} new · {c['mature']} well known"
        ttk.Label(self, text=f"{summary} · {tracker.streak()}-day streak").pack(
            anchor="w", pady=PAD
        )
        ttk.Button(self, text="Study today’s words", command=self.study).pack(fill="x", pady=3)
        for lesson in app.pack.lessons:
            ttk.Button(
                self, text=f"Lesson: {lesson.title}", command=lambda x=lesson: self.study(x)
            ).pack(fill="x", pady=3)
        bottom = ttk.Frame(self)
        bottom.pack(anchor="w", pady=PAD)
        ttk.Button(bottom, text="Progress", command=lambda: app.show(DashboardScreen)).pack(
            side="left"
        )
        ttk.Button(bottom, text="Change learner", command=lambda: app.show(LearnerScreen)).pack(
            side="left", padx=PAD
        )

    def change(self, pack: LanguagePack) -> None:
        self.app.pack = pack
        self.app.show(HomeScreen)

    def study(self, lesson: Lesson | None = None) -> None:
        app = self.app
        app.show(StudyScreen, Session(app.user, app.pack, app.storage, app.today(), lesson))


class StudyScreen(ttk.Frame):
    def __init__(self, app: App, session: Session) -> None:
        super().__init__(app)
        self.app, self.session = app, session
        self.status = ttk.Label(self)
        self.status.pack(anchor="w")
        self.prompt = ttk.Label(self, style="Prompt.TLabel", wraplength=660)
        self.prompt.pack(pady=PAD * 2)
        self.entry = ttk.Entry(self, font=("Helvetica", 18), justify="center")
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda _e: self.submit())
        keys = ttk.Frame(self)
        keys.pack(pady=PAD)
        for n, letter in enumerate(ACCENTS):
            ttk.Button(keys, text=letter, width=2, command=lambda x=letter: self.insert(x)).grid(
                row=n // 10, column=n % 10
            )
        self.feedback = ttk.Label(self, wraplength=660, justify="center")
        self.feedback.pack(pady=PAD)
        self.button = ttk.Button(self, command=self.submit)
        self.button.pack()
        ttk.Button(self, text="Finish", command=lambda: app.show(HomeScreen)).pack(
            side="bottom", anchor="w"
        )
        self.waiting = False
        self.next_word()

    def insert(self, letter: str) -> None:
        self.entry.insert("insert", letter)
        self.entry.focus_set()

    def next_word(self) -> None:
        self.waiting = False
        word = self.session.current
        self.status["text"] = f"{self.session.remaining} to go"
        self.entry["state"] = "normal"
        self.entry.delete(0, "end")
        self.feedback["text"] = ""
        if word is None:
            s = self.session
            self.prompt["text"] = (
                f"{s.correct} of {s.answered} right first time" if s.answered else "Nothing is due"
            )
            self.entry["state"] = "disabled"
            self.button.configure(text="Home", command=lambda: self.app.show(HomeScreen))
            return
        self.prompt["text"] = word.prompt
        self.button["text"] = "Check"
        self.entry.focus_set()
        self.started = self.app.clock()

    def submit(self) -> None:
        if self.waiting:
            self.next_word()
            return
        word = self.session.current
        if word is None:
            return
        verdict = self.session.answer(self.entry.get(), self.app.clock() - self.started)
        heading = "Correct" if verdict.correct else "Not this time"
        lines = [f"{heading}: {word.answers[0]}", verdict.note, word.example]
        self.feedback["text"] = "\n".join(x for x in lines if x)
        self.entry["state"] = "disabled"
        self.button["text"] = "Next"
        self.button.focus_set()
        self.waiting = True


class DashboardScreen(ttk.Frame):
    def __init__(self, app: App) -> None:
        super().__init__(app)
        tracker = ProgressTracker(app.user, app.pack, app.storage, app.today())
        ttk.Label(self, text="Progress", style="Title.TLabel").pack(anchor="w")
        retention, counts = tracker.retention(), tracker.counts()
        rate = "not enough reviews yet" if retention is None else f"{retention:.0%}"
        facts = f"30-day retention: {rate}   ·   Streak: {tracker.streak()} days"
        ttk.Label(self, text=facts).pack(anchor="w", pady=(PAD, 0))
        known = f"New {counts['new']}   Learning {counts['learning']}   Mature {counts['mature']}"
        ttk.Label(self, text=known).pack(anchor="w", pady=(0, PAD))
        charts = ttk.Frame(self)
        charts.pack(fill="x")
        daily = [(d.strftime("%d"), n) for d, n, _ in tracker.daily()]
        self.bars(charts, "Reviews, last 14 days", daily)
        ahead = [("Now" if n == 0 else f"+{n}", v) for n, v in enumerate(tracker.forecast())]
        self.bars(charts, "Due in the next 7 days", ahead)
        for title, areas in (
            ("Weakest lessons", tracker.weak_lessons()[:3]),
            ("Weakest words", tracker.weak_words()),
        ):
            listed = ", ".join(f"{a.label} ({a.accuracy:.0%})" for a in areas) or "none yet"
            ttk.Label(self, text=f"{title}: {listed}", wraplength=680).pack(anchor="w", pady=4)
        if leeches := tracker.leeches():
            text = f"Often forgotten, try a memory trick: {', '.join(leeches)}"
            ttk.Label(self, text=text, wraplength=680).pack(anchor="w", pady=4)
        ttk.Button(self, text="Home", command=lambda: app.show(HomeScreen)).pack(
            side="bottom", anchor="w"
        )

    @staticmethod
    def bars(parent: ttk.Frame, title: str, values: list[tuple[str, int]]) -> None:
        frame = ttk.Frame(parent)
        frame.pack(side="left", padx=(0, PAD))
        ttk.Label(frame, text=title).pack(anchor="w")
        width, height = 330, 150
        canvas = tk.Canvas(frame, width=width, height=height, background="white",
                           highlightthickness=0)  # fmt: skip
        canvas.pack()
        top, slot = max([v for _, v in values] + [1]), width / len(values)
        for i, (label, value) in enumerate(values):
            x, base = i * slot, height - 20
            y = base - value / top * (base - 20)
            canvas.create_rectangle(x + 3, y, x + slot - 3, base, fill="#2563eb", width=0)
            canvas.create_text(x + slot / 2, height - 9, text=label, fill="#444")
            if value:
                canvas.create_text(x + slot / 2, y - 8, text=str(value), fill="#222")
