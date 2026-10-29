from langgraph.graph import StateGraph, START, END
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI
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
from helpers.retrieval import hybrid_retrieval, similarity_search
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
import json
import pandas as pd

import time

load_dotenv()

logger = logging.getLogger(__name__)

SYSTEM_CATALOG_SCHEMAS = {"information_schema", "pg_catalog"}

def sanitise_tool_calls_and_previous_messages(messages):
    """ Drop or repair left over tool calls and previous messages that can be picked up in the later conversation"""
    cleaned, i, n = [], 0, len(messages)
    while i < n:
        msg = messages[i]
        cleaned.append(msg)
        tool_calls = getattr(msg, "tool_calls", None)
        if isinstance(msg, AIMessage) and tool_calls:
            expected = {tc['id'] for tc in tool_calls if tc.get("id")}
            if len(expected) != len(tool_calls):
                cleaned.pop()
                i +=1
                continue
            seen, j = set(), i + 1
            while j < n and isinstance(messages[j], ToolMessage):
                seen.add(messages[j].tool_call_id)
                cleaned.append(messages[j])
                j = j+1

            for tid in expected - seen:
                cleaned.append(ToolMessage(
                    tool_call_id = tid,
                    content = "Tool call was not completed. Please try again."
                ))
            i = j
        else:
            i += 1
    return cleaned


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
    success : bool


checker = QueryCheck(check_method = "LLM")


class QueryRejected(Exception):
    """ Raised when a query fails tenant scoping or the safety check. """


async def _run_scoped_query(query: str, tenant_id: str | None) -> pd.DataFrame:
    """ Shared gate for every tool that touches the farm DB: tenant-scope, safety-check, execute. """
    if not tenant_id:
        raise QueryRejected("no tenant_id available for this session.")
    try:
        scoped_query = _scope_query_to_tenant(query, tenant_id)
    except ValueError as e:
        raise QueryRejected(str(e))
    except sqlglot.errors.ParseError as e:
        raise QueryRejected(f"could not parse SQL ({e}).")

    logger.info("scoped query tenant=%s: %s", tenant_id, scoped_query)

    if not await checker.check(scoped_query):
        raise QueryRejected("contains a disallowed/unsafe SQL operation.")

    start = time.monotonic()
    async with myconext_session_maker() as session:
        result = await session.execute(text(scoped_query))
        df = pd.DataFrame(result.fetchall(), columns = list(result.keys()))
    logger.info("query executed tenant=%s rows=%d in %.2fs", tenant_id, len(df), time.monotonic() - start)
    return df


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

    try:
        df = await _run_scoped_query(query, tenant_id)
    except QueryRejected as e:
        logger.warning("db_query_tool rejected: %s", e)
        return f"Query rejected: {e}"
    return str(list(df.itertuples(index = False, name = None)))


# @tool
# async def grep(pattern: str, path: str = ".", glob: str = "*", max_results: int = 100) -> str:
#     """ Search files under `path` for lines matching the regex pattern
#     Args:
#         pattern: Regular expression to search for.
#         path: Directory (searched recursively) or single file to search.
#         glob: Filename glob to restrict which files are searched, e.g. "*.py".
#         max_results: Maximum number of matching lines to return.
#     """

#     import fnmatch

#     try:
#         regex = re.compile(pattern)
#     except re.error as e:
#         return f"Invalid regex: {e}"

#     if os.path.isfile(path):
#         files = [path]
#     else:
#         files = []
#         for root, _dirs, filename in os.walk(path):
#             for name in filename:
#                 if fnmatch.fnmatch(name, glob):
#                     files.append(os.path.join(root, name))

#     matches = []
#     for file_path in files:
#         try:
#             with open(file_path, "r", encoding = "utf-8", errors = "ignore") as f:
#                 for lineo, line in enumerate(f, start = 1):
#                     if regex.search(line):
#                         matches.append(f"{file_path}: {lineo} : {line.rstrip()}")
#                         if len(matches) >= max_results:
#                             break
#         except OSError:
#             continue
#         if len(matches) >= max_results:
#             break

#     if not matches:
#         return "No matches found."

#     document = "\n".join(matches)

#     return document

@tool
async def retrieve_documents(query: str, top_k : int = 5) -> str:
    """ Search ingested documents for chunks relevant to the query"""
    results = await hybrid_retrieval(query, top_k)
    if not results:
        return "No relevant documents found."

    return "\n\n".join(
        f"[{r['title']} — doc {r['document_id']}]\n{r['chunk_text']}"
        for r in results
    )


ANALYSES = ("summary_stats", "group_sum", "trend", "top_n")
CHART_TYPES = ("bar", "line", "pie")
MAX_ANALYSIS_ROWS = 200


def _run_analysis(df: pd.DataFrame, analysis: str, x, y, group_by, freq: str, n: int) -> pd.DataFrame:
    """ Pure pandas dispatch for the closed set of supported analyses. """
    for col in (x, y, group_by):
        if col is not None and col not in df.columns:
            raise ValueError(f"column {col!r} not in query result; columns are {list(df.columns)}")
    if y is not None:
        df[y] = pd.to_numeric(df[y], errors = "coerce")

    match analysis:
        case "summary_stats":
            cols = [y] if y else df.select_dtypes("number").columns
            return df[cols].apply(pd.to_numeric, errors = "coerce").describe().T.reset_index(names = "column")
        case "group_sum":
            if not (group_by and y):
                raise ValueError("group_sum needs group_by and y")
            return df.groupby(group_by, as_index = False)[y].sum().sort_values(y, ascending = False)
        case "top_n":
            if not (group_by and y):
                raise ValueError("top_n needs group_by and y")
            return df.groupby(group_by, as_index = False)[y].sum().nlargest(n, y)
        case "trend":
            if not (x and y):
                raise ValueError("trend needs x (a date column) and y")
            df[x] = pd.to_datetime(df[x], errors = "coerce", utc = True)
            out = df.dropna(subset = [x]).set_index(x)[y].resample(freq).sum().reset_index()
            out[x] = out[x].dt.strftime("%Y-%m-%d")
            return out
        case _:
            raise ValueError(f"unsupported analysis {analysis!r}; use one of {ANALYSES}")


