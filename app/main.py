from dotenv import load_dotenv
load_dotenv()

from helpers.logging_config import setup_logging, redact_url
setup_logging()

import logging
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from graph.graph import graph
import os
from psycopg.rows import dict_row
from api.routes import router
from db.models import Base
from db.engine import session_maker

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app : FastAPI):
    chkpt_url = os.getenv("CHKPT_URL")
    logger.info("Starting up: opening checkpoint pool (%s)", redact_url(chkpt_url))
    async with AsyncConnectionPool(conninfo = chkpt_url, max_size = 20, kwargs = {"autocommit" : True, "row_factory" : dict_row}, open = False,) as pool:
        await pool.open()
        logger.info("Checkpoint pool open")
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        logger.info("Checkpointer ready")
        app.state.graph = graph.compile(checkpointer= checkpointer)
        logger.info("Graph compiled — ready to serve")
        yield
        logger.info("Shutting down")


app = FastAPI(lifespan = lifespan)

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router)

