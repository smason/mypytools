import argparse
import hashlib
import importlib.util
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Self

from .pathevents import FileChanges


# integration with Matplotlib's event-loop
def _matplotlib_try_get_current_canvas():
    "fetch canvas from currently active figure, if one exists"
    if helper := sys.modules.get("matplotlib._pylab_helpers"):
        if manager := helper.Gcf.get_active():
            return manager.canvas


def _matplotlib_run_event_loop(canvas):
    "block in Matplotlib's event loop"
    if canvas.figure.stale:
        canvas.draw_idle()
    if plt := sys.modules.get("matplotlib.pyplot"):
        plt.show(block=False)
    canvas.start_event_loop()


def _matplotlib_interrupt_event_loop(canvas):
    "stop Matplotlib's running event loop"
    canvas.stop_event_loop()
    try:
        canvas.flush_events()
    except Exception as err:
        print(f"failed to flush matplotlib events: {err}")


def load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ModuleNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


BLOCK_SEP = re.compile(r"^##.*", re.MULTILINE)


def _hashed_blocks(path: Path):
    "iterate over chunks in a file"

    def blocks(source):
        start = 0
        for m in BLOCK_SEP.finditer(source):
            end = m.start(0)
            yield source[start:end]
            start = end
        yield source[start:]

    for block in blocks(path.read_text()):
        buf = block.strip().encode()
        digest = hashlib.blake2b(buf, digest_size=32).digest()
        yield digest, block


def _evaluate(source: str, module: ModuleType) -> None:
    "evaluate source code 'inside' a specified module"
    filename = module.__file__ or "<unknown>"
    globals = vars(module)

    try:
        # possibly use codeop.compile_command for better diagnostics
        code = compile(source, filename, "exec")
        if code is not None:
            exec(code, globals)
    except Exception as err:
        traceback.print_exception(err, limit=0)


@dataclass(slots=True)
class WatchedModule:
    path: Path
    module: ModuleType
    digests: set[bytes]

    @classmethod
    def from_module(cls, module) -> Self:
        path = Path(module.__file__)
        digests = {digest for digest, _ in _hashed_blocks(path)}
        return cls(path, module, digests)

    def run_changed(self):
        processed = set()
        for digest, block in _hashed_blocks(self.path):
            processed.add(digest)
            if digest not in self.digests:
                print(block.rstrip())
                _evaluate(block, self.module)
        self.digests = processed


def parse_args():
    "parse command line arguments"
    parser = argparse.ArgumentParser()
    parser.add_argument("main")
    parser.add_argument("watched", nargs="*")
    parser.add_argument("--name", action="store", default="_kmain_")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    handler: FileChanges[WatchedModule] = FileChanges()

    def add_module(module: ModuleType) -> None:
        value = WatchedModule.from_module(module)
        handler.watch(value.path, value)

    def add_remaining_modules(names: set[str]) -> set[str]:
        remaining = set()
        for name in names:
            if module := sys.modules.get(name):
                add_module(module)
                print(f"module {name!r} loaded from {module.__file__!r}")
            else:
                remaining.add(name)
        return remaining

    add_module(load_module(args.name, args.main))

    if remaining := add_remaining_modules(set(args.watched)):
        lst = ", ".join(map(repr, remaining))
        print(f"warning: these modules haven't been loaded: {lst}")

    def on_value():
        if canvas := _matplotlib_try_get_current_canvas():
            _matplotlib_interrupt_event_loop(canvas)

    def on_idle():
        nonlocal remaining
        if remaining:
            remaining = add_remaining_modules(remaining)
        if canvas := _matplotlib_try_get_current_canvas():
            _matplotlib_run_event_loop(canvas)

    handler.on_idle = on_idle
    handler.on_value = on_value
    handler.start()

    for watched in handler.fetch_paths():
        watched.run_changed()


if __name__ == "__main__":
    main()