def _chart_spec(result: pd.DataFrame, chart: str, title: str) -> dict:
    """ Chart description for the frontend to render: first column is the label axis, second the value. """
    if chart not in CHART_TYPES:
        raise ValueError(f"unsupported chart {chart!r}; use one of {CHART_TYPES}")
    if result.shape[1] < 2:
        raise ValueError("chart needs a result with at least two columns")
    label_col, value_col = result.columns[0], result.columns[1]
    return {
        "type": chart,
        "title": title,
        "x_label": str(label_col),
        "y_label": str(value_col),
        "labels": result[label_col].astype(str).tolist(),
        "values": result[value_col].tolist(),
    }


@tool
async def analyze_tool(
    query: str,
    analysis: str,
    config: RunnableConfig,
    y: str | None = None,
    x: str | None = None,
    group_by: str | None = None,
    freq: str = "W",
    n: int = 10,
    chart: str | None = None,
    title: str = "",
) -> str:
    """ Run a read query against the database, then compute an analysis on the result and
    optionally return a chart. Use this instead of db_query_tool for totals, rankings, trends and
    comparisons, so the maths is done in code rather than by you.

    query: a PostgreSQL SELECT (tenant scoping is applied automatically, same as db_query_tool).
    analysis: one of
      summary_stats - count/mean/min/max of numeric columns (optionally just `y`)
      group_sum     - sum of `y` per `group_by`, largest first
      top_n         - the `n` largest `group_by` groups by sum of `y`
      trend         - sum of `y` over time; `x` is a date column, `freq` is a pandas
                      frequency: D (day), W (week), MS (month), QS (quarter)
    x / y / group_by: column names exactly as returned by the query.
    chart: optional "bar", "line" or "pie" to also return a chart spec for the user's dashboard.
    Always account for units when summing a weight column."""
    tenant_id = config['configurable'].get('tenant_id')
    logger.info("analyze_tool called tenant=%s analysis=%s chart=%s", tenant_id, analysis, chart)

    try:
        df = await _run_scoped_query(query, tenant_id)
        if df.empty:
            return "Query returned no rows; nothing to analyze."
        result = _run_analysis(df, analysis, x, y, group_by, freq, n)
        spec = _chart_spec(result, chart, title) if chart else None
    except QueryRejected as e:
        logger.warning("analyze_tool rejected: %s", e)
        return f"Query rejected: {e}"
    except ValueError as e:
        return f"Analysis failed: {e}"

    return json.dumps({
        "analysis": analysis,
        "total_rows": len(result),
        "truncated": len(result) > MAX_ANALYSIS_ROWS,
        "rows": json.loads(result.head(MAX_ANALYSIS_ROWS).to_json(orient = "records", date_format = "iso")),
        "chart": spec,
    })


@tool
async def save(content: str) -> str:
    """ Saving notes is not wired up yet. """
    return "Save is not available yet."


@tool
async def add_entries(type : str, section : str, entry : Dict[str, str], config : RunnableConfig) -> str:
    """ Making api requests to the actual enterprise platforms that contain these apis to facilitate input.
    It only needs batch count ( integer ), recipe, strain, parent type, parent (optional), substrate ratio, size, unit, status.
    Before this, you should run a cross check with the data asked to be input, if the strain, parent type, parent (if there and is not contaminated or empty yet) using the db_call tool. date is auto added on adding, parent field can be left empty if not specified"""
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

tools = [db_query_tool, analyze_tool, search, save, add_entries, retrieve_documents]

# agent = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0.0).bind_tools(tools)
# agent = ChatOpenAI(model = "deepseek-v4-flash",
#                     openai_api_base=os.getenv("OPENCODE_API_BASE"),
#                     openai_api_key=os.getenv("OPENCODE_API"),
#                     ).bind_tools(tools)

def _tool_error(e: Exception) -> str:
    logger.exception("tool failed")                 # or logger.warning
    return f"Tool failed: {type(e).__name__}: {e}"


async def model_call(state : AgentState, config : RunnableConfig) -> AgentState:
    """Calling the LLM model to generate answers or call tools that give relevant context to help answer better."""
    system_prompt = SystemMessage(content=
    """You are a helpful assistant that can answer questions and help with tasks for the internal team.
    Your first priority is to answer in a very clean manner. If you're querying tabular data then the user would like to see in bullet points rather than making at table with ASCII. No astericks formatting. Clean and professional output.
    For totals, rankings, trends or comparisons use analyze_tool (pass chart= when a visual helps) instead of summing rows yourself; use db_query_tool for plain lookups."""
    )
    thread_id = config['configurable'].get('thread_id', 'jf-ai-agent')

    agent = ChatOpenAI(
        model=os.getenv("OPENCODE_MODEL"),
        openai_api_base=os.getenv("OPENCODE_API_BASE"),
        openai_api_key=os.getenv("OPENCODE_API"),
        default_headers={"x-opencode-session": thread_id},
    ).bind_tools(tools)

    logger.info("model_call invoked with %d messages in context", len(state["messages"]))
    start = time.monotonic()
    history = sanitise_tool_calls_and_previous_messages(state["messages"])
    response = await agent.ainvoke([system_prompt] + history)
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
tool_node = ToolNode(tools = tools, handle_tool_errors= _tool_error)
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
