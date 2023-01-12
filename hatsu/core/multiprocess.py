import multiprocessing
import threading
import typing
import socket
import signal
import time
import sys
import os

multiprocessing.allow_connection_pickling()
spawn = multiprocessing.get_context("spawn")

def __target__(target, sockets, stdin):
    # This function is used to run the server.
    if stdin is not None:
        sys.stdin = os.fdopen(stdin)

    target(sockets=sockets)

class Mutliprocessing(object):
    """To handle the mutliprocessing
    """

    def __init__(self, workers: int, sockets: typing.List[socket.socket]):
        self.workers = workers
        self.sockets = sockets
        self.processes = []

        # Exit.
        self.exit_event = threading.Event()

    def init_signals(self):
        # To install the signals to exit when needed.

        def __callback__(sig, frame):
            self.exit_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, __callback__)

    def run(self, target: typing.Callable):
        # Start the process.

        self.init_signals()

        for index in range(self.workers):
            try:
                stdin_fileno = sys.stdin.fileno()
            except OSError:
                stdin_fileno = None

            process = spawn.Process(
                target=__target__,
                kwargs=dict(
                    target=target,
                    sockets=self.sockets,
                    stdin=stdin_fileno
                )
            )

            self.processes.append(process)
            process.start()

        self.exit_event.wait()
        time.sleep(0.1)

        for process in self.processes:
            process.terminate()
            process.join()
