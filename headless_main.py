import argparse
import asyncio
import logging
import os
import signal
from typing import Sequence

import uvicorn

from api import API
from config.manager import ConfigManager
from drivers.factory import create_driver
from drivers.parallel_manager import ParallelDriversManager
from headless_settings import register_headless_settings_routes
from utils.logger import Logger
from utils.providers_in_parallel import is_parallel_runtime_active


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run IntenseRP Next without the PySide6 desktop UI (headless API runtime)."
        )
    )
    parser.add_argument(
        "--host",
        default=None,
        help="API bind host override. Defaults to config-based host (LAN or localhost).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="API port override. Defaults to configured API port.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--headed",
        action="store_true",
        help="Launch provider browser in headed mode (useful for solving CAPTCHA/login challenges).",
    )
    mode.add_argument(
        "--headless",
        action="store_true",
        help="Force headless browser mode (default behavior).",
    )
    return parser


def _resolve_server_host(config_manager: ConfigManager, override: str | None) -> str:
    if override:
        return str(override)

    available_on_lan = bool(config_manager.get_setting("network_settings", "available_on_lan"))
    return "0.0.0.0" if available_on_lan else "127.0.0.1"


def _resolve_server_port(config_manager: ConfigManager, override: int | None) -> int:
    if override is not None:
        return int(override)

    configured = config_manager.get_setting("network_settings", "port")
    try:
        return int(configured)
    except Exception:
        return 7777


async def _run_headless(argv: Sequence[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(list(argv) if argv is not None else None)
    if args.headed:
        os.environ["IRP_HEADED"] = "1"
    elif args.headless:
        os.environ["IRP_HEADED"] = "0"
        os.environ["IRP_HEADLESS"] = "1"

    config_manager = ConfigManager()

    # Silence uvicorn loggers (same approach as GUI runtime).
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers = [logging.NullHandler()]
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
        logger.disabled = True

    if is_parallel_runtime_active(config_manager):
        driver = ParallelDriversManager(config_manager)
    else:
        driver = create_driver(config_manager)

    host = _resolve_server_host(config_manager, args.host)
    port = _resolve_server_port(config_manager, args.port)

    Logger.info("Starting headless runtime (no PySide6 UI)...")
    await driver.start(status_callback=lambda msg: Logger.info(msg))

    api = API(driver)
    register_headless_settings_routes(api.app, config_manager)
    server = uvicorn.Server(
        uvicorn.Config(
            app=api.app,
            host=host,
            port=port,
            log_level="critical",
            log_config=None,
            access_log=False,
            loop="asyncio",
            http="h11",
        )
    )

    shutdown_event = asyncio.Event()

    def _request_shutdown() -> None:
        if not shutdown_event.is_set():
            shutdown_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except Exception:
            pass

    server_task = asyncio.create_task(server.serve())
    wait_task = asyncio.create_task(shutdown_event.wait())

    Logger.success(f"Headless API running at http://{host}:{port}/v1")

    done, pending = await asyncio.wait(
        {server_task, wait_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if wait_task in done:
        Logger.info("Shutdown signal received, stopping API server...")
        server.should_exit = True

    for task in pending:
        task.cancel()

    try:
        await server_task
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await driver.close()
        except Exception as exc:
            Logger.warning(f"Error while closing driver: {exc}")

    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(_run_headless(argv))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
