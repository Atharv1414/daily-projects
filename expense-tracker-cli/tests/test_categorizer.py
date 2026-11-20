import pytest

from expense_tracker.categorizer import Categorizer, normalise_merchant
from expense_tracker.models import CategoryRule


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("CARD PAYMENT TO TESCO STORES 2231*1234 ON 03 NOV", "Tesco Stores"),
        ("  DELIVEROO   ", "Deliveroo"),
        ("AMZN MKTP UK*AB12CD", "Amzn Mktp Uk"),
        ("DIRECT DEBIT TO OCTOPUS ENERGY", "Octopus Energy"),
        ("SAINSBURYS S/MKTS", "Sainsburys S Mkts"),
        ("1234567", ""),
    ],
)
def test_normalise_merchant(raw, clean):
    assert normalise_merchant(raw) == clean


@pytest.mark.parametrize(
    ("merchant", "category"),
    [
        ("Tesco Stores", "food"),
        ("Uber Eats", "food"),
        ("Uber", "transport"),
        ("Foxtons Rent", "housing"),
        ("Netflix.Com", "entertainment"),
        ("Currys Pc World", "shopping"),
        ("Coffee Corner", "other"),  # "ee" must not match inside words
    ],
)
def test_builtin_rules(merchant, category):
    assert Categorizer().categorize(merchant).category == category


def test_precedence_user_rule_then_history_then_builtin():
    cat = Categorizer(
        rules=[CategoryRule(r"(?i)amazon fresh", "food", priority=10)],
        history={"Amazon": "entertainment"},
    )
    assert cat.categorize("Amazon Fresh").reason.startswith("rule:")
    assert cat.categorize("Amazon Fresh").category == "food"
    assert cat.categorize("Amazon") == cat.categorize("Amazon")
    assert cat.categorize("Amazon").reason == "history"
    assert cat.categorize("Amazon Prime Video").category == "shopping"  # builtin
    assert cat.categorize("Mystery Ltd").reason == "fallback"
