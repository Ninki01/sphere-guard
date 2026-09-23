import sys
from shared.util.clock import now_local_str


def info(msg: str) -> None:
    print(f"[{now_local_str()}] INFO  {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[{now_local_str()}] WARN  {msg}", flush=True)


def error(msg: str) -> None:
    print(f"[{now_local_str()}] ERROR {msg}", file=sys.stderr, flush=True)
