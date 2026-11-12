"""Start the portal:  python run.py"""
import webbrowser
import threading

import uvicorn

from app import config

if __name__ == "__main__":
    url = f"http://{config.HOST}:{config.PORT}"
    print(f"\n  Wealth Portal running at {url}  (Ctrl+C to stop)\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")
