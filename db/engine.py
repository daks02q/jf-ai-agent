from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
import os 
from dotenv import load_dotenv

load_dotenv() 


DB_URL = os.getenv("DATABASE_URL")
db = create_async_engine(DB_URL)
session_maker =  async_sessionmaker(db, expire_on_commit = False)

async def make_db_session():
    """ makes an async session for the db """     
    async with session_maker() as s:
        yield s 
      