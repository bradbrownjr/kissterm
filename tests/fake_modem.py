"""A stand-in modem program for the supervisor's tests: listens on a TCP
port, prints a line, and leaves on SIGTERM -- or ignores it, or exits at
once, as told. Run as `python tests/fake_modem.py PORT [options]`.

`--vara` makes it a minimal VARA (EA5HVK's command document): commands on
PORT answered `OK<cr>`, `CONNECT a b` followed by `CONNECTED a b`, and a
data port on PORT+1 -- enough for a VARA transport to open and connect
through a program kissterm stops and starts (the CAT port hand-off)."""

from __future__ import annotations

import argparse
import signal
import socket
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("port", type=int)
parser.add_argument("--ignore-term", action="store_true")
parser.add_argument("--exit-code", type=int, default=None, help="exit at once with this code")
parser.add_argument("--delay", type=float, default=0.0, help="seconds before listening")
parser.add_argument("--vara", action="store_true", help="answer VARA's command set")
args = parser.parse_args()

print("fake modem starting", flush=True)
if args.exit_code is not None:
    print("fake modem failing", file=sys.stderr, flush=True)
    sys.exit(args.exit_code)
if not args.ignore_term:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
else:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(args.delay)
def listen(port: int) -> socket.socket:
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", port))
    sock.listen()
    return sock


def vara_commands(conn: socket.socket) -> None:
    buffer = b""
    while chunk := conn.recv(1024):
        buffer += chunk
        while b"\r" in buffer:
            line, buffer = buffer.split(b"\r", 1)
            words = line.decode().split()
            reply = "OK\r"
            if words[:1] == ["CONNECT"] and len(words) >= 3:
                reply += f"CONNECTED {words[1]} {words[2]}\r"
            elif words == ["DISCONNECT"]:
                reply += "DISCONNECTED\r"
            conn.sendall(reply.encode())


def hold(conn: socket.socket) -> None:
    while conn.recv(1024):
        pass


server = listen(args.port)
data = listen(args.port + 1) if args.vara else None
print("fake modem listening", flush=True)
if data is not None:
    import threading

    def serve_data() -> None:
        while True:
            conn, _ = data.accept()
            threading.Thread(target=hold, args=(conn,), daemon=True).start()

    threading.Thread(target=serve_data, daemon=True).start()
while True:
    conn, _ = server.accept()
    if args.vara:
        threading.Thread(target=vara_commands, args=(conn,), daemon=True).start()
    else:
        conn.close()
