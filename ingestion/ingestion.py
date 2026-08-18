import cv2 
from paddleocr import PaddleOCR
import paddlex
from PIL import Image
from sentence_transformers import SentenceTransformers 
from langchain_text_splitters import RecursiveCharacterTextSplitter

embedding_model = SentenceTransformers(
    "Qwen/Qwen3-Embedding-0.6B",
)   

class Ingestion():
    def __init__(self, engine, process):
        self.engine = engine 
        self.process = process 
        return self

    def ingest(self, file : str):
        """ takes pdf and runs them through an OCR engine""" 
        text = []
        ocr = PaddleOCR(use_angle_cls = True, lang='en')
        opened_file = ocr.predict(file)

        pages_text = [
            "\n".join(page_result.get('rec_texts', []))
            for page_result in opened_file
        ]


        return "\n\n".join(pages_text)

    def chunking(self, text): 
        splitter = RecursiveCharacterTextSplitter(
            chunk_size = 700, 
            chunk_overlap =100, 
            separators = [ 
                '\n',
                '\n\n',
                ". ",
                '',
            ]
        )

        chunks = splitter.split_text(text)
        return chunks

    def get_embeddings(chunks : list): 
        embeddings = [ embedding_model.embed_query(chunk)
        for chunk in chunks
        ] 
        return embeddings

        

    


    


