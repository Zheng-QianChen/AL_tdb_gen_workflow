"""Browser launcher; pass --desktop for the optional pywebview window."""
import argparse
import threading
import time
import uvicorn
from app import app, serve
from config import HOST, PORT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop", action="store_true", help="Open an optional pywebview window")
    options = parser.parse_args()
    if not options.desktop:
        serve()
        return
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("Desktop mode needs pywebview: pip install pywebview") from exc
    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{PORT}"
    try:
        for _ in range(100):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError("Backend failed to start")
            time.sleep(.1)
        else:
            raise RuntimeError("Backend did not become ready")
        webview.create_window("AL TDB Generator", url)
        webview.start()
    finally:
        server.should_exit = True
        thread.join()


if __name__ == "__main__":
    main()
