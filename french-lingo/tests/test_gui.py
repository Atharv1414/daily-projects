"""Drives the real widgets. Skipped where there is no display, such as CI."""

from datetime import date

import pytest

from lingo.pack_loader import load_packs
from lingo.storage import Storage

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app():
    from lingo.gui import App

    storage = Storage(":memory:")
    try:
        app = App(storage, load_packs()[0], today=lambda: date(2026, 1, 1), clock=lambda: 0.0)
    except tk.TclError as exc:
        storage.close()
        pytest.skip(f"no display: {exc}")
    app.withdraw()
    yield app
    app.destroy()
    storage.close()


def test_study_and_dashboard(app):
    from lingo.gui import DashboardScreen, HomeScreen, StudyScreen

    app.screen.add("Léa")
    assert isinstance(app.screen, HomeScreen)
    app.screen.study()
    screen = app.screen
    assert isinstance(screen, StudyScreen)
    first = screen.session.current
    screen.entry.insert(0, "wrong")
    screen.submit()
    assert first.answers[0] in screen.feedback["text"]
    screen.submit()
    while word := screen.session.current:
        screen.entry.insert(0, word.answers[0])
        screen.submit()
        screen.submit()
    assert screen.prompt["text"] == "9 of 10 right first time"
    screen.submit()  # pressing Return after the end does nothing
    app.show(DashboardScreen)
    app.update_idletasks()


def test_accent_buttons_and_language_switch(app):
    from lingo.gui import HomeScreen

    app.screen.add("Tom")
    app.screen.change(app.packs["spanish"])
    assert isinstance(app.screen, HomeScreen)
    app.screen.study()
    app.screen.insert("é")
    assert app.screen.entry.get() == "é"
