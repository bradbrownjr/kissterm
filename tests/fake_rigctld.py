"""A fake `rigctld` for tests: the Extended Response Protocol subset kissterm
speaks (`+f`, `+m`, `+t`, `+l SWR`, `+F`, `+M`, `+T`, `+U`, `+G`, `+U ?`, `+G ?`,
`+\\chk_vfo`). The `?` replies are `rigctl_parse.c`'s: the header, one line
of names, `RPRT 0`.

State lives on the instance so a test can watch what a client changed, and
`swr` may be a list the server walks through, one reading per `l SWR`."""

from __future__ import annotations

import asyncio


class FakeRigctld:
    def __init__(self) -> None:
        self.frequency = 7101500
        self.mode = "USB"
        self.passband = 2400
        self.ptt = 0
        self.swr: list[float] = [1.2]
        self.tuner = 0
        #: What `U ?` and `G ?` list; an ATU cycle keys for `tune_seconds`.
        self.funcs = {"TUNER", "VOX"}
        self.ops = {"TUNE", "CPY"}
        self.tune_seconds = 0.2
        self.tunes = 0
        self.fail: dict[str, int] = {}  # command letter -> RPRT code
        self.silent: set[str] = set()   # commands that never answer
        self.log: list[str] = []
        self.connections = 0
        self.server: asyncio.AbstractServer | None = None
        self.port = 0

    async def start(self) -> "FakeRigctld":
        self.server = await asyncio.start_server(self._client, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        # Python 3.12+ `wait_closed` waits for every client; close them first.
        self.drop_clients()
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    def drop_clients(self) -> None:
        for writer in list(getattr(self, "_writers", [])):
            writer.close()

    async def _client(self, reader, writer) -> None:
        self.connections += 1
        self._writers = getattr(self, "_writers", [])
        self._writers.append(writer)
        try:
            while line := await reader.readline():
                text = line.decode().strip()
                self.log.append(text)
                reply = self._answer(text)
                if reply is not None:
                    writer.write(reply.encode())
                    await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    def _answer(self, text: str) -> str | None:
        assert text.startswith("+"), "kissterm must use the extended protocol"
        command, _, rest = text[1:].partition(" ")
        if command in self.silent:
            return None
        if command in self.fail:
            return f"RPRT {self.fail[command]}\n"
        if command == "f":
            return f"get_freq:\nFrequency: {self.frequency}\nRPRT 0\n"
        if command == "m":
            return f"get_mode:\nMode: {self.mode}\nPassband: {self.passband}\nRPRT 0\n"
        if command == "t":
            return f"get_ptt:\nPTT: {self.ptt}\nRPRT 0\n"
        if command == "l" and rest == "SWR":
            value = self.swr.pop(0) if len(self.swr) > 1 else self.swr[0]
            return f"get_level: SWR\nLevel Value: {value}\nRPRT 0\n"
        if command == "U" and rest == "?":
            return f"set_func: ?\n{' '.join(sorted(self.funcs))}\nRPRT 0\n"
        if command == "G" and rest == "?":
            return f"vfo_op: ?\n{' '.join(sorted(self.ops))}\nRPRT 0\n"
        if command == "\\chk_vfo":
            return "ChkVFO: 0\n"  # no header, no RPRT: rigctl_parse.c, cmd 0xf0
        if command == "F":
            self.frequency = int(float(rest))
        elif command == "M":
            self.mode, self.passband = rest.split()[0], int(rest.split()[1])
        elif command == "T":
            self.ptt = int(rest)
        elif command == "U" and rest.startswith("TUNER"):
            self.tuner = int(rest.split()[1])
        elif command == "G" and rest == "TUNE":
            # The rig keys a carrier for the cycle, then drops it by itself.
            self.tunes += 1
            self.ptt = 1
            asyncio.get_running_loop().call_later(self.tune_seconds, setattr, self, "ptt", 0)
        else:
            return "RPRT -4\n"
        return f"set: {rest}\nRPRT 0\n"
