from langgraph.graph import StateGraph, START, END
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_anthropic import ChatAnthropic
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from typing import TypedDict, Annotated, Sequence, Dict, List
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from langchain_core.tools import tool
from langgraph.graph.state import RunnableConfig
from langgraph.prebuilt import ToolNode
from dotenv import load_dotenv
from sqlalchemy import text
from db.engine import session_maker
import os
import requests
import re 
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from helpers.retrieval import similarity_search
from psycopg_pool import AsyncConnectionPool
from fastapi import FastAPI, HTTPException, Request, Response
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from helpers.query_checker import QueryCheck    
import httpx

load_dotenv()


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sucess : bool


checker = QueryCheck(check_method = "LLM")
@tool
async def db_query_tool(query: str) -> str: 
    """ query the database for the query by the LLM"""
    if not checker.check(query):
        return "Query rejected: contains a disallowed/unsafe SQL operation."
    async with session_maker() as session:
        result = await session.execute(text(query))
        return str(result.fetchall())


@tool 
async def grep(pattern: str, path: str = ".", glob: str = "*", max_results: int = 100) -> str:
    """ Search files under `path` for lines matching the regex pattern

    Args:
        pattern: Regular expression to search for.
        path: Directory (searched recursively) or single file to search.
        glob: Filename glob to restrict which files are searched, e.g. "*.py".
        max_results: Maximum number of matching lines to return.
    """

    import fnmatch

    try: 
        regex = re.compile(pattern)
    except re.error as e: 
        return f"Invalid regex: {e}"

    if os.path.isfile(path):
        files = [path]
    else: 
        files = []
        for root, _dirs, filename in os.walk(path):
            for name in filename: 
                if fnmatch.fnmatch(name, glob):
                    files.append(os.path.join(root, name))

    matches = []
    for file_path in files: 
        try: 
            with open(file_path, "r", encoding = "utf-8", errors = "ignore") as f: 
                for lineo, line in enumerate(f, start = 1):
                    if regex.search(line):
                        matches.append(f"{file_path}: {lineo} : {line.rstrip()}")
                        if len(matches) >= max_results:
                            break
        except OSError: 
            continue
        if len(matches) >= max_results:
            break
        
    if not matches: 
        return "No matches found."

    document = "\n".join(matches)
        
    return document

@tool
async def retrieve_documents(query: str, top_k : int = 5) -> str: 
    """ Search ingested documents for chunks relevant to the query"""
    results = await similarity_search(query, top_k)
    if not results:
        return "No relevant documents found."

    return "\n\n".join(
        f"[{r['title']} — doc {r['document_id']}]\n{r['chunk_text']}"
        for r in results
    )


@tool
async def save(content: str) -> str:
    """ Saving notes is not wired up yet. """
    return "Save is not available yet."


@tool
async def add_entries(type : str, section : str, entry : Dict[str, str], config : RunnableConfig) -> str:
    """ Making input requests for making entries"""
    base_url = "https://app.jnanafarms.com"
    token = os.getenv("ENTERPRISE_TOKEN")
    tenant_id = config['configurable'].get('tenant_id') 

    async with httpx.AsyncClient() as client:
        response = await client.post(
        f"{base_url}/api/{section}",
        json = {
            "type" : type,
            "entry" : entry
        },
        headers = {"Authorization": f"Bearer {token}",
        'x-tenant' : tenant_id},
    )
    

    return response.json(), response.status_code


@tool
async def search(keyword: str, url: str, topic: str) -> str:
    """ Web search is not wired up yet. """
    return "Search is not available yet."

async def should_continue(state: AgentState) -> AgentState:
    """This helps determine if the model should continue going or no""" 
    messages = state['messages']
    last_message = messages[-1]
    if not last_message.tool_calls:
        return "end"
    else:
        return "continue"
    
tools = [db_query_tool, search, save, grep, add_entries, retrieve_documents]


# agent = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0.0).bind_tools(tools)
agent = ChatOpenAI(model = "deepseek-v4-flash",
                    openai_api_base=os.getenv("OPENCODE_API_BASE"),
                    openai_api_key=os.getenv("OPENCODE_API")).bind_tools(tools)


async def model_call(state : AgentState) -> AgentState:
    """ calling model for answers or tool calling"""
    system_prompt = SystemMessage(content="You are a helpful assistant that can answer questions and help with tasks for the internal team.")
    response = await agent.ainvoke([system_prompt] + state["messages"])
    return {"messages" : [response]}


graph = StateGraph(AgentState)


graph.add_node("model", model_call)
graph.add_edge(START, "model")
tool_node = ToolNode(tools = tools)
graph.add_node("tools", tool_node)

graph.add_conditional_edges(
    "model",
    should_continue,
    {
        "continue" : "tools",
        "end" : END
    }
)

graph.add_edge("tools", "model")

