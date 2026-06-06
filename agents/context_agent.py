import logging

from pipeline.state import PipelineState
from utils.chroma_setup import get_collection, get_embedder

_TOP_K = 3


def run_context_agent(state: PipelineState) -> dict:
    logging.info("[context_agent] Querying ChromaDB for historical context")
    analysis = state.get("analysis") or {}

    # Build query from the richest available text field
    query_text = (
        analysis.get("trend_summary")
        or (analysis.get("observations") or ["weather patterns"])[0]
    )

    try:
        embedder = get_embedder()
        collection = get_collection()
        query_embedding = embedder.encode([query_text]).tolist()
        results = collection.query(query_embeddings=query_embedding, n_results=_TOP_K)
        docs: list[str] = results.get("documents", [[]])[0]
        logging.info("[context_agent] Retrieved %d documents", len(docs))
        return {"context_docs": docs, "status": "context_complete"}
    except Exception as exc:
        logging.error("[context_agent] Failed: %s", exc)
        return {
            "context_docs": ["No historical context available due to retrieval error."],
            "errors": state["errors"] + [f"context_agent: {exc}"],
            "status": "context_failed",
        }
