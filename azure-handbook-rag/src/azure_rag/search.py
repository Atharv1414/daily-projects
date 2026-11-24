"""Azure AI Search: index definition and hybrid (keyword + vector) retrieval."""

from typing import Any

from azure.core.credentials import TokenCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes import models as ix
from azure.search.documents.models import VectorizedQuery

from .config import Settings
from .models import Chunk, Hit

SEMANTIC_CONFIG = "default"
BATCH = 500


def build_index(name: str, dimensions: int, semantic: bool) -> ix.SearchIndex:
    string = ix.SearchFieldDataType.STRING
    return ix.SearchIndex(
        name=name,
        fields=[
            ix.SimpleField(name="id", type=string, key=True, filterable=True, sortable=True),
            ix.SimpleField(name="source", type=string, filterable=True, facetable=True),
            ix.SearchableField(name="title", analyzer_name="en.microsoft"),
            ix.SearchableField(name="content", analyzer_name="en.microsoft"),
            ix.SearchField(
                name="embedding",
                type=ix.SearchFieldDataType.Collection(ix.SearchFieldDataType.SINGLE),
                searchable=True,
                hidden=True,
                vector_search_dimensions=dimensions,
                vector_search_profile_name="hnsw",
            ),
        ],
        vector_search=ix.VectorSearch(
            algorithms=[ix.HnswAlgorithmConfiguration(name="hnsw-config")],
            profiles=[
                ix.VectorSearchProfile(name="hnsw", algorithm_configuration_name="hnsw-config")
            ],
        ),
        semantic_search=ix.SemanticSearch(
            configurations=[
                ix.SemanticConfiguration(
                    name=SEMANTIC_CONFIG,
                    prioritized_fields=ix.SemanticPrioritizedFields(
                        title_field=ix.SemanticField(field_name="title"),
                        content_fields=[ix.SemanticField(field_name="content")],
                    ),
                )
            ]
        )
        if semantic
        else None,
    )


class AzureSearchStore:
    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential,
        client: Any = None,
        index_client: Any = None,
    ):
        self._settings = settings
        self._client = client or SearchClient(
            settings.search_endpoint, settings.search_index, credential
        )
        self._index_client = index_client or SearchIndexClient(settings.search_endpoint, credential)

    def ensure_index(self) -> None:
        s = self._settings
        self._index_client.create_or_update_index(
            build_index(s.search_index, s.embedding_dimensions, s.use_semantic)
        )

    def existing_ids(self) -> set[str]:
        # Paging by key avoids the 100,000-result limit on skip.
        ids: set[str] = set()
        last = ""
        while True:
            page = [
                r["id"]
                for r in self._client.search(
                    "*", filter=f"id gt '{last}'", order_by=["id"], select=["id"], top=1000
                )
            ]
            if not page:
                return ids
            ids.update(page)
            last = page[-1]

    def upload(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        documents = [
            {**vars(chunk), "embedding": vector}
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        for start in range(0, len(documents), BATCH):
            self._check(self._client.upload_documents(documents[start : start + BATCH]))

    def delete(self, ids: set[str]) -> None:
        documents = [{"id": i} for i in sorted(ids)]
        for start in range(0, len(documents), BATCH):
            self._check(self._client.delete_documents(documents[start : start + BATCH]))

    @staticmethod
    def _check(results: list[Any]) -> None:
        if failed := [r for r in results if not r.succeeded]:
            raise RuntimeError(
                f"{len(failed)} documents failed to index. First error: {failed[0].error_message}"
            )

    def search(self, query: str, vector: list[float], top: int) -> list[Hit]:
        options: dict[str, Any] = {}
        if self._settings.use_semantic:
            options = {"query_type": "semantic", "semantic_configuration_name": SEMANTIC_CONFIG}
        results = self._client.search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(vector=vector, k_nearest_neighbors=50, fields="embedding")
            ],
            select=["id", "source", "title", "content"],
            top=top,
            **options,
        )
        hits = []
        for r in results:
            rerank = r.get("@search.reranker_score")
            if rerank is not None and rerank < self._settings.min_reranker_score:
                continue
            chunk = Chunk(r["id"], r["source"], r["title"], r["content"])
            hits.append(Hit(chunk, rerank if rerank is not None else r["@search.score"]))
        return hits
