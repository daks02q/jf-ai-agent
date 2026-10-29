import cv2
from paddleocr import PaddleOCR, PPStructureV3
import paddlex
from PIL import Image
from db.models import DocumentEmbedding, Document
from helpers.chunking import Chunking
from helpers.embeddings import embed_documents
from db.engine import session_maker
import torch
import paddle
import logging

logger = logging.getLogger(__name__)

chunker = Chunking()

torch.set_num_threads(1)

if hasattr(paddle, "set_num_threads"):
    paddle.set_num_threads(1)
else:
    from paddle.base import core as _paddle_core
    _paddle_core.set_num_threads(1)

_MODEL_BUILDERS = {
    "ocr": lambda: PaddleOCR(use_textline_orientation=True, lang="en", enable_mkldnn=False),
    "layout": lambda: paddlex.create_model(model_name="PP-DocLayout-L"),
    "table": lambda: paddlex.create_model(model_name="SLANet_plus"),
    "formula": lambda: paddlex.create_model(model_name="PP-FormulaNet_plus-L"),
    "structure": lambda: PPStructureV3(),
}

_instances: dict[str, object] = {}

def get_model(name: str):
    if name not in _MODEL_BUILDERS:
        raise ValueError(f"Unknown model: {name!r}")
    if name not in _instances:
        _instances[name] = _MODEL_BUILDERS[name]()
    return _instances[name]


_ocr : PaddleOCR | None = None

def _get_paddleocr():
    global _ocr
    if _ocr is None:
        _ocr = PaddleOCR(use_textline_orientation=True, lang='en', enable_mkldnn=False)
    return _ocr

cateogories_supported = {
    "research_articles" : {'formula', 'ocr', 'layout'},
    "invoices" : {"table", 'ocr', 'layout'},
    "articles" : {"ocr"}
}

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
            ocr = _get_paddleocr()
            opened_file = ocr.predict(str(file))

            pages_text = [
                "\n".join(page_result.get('rec_texts', []))
                for page_result in opened_file
            ]

            page_count = len(pages_text)

            return "\n\n".join(pages_text), page_count
        except Exception as e:
            print("ingestion is failing in ingestion", e)


    def _fill_table_cells(self, table_crop, table_result) -> str:
        """ SLANet_plus's 'structure' output is a table skeleton (HTML tokens)
        with no cell text — 'bbox' gives one cell box per <td>-family token,
        in the same order those tokens appear in 'structure'. OCR each cell
        crop and splice the text back into its slot to get real HTML. """
        structure_tokens = table_result.get("structure") or []
        cell_bboxes = table_result.get("bbox") or []
        td_family = ("<td>", "<td", "<td></td>")

        html_parts = []
        bbox_i = 0
        for tok in structure_tokens:
            html_parts.append(tok)
            if tok in td_family and bbox_i < len(cell_bboxes):
                coords = cell_bboxes[bbox_i]
                bbox_i += 1
                xs = coords[0::2]
                ys = coords[1::2]
                cx0, cx1 = int(min(xs)), int(max(xs))
                cy0, cy1 = int(min(ys)), int(max(ys))
                cell_crop = table_crop[cy0:cy1, cx0:cx1]
                cell_text = ""
                if cell_crop.size > 0:
                    cell_result = next(iter(get_model("ocr").predict(cell_crop)))
                    cell_text = "".join(cell_result.get("rec_texts", []))

                if tok == "<td></td>":
                    html_parts[-1] = f"<td>{cell_text}</td>"
                else:
                    # spanned cell — its own </td> token arrives later in the sequence
                    html_parts.append(cell_text)

        return "".join(html_parts)

    async def updated_ingest(self, file : str, doc_type : str) -> tuple[list[dict], int]:
        """ Document-layout-aware ingestion: runs only the models a doc_type
        needs, routing each detected layout region to the right recognizer
        (table structure, formula, or plain OCR) instead of always paying
        for the full PPStructureV3 pipeline. """
        if doc_type not in cateogories_supported:
            raise ValueError(f"Unknown doc_type: {doc_type!r}")
        categories = cateogories_supported[doc_type]

        if categories == {"ocr"}:
            # no structural routing needed — plain OCR already does this
            return await self.ingest(file)

        if "layout" not in categories:
            raise ValueError(
                f"doc_type {doc_type!r} needs 'layout' in its categories to route regions"
            )

        layout_model = get_model("layout")
        pages_blocks: list[dict] = []

        for page_result in layout_model.predict(str(file)):
            page_image = page_result["input_img"]  # numpy array (BGR), same page the boxes are in
            seen_labels = set()

            for box in page_result["boxes"]:
                label = box["label"]
                seen_labels.add(label)
                xmin, ymin, xmax, ymax = (int(v) for v in box["coordinate"])
                crop = page_image[ymin:ymax, xmin:xmax]
                if crop.size == 0:
                    continue

                lower_label = label.lower()

                if "table" in lower_label and "table" in categories:
                    result = next(iter(get_model("table").predict(crop)))
                    content = self._fill_table_cells(crop, result)
                    block_type = "table"
                elif "formula" in lower_label and "formula" in categories:
                    result = next(iter(get_model("formula").predict(crop)))
                    content = result["rec_formula"]
                    block_type = "formula"
                elif "ocr" in categories:
                    result = next(iter(get_model("ocr").predict(crop)))
                    content = "\n".join(result.get("rec_texts", []))
                    block_type = "text"
                else:
                    # region type not requested for this doc_type — skip it
                    continue

                pages_blocks.append({
                    "label": label,
                    "block_type": block_type,
                    "content": content,
                    "bbox": [xmin, ymin, xmax, ymax],
                    "page_index": page_result.get("page_index", len(pages_blocks)),
                })

            logger.info("updated_ingest doc_type=%s labels seen on page: %s", doc_type, seen_labels)

        page_count = len({b["page_index"] for b in pages_blocks}) or 1
        return pages_blocks, page_count


    async def chunking(self, text : str) -> list[str]:
        return await chunker.chunk(text)

    async def chunking_blocks(self, blocks : list[dict]) -> list[dict]:
        """ Structure-aware counterpart to chunking() — consumes updated_ingest's
        block output instead of flat text. """
        return await chunker.chunk_blocks(blocks)

    async def get_embeddings(self, chunks : list[str]) -> list[list[float]]:
        return await embed_documents(chunks)

    async def store_document(self, source, title, text, page_count, chunks, embeddings, thread_id=None, user=None) -> int:
        """ chunks may be either list[str] (from chunking()) or list[dict]
        (from chunking_blocks(), each with a "content" key plus optional
        "block_type"/"label" metadata) — both are accepted here. """
        async with session_maker() as session:
            doc = Document(
                source = source,
                title = title,
                content = text,
                page_count = page_count,
                doc_metadata = {"thread_id": thread_id, "user": user},
            )
            session.add(doc)
            await session.flush()

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                if isinstance(chunk, dict):
                    chunk_text = chunk.get("content", "")
                    block_type = chunk.get("block_type")
                    label = chunk.get("label")
                else:
                    chunk_text = chunk
                    block_type = None
                    label = None

                session.add(DocumentEmbedding(
                document_id=doc.id,
                chunk_index=i,
                chunk_text=chunk_text,
                block_type=block_type,
                label=label,
                embedding=embedding,
            ))

            await session.commit()
            return doc.id
