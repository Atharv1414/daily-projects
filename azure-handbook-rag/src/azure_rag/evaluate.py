import json
from pathlib import Path

from .pipeline import REFUSAL, RagPipeline


def evaluate(pipeline: RagPipeline, path: Path) -> dict[str, float | int]:
    """Retrieval hit rate, cited-source rate, and correct refusals for unanswerable questions."""
    lines = path.read_text(encoding="utf-8").splitlines()
    cases = [json.loads(line) for line in lines if line.strip()]
    answerable = [c for c in cases if c["source"]]
    unanswerable = [c for c in cases if not c["source"]]
    retrieved = cited = 0
    for case in answerable:
        hits = pipeline.retrieve(case["question"])
        retrieved += case["source"] in {h.chunk.source for h in hits}
        answer = pipeline.ask(case["question"])
        cited += case["source"] in {h.chunk.source for h in answer.sources}
    refused = sum(pipeline.ask(c["question"]).text == REFUSAL for c in unanswerable)
    return {
        "questions": len(cases),
        "retrieval_hit_rate": retrieved / len(answerable) if answerable else 0.0,
        "correct_source_cited": cited / len(answerable) if answerable else 0.0,
        "correct_refusals": refused / len(unanswerable) if unanswerable else 0.0,
    }
