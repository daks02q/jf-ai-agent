import logging
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from graph.graph import graph
import os
from psycopg.rows import dict_row
from dotenv import load_dotenv
import logging
from ..api.routes import router
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok = True)
file_handler = RotatingFileHandler(
    LOG_DIR / "app.log",
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
)


file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)

load_dotenv()

@asynccontextmanager
async def lifespan(app : FastAPI):
    async with AsyncConnectionPool(conninfo = os.getenv("CHKPT_URL"), max_size = 20, kwargs = {"autocommit" : True, "row_factory" : dict_row}, open = False,) as pool: 
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        app.state.graph = graph.compile(checkpointer= checkpointer)
        yield


app = FastAPI(lifespan = lifespan)

FRONTEND_ORIGIN = os.getenv("FRONTEND_URL")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv(FRONTEND_ORIGIN, "http://localhost:3000")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router)
