"""MCP client + Claude loop. Type a command, Claude picks Spotify tools via MCP.

Run:  python agent.py
Later, the ESP32's /voice endpoint will call SpotifyAgent.ask() with the transcript.
"""
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).parent
load_dotenv(HERE / ".env", override=True)

MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
SYSTEM = (
    "You control Spotify for a small voice remote with a tiny OLED screen. "
    "Use the tools to do what the user asks. If they describe a mood or vague "
    "request, pick a sensible search query yourself instead of asking questions. "
    "Your final reply is shown on the OLED: plain text, under 60 characters, "
    "no emojis, no markdown (e.g. 'Playing Blinding Lights')."
)


class SpotifyAgent:
    def __init__(self):
        self.llm = Anthropic()  # uses ANTHROPIC_API_KEY
        self.stack = AsyncExitStack()
        self.session = None
        self.tools = []

    async def start(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(HERE / "spotify_mcp_server.py")],
            env=dict(os.environ),  # pass Spotify credentials to the server process
        )
        read, write = await self.stack.enter_async_context(stdio_client(params))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        listed = await self.session.list_tools()
        self.tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in listed.tools
        ]

    async def ask(self, text: str) -> str:
        messages = [{"role": "user", "content": text}]
        for _ in range(6):  # safety cap on tool-call rounds
            resp = await asyncio.to_thread(
                self.llm.messages.create,
                model=MODEL,
                max_tokens=300,
                system=SYSTEM,
                tools=self.tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                return "".join(b.text for b in resp.content if b.type == "text").strip()

            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                r = await self.session.call_tool(block.name, block.input)
                out = "".join(c.text for c in r.content if getattr(c, "type", "") == "text")
                item = {"type": "tool_result", "tool_use_id": block.id, "content": out}
                if r.isError:
                    item["is_error"] = True
                results.append(item)
            messages.append({"role": "user", "content": results})
        return "Sorry, that took too many steps."

    async def close(self):
        await self.stack.aclose()


async def main():
    agent = SpotifyAgent()
    await agent.start()
    print("Ready. Type a command (e.g. 'play something chill'), or 'quit'.")
    try:
        while True:
            text = (await asyncio.to_thread(input, "> ")).strip()
            if text.lower() in {"quit", "exit"}:
                break
            if text:
                print("->", await agent.ask(text))
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
