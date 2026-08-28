from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os
import logging
from dotenv import load_dotenv
from helpers.logging_config import redact_url

load_dotenv()

logger = logging.getLogger(__name__)


def _make_engine(env_var: str):
    url = os.getenv(env_var)
    if not url:
        raise RuntimeError(f"{env_var} is not set — check .env on this machine.")
    logger.info("Creating DB engine for %s -> %s", env_var, redact_url(url))
    return create_async_engine(url)


db = _make_engine("DATABASE_URL")
session_maker =  async_sessionmaker(db, expire_on_commit = False)

async def make_db_session():
    """ makes an async session for the db """
    async with session_maker() as s:
        yield s


myconext_db = _make_engine("MYCONEXT_DATABASE_URL")
myconext_session_maker = async_sessionmaker(myconext_db, expire_on_commit = False)
      