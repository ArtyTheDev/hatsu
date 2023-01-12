import typing
import asyncio
import logging
import enum
import http
import h11

from hatsu.types import Scope, Transport, Protocol
from hatsu.utils import get_addr, get_scheme, should_upgradge

if typing.TYPE_CHECKING:
    from hatsu.core.server import Server

from urllib.parse import unquote

class RequestState(enum.Enum):
    """The response needs to start with a `StartReponse`
    and ends with `BodyResponse`
    """

    START = 1
    BODY = 2

class RequestImpl(object):
    """A request implementation for the `h11` lib."""

    def __init__(
        self,
        transport: Transport,
        connection: h11.Connection,
        scope: Scope,
        server: "H11ImplProtocol"
    ) -> None:

        # Init.
        self.transport = transport
        self.connection = connection
        self.scope = scope
        self.server = server

        # Other attrs.
        self.state = RequestState.START
        self.is_disconnected = False
        self.waiting_for_100_continue = None
        self.keep_alive = True

        # Logging.
        self.logger = logging.getLogger('hatsu.RequestImpl')

        # Send function attrs.
        self.response = None
        self.response_complete = False
        self.body_complete = False

        # Recv functino attrs.
        self.body = b""
        self.more_body = True
        self.message_event = asyncio.Event()

    async def asgi_send(self, message):
        # Build the interface for comm with the client.

        message_type = message["type"]

        if self.is_disconnected is True:
            # TODO: Change `ValueError` to something else.
            raise ValueError("Can't send a message to disconnected clients.")

        if self.server.write_pause is True:
            await self.server.write_event.wait()

        if self.state is RequestState.START:
            if message_type != "http.response.start":
                # TODO: Change `ValueError` to something else.
                raise ValueError("Can't send this message along with this state.")

            self.response = message
            self.state = RequestState.BODY

        elif self.state is RequestState.BODY:
            if self.response_complete is False:
                headers, status_code = self.response.get("headers", []), \
                    self.response.get("status", None)

                if status_code is None:
                    raise ValueError("Status can be in a range between 200-1000 not `None`")

                event = h11.Response(
                    headers=headers, status_code=status_code,
                        reason=http.HTTPStatus(status_code).phrase.encode()
                )
                self.transport.write(
                    self.connection.send(event=event)
                )
                self.response_complete = True
                self.waiting_for_100_continue = False

            body, more_body = message.get("body", b""), \
                message.get("more_body", False)

            event = h11.Data(data=body)
            self.transport.write(
                self.connection.send(event=event)
            )

            if not more_body:
                self.body_complete = True
                event = h11.EndOfMessage()
                self.transport.write(
                    self.connection.send(event=event)
                )

        if self.response_complete is True:
            if self.connection.our_state is h11.MUST_CLOSE or not self.keep_alive:
                event = h11.ConnectionClosed()
                output = self.connection.send(event=event)
                self.transport.close()


        if self.response_complete and self.body_complete:
            event = h11.ConnectionClosed()
            self.connection.send(event=event)
            self.transport.close()


    async def asgi_recv(self):
        # An interface for receive data from the client.

        if self.connection.client_is_waiting_for_100_continue \
            and self.transport.is_closing():

            event = h11.InformationalResponse(status_code=100,
                headers=[], reason="Continue")
            self.transport.write(
                self.connection.send(event=event)
            )
            self.waiting_for_100_continue = False

        if not self.response_complete and not self.body_complete:
            await self.message_event.wait()
            self.message_event.clear()

        message = None
        if self.is_disconnected is True:
            message = {"type": "http.disconnect"}
        else:
            message = {
                "type": "http.request",
                "body": self.body,
                "more_body": self.more_body
            }

        if message is None:
            raise ValueError(":)")

        return message

    async def asgi_run(self) -> None:
        # Calls the `application`
        rest = await self.server.app(
            self.scope, self.asgi_recv, self.asgi_send
        )

        if rest is not None:
            self.logger.debug("Application can't return a value.")
        if self.response_complete is False:
            self.logger.debug("Application should send a response.")

            await self.send_error_payload(500, b"Can't leave the connection without payload.")

    async def send_error_payload(self, code: int, body: bytes):
        # Send an error payload.

        await self.asgi_send({
            "type": "http.response.start",
            "status": code,
            "headers": [(b"connection", b"close")],
        })

        await self.asgi_send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

