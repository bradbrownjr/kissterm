"""A stand-in modem program for the supervisor's tests: listens on a TCP
port, prints a line, and leaves on SIGTERM -- or ignores it, or exits at
once, as told. Run as `python tests/fake_modem.py PORT [options]`."""

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
server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", args.port))
server.listen()
print("fake modem listening", flush=True)
while True:
    conn, _ = server.accept()
    conn.close()
