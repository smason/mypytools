import time
from queue import Queue
from pathlib import Path
from typing import Callable, Generic, Iterator, Optional, TypeVar

from watchdog.events import FileModifiedEvent, FileMovedEvent, FileSystemEvent
from watchdog.observers import Observer


T = TypeVar("T")


class FileChanges(Generic[T]):
    "Watch a set of Paths for changes"

    queue: Queue[Path]
    watched: dict[Path, T]
    parents: set[Path]

    # event loop hooks:
    #  on_idle will be called before waiting for changes
    on_idle: Optional[Callable[[], None]]
    #  on_value will be called from a thread to interrupt the event loop
    on_value: Optional[Callable[[], None]]

    def __init__(self) -> None:
        self.watchdog = Observer()
        self.queue = Queue()
        self.watched = dict()
        self.parents = set()
        self.on_idle = None
        self.on_value = None

    def watch(self, path: Path, value: T) -> None:
        "watch path for changes yielding value in response"
        self.watched[path] = value
        parent = path.parent
        if parent not in self.parents:
            self.watchdog.schedule(self, parent)
            self.parents.add(parent)

    def start(self):
        self.watchdog.start()

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
        if path in self.watched:
            if callback := self.on_value:
                callback()
            self.queue.put(path)

    def fetch_paths(self) -> Iterator[T]:
        "iterate over watches in main thread"
        queue = self.queue
        while True:
            if callback := self.on_idle:
                callback()
            collection = {queue.get()}
            # wait a bit for more events to be dispatched
            time.sleep(0.01)
            while not queue.empty():
                collection.add(queue.get_nowait())
            for key in collection:
                yield self.watched[key]
