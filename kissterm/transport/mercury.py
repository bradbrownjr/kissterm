"""Mercury HF modem -- its documented VARA-compatible TCP TNC interface.

Mercury v2 provides an ARQ control socket and a separate data socket, using
the same command/data shape as VARA. The upstream manual specifies a
carriage-return-terminated control protocol on the configured base TCP port
(8300 by default), with the raw session byte stream on the next port. It also
documents the commands this transport uses: ``MYCALL``, ``LISTEN``,
``PUBLIC``, ``CONNECT``, ``DISCONNECT``, ``ABORT``, and ``BUFFER`` status
updates. See <https://rhizomatica.github.io/mercury/>.

The over-the-air modem protocol remains Mercury's responsibility. At this
boundary it has already established its ARQ link, so this is a
``SessionTransport`` and intentionally reuses the tested VARA-compatible TNC
implementation rather than inventing a second copy of its control/data socket
lifecycle.
"""

from __future__ import annotations

from .vara import DEFAULT_CONNECT_TIMEOUT, DEFAULT_HIGH_WATER, VaraTransport

#: Mercury's documented ARQ control port. The matching data port is always
#: this value plus one unless an operator explicitly overrides it.
DEFAULT_MERCURY_PORT = 8300


class MercuryTransport(VaraTransport):
    """A Mercury ARQ session through its VARA-compatible TCP TNC interface."""

    kind_name = "mercury"

    def __init__(
        self,
        host: str,
        mycall: str,
        port: int = DEFAULT_MERCURY_PORT,
        data_port: int | None = None,
        listen: bool = True,
        public: bool = True,
        high_water: int = DEFAULT_HIGH_WATER,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        super().__init__(
            host,
            mycall,
            cmd_port=port,
            data_port=port + 1 if data_port is None else data_port,
            bandwidth=None,
            listen=listen,
            public=public,
            high_water=high_water,
            connect_timeout=connect_timeout,
        )
