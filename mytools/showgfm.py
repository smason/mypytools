import asyncio
import html
import json
import logging
from pathlib import Path
from string import Template
from typing import Callable
from weakref import WeakSet

import cmarkgfm
import nh3
from aiohttp import WSCloseCode, WSMsgType, web
from watchdog.events import FileModifiedEvent, FileMovedEvent, FileSystemEvent
from watchdog.observers import Observer

CLOSE_MSG_TYPES = WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED

ROOT = Path.cwd()
observer = None
needles: dict[str, set[Callable]] = {}

logger = logging.getLogger(__name__)


class RootHandler:
    def dispatch(self, event: FileSystemEvent):
        match event:
            case FileModifiedEvent(src_path=path) if path in needles:
                pass
            case FileMovedEvent(dest_path=path) if path in needles:
                pass
            case _:
                return
        for fn in needles.pop(path):
            try:
                fn()
            except Exception:
                logger.exception("running %s failed", fn)


def add_watch(path: Path, callback: Callable) -> Callable[[], None]:
    global observer
    if not observer:
        observer = Observer()
        observer.schedule(RootHandler(), ROOT, recursive=True)
        observer.start()

    pathstr = str(path)
    if existing := needles.get(pathstr):
        existing.add(callback)
    else:
        needles[pathstr] = existing = {callback}

    def cleanup():
        existing.discard(callback)

    return cleanup


def resolve(path: str) -> Path:
    resolved = Path(path.lstrip("/")).resolve()
    if not resolved.is_relative_to(ROOT):
        logger.warning("client has a malformed url %r", path)
        raise IOError("Trying to escape from root")
    return resolved


async def render_markdown(request: web.Request) -> web.Response:
    tail = request.match_info["tail"]
    try:
        text = resolve(tail).read_text()
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


async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    path = resolve(request.match_info["tail"])

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    loop = asyncio.get_running_loop()

    def reload():
        def tramp():
            loop.create_task(ws.send_str("reload"))

        loop.call_soon_threadsafe(tramp)

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


def tree_handler(request: web.Request) -> web.Response:
    path = resolve(request.match_info["tail"])

    router = request.app.router
    tree_router = router["tree"]
    md_router = router["markdown"]

    if not path.is_dir():
        target = path.parent
        tail = "" if target == ROOT else f"{target.relative_to(ROOT)}/"
        raise web.HTTPFound(tree_router.url_for(tail=tail))

    def is_visible(child: Path):
        return not child.name.startswith(".")

    def key_type_date(child: Path):
        stat = child.stat()
        return child.is_dir(), stat.st_mtime

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


def make_redirecter(target: str):
    async def handler(request: web.Request):
        raise web.HTTPFound(location=target)

    return handler


async def on_shutdown(app):
    websockets = app["websockets"]
    if not websockets:
        return
    logging.info(f"shutting down {len(websockets)} websockets")
    for ws in set(websockets):
        await ws.close(code=WSCloseCode.GOING_AWAY, message="Server shutdown")


def main():
    routes = [
        web.get("/", make_redirecter("/tree/")),
        web.get("/tree/{tail:.*}", tree_handler, name="tree"),
        web.get("/md/{tail:.*}", render_markdown, name="markdown"),
        web.get("/ws/{tail:.*}", websocket_handler),
    ]
    template = Path(__file__).parent / "showgfm.html"
    app = web.Application()
    app["websockets"] = WeakSet()
    app["template"] = Template(template.read_text())
    app.on_shutdown.append(on_shutdown)
    app.add_routes(routes)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(main())
