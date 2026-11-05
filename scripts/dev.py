"""Start local backend and Vite, and reap both process groups on exit."""

import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent


def main():
    processes = []
    stopping = False

    def stop(signum=None, frame=None):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        processes.append(
            subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "pprouter.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "4000",
                    "--no-access-log",
                ],
                cwd=ROOT,
                start_new_session=True,
            )
        )
        processes.append(
            subprocess.Popen(
                ["npm", "run", "dev", "--", "--host", "127.0.0.1", "--strictPort"],
                cwd=ROOT / "frontend",
                start_new_session=True,
            )
        )
        print("Admin: http://127.0.0.1:5173   API: http://127.0.0.1:4000", flush=True)
        while not stopping and all(p.poll() is None for p in processes):
            time.sleep(0.2)
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


if __name__ == "__main__":
    main()
