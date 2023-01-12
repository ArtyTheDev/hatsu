import typing
import signal
import sys

from gunicorn.workers.base import Worker
from gunicorn.arbiter import Arbiter
from hatsu.core.server import Server

class HatsuWorker(Worker):
    """A worker class for gunicorn."""

    def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
        super(HatsuWorker, self).__init__(*args, **kwargs)

    def init_signals(self):
        for sig in self.SIGNALS:
            signal.signal(sig, signal.SIG_DFL)

        signal.signal(signal.SIGUSR1, self.handle_usr1)
        signal.siginterrupt(signal.SIGUSR1, False)

    def run(self):
        async def __serve__() -> None:
            server = Server(**self.cfg)
            server.run(sockets=self.sockets)
            if server.started is False:
                sys.exit(Arbiter.WORKER_BOOT_ERROR)
