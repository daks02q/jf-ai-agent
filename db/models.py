from pydantic import BaseModel 
from sqlalchemy.orm import DeclarativeBase, declarative_base, mapped_column, Mapped
from sqlalchemy import Column, Integer, String, ForeignKey

class ChatRequest(BaseModel): 
    message : str 
    session_id : str 
    user_id : str


class MessageResponse(BaseModel): 
    response : str 
    session_id : str
    user_id : str 

class OpenChat(BaseModel):
    first_text : str 
    session_id : str 
    user_id : str


Base = declarative_base()

class QueryChecks(Base): 
    __tablename__ = "query_check"
    id = Column(Integer, primary_key = True, autoincrement=True)
    query = Column(String(length = 200))
    answer = Column(String(length = 100))

# class Document(Base): 


