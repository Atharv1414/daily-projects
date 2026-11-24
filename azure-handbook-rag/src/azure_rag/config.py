import os
from dataclasses import dataclass


class ConfigError(ValueError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or "<" in value:
        raise ConfigError(f"{name} is not set. Copy .env.example to .env and fill it in.")
    return value


@dataclass(frozen=True)
class Settings:
    project_endpoint: str
    openai_endpoint: str
    search_endpoint: str
    search_index: str = "handbook"
    chat_deployment: str = "chat"
    embedding_deployment: str = "embedding"
    embedding_dimensions: int = 1536
    use_semantic: bool = True
    min_reranker_score: float = 1.5

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            project_endpoint=_required("PROJECT_ENDPOINT"),
            openai_endpoint=_required("OPENAI_ENDPOINT"),
            search_endpoint=_required("SEARCH_ENDPOINT"),
            search_index=env("SEARCH_INDEX", "handbook"),
            chat_deployment=env("CHAT_DEPLOYMENT", "chat"),
            embedding_deployment=env("EMBEDDING_DEPLOYMENT", "embedding"),
            embedding_dimensions=int(env("EMBEDDING_DIMENSIONS", "1536")),
            use_semantic=env("USE_SEMANTIC", "true").strip().lower() in {"1", "true", "yes"},
            min_reranker_score=float(env("MIN_RERANKER_SCORE", "1.5")),
        )
