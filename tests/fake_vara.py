"""A fake VARA modem for tests: the command port and data port of EA5HVK's
"VARA Protocol Native TNC Commands" (November 2021; cited in docs/SOURCES.md).

Every command is answered `OK`; `CONNECT a b` is followed by
`CONNECTED a b`, `DISCONNECT` by `DISCONNECTED`. A test sends VARA's own
notifications (`PTT ON`, `PTT OFF`) with `notify`, as VARA does when it
wants the host to key the radio. Lines end in CR, as the document's `<cr>`.
"""

from __future__ import annotations

import asyncio


class FakeVara:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.cmd_port = 0
        self.data_port = 0
        self._servers: list[asyncio.AbstractServer] = []
        self._writer: asyncio.StreamWriter | None = None
        self._data_writers: list[asyncio.StreamWriter] = []

    async def start(self) -> "FakeVara":
        cmd = await asyncio.start_server(self._command, "127.0.0.1", 0)
        data = await asyncio.start_server(self._data, "127.0.0.1", 0)
        self._servers = [cmd, data]
        self.cmd_port = cmd.sockets[0].getsockname()[1]
        self.data_port = data.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        self.drop()
        for server in self._servers:
            server.close()
            await server.wait_closed()

    def drop(self) -> None:
        """Close the command socket, as VARA exiting would."""
        for writer in [self._writer, *self._data_writers]:
            if writer is not None:
                writer.close()
        self._writer = None
        self._data_writers = []

    async def notify(self, line: str) -> None:
        assert self._writer is not None, "nothing is connected to the command port"
        self._writer.write((line + "\r").encode())
        await self._writer.drain()

    async def _data(self, reader, writer) -> None:
        self._data_writers.append(writer)
        try:
            while await reader.read(4096):
                pass
        except ConnectionError:
            pass

    async def _command(self, reader, writer) -> None:
        self._writer = writer
        try:
            while line := await reader.readuntil(b"\r"):
                text = line.decode().strip()
                self.commands.append(text)
                replies = ["OK"]
                if text.startswith("CONNECT "):
                    _, source, target, *_ = text.split()
                    replies.append(f"CONNECTED {source} {target}")
                elif text == "DISCONNECT":
                    replies.append("DISCONNECTED")
                for reply in replies:
                    writer.write((reply + "\r").encode())
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
