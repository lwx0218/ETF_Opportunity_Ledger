"""python -m src.web：默认隔离演示；readonly / market 不初始化演示库。"""
import argparse

from src.ledger.store import ROOT
from .application import Application
from .server import create_server, validate_binding


def main():
    parser = argparse.ArgumentParser(description="ETF 前向机会台账 · 本机预览")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1", help="监听 IPv4 地址，默认仅本机")
    parser.add_argument("--public-host", help="额外允许的明确 IPv4 Host（不含端口）")
    parser.add_argument("--demo-only", action="store_true", help="仅合成演示，禁止正式入口与行情/规则读取")
    parser.add_argument("--mode", choices=("demo", "readonly", "market"), default="demo")
    parser.add_argument("--demo-dir", type=str, default=str(ROOT / "outputs" / "app-demo"))
    args = parser.parse_args()
    try:
        validate_binding(args.host, args.public_host, args.demo_only, mode=args.mode)
        app = Application(args.demo_dir, mode=args.mode, demo_only=args.demo_only)
    except ValueError as err:
        parser.error(str(err))
    with create_server(app, args.port, host=args.host, public_host=args.public_host) as server:
        print(f"ETF 机会台账：http://{args.public_host or args.host}:{server.server_port} · "
              f"{'demo-only' if args.demo_only else args.mode}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
