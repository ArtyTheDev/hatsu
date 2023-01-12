import typing
import asyncio

# All kind of scopes.
Scope = typing.MutableMapping[str, typing.Any]

# Recv and Send.
Message = typing.MutableMapping[str, typing.Any]
Receive = typing.Callable[[], typing.Awaitable[Message]]
Send = typing.Callable[[Message], typing.Awaitable[None]]

# The main app.
Application = typing.Callable[
    [Scope, Receive, Send],
    typing.Awaitable[None]
]

# Asyncio Protocol.
Transport = asyncio.Transport
Protocol = asyncio.Protocol
