import typing
import asyncio
import logging
import enum
import time

# wsproto
import wsproto
import wsproto.events

from hatsu.types import Scope, Transport, Protocol
from hatsu.utils import get_addr, get_scheme

if typing.TYPE_CHECKING:
    from hatsu.core.server import Server

from urllib.parse import unquote

class WebsocketState(enum.Enum):
    HANDSHAKE = 0
    CONNECTED = 1
    CLOSED = 2

class WSProtoImpl(Protocol):
    """A ws implementation using `asyncio.Protocol`."""

    def __init__(self, server: "Server") -> None:
        self.server = server

        # Logging.
        self.logger = logging.getLogger('hatsu.protocols.websocket_wsproto')

        # Asyncio.
        self.loop = asyncio.get_event_loop()

        # Connection state.
        self.transport = None
        self.peername = None
        self.sockname = None
        self.connection = wsproto.WSConnection(
            wsproto.ConnectionType.SERVER
        )
        self.queue = asyncio.Queue()
        self.handshake_complete = False

        # Send and recv state.
        self.start_end = False
        self.body_end = False
        self.send_close = False
        self.state = WebsocketState.HANDSHAKE

        # Ping control.
        self.last_ping = time.time()

        # Flow control.
        self.write_pause = False
        self.read_pause = False

        # Buffer.
        self.text = ""
        self.bytes = b""

    def connection_made(self, transport: Transport) -> None:
        # When a connection is initialized
        # it save the `transport` to the class
        # so it can be used later.

        self.server.connections.add(self)

        self.transport = transport
        self.schme = get_scheme(self.transport, type="websocket")
        self.peername = get_addr(self.transport, type="peername")
        self.sockname = get_addr(self.transport, type="sockname")

        self.logger.debug('Connection made.')

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        # When a connection is closed
        # it updates the `request` state
        # to `disconnected.`

        self.server.connections.discard(self)
        self.logger.debug("Connection closed.")

        if self.read_pause is True:
            self.read_pause = False
            self.transport.resume_reading()

        self.transport.close()

    def data_received(self, data: bytes) -> None:
        # Called when the packet is complete.

        if len(data) > self.server.ws_max_size:
            raise ValueError("Data is too big.")

        self.connection.receive_data(data)

        def __request__(event: wsproto.events.Request):
            # Called when the request is complete
            # it also build the scope.

            self.handshake_complete = True

            headers = [
                (b"host", event.host.encode("utf-8")),
                *event.extra_headers
            ]
            raw_path, _, query_string = event.target.partition("?")
            self.scope: "Scope" = {
                "type": "websocket",
                "asgi": {
                    "version": "3",
                    "spec_version": "2.3"
                },
                "http_version": "1.1",
                "scheme": self.schme,
                "path": unquote(raw_path),
                "query_string": query_string,
                "root_path": self.server.root_path,
                "headers": headers,
                "client": self.peername,
                "server": self.sockname,
                "subprotocls": event.subprotocols
            }
            message = {
                "type": "websocket.connect"
            }
            self.queue.put_nowait(message)

            if self.server.limit_concurrency is not None:
                if len(self.server.connections) >= self.server.limit_concurrency \
                    or len(self.server.tasks) >= self.server.limit_concurrency:
                        self.logger.warning("Exceeded concurrency limit.")

            self.app = self.server.application

            task = self.loop.create_task(
                self.app(
                    self.scope, self.asgi_recv, self.asgi_send
                )
            )
            task.add_done_callback(self.server.tasks.discard)
            self.server.tasks.add(task)

        def __byte_message__(event: wsproto.events.BytesMessage):
            # Called when the client sends a message.
            self.bytes += event.data

            if event.message_finished is True:
                message = {
                    "type": "websocket.receive",
                    "bytes": self.bytes
                }
                self.queue.put_nowait(message)
                self.bytes = b""

        def __text_message__(event: wsproto.events.TextMessage):
            # Called when the client sends a message.
            self.text += event.data

            if event.message_finished is True:
                message = {
                    "type": "websocket.receive",
                    "text": self.text
                }
                self.queue.put_nowait(message)
                self.text = ""

        def __close__(event: wsproto.events.CloseConnection):
            # Called when the connection is about to close.

            message = {
                "type": "websocket.disconnect",
                "code": event.code
            }
            self.queue.put_nowait(message)
            self.transport.close()

        def __ping__(event: wsproto.events.Ping):
            # Called when the server recv ping.

            if time.time() - (self.last_ping - self.server.ws_ping_interval):
                return

            self.transport.write(
                self.conn.send(event.response())
            )

        def __close__(event: wsproto.events.CloseConnection):
            # Called when the server recv close.

            message = {
                "type": "websocket.disconnect",
                "code": event.code
            }
            self.queue.put_nowait(message)
            self.transport.close()

        handlers = {
            wsproto.events.Request: __request__,
            wsproto.events.TextMessage: __text_message__,
            wsproto.events.BytesMessage: __byte_message__,
            wsproto.events.Ping: __ping__,
            wsproto.events.CloseConnection: __close__,
        }

        for event in self.connection.events():
            event_type = type(event)
            handlers[event_type](event)

    async def asgi_send(self, message):
        # Send interface for the application.

        if self.state is WebsocketState.HANDSHAKE:
            if message["type"] != "websocket.accept":
                # TODO: MAKE IT BETTER.
                raise ValueError("Can't send this message in that state.")

            subprotocls = message.get("subprotocls")
            event = wsproto.events.AcceptConnection(
                subprotocol=subprotocls
            )
            self.transport.write(
                self.connection.send(event=event)
            )
            self.start_end = True
            self.state = WebsocketState.CONNECTED

            self.logger.debug(
                f'Websocket handshake complete. ({self.peername})'
            )

        elif self.state is WebsocketState.CONNECTED:
            if message["type"] not in ("websocket.send", "websocket.close"):
                # TODO: MAKE IT BETTER.
                raise ValueError("Can't send this message in that state.")

            if message["type"] == "websocket.close":
                code, reason = message.get("code"), \
                    message.get("reason", "")
                event = wsproto.events.CloseConnection(
                    code=code, reason=reason
                )
                message = {
                    "type": "websocket.disconnect",
                    "code": code
                }

                self.queue.put_nowait(message)
                if self.transport.is_closing() is False:
                    self.transport.write(
                        self.connection.send(event=event)
                    )
                    self.transport.close()

            if self.transport.is_closing() is False:
                text = message.get('text', None)
                bytes = message.get('bytes', None)

                if text is not None:
                    event = wsproto.events.TextMessage(
                        data=text
                    )
                elif bytes is not None:
                    event = wsproto.events.BytesMessage(
                        data=bytes
                    )

                self.transport.write(
                    self.connection.send(event=event)
                )

    async def asgi_recv(self):
        # Recv interface for the application.

        message = await self.queue.get()
        if self.read_pause is True and self.queue.empty():
            self.read_pause = False
            self.transport.resume_reading()
        return message

    def close_protocol(self):
        # To close the connection when clean up.

        if self.handshake_complete is True:
            message = {"type": "websocket.disconnect", "code": 1012}
            self.queue.put_nowait(message)

            event = wsproto.events.CloseConnection(code=1012)
            self.transport.write(
                self.connection.send(event=event)
            )
        else:
            headers = [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"connection", b"close"),
            ]
            output = self.connection.send(
                wsproto.events.RejectConnection(
                    status_code=500, headers=headers, has_body=True
                )
            )
            output += self.connection.send(
                wsproto.events.RejectData(data=b"Internal Server Error")
            )
            self.transport.write(output)
        self.transport.close()
