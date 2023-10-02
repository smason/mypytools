import asyncio
import hashlib
import html
import json
import logging
from pathlib import Path
from string import Template
from typing import Awaitable, Callable, NoReturn
from weakref import WeakSet

import cmarkgfm
import nh3
from aiohttp import WSCloseCode, WSMsgType, web

from .pathevents import FileChanges

CLOSE_MSG_TYPES = WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED

AsyncPathCallback = Callable[[str], Awaitable[None]]


class Rendered:
    subscribed: set[AsyncPathCallback]
    cleanup: Callable[[], None]

    def __init__(self, path: Path):
        self.path = path
        self.digest = digest_file(path)
        self.subscribed = set()

    async def process(self):
        try:
            digest = digest_file(self.path)
            if digest == self.digest:
                return
            self.digest = digest
            markdown = self.path.read_text()
        except IOError:
            # ignore reloading for now in the hope that it sorts itself out
            # again
            return
        rendered = render_markdown(markdown)
        for sub in self.subscribed:
            await sub(rendered)


ROOT = Path.cwd()
observer: FileChanges[Rendered] = None
responders: dict[Path, Rendered] = {}

logger = logging.getLogger(__name__)


async def _dequeue() -> None:
    "move sync world to async world"

    async for ren in observer.afetch_paths():
        try:
            await ren.process()
        except Exception:
            logger.exception("processing %s failed", ren)


def add_watch(path: Path, callback: AsyncPathCallback) -> Callable[[], None]:
    global observer
    if observer is None:
        observer = FileChanges()
        observer.start()
        asyncio.create_task(_dequeue())

    if not (existing := responders.get(path)):
        responders[path] = existing = Rendered(path)
        existing.cleanup = observer.watch(path, existing)

    existing.subscribed.add(callback)

    def cleanup() -> None:
        existing.subscribed.discard(callback)
        if existing.subscribed:
            return
        del responders[path]
        existing.cleanup()

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


def render_markdown(markdown: str) -> str:
    body = cmarkgfm.github_flavored_markdown_to_html(
        markdown,
        cmarkgfm.Options.CMARK_OPT_UNSAFE,
    )
    return nh3.clean(body)


async def handle_markdown(request: web.Request) -> web.Response:
    tail = request.match_info["tail"]
    path = resolve_file(request, tail)
    try:
        text = path.read_text()
    except IOError:
        raise web.HTTPNotFound()
    args = {
        "websocket": json.dumps(f"ws://{request.host}/ws/{tail}"),
        "title": html.escape(tail),
        "body": render_markdown(text),
    }
    text = request.app["template"].substitute(args)
    return web.Response(text=text, content_type="text/html")


def digest_file(path):
    hash = hashlib.sha256()
    with open(path, "rb") as fd:
        while buf := fd.read(1024 * 1024):
            hash.update(buf)
    return hash.digest()


async def handle_websocket(request: web.Request) -> web.WebSocketResponse:
    path = resolve_file(request, request.match_info["tail"])

    ws = web.WebSocketResponse()
    unwatch = add_watch(path, ws.send_str)

    try:
        await ws.prepare(request)
    except Exception:
        unwatch()
        raise

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
    observer.shutdown()
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
