from __future__ import annotations

import signal
import sys

from .config import load_config
from .server import create_server


def main() -> None:
    config = load_config()
    server = create_server(config)

    def _shutdown(*_args: object) -> None:
        server.shutdown()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
