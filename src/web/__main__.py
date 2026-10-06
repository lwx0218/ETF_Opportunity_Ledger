"""python -m src.web：默认隔离演示；--mode readonly 完全不初始化演示库。"""
import argparse

from src.ledger.store import ROOT
from .application import Application
from .server import create_server


def main():
    parser = argparse.ArgumentParser(description="ETF 前向机会台账 · 本机预览")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mode", choices=("demo", "readonly"), default="demo")
    parser.add_argument("--demo-dir", type=str, default=str(ROOT / "outputs" / "app-demo"))
    args = parser.parse_args()
    app = Application(args.demo_dir, mode=args.mode)
    with create_server(app, args.port) as server:
        print(f"ETF 机会台账：http://127.0.0.1:{server.server_port} · {args.mode}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
