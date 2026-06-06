import logging
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
COLLECTION_NAME = "weather_history"
EMBED_MODEL = "all-MiniLM-L6-v2"

MOCK_DOCUMENTS = [
    "January 2024 recorded unusually high temperatures across Europe, with some regions exceeding 15°C above seasonal norms for the month.",
    "The summer 2023 Mediterranean heatwave pushed temperatures to 47°C in parts of Greece and Italy, straining power grids for weeks.",
    "Winter 2023 brought anomalous heavy snowfall to traditionally arid Middle Eastern regions, disrupting transport infrastructure.",
    "Spring 2024 featured extreme 48-hour temperature swings of up to 20°C in central Europe, causing widespread agricultural frost damage.",
    "The El Niño event of 2023–2024 shifted global monsoon patterns, intensifying drought in East Africa and flooding in South America.",
]

_model: SentenceTransformer | None = None


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def get_collection() -> chromadb.Collection:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(name=COLLECTION_NAME)

    if collection.count() == 0:
        logging.info("[chroma] Seeding collection with %d mock documents", len(MOCK_DOCUMENTS))
        embedder = get_embedder()
        embeddings = embedder.encode(MOCK_DOCUMENTS).tolist()
        collection.add(
            documents=MOCK_DOCUMENTS,
            embeddings=embeddings,
            ids=[f"mock_{i}" for i in range(len(MOCK_DOCUMENTS))],
        )

    return collection