class H11ImplProtocol(Protocol):
    """A http implementation using `asyncio.Protocol`."""

    def __init__(self, server: "Server") -> None:
        self.server = server
        self.logger = logging.getLogger('hatsu.protocols.http_h11')
        self.loop = asyncio.get_event_loop()

        # Connection state.
        self.transport = None
        self.request = None
        self.scheme = None
        self.peername = None
        self.sockname = None
        self.connection = h11.Connection(
            h11.SERVER,
            server.max_incomplete_event_size
        )
        self.is_ws = False

        # State of transport.
        self.read_pause = False
        self.write_pause = False
        self.write_event = asyncio.Event()
        self.write_event.set()

    def connection_made(self, transport: Transport) -> None:
        # When a connection is initialized
        # it save the `transport` to the class
        # so it can be used later.

        self.server.connections.add(self)
        self.transport = transport

        # client addr, server addr and scheme
        self.scheme = get_scheme(self.transport, type="http")
        self.peername = get_addr(self.transport, type="peername")
        self.sockname = get_addr(self.transport, type="sockname")

    def connection_lost(self, exc: typing.Optional[Exception]) -> None:
        # When a connection is closed
        # it updates the `request` state
        # to `disconnected.`

        self.server.connections.discard(self)
        self.logger.debug("Connection closed.")

        if self.request is not None:
            self.request.is_disconnected = True
            self.request.message_event.set()

        if self.read_pause is True:
            self.read_pause = False
            self.transport.resume_reading()

        self.transport.close()

    def data_received(self, data: bytes) -> None:
        # When data get received
        # it pass it into the `connection`
        # then the `connection` gives events
        # which can be used to setup the stuff.

        self.connection.receive_data(data=data)

        def __pasued__(event: h11.PAUSED):
            # Called when the transport should stop reading.

            if not self.read_pause:
                self.read_pause = True
                self.transport.pause_reading()

        def __request__(event: h11.Request):
            # Called when headers, status and path is completed.

            self.logger.debug(
                f'Connection accepted ({self.peername})'
            )

            headers = [
                (key.lower(), value)
                for key, value in event.headers
            ]
            raw_path, _, query_string = event.target.partition(b"?")

            self.scope: "Scope" = {
                "type": "http",
                "asgi": {
                    "version": "3",
                    "spec_version": "2.3"
                },
                "http_version": event.http_version.decode("ascii"),
                "method": event.method.decode("ascii"),
                "scheme": self.scheme,
                "client": self.peername,
                "server": self.sockname,
                "root_path": self.server.root_path,
                "path": unquote(string=raw_path.decode("ascii")),
                "raw_path": raw_path,
                "query_string": query_string,
                "headers": headers
            }

            upgradge = should_upgradge(headers)
            if upgradge == b"websocket" and self.server.ws_class is not None:
                self.server.connections.discard(self)

                self.logger.debug(
                    f'Upgrading to wsproto ({self.peername})'
                )

                output = [event.method, b" ", event.target, b" HTTP/1.1\r\n"]
                for name, value in headers:
                    output += [name, b": ", value, b"\r\n"]
                output.append(b"\r\n")

                proto = self.server.ws_class(
                    server=self.server
                )
                proto.connection_made(self.transport)
                proto.data_received(b"".join(output))
                self.transport.set_protocol(proto)
                self.is_ws = True
                return

            self.request = RequestImpl(
                transport=self.transport,
                connection=self.connection,
                scope=self.scope,
                server=self
            )

            if self.server.limit_concurrency is not None \
                and len(self.server.connections) >= self.server.limit_concurrency:
                    if len(self.server.tasks) >= self.server.limit_concurrency:
                        self.logger.warning("Exceeded concurrency limit.")

            self.app = self.server.application

            task = self.loop.create_task(self.request.asgi_run())
            task.add_done_callback(self.server.tasks.discard)
            self.server.tasks.add(task)

        def __data__(event: h11.Data):
            # Called when the data is completed.

            if self.connection.our_state is h11.DONE:
                return

            self.request.body += event.data
            self.request.message_event.set()

        def __end__(event):
            if self.connection.our_state is h11.DONE:
                self.transport.resume_reading()
                self.connection.start_next_cycle()

            if self.request is not None:
                self.request.more_body = False
                self.request.message_event.set()

        handlers = {
            h11.PAUSED: __pasued__,
            h11.Request: __request__,
            h11.Data: __data__,
            h11.EndOfMessage: __end__,
        }

        while not self.is_ws:
            try:
                event = self.connection.next_event()
            except h11.RemoteProtocolError:
                reason = http.HTTPStatus(200).phrase.encode()
                headers = [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"connection", b"close"),
                ]
                event = h11.Response(status_code=400, headers=headers, reason=reason)
                output = self.connection.send(event)
                self.transport.write(output)
                event = h11.Data(data="Hola".encode("ascii"))
                output = self.connection.send(event)
                self.transport.write(output)
                event = h11.EndOfMessage()
                output = self.connection.send(event)
                self.transport.write(output)
                self.transport.close()

            event_type = type(event)

            if isinstance(event, h11.NEED_DATA):
                break

            if event_type not in handlers:
                return

            handlers[event_type](event)

    def close_protocol(self):
        # To close the connection when clean up.

        if self.request is None or self.request.response_complete:
            event = h11.ConnectionClosed()
            self.connection.send(event=event)
            self.transport.close()
        else:
            self.request.keep_alive = False
