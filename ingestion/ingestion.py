import cv2 
from paddleocr import PaddleOCR
import paddlex
from PIL import Image
from openai import AsyncOpenAI 
from db.models import DocumentEmbedding, Document
from helpers.chunking import Chunking
from db.engine import session_maker

import os 
from dotenv import load_dotenv

# TODO : change dim to 2054 in db and make an efficient pipeline to store the chunk + embedding 
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b")


_client = AsyncOpenAI(
    base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    api_key=os.getenv("OPENROUTER_API_KEY"),
    default_headers={"X-Title": "ai_agent"},
    timeout=30,
)


chunker = Chunking()

class Ingestion():
    def __init__(self, engine, process):
        self.engine = engine 
        self.process = process 

    async def ingest(self, file : str):
        """ takes pdf and runs them through an OCR engine""" 
        try: 
            # ocr
            # enable_mkldnn=False works around a paddlepaddle 3.3.1 bug where the
            # PIR executor's oneDNN text-detection kernel raises
            # NotImplementedError (ConvertPirAttribute2RuntimeAttribute), which
            # otherwise makes predict() yield zero pages silently.
            ocr = PaddleOCR(use_textline_orientation=True, lang='en', enable_mkldnn=False)
            opened_file = ocr.predict(file)

            pages_text = [
                "\n".join(page_result.get('rec_texts', []))
                for page_result in opened_file
            ]
            
            page_count = len(pages_text)

            return "\n\n".join(pages_text), page_count
        
        except Exception as e:
            print("ingestion is failing in ingestion", e)


    async def chunking(self, text : str) -> list[str]:
        return await chunker.chunk(text)

    # async def get_embeddings(self, chunks : list):
    #     return embedding_model.encode(chunks).tolist()

    async def embed(self, chunk : str) -> list[float]: 
        response = await _client.embeddings.create(
            model = EMBEDDING_MODEL,
            input = chunk
        )
        return response.data[0].embedding

    #TODO : need to implemenet a faster way of uploading to the db 
    async def get_embeddings(self, chunks : list[str]) -> list[list[float]]: 
        embeddings = []
        for chunk in chunks: 
            embedding = await self.embed(chunk)
            embeddings.append(embedding)
        return embeddings

    async def store_document(self, source, title, text, page_count, chunks, embeddings) -> int: 
        async with session_maker() as session:
            doc = Document(
                source = source,
                title = title, 
                content = text, 
                page_count = page_count, 
            )
            session.add(doc)
            await session.flush()

            for i, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)): 
                session.add(DocumentEmbedding(
                document_id=doc.id,
                chunk_index=i,
                chunk_text=chunk_text,
                embedding=embedding,
            ))

            await session.commit()
            return doc.id
            

    


    


