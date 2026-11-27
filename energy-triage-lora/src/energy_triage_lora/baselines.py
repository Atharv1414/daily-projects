"""The models a fine-tuned transformer has to beat to be worth running."""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from .data import Message
from .labels import FIELDS, Triage


class Majority:
    """Predicts the most common value of each field. The floor."""

    name = "majority"

    def fit(self, train: list[Message]) -> Majority:
        self.answer = Triage(
            *(Counter(getattr(m, name) for m in train).most_common(1)[0][0] for name, _ in FIELDS)
        )
        return self

    def predict(self, texts: list[str]) -> list[Triage]:
        return [self.answer] * len(texts)


KEYWORDS: list[tuple[str, str]] = [
    (
        r"smell of gas|smell gas|no gas|power cut|no electricity|no power"
        r"|tripp|flicker|meter box|cupboard",
        "supply_fault",
    ),
    (r"smart|in-home display|display", "smart_meter"),
    (r"reading|read\b|reads\b", "meter_reading"),
    (r"switch|exit fee|leaving|transfer|moving over", "switching"),
    (r"moving|moved|new tenant|keys|close my account|previous owner", "moving_home"),
    (
        r"payment plan|afford|arrears|debt|grant|struggling|direct debit date|payday|wages",
        "payment_support",
    ),
    (r"tariff|fixed|fix is|ev |electric car|solar|price rise|cheaper|unit rates", "tariff"),
    (r"bill|charged|statement|invoice|estimate", "billing"),
]
URGENT = (
    r"urgent|today|no electricity|no power|no gas|smell|cold|freezing"
    r"|self-disconnect|debt collect|without my permission|twice"
)
VULNERABLE = (
    # Written from the seen phrasings only, as a team would before the held-out ones turned up.
    r"\b(8\d|9\d)\b|oxygen|baby|disabled|housebound|dementia|carer|pregnant|blind"
)


class Keywords:
    """Hand-written rules, the way a team would start before any model. Needs no training data."""

    name = "keyword rules"

    def fit(self, _train: list[Message]) -> Keywords:
        return self

    def predict(self, texts: list[str]) -> list[Triage]:
        out = []
        for text in texts:
            t = text.lower()
            category = next((c for pattern, c in KEYWORDS if re.search(pattern, t)), "billing")
            urgency = (
                "high"
                if re.search(URGENT, t)
                else "low"
                if re.search(r"no rush|not urgent|whenever", t)
                else "medium"
            )
            vulnerable = "yes" if re.search(VULNERABLE, t) else "no"
            out.append(Triage(category, urgency, vulnerable))
        return out


class TfidfLogistic:
    """Word and character n-grams into one logistic regression per field.

    The strong classical baseline.
    """

    name = "TF-IDF + logistic regression"

    def fit(self, train: list[Message]) -> TfidfLogistic:
        texts = [m.text for m in train]
        self.models = {}
        for name, _ in FIELDS:
            features = FeatureUnion(
                [
                    (
                        "words",
                        TfidfVectorizer(
                            ngram_range=(1, 2), min_df=2, sublinear_tf=True, lowercase=True
                        ),
                    ),
                    (
                        "chars",
                        TfidfVectorizer(
                            analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True
                        ),
                    ),
                ]
            )
            model = Pipeline(
                [("features", features), ("clf", LogisticRegression(C=8.0, max_iter=2000))]
            )
            model.fit(texts, [getattr(m, name) for m in train])
            self.models[name] = model
        return self

    def predict(self, texts: list[str]) -> list[Triage]:
        columns = [self.models[name].predict(texts) for name, _ in FIELDS]
        return [Triage(*row) for row in zip(*columns, strict=True)]

    def confidence(self, texts: list[str]) -> np.ndarray:
        """Product of each field's top probability, comparable with the transformer's confidence."""
        probs = [self.models[name].predict_proba(texts).max(axis=1) for name, _ in FIELDS]
        return np.prod(np.vstack(probs), axis=0)
