import cv2 
from paddleocr import PaddleOCR
import paddlex
from PIL import Image
from sentence_transformers import SentenceTransformer
from db.models import DocumentEmbedding, Document
from helpers.chunking import Chunking
from db.engine import session_maker

embedding_model = SentenceTransformer(
    "Qwen/Qwen3-Embedding-0.6B",
)


chunker = Chunking()

class Ingestion():
    def __init__(self, engine, process):
        self.engine = engine 
        self.process = process 

    async def ingest(self, file : str):
        """ takes pdf and runs them through an OCR engine""" 
        text = []


        # ocr
        ocr = PaddleOCR(use_angle_cls = True, lang='en')
        opened_file = ocr.predict(file)

        pages_text = [
            "\n".join(page_result.get('rec_texts', []))
            for page_result in opened_file
        ]
        
        page_count = len(pages_text)

        return "\n\n".join(pages_text), page_count

    async def chunking(self, text : str) -> list[str]:
        return await chunker.chunk(text)

    async def get_embeddings(self, chunks : list):
        return embedding_model.encode(chunks).tolist()


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
            

    


    


