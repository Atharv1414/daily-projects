from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .pipeline import RagPipeline


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000, pattern=r"\S")


def create_app(pipeline: RagPipeline) -> FastAPI:
    app = FastAPI(title="Azure RAG")
    page = (Path(__file__).parent / "page.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse)
    def home() -> str:
        return page

    @app.post("/ask")
    def ask(body: Question) -> dict:
        answer = pipeline.ask(body.question)
        return {
            "answer": answer.text,
            "sources": [
                {
                    "number": n,
                    "source": h.chunk.source,
                    "title": h.chunk.title,
                    "excerpt": h.chunk.content,
                }
                for n, h in zip(answer.numbers, answer.sources, strict=True)
            ],
        }

    return app
