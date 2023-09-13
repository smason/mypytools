import asyncio
import html
import json
import logging
from pathlib import Path
from queue import Queue
from string import Template
from typing import AsyncIterator, Awaitable, Callable, NoReturn
from weakref import WeakSet

import cmarkgfm
import nh3
from aiohttp import WSCloseCode, WSMsgType, web
from watchdog.events import FileModifiedEvent, FileMovedEvent, FileSystemEvent
from watchdog.observers import Observer

CLOSE_MSG_TYPES = WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED

AsyncPathCallback = Callable[[str], Awaitable[None]]

ROOT = Path.cwd()
observer = None
needles: dict[str, set[AsyncPathCallback]] = {}
queue: Queue[str | None] = Queue()

logger = logging.getLogger(__name__)


class RootHandler:
    def dispatch(self, event: FileSystemEvent) -> None:
        match event:
            case FileModifiedEvent(src_path=path):
                queue.put(path)
            case FileMovedEvent(dest_path=path):
                queue.put(path)


async def _dequeue(loop: asyncio.AbstractEventLoop) -> None:
    "move sync world to async world"

    async def asyncify() -> AsyncIterator[str | None]:
        while True:
            yield await loop.run_in_executor(None, queue.get)
            # TODO: check if run_in_executor is slow
            # assuming run_in_executor is slow, we want to batch calls up, so
            # fetch anything already added to the queue
            while not queue.empty():
                yield queue.get_nowait()

    async for path in asyncify():
        # None is passed to shutdown
        if path is None:
            break
        # is anybody interested
        if not (fns := needles.get(path)):
            continue
        for fn in fns:
            try:
                await fn(path)
            except Exception:
                logger.exception("running %s failed", fn)


def add_watch(path: Path, callback: AsyncPathCallback) -> Callable[[], None]:
    global observer
    if not observer:
        observer = Observer()
        observer.schedule(RootHandler(), ROOT, recursive=True)
        observer.start()

        loop = asyncio.get_running_loop()
        loop.create_task(_dequeue(loop))

    pathstr = str(path)
    if existing := needles.get(pathstr):
        existing.add(callback)
    else:
        needles[pathstr] = existing = {callback}

    def cleanup() -> None:
        existing.discard(callback)
        if not existing:
            needles.pop(pathstr)

    return cleanup


def resolve(tail: str) -> Path:
    resolved = Path(tail.lstrip("/")).resolve()
    if not resolved.is_relative_to(ROOT):
        logger.warning("client has a malformed url %r", tail)
        raise web.HTTPForbidden()
    if not resolved.exists():
        raise web.HTTPNotFound()
    return resolved


def resolve_file(request: web.Request, tail: str) -> Path:
    path = resolve(tail)
    if path.is_dir():
        redirect(request, "tree", tail=tail)
    if not path.is_file():
        raise web.HTTPForbidden()
    return path


async def handle_markdown(request: web.Request) -> web.Response:
    tail = request.match_info["tail"]
    path = resolve_file(request, tail)
    try:
        text = path.read_text()
    except IOError:
        raise web.HTTPNotFound()
    options = cmarkgfm.Options.CMARK_OPT_UNSAFE
    body = cmarkgfm.github_flavored_markdown_to_html(text, options)
    args = {
        "websocket": json.dumps(f"ws://{request.host}/ws/{tail}"),
        "title": html.escape(tail),
        "body": nh3.clean(body),
    }
    text = request.app["template"].substitute(args)
    return web.Response(text=text, content_type="text/html")


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    path = resolve_file(request, request.match_info["tail"])

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async def reload(path: str) -> None:
        await ws.send_str("reload")

    unwatch = add_watch(path, reload)

    websockets = request.app["websockets"]
    websockets.add(ws)

    try:
        msg = await ws.receive()
        if msg.type not in CLOSE_MSG_TYPES:
            logging.warning("expecting a close message, not %r", msg)
    finally:
        websockets.discard(ws)
        unwatch()

    return ws


async def handle_tree(request: web.Request) -> web.Response:
    path = resolve(request.match_info["tail"])

    if not path.is_dir():
        target = path.parent
        tail = "" if target == ROOT else f"{target.relative_to(ROOT)}/"
        redirect(request, "tree", tail=tail)

    def is_visible(child: Path) -> bool:
        return not child.name.startswith(".")

    def key_type_date(child: Path) -> tuple[bool, float]:
        stat = child.stat()
        return child.is_dir(), stat.st_mtime

    router = request.app.router
    tree_router = router["tree"]
    md_router = router["markdown"]

    children = list(filter(is_visible, path.iterdir()))
    children.sort(key=key_type_date, reverse=True)
    result = ["<ul>\n"]

    for child in children:
        name = html.escape(child.name)
        rel = child.relative_to(ROOT)
        if child.is_dir():
            url = tree_router.url_for(tail=f"{rel}/")
            result.append(
                f'<li><a href="{url}">dir) {name}/</a>\n',
            )
        else:
            url = md_router.url_for(tail=f"{rel}")
            result.append(
                f'<li><a href="{url}">file) {name}</a>\n',
            )

    result.append("</ul>\n")

    return web.Response(body="".join(result), content_type="text/html")


def redirect(request: web.Request, name: str, **kwds) -> None:
    router = request.app.router[name]
    raise web.HTTPFound(router.url_for(**kwds))


def make_redirecter(
    target: str,
) -> Callable[[web.Request], Awaitable[web.Response]]:
    async def handler(request: web.Request) -> NoReturn:
        raise web.HTTPFound(location=target)

    return handler


async def on_shutdown(app: web.Application) -> None:
    queue.put(None)
    websockets = app["websockets"]
    if not websockets:
        return
    logging.info(f"shutting down {len(websockets)} websockets")
    for ws in set(websockets):
        await ws.close(code=WSCloseCode.GOING_AWAY, message="Server shutdown")


def main() -> None:
    routes = [
        web.get("/", make_redirecter("/tree/")),
        web.get("/tree/{tail:.*}", handle_tree, name="tree"),
        web.get("/md/{tail:.*}", handle_markdown, name="markdown"),
        web.get("/ws/{tail:.*}", handle_websocket),
    ]
    template = Path(__file__).parent / "showgfm.html"
    app = web.Application()
    app["websockets"] = WeakSet()
    app["template"] = Template(template.read_text())
    app.on_shutdown.append(on_shutdown)
    app.add_routes(routes)
    web.run_app(app)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
