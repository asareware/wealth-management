"""Start the portal:  python run.py

Locally it opens your browser at http://127.0.0.1:8765.
On Azure App Service this is also the startup command; there it listens on 0.0.0.0:8000
and does not try to open a browser.
"""
import threading
import webbrowser

import uvicorn

from app import config

if __name__ == "__main__":
    if config.ON_AZURE:
        print(f"Wealth Portal starting on App Service, port {config.PORT}, data in {config.DATA_DIR}")
    else:
        url = f"http://{config.HOST}:{config.PORT}"
        print(f"\n  Wealth Portal running at {url}  (Ctrl+C to stop)\n")
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # One process only: the SQLite database and the background bank sync both assume a single worker.
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT,
                log_level="info" if config.ON_AZURE else "warning",
                proxy_headers=config.ON_AZURE, forwarded_allow_ips="*" if config.ON_AZURE else None)
