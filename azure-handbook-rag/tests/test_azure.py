"""Real Azure/OpenAI SDK clients talking to fake HTTP transports."""

import json
import time
from types import SimpleNamespace

import httpx2
import pytest
from azure.core.credentials import AccessToken, AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import OpenAI

from azure_rag.config import Settings
from azure_rag.foundry import FoundryEmbedder, FoundryGenerator
from azure_rag.models import Chunk
from azure_rag.search import AzureSearchStore

SETTINGS = Settings("https://p.example", "https://o.example/openai/v1/", "https://s.example")


class FakeCredential:
    def get_token(self, *scopes, **kwargs):
        return AccessToken("t", int(time.time()) + 3600)


class Adapter:
    """A requests-session stand-in: records requests, replays JSON responses."""

    def __init__(self, *bodies):
        self.bodies, self.calls = list(bodies), []

    def request(self, method, url, **kwargs):
        import requests

        self.calls.append((method, url, kwargs.get("data")))
        response = requests.Response()
        response.status_code = 200
        response.headers["content-type"] = "application/json"
        response._content = json.dumps(self.bodies.pop(0)).encode()
        response._content_consumed = True
        response.raw = SimpleNamespace()
        response.url = url
        return response

    def mount(self, *args):
        pass

    def close(self):
        pass

    def body(self, i=0):
        return json.loads(self.calls[i][2])


def make_store(*bodies, settings=SETTINGS):
    from azure.core.pipeline.transport import RequestsTransport

    http = Adapter(*bodies)
    key = AzureKeyCredential("fake")
    transport = RequestsTransport(session=http, session_owner=False)
    return (
        AzureSearchStore(
            settings,
            FakeCredential(),
            client=SearchClient("https://s.example", "i", key, transport=transport),
            index_client=SearchIndexClient("https://s.example", key, transport=transport),
        ),
        http,
    )


def row(i, rerank):
    return {
        "id": i,
        "source": "a.md",
        "title": "T",
        "content": "C",
        "@search.score": 0.03,
        "@search.rerankerScore": rerank,
    }


def test_hybrid_semantic_query_and_threshold():
    store, http = make_store({"value": [row("1", 2.9), row("2", 0.4)]})
    hits = store.search("leave", [0.1, 0.2], 5)
    body = http.body()
    assert body["search"] == "leave"
    assert body["queryType"] == "semantic"
    vector = body["vectorQueries"][0]
    assert (vector["kind"], vector["k"], vector["fields"]) == ("vector", 50, "embedding")
    assert [(h.chunk.id, h.score) for h in hits] == [("1", 2.9)]


def test_without_semantic_ranking():
    settings = Settings("p", "o", "s", use_semantic=False)
    store, http = make_store({"value": [row("1", None)]}, settings=settings)
    assert store.search("q", [0.1], 5)[0].score == 0.03
    assert "semanticConfiguration" not in http.body()


def test_index_definition_on_the_wire():
    store, http = make_store({"name": "handbook", "fields": []})
    store.ensure_index()
    body = http.body()
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["id"]["key"] is True
    assert fields["embedding"]["dimensions"] == 1536
    assert fields["embedding"]["type"] == "Collection(Edm.Single)"
    assert fields["embedding"]["vectorSearchProfile"] == "hnsw"
    assert fields["content"]["searchable"] is True
    assert body["semantic"]["configurations"][0]["name"] == "default"


def test_existing_ids_pages_by_key():
    store, http = make_store({"value": [{"id": "a"}, {"id": "b"}]}, {"value": []})
    assert store.existing_ids() == {"a", "b"}
    assert http.body(1)["filter"] == "id gt 'b'"


@pytest.mark.parametrize("ok", [True, False])
def test_upload_reports_failures(ok):
    result = {"key": "1", "status": ok, "errorMessage": "bad", "statusCode": 200 if ok else 400}
    store, http = make_store({"value": [result]})
    if ok:
        store.upload([Chunk("1", "a", "t", "c")], [[0.1]])
        assert http.body()["value"][0]["@search.action"] == "upload"
    else:
        with pytest.raises(RuntimeError, match="bad"):
            store.upload([Chunk("1", "a", "t", "c")], [[0.1]])


def openai_client(body, seen):
    def handler(request):
        seen.append((str(request.url), json.loads(request.content)))
        return httpx2.Response(200, json=body)

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return OpenAI(base_url="https://o.example/openai/v1/", api_key="fake", http_client=http)


def test_embeddings_are_reordered_by_index():
    seen = []
    data = [{"object": "embedding", "index": i, "embedding": [float(i)]} for i in (1, 0)]
    body = {
        "object": "list",
        "model": "m",
        "data": data,
        "usage": {"prompt_tokens": 1, "total_tokens": 1},
    }
    embedder = FoundryEmbedder(SETTINGS, FakeCredential(), openai_client(body, seen))
    assert embedder.embed(["a", "b"]) == [[0.0], [1.0]]
    assert seen[0][0].endswith("/openai/v1/embeddings")
    assert seen[0][1]["dimensions"] == 1536


@pytest.mark.parametrize("status", ["completed", "incomplete"])
def test_generation(status):
    seen = []
    message = {
        "type": "message",
        "id": "m",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "Hi [1]", "annotations": []}],
    }
    body = {
        "id": "r",
        "object": "response",
        "created_at": 0,
        "model": "m",
        "status": status,
        "output": [message],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
    }
    generator = FoundryGenerator(SETTINGS, FakeCredential(), openai_client(body, seen))
    if status == "completed":
        assert generator.generate("rules", "q") == "Hi [1]"
        assert seen[0][1]["store"] is False
        assert seen[0][1]["model"] == "chat"
    else:
        with pytest.raises(RuntimeError, match="incomplete"):
            generator.generate("rules", "q")


def test_real_clients_construct_without_network():
    from azure_rag.cli import RagPipeline

    credential = FakeCredential()
    embedder = FoundryEmbedder(SETTINGS, credential)
    generator = FoundryGenerator(SETTINGS, credential)
    RagPipeline(AzureSearchStore(SETTINGS, credential), embedder, generator)
    assert str(generator._client.base_url).rstrip("/").endswith("/openai/v1")
