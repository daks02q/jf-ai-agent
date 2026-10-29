import re
from typing import TypedDict 
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Chunking(): 
    def __init__(self):
        self = self

    async def chunk(self, text, chunk_size : int = 700, chunk_overlap : int = 150) -> list[str]:
        """ chunks the the received document """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size = chunk_size, 
            chunk_overlap = chunk_overlap,
            separators=["\n\n", "\n", ". ", ""],
        )

        split_text = splitter.split_text(text)
        cleaned_split_text = [ c.strip() for c in split_text if c.strip()]
        return cleaned_split_text

    async def chunk_blocks(self, blocks: list[dict], chunk_size: int = 700, chunk_overlap: int = 150) -> list[dict]:
        """ Structure-aware chunking for document_aware_ingestion's block output
        (see ingestion.py's updated_ingest). Table and formula blocks are kept
        atomic — never split, since splitting a table's HTML or a formula
        mid-expression destroys its meaning. Text blocks under chunk_size stay
        whole; longer ones fall back to the same RecursiveCharacterTextSplitter
        used for plain-OCR text. Each resulting chunk carries the source
        block's metadata (label, block_type, bbox, page_index) forward. """
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", ""],
        )

        chunks: list[dict] = []
        for block in blocks:
            content = (block.get("content") or "").strip()
            if not content:
                continue

            if block.get("block_type") in ("table", "formula") or len(content) <= chunk_size:
                chunks.append({**block, "content": content})
                continue

            for piece in splitter.split_text(content):
                piece = piece.strip()
                if piece:
                    chunks.append({**block, "content": piece})

        return chunks

