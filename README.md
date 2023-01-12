# Hatsu 🫒
A nice small cute ASGI inspired by `uvicorn` impl using `wsproto` and `h11`

## Quickstart
Installing using pip
```
pip install git+https://github.com/ArtyTheDev/hatsu.git
```
Note: This is just an impl I don't think it's ready I wrote this in 3 days and did take a lot from the `uvicorn` project but did some stuff in my way.

### Example
```py
import hatsu

async def app(scope, receive, send):
    message_type = scope['type']

    if message_type == "http":
        await send({
            'type': 'http.response.start',
            'status': 200,
            'headers': [
                (b'content-type', b'text/plain'),
            ],
        })
        await send({
            'type': 'http.response.body',
            'body': b'Hello, world!',
        })

hatsu.run(app, host="localhost", port=8080, workers=1)
```
this is a simple demo for the application but you can use it using any framework you like such as `fastapi`, `starlette`, `quart`, `tinyws`

### Speedups
you can also speed it up using `uvloop`
```py
import hatsu

hatsu.loops.set_event_loop_policy("uvloop")
```
