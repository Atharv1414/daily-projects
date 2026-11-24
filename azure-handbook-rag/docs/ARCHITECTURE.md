# Architecture

Ingestion and questions share one pipeline (`pipeline.py`). Storage, embedding and generation sit behind small protocols (`models.py`), so Azure and offline implementations are interchangeable.

## Design choices

| Choice | Reason |
|---|---|
| Hybrid search plus semantic rerank | Keywords find exact terms, vectors find paraphrases, reranking orders the combined results |
| Embeddings on the OpenAI v1 endpoint, answers on the project endpoint | The Foundry project endpoint does not route embedding requests |
| Microsoft Entra ID only | Local (key) authentication is turned off on both services, so there are no keys to leak |
| Content-hash chunk IDs | Re-running ingestion embeds only new text and removes stale chunks |
| Reranker threshold, then citation check | Weak matches never reach the model, and answers with no valid citation are refused |
| Passages escaped and labelled as data | Makes prompt injection harder, but does not eliminate it |

The citation check confirms that a cited passage exists, not that it supports the claim. Tune `MIN_RERANKER_SCORE` with `azure-rag eval` on your own questions.

## Limits

Reads `.md` and `.txt` only, has no conversation memory, and the web page has no sign-in (it listens on localhost only). Anyone who can use it can query every indexed document.
