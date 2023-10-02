import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import (
    AsyncIterator,
    Callable,
    Generic,
    Iterator,
    Optional,
    TypeVar,
)

from watchdog.events import FileModifiedEvent, FileMovedEvent, FileSystemEvent
from watchdog.observers import Observer

T = TypeVar("T")


@dataclass(kw_only=True, slots=True)
class Watched:
    watch: object
    files: set[object]


class FileChanges(Generic[T]):
    "Watch a set of Paths for changes"

    # None => shutdown
    queue: Queue[Optional[Path]]
    files: dict[Path, T]
    dirs: dict[Path, Watched]

    # event loop hooks:
    #  on_idle will be called before waiting for changes
    on_idle: Optional[Callable[[], None]]
    #  on_value will be called from a thread to interrupt the event loop
    on_value: Optional[Callable[[], None]]

    def __init__(self) -> None:
        self.watchdog = Observer()
        self.queue = Queue()
        self.files = dict()
        self.dirs = dict()
        self.on_idle = None
        self.on_value = None

    def watch(self, path: Path, value: T) -> Callable[[], None]:
        "watch path for changes yielding value in response"
        if path in self.files:
            raise ValueError(f"{path!r} already being watched")
        self.files[path] = value
        parent = path.parent
        if parent in self.dirs:
            watch = self.dirs[parent]
        else:
            watch = self.dirs[parent] = Watched(
                watch=self.watchdog.schedule(self, parent),
                files=set(),
            )

        myself = object()
        watch.files.add(myself)

        def cleanup() -> None:
            del self.files[path]
            watch.files.remove(myself)
            if watch.files:
                return
            self.watchdog.unschedule(watch.watch)
            del self.dirs[parent]

        return cleanup

    def start(self) -> None:
        self.watchdog.start()

    def shutdown(self) -> None:
        self.watchdog.stop()
        self.queue.put(None)

    def dispatch(self, event: FileSystemEvent) -> None:
        "process an incoming event in worker thread"
        match event:
            case FileModifiedEvent(src_path=name):
                pass
            case FileMovedEvent(dest_path=name):
                pass
            case _:
                return
        path = Path(name)
        if path in self.files:
            if callback := self.on_value:
                callback()
            self.queue.put(path)

    def _fetch_coalesced(self) -> set[Optional[Path]]:
        queue = self.queue
        if callback := self.on_idle:
            callback()
        collection = {queue.get()}
        # wait a bit for more events to be dispatched
        time.sleep(0.01)
        while not queue.empty():
            collection.add(queue.get_nowait())
        return collection

    def fetch_paths(self) -> Iterator[T]:
        "iterate over watches in main thread"
        while True:
            for key in self._fetch_coalesced():
                if key is None:
                    return
                yield self.files[key]

    async def afetch_paths(self) -> AsyncIterator[T]:
        loop = asyncio.get_running_loop()
        while True:
            for key in await loop.run_in_executor(None, self._fetch_coalesced):
                if key is None:
                    return
                yield self.files[key]
