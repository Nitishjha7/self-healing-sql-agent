"""MCP client — reaches the database through tool calls to a subprocess server.

**The real engineering problem here is not transport, it is bridging two worlds.**
The MCP Python SDK is async and keeps its stdio session inside a long-lived
`async with` block. Our graph nodes are sync (they run under the sync `invoke` of
LangGraph, which FastAPI calls on a threadpool). There were three ways across:

1. **`asyncio.run()` per call** — easiest, and worst: every SQL query would spawn
   a fresh Python subprocess, ~200-300ms of pure process startup.
2. **Make the whole stack async** — graph nodes, FastAPI handlers, everything.
   Correct, but a rewrite of the entire agent for the sake of one MCP toggle.
3. **A background thread with its own event loop** that keeps the session alive,
   with sync callers submitting work to it. This is what was chosen.

The session opens once and stays alive for the life of the process. The sync side
submits calls with `asyncio.run_coroutine_threadsafe` and waits for the result -
so the caller never notices there is an event loop behind it.

**This entire file is the real cost of MCP**, and it is why `USE_MCP` defaults to
off: a direct driver call will always be faster. The benefit of MCP is not speed
- it is that data access becomes a **swappable, standard interface**.
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

# The server is launched as a module rather than by path, which removes any
# dependency on the working directory or the file layout.
_SERVER_CMD = [sys.executable, "-m", "mcp_server.server"]

_client: Optional["_McpBridge"] = None
_lock = threading.Lock()


class McpUnavailable(RuntimeError):
    """The session never started — the caller should fall back to the direct driver."""


class _McpBridge:
    """A background event loop that keeps the MCP stdio session alive."""

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

        # A daemon thread, so it never keeps the process alive. When uvicorn shuts
        # down, this session should end with it.
        if not self._ready.wait(timeout=30):
            raise McpUnavailable("MCP server did not start within 30s")
        if self._error:
            raise McpUnavailable(f"MCP session failed to start: {self._error}")

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._open())
        # Once the session is open the loop keeps running so it stays alive.
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

    def call(self, tool: str, args: dict[str, Any], timeout: float = 30.0) -> str:
        """Call a tool from the sync side and return its text content.

        **Nothing is JSON-decoded here, deliberately.** The first version did, and
        it broke on `describe_schema` — which returns plain text, not JSON. The
        transport should not decide what shape a tool payload has; the caller
        knows that. This layer only moves bytes.
        """
        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(tool, args), self._loop
        )
        result = future.result(timeout=timeout)

        # MCP tool results are a list of content blocks. Our tools return a single
        # text block, but this reads defensively: if the server ever changes shape,
        # the failure here should be a clear error, not a silent `None`.
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                return text
        raise McpUnavailable(f"Tool {tool} returned no text content")


def get_client() -> Optional["_McpBridge"]:
    """The process-wide bridge, or `None` if MCP is off or failed to start.

    The failure is logged once and `None` is cached afterwards, otherwise every
    request would try to spawn a subprocess and block for 30 seconds each time.
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
            # Turn the toggle off here so nothing retries.
            globals()["USE_MCP"] = False
    return _client


def reset_for_tests() -> None:
    """Forget the cached bridge — for tests only."""
    global _client
    _client = None
