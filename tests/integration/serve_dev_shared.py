"""Temporary real shared store for browser tests; no user data or live runtime."""
import functools
import shutil
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.static_ops.dev_projects import SharedProjects  # noqa: E402
from scripts.static_ops.local_runtime import Settings, StaticHandler  # noqa: E402


def main():
    with TemporaryDirectory(prefix="navmate-dev-shared-") as directory:
        root = Path(directory)
        release = root / "published/releases" / ("r-" + "a" * 32)
        shutil.copytree(ROOT / "web/dist-local", release)
        (root / "published/current").symlink_to(release)
        settings = Settings(root / "source", root / "state", root / "published", port=4175)
        projects = SharedProjects(root / "private/projects.sqlite3", {"http://127.0.0.1:4175"})
        with ThreadingHTTPServer(("127.0.0.1", 4175), functools.partial(
                StaticHandler, settings=settings, projects=projects)) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
