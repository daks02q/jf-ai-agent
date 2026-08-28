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
from db.engine import session_maker, myconext_session_maker
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
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope
import logging
import time

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_CATALOG_SCHEMAS = {"information_schema", "pg_catalog"}


def _scope_query_to_tenant(query: str, tenant_id: str) -> str:
    """ Parses `query`, then injects an alias-qualified `tenant = '<tenant_id>'`
    filter into every base-table scope in the query (top-level, each CTE, each
    subquery, each side of a UNION/etc.) so tenant scoping doesn't depend on
    the LLM remembering to write it correctly. CTE/derived-table references
    are skipped — they're already scoped via their own defining SELECT.
    """
    tree = sqlglot.parse_one(query, dialect="postgres")

    if not isinstance(tree, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
        raise ValueError("Only SELECT statements are allowed.")

    for scope in traverse_scope(tree):
        for alias, source in scope.sources.items():
            if not isinstance(source, exp.Table):
                continue  # CTE/derived-table reference, not a base table
            if (source.db or "").lower() in SYSTEM_CATALOG_SCHEMAS:
                continue  # information_schema / pg_catalog — no tenant column
            condition = exp.condition(f"\"{alias}\".tenant = '{tenant_id}'")
            scope.expression.where(condition, copy=False)

    return tree.sql(dialect="postgres")


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    sucess : bool


checker = QueryCheck(check_method = "LLM")
@tool
async def db_query_tool(query: str, config: RunnableConfig) -> str:
    """ Run a read query against the farm operations database (PostgreSQL,
    NOT SQLite — do not use sqlite_master or other SQLite-only syntax).

    Key tables: strains, recipes, spores, cultures, spawns, bulks, flushes,
    products, store, tents, vendors, tasks, activity_logs, task_logs,
    tent_logs, inventory, orders, expenses, fuel_logs, pay_funds,
    sale_products, harvest_stock_logs, customsers, users, attendance,
    leave_requests. Tenant scoping is applied automatically to every table
    referenced (including in joins, subqueries, CTEs, and UNIONs) — don't add
    a tenant filter yourself. To see exact column names for a table, query
    information_schema.columns (e.g. SELECT column_name FROM
    information_schema.columns WHERE table_name = 'spores').
    Always account for units when querying a table that a weight column.
    """
    tenant_id = config['configurable'].get('tenant_id')
    logger.info("db_query_tool called tenant=%s query=%r", tenant_id, query)

    if not tenant_id:
        logger.warning("db_query_tool rejected: no tenant_id in session config")
        return "Query rejected: no tenant_id available for this session."
    try:
        scoped_query = _scope_query_to_tenant(query, tenant_id)
    except ValueError as e:
        logger.warning("db_query_tool rejected (rewrite failed): %s", e)
        return f"Query rejected: {e}"
    except sqlglot.errors.ParseError as e:
        logger.warning("db_query_tool rejected (parse error): %s", e)
        return f"Query rejected: could not parse SQL ({e})."

    logger.info("db_query_tool scoped query: %s", scoped_query)

    if not await checker.check(scoped_query):
        logger.warning("db_query_tool rejected by QueryCheck: %s", scoped_query)
        return "Query rejected: contains a disallowed/unsafe SQL operation."

    start = time.monotonic()
    async with myconext_session_maker() as session:
        result = await session.execute(text(scoped_query))
        rows = result.fetchall()
        logger.info(
            "db_query_tool executed tenant=%s rows=%d in %.2fs",
            tenant_id, len(rows), time.monotonic() - start,
        )
        return str(rows)


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
        logger.info("Graph loop ending — final answer produced")
        return "end"
    else:
        tool_names = [tc["name"] for tc in last_message.tool_calls]
        logger.info("Graph loop continuing — tools requested: %s", tool_names)
        return "continue"
    
tools = [db_query_tool, search, save, grep, add_entries, retrieve_documents]


# agent = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0.0).bind_tools(tools)
agent = ChatOpenAI(model = "deepseek-v4-flash",
                    openai_api_base=os.getenv("OPENCODE_API_BASE"),
                    openai_api_key=os.getenv("OPENCODE_API")).bind_tools(tools)


async def model_call(state : AgentState) -> AgentState:
    """ calling model for answers or tool calling"""
    system_prompt = SystemMessage(content=
    """You are a helpful assistant that can answer questions and help with tasks for the internal team.
    Your first priority is to answer in a very clean manner. If you're querying tabular data then the user would like to see in bullet points rather than making at table with ASCII."""
    )
    logger.info("model_call invoked with %d messages in context", len(state["messages"]))
    start = time.monotonic()
    response = await agent.ainvoke([system_prompt] + state["messages"])
    elapsed = time.monotonic() - start
    if response.tool_calls:
        logger.info(
            "model_call finished in %.2fs — requesting tools: %s",
            elapsed, [tc["name"] for tc in response.tool_calls],
        )
    else:
        logger.info(
            "model_call finished in %.2fs — final answer (%d chars)",
            elapsed, len(response.content or ""),
        )
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

