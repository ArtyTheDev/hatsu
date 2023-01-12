import typing
import asyncio
import logging

from hatsu.types import Scope
if typing.TYPE_CHECKING:
    from hatsu.core.server import Server

ACCEPT_MESSAGE_TYPES = (
    "lifespan.startup.complete",
    "lifespan.startup.failed",
    "lifespan.shutdown.complete",
    "lifespan.shutdown.failed"
)

class LifespanImpl(object):
    """A lifespan impl for the server."""

    def __init__(self, server: "Server") -> None:
        self.server = server
        self.logger = logging.getLogger("hatsu.lifespan")

        # Events.
        self.loop = asyncio.get_event_loop()
        self.startup_event = asyncio.Event()
        self.shutdown_event = asyncio.Event()
        self.message_queue = asyncio.Queue()

        # Exit.
        self.startup_failed = False
        self.shutdown_failed = False

    # Events.
    async def startup(self) -> None:
        # Start the lifespan function.

        scope: "Scope" = {
            "type": "lifespan",
            "asgi": {
                "version": "3",
                "asgi_spec": "2.0"
            }
        }

        self.loop.create_task(
            self.server.application(
                scope, self.asgi_recv, self.send
            )
        )

        message = {"type": "lifespan.startup"}
        await self.message_queue.put(message)
        # await self.startup_event.wait()

    async def shutdown(self):
        # Startup.
        message = {
            "type": "lifespan.shutdown"
        }
        await self.message_queue.put(message)
        # await self.shutdown_event.wait()

    async def send(self, message) -> None:
        # Lifespan send interface.

        message_type = message["type"]

        if message_type not in ACCEPT_MESSAGE_TYPES:
            raise ValueError("Not a type.")

        # Startup.
        if message_type == "lifespan.startup.complete":
            self.startup_event.set()
        elif message_type == "lifespan.startup.failed":
            self.startup_failed = True
            self.startup_event.set()
            error = message.get('message', "")
            if error != "":
                self.logger.error(error)

        # Shutdown.
        elif message_type == "lifespan.shutdown.complete":
            self.shutdown_event.set()
        elif message_type == "lifespan.shutdown.failed":
            self.shutdown_failed = True
            self.shutdown_event.set()
            error = message.get('message', "")
            if message != "":
                self.logger.error(error)

    async def asgi_recv(self):
        # Interface for recieving.

        return await self.message_queue.get()
