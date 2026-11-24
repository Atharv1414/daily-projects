"""Azure AI Foundry: embeddings and answer generation."""

from typing import Any

from azure.ai.projects import AIProjectClient
from azure.core.credentials import TokenCredential
from azure.identity import get_bearer_token_provider
from openai import OpenAI

from .config import Settings

TOKEN_SCOPE = "https://ai.azure.com/.default"


class FoundryEmbedder:
    """The project endpoint does not route embeddings, so this uses the OpenAI v1 endpoint."""

    def __init__(self, settings: Settings, credential: TokenCredential, client: Any = None):
        self._settings = settings
        self._client = client or OpenAI(
            base_url=settings.openai_endpoint,
            api_key=get_bearer_token_provider(credential, TOKEN_SCOPE),
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 64):
            response = self._client.embeddings.create(
                model=self._settings.embedding_deployment,
                input=texts[start : start + 64],
                dimensions=self._settings.embedding_dimensions,
            )
            vectors += [d.embedding for d in sorted(response.data, key=lambda d: d.index)]
        return vectors


class FoundryGenerator:
    def __init__(self, settings: Settings, credential: TokenCredential, client: Any = None):
        self._settings = settings
        self._client = (
            client
            or AIProjectClient(
                endpoint=settings.project_endpoint, credential=credential
            ).get_openai_client()
        )

    def generate(self, instructions: str, prompt: str) -> str:
        response = self._client.responses.create(
            model=self._settings.chat_deployment,
            instructions=instructions,
            input=prompt,
            reasoning={"effort": "low"},
            max_output_tokens=2000,
            store=False,
        )
        if response.status != "completed":
            raise RuntimeError(f"The model did not finish its answer (status: {response.status}).")
        return response.output_text.strip()
