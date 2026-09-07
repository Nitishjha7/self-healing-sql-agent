"""MCP client — database ko subprocess me chalte server se tool calls ke through use karta hai.

**Yahan asli engineering problem transport nahi, do duniyaon ka mel hai.** MCP ka
Python SDK async hai aur stdio session ko ek long-lived `async with` block me
rakhta hai. Humare graph nodes sync hain (LangGraph ke sync `invoke` pe chalte
hain, jise FastAPI threadpool me bulata hai). Beech me teen raaste the:

1. **Har call pe `asyncio.run()`** — sabse aasan, aur sabse ghatiya: har SQL
   query ek naya Python subprocess spawn karti, ~200-300ms sirf process start me.
2. **Poora stack async karna** — graph nodes, FastAPI handlers, sab. Sahi hai,
   par ek MCP toggle ke liye poore agent ka rewrite.
3. **Ek background thread jisme apna event loop ho**, jo session ko zinda rakhe,
   aur sync callers uspe kaam bhejein. Yahi chuna.

Session ek baar khulta hai aur process ke jeevan bhar zinda rehta hai. Sync taraf
`asyncio.run_coroutine_threadsafe` se call bhejti hai aur result ka intezaar
karti hai — matlab caller ko ye ehsaas hi nahi hota ki peeche async hai.

**Ye poora file MCP ki asli laagat hai**, aur isi wajah se `USE_MCP` default off
hai: seedha driver call hamesha tez rahegi. MCP ka faayda speed nahi — ye hai ki
data access ek **swappable, standard interface** ban jaata hai.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from typing import Any, Optional

log = logging.getLogger(__name__)

USE_MCP = os.environ.get("USE_MCP", "").lower() in ("1", "true", "yes")

# Server ko module ki tarah chalate hain, path se nahi — isse working directory
# aur file layout par nirbharta khatam ho jaati hai.
_SERVER_CMD = [sys.executable, "-m", "mcp_server.server"]

_client: Optional["_McpBridge"] = None
_lock = threading.Lock()


class McpUnavailable(RuntimeError):
    """Session shuru hi nahi ho paayi — caller ko direct driver pe girna chahiye."""


class _McpBridge:
    """Ek background event loop jisme MCP stdio session zinda rehti hai."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: Optional[BaseException] = None
        self._session = None
        self._stack = None

        self._thread = threading.Thread(
            target=self._run_loop, name="mcp-bridge", daemon=True
        )
        self._thread.start()

        # Daemon thread isliye ki ye process ko zinda na rakhe. Uvicorn ke band
        # hone par is session ka bhi khatam ho jaana hi sahi hai.
        if not self._ready.wait(timeout=30):
            raise McpUnavailable("MCP server did not start within 30s")
        if self._error:
            raise McpUnavailable(f"MCP session failed to start: {self._error}")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._open())
        # Session khulne ke baad loop chalta rehta hai taaki wo zinda rahe.
        self._loop.run_forever()

    async def _open(self) -> None:
        try:
            from contextlib import AsyncExitStack

            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            self._stack = AsyncExitStack()
            params = StdioServerParameters(
                command=_SERVER_CMD[0],
                args=_SERVER_CMD[1:],
                env=dict(os.environ),
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self._session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
            log.info("MCP session ready — database access is going through tools.")
        except BaseException as exc:  # noqa: BLE001 — reported to the caller thread
            self._error = exc
        finally:
            self._ready.set()

    def call(self, tool: str, args: dict[str, Any], timeout: float = 30.0) -> Any:
        """Tool ko sync taraf se bulata hai aur JSON-decoded result deta hai."""
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool, args), self._loop
        )
        result = future.result(timeout=timeout)

        # MCP tool results content blocks ki list hote hain. Hamare tools ek
        # single JSON text block dete hain, par defensively padhte hain: agar
        # server kabhi shape badle to yahan saaf error aana chahiye, silently
        # `None` nahi.
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                return json.loads(text)
        raise McpUnavailable(f"Tool {tool} returned no text content")


def get_client() -> Optional["_McpBridge"]:
    """Process-wide bridge, ya `None` agar MCP off hai ya start nahi ho paaya.

    Failure ek hi baar log hoti hai aur uske baad `None` cache ho jaata hai —
    warna har request ek subprocess spawn karne ki koshish karti aur har baar
    30 second rukti.
    """
    global _client

    if not USE_MCP:
        return None
    if _client is not None:
        return _client

    with _lock:
        if _client is not None:
            return _client
        try:
            _client = _McpBridge()
        except Exception as exc:  # noqa: BLE001
            log.warning("MCP unavailable (%s) — falling back to the direct driver.", exc)
            _client = None
            # Dobara koshish na ho isliye toggle yahin off kar dete hain.
            globals()["USE_MCP"] = False
    return _client


def reset_for_tests() -> None:
    """Cached bridge bhool jao — sirf tests ke liye."""
    global _client
    _client = None
