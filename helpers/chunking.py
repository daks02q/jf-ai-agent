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


 

