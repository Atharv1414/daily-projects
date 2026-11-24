import argparse
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .config import ConfigError, Settings
from .offline import ExtractiveGenerator, HashEmbedder, MemoryStore
from .pipeline import RagPipeline

DOCS = Path("sample_docs")


def build_pipeline(offline: bool) -> RagPipeline:
    if offline:
        return RagPipeline(MemoryStore(), HashEmbedder(), ExtractiveGenerator())
    from azure.identity import DefaultAzureCredential

    from .foundry import FoundryEmbedder, FoundryGenerator
    from .search import AzureSearchStore

    settings = Settings.from_env()
    credential = DefaultAzureCredential()
    return RagPipeline(
        AzureSearchStore(settings, credential),
        FoundryEmbedder(settings, credential),
        FoundryGenerator(settings, credential),
    )


def run(args: argparse.Namespace) -> None:
    pipeline = build_pipeline(args.offline)
    if args.offline and args.command != "ingest":
        pipeline.ingest(args.docs)  # the in-memory index lasts for one command
    if args.command == "ingest":
        r = pipeline.ingest(args.docs)
        print(f"{r.total} chunks: {r.added} added, {r.deleted} deleted")
    elif args.command == "ask":
        answer = pipeline.ask(args.question)
        print(answer.text)
        for n, hit in zip(answer.numbers, answer.sources, strict=True):
            print(f"  [{n}] {hit.chunk.source}: {hit.chunk.title} (score {hit.score:.2f})")
    elif args.command == "eval":
        from .evaluate import evaluate

        for name, value in evaluate(pipeline, args.file).items():
            print(f"{name:22} {value:.0%}" if isinstance(value, float) else f"{name:22} {value}")
    else:
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(pipeline), host="127.0.0.1", port=args.port)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(find_dotenv(usecwd=True))
    parser = argparse.ArgumentParser(prog="azure-rag")
    parser.add_argument("--offline", action="store_true", help="run without Azure")
    parser.add_argument("--docs", type=Path, default=DOCS, help="folder of .md and .txt files")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="make the index match the docs folder")
    sub.add_parser("ask", help="ask one question").add_argument("question")
    ev = sub.add_parser("eval", help="score retrieval, citations and refusals")
    ev.add_argument("file", type=Path, nargs="?", default=Path("eval.jsonl"))
    serve = sub.add_parser("serve", help="run the web page")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    from azure.core.exceptions import AzureError
    from openai import OpenAIError

    try:
        run(args)
    except (ConfigError, ValueError, OSError, RuntimeError, AzureError, OpenAIError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
