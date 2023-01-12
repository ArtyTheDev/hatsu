import typing
import ssl

from hatsu.core import (
    Server,
    Mutliprocessing
)
from hatsu.types import Application
from hatsu.utils import create_socket

def run(
    application: typing.Union[Application, str],
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
    workers: int = 1
) -> Server:
    """Create a server."""

    config = dict(
        application=application,
        host=host,
        port=port,
        ws_max_size=ws_max_size,
        ws_ping_interval=ws_ping_interval,
        root_path=root_path,
        backlog=backlog,
        limit_concurrency=limit_concurrency,
        support_lifespan=support_lifespan,
        fd=fd,
        uds=uds,
        headers=headers,
        ssl=ssl,
        max_incomplete_event_size=max_incomplete_event_size,
        workers=workers
    )
    server = Server(**config)

    if workers > 1:
        socket = create_socket(host=host, port=port, fd=fd, uds=uds)
        ctx = Mutliprocessing(workers=workers, sockets=[socket])
        ctx.run(server.run)
    else:
        server.run()

    return server
