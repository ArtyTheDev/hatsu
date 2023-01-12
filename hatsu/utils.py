import importlib
import typing
import socket
import ssl
import os

from hatsu.types import Transport

def get_scheme(transport: Transport, type: str = "http") -> str:
    """A method used to get the scheme of the request."""

    ssl_context = transport.get_extra_info("sslcontext")

    if ssl_context is True:
        return "https" if type == "http" else "wss"

    return "http" if type == "http" else "ws"

def get_addr(transport: Transport, type: str = "peername") -> typing.List[str]:
    """A method used to get the addr of the trasnport."""

    trasnport_socket: socket.socket = transport.get_extra_info('socket', None)

    if trasnport_socket is not None:
        methods = {
            "peername": trasnport_socket.getpeername,
            "sockname": trasnport_socket.getsockname
        }

        info = methods[type]()
        return str(info[0]), int(info[1])

    trasnport_val: typing.Tuple[str, str] = transport.get_extra_info(type, None)
    if trasnport_val is not None:
        return str(trasnport_val[0]), int(trasnport_val[1])

def should_upgradge(headers) -> typing.Optional[str]:
    """See if it should upgrade to websocket"""
    connections = []
    upgrade = None

    for key, value in headers:
        if key == b"connection":
            connections = [
                token.lower().strip() for token in value.split(b",")
            ]
        if key == b"upgrade":
            upgrade = value

    if b"upgrade" in connections:
        return upgrade

    return None

def create_ssl(
    keyfile: typing.Optional[str],
    certfile: typing.Optional[typing.Union[str, os.PathLike]],
    keyfile_password: typing.Optional[str],
    version: int,
    cert_reqs: int,
    ca_certs: typing.Optional[str],
    ciphers: str,
) -> ssl.SSLContext:
    """Create a ssl context."""

    ctx = ssl.SSLContext(version)

    ctx.load_cert_chain(
        certfile=certfile,
        keyfile=keyfile,
        password=keyfile_password
    )
    ctx.verify_mode = ssl.VerifyMode(cert_reqs)
    if ca_certs:
        ctx.load_cert_chain(ca_certs)
    if ciphers:
        ctx.set_ciphers(ciphers)
    return ctx

def create_socket(host=None, port=None, fd=None, uds=False):
    if fd is not None:
        skt = socket.fromfd(
            fd, family=socket.AF_UNIX, type=socket.SOCK_STREAM
        )
    elif uds is not None:
        skt = socket.socket(
            family=socket.AF_UNIX, type=socket.SOCK_STREAM
        )
        try:
            skt.bind(uds)
            os.chmod(fd, 0o666)
        except OSError as e:
            print(e)
    else:
        skt = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
        skt.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR, 1)
        try:
            skt.bind((host, port))
        except OSError as e:
            print("error")

    skt.set_inheritable(True)
    return skt

def import_from_string(import_str):
    """Parse the import string."""
    module_str, attrs_str = import_str.split(":")
    if not module_str or not attrs_str:
        pass

    instance = importlib.import_module(module_str)
    try:
        for attr_str in attrs_str.split("."):
            instance = getattr(instance, attr_str)
    except AttributeError:
        pass

    return instance
