import typing
import asyncio
import logging
import functools
import socket
import signal
import threading
import platform
import ssl
import os

from hatsu.types import Application
from hatsu.protocols import (
    H11ImplProtocol, WSProtoImpl
)
from hatsu.lifespan import LifespanImpl
from hatsu.utils import import_from_string

logging.getLogger("asyncio").setLevel(logging.WARNING)


class Server(object):
    """A server class for initialize all the classes."""

    # HTTP.
    h11_class: typing.Type[H11ImplProtocol] = H11ImplProtocol
    ws_class: typing.Type[WSProtoImpl] = WSProtoImpl

    def __init__(
        self,
        application: Application,
        host: str,
        port: int,
        ws_max_size: int = 16 * 1024 * 1024,
        ws_ping_interval: int = 20.0,
        root_path: str = "",
        backlog: int = 2048,
        limit_concurrency: typing.Optional[int] = None,
        support_lifespan: typing.Optional[bool] = True,
        fd: typing.Optional[int] = None,
        uds: typing.Optional[str] = None,
        headers: typing.Optional[typing.List[typing.Tuple[str, str]]] = None,
        ssl: typing.Optional[ssl.SSLContext] = None,
        max_incomplete_event_size: int = 16 * 1024,
        workers: int = 2
    ) -> None:
        # The a p p l i c a t i o n.
        self.application = application
        self.workers = workers

        # Serving.
        self.host = host
        self.port = port
        self.servers: typing.List[asyncio.Server] = []
        self.backlog = backlog
        self.limit_concurrency = limit_concurrency
        self.max_incomplete_event_size = max_incomplete_event_size

        # Unix.
        self.fd = fd
        self.uds = uds
        self.ssl = ssl

        # HTTP settings.
        self.root_path = root_path
        self.headers = headers

        # Websocket settings.
        self.ws_max_size = ws_max_size
        self.ws_ping_interval = ws_ping_interval

        # Stats.
        self.connections = set()
        self.tasks = set()
        self.started = False

        # Other.
        self.support_lifespan = support_lifespan
        self.exit = False

        # Logging.
        self.logger = logging.getLogger('hatsu.server')

    def init_singals(self):
        """Init the singals handlers."""

        if threading.current_thread() is not threading.main_thread():
            return

        def __sig_callback__(sig, frame):
            self.exit = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, __sig_callback__)

    async def clean_up(self, sockets: typing.Optional[typing.List[socket.socket]] = None):
        """Method used to clean up everything before leaving."""

        if sockets is not None:
            for skt in sockets:
                skt.close()

        for server in self.servers:
            try:
                server.close()
            except Exception:
                pass

        for connection in self.connections:
            connection.close_protocol()

    def run(self, sockets: typing.Optional[typing.List[socket.socket]] = None) -> None:
        """Run the application."""

        if isinstance(self.application, str):
            self.application = import_from_string(self.application)

        self.lifespan = LifespanImpl(self)
        self.loop = asyncio.get_event_loop()

        async def __serve__():

            if self.support_lifespan is True:
                await self.lifespan.startup()

                if self.lifespan.startup_failed:
                    return

            protocol = functools.partial(
                self.h11_class, server=self
            )

            if sockets is not None:
                for skt in sockets:
                    if self.workers > 1 and platform.system() == "Windows":
                        from socket import fromshare

                        skt = fromshare(
                            skt.share(os.getpid())
                        )

                    server = await self.loop.create_server(
                        protocol, backlog=self.backlog, ssl=self.ssl, sock=skt
                    )
                    self.servers.append(server)
            elif self.fd is not None:
                skt = socket.fromfd(self.fd, socket.AF_UNIX, socket.SOCK_STREAM)
                server = await self.loop.create_server(
                    protocol, backlog=self.backlog, ssl=self.ssl,
                    sock=skt
                )
                self.servers = [server]
            elif self.uds is not None:
                uds_perms = 0o666
                if os.path.exists(self.uds):
                    uds_perms = os.stat(self.uds).st_mode

                server = await self.loop.create_unix_server(
                    protocol, path=uds_perms, ssl=self.ssl,
                    backlog=self.backlog
                )
                self.servers = [server]
            else:
                server = await self.loop.create_server(
                    protocol, self.host, self.port,
                    backlog=self.backlog, ssl=self.ssl
                )
                self.servers = [server]
                self.started = True

            self.logger.debug("Server started.")
            while not self.exit:
                await asyncio.sleep(0.1)

            await self.clean_up(sockets=sockets)
            if self.support_lifespan is True:
                await self.lifespan.shutdown()

        self.init_singals()
        self.loop.run_until_complete(__serve__())
