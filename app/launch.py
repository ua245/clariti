import threading
import time
import urllib.request
import webbrowser

import uvicorn

from app.config import HOST, PORT
from app.security_runtime import bootstrap_security_checks


def open_browser_after_startup() -> None:
    # Loopback-only UI; never advertise on LAN / public-private network profiles.
    health_url = f"http://{HOST}:{PORT}/health"
    for _ in range(40):
        try:
            with urllib.request.urlopen(health_url, timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(f"http://{HOST}:{PORT}/")
                    return
        except OSError:
            time.sleep(0.25)


def main() -> None:
    bootstrap_security_checks()
    threading.Thread(target=open_browser_after_startup, daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT)


if __name__ == "__main__":
    main()
