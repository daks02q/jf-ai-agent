import os
import logging

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b")

# Nemotron retrievers must know whether a text is a stored document or a query;
# using the wrong one causes large retrieval-accuracy drops.
PASSAGE = "passage"
QUERY = "query"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Build the OpenRouter embeddings client on first use.

    Kept lazy (not module-level) so a missing key fails with a clear error at
    call time instead of breaking every module that imports this one.
    """
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_KEY")
        if not api_key:
            raise RuntimeError(
                "OpenRouter API key not set — set OPENROUTER_API_KEY in the env."
            )
        _client = AsyncOpenAI(
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=api_key,
            default_headers={"X-Title": "ai_agent"},
            timeout=30,
        )
    return _client


async def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    response = await _get_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        extra_body={"input_type": input_type},
    )
    # Sort by index so embeddings[i] corresponds to texts[i].
    return [d.embedding for d in sorted(response.data, key=lambda d: d.index)]


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed document chunks for indexing."""
    if not texts:
        return []
    return await _embed(texts, PASSAGE)


async def embed_query(text: str) -> list[float]:
    """Embed a single retrieval query."""
    embeddings = await _embed([text], QUERY)
    return embeddings[0]
