from __future__ import annotations

import json
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .replay import list_game_logs, list_tournament_logs, load_events, log_path


class VisualizerServer:
    def __init__(self, host: str, port: int, log_dir: str) -> None:
        self.host = host
        self.port = port
        self.log_dir = log_dir

    def run(self) -> None:
        handler_cls = self._build_handler()
        server = ThreadingHTTPServer((self.host, self.port), handler_cls)
        print(f"Visualizer server on http://{self.host}:{self.port}")
        print(f"Views: /  /table  /arena")
        print(f"Watching logs in {Path(self.log_dir).resolve()}")
        server.serve_forever()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        log_dir = self.log_dir
        static_index = Path(__file__).with_name("static").joinpath("index.html")
        static_table = Path(__file__).with_name("static").joinpath("table.html")
        static_arena = Path(__file__).with_name("static").joinpath("arena.html")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                path = parsed.path.rstrip("/") or "/"
                if path == "/":
                    self._send_index(static_index)
                    return
                if path == "/table":
                    self._send_index(static_table)
                    return
                if path == "/arena":
                    self._send_index(static_arena)
                    return
                if path == "/api/games":
                    self._send_games(log_dir)
                    return
                if path == "/api/tournaments":
                    self._send_tournaments(log_dir)
                    return
                if path == "/api/replay":
                    self._send_replay(log_dir, parse_qs(parsed.query))
                    return
                if path == "/api/stream":
                    self._stream(log_dir, parse_qs(parsed.query))
                    return
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_index(self, index_path: Path) -> None:
                if not index_path.exists():
                    self.send_error(HTTPStatus.NOT_FOUND, "index.html missing")
                    return
                body = index_path.read_text(encoding="utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))

            def _send_games(self, run_dir: str) -> None:
                games = list_game_logs(run_dir)
                payload = {
                    "games": [
                        {
                            "game_id": g.game_id,
                            "event_count": g.event_count,
                            "modified_ts": g.modified_ts,
                        }
                        for g in games
                    ]
                }
                self._send_json(payload)

            def _send_tournaments(self, run_dir: str) -> None:
                tournaments = list_tournament_logs(run_dir)
                payload = {
                    "tournaments": [
                        {
                            "tournament_id": t.game_id,
                            "event_count": t.event_count,
                            "modified_ts": t.modified_ts,
                        }
                        for t in tournaments
                    ]
                }
                self._send_json(payload)

            def _send_replay(self, run_dir: str, qs: dict[str, list[str]]) -> None:
                game_id = _single(qs, "game_id")
                if not game_id:
                    self._send_json({"error": "missing game_id"}, status=HTTPStatus.BAD_REQUEST)
                    return
                try:
                    events = load_events(run_dir, game_id)
                except FileNotFoundError:
                    self._send_json({"error": f"game not found: {game_id}"}, status=HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"game_id": game_id, "events": events})

            def _stream(self, run_dir: str, qs: dict[str, list[str]]) -> None:
                game_id = _single(qs, "game_id")
                if not game_id:
                    self._send_json({"error": "missing game_id"}, status=HTTPStatus.BAD_REQUEST)
                    return
                path = log_path(run_dir, game_id)
                if not path.exists():
                    self._send_json({"error": f"game not found: {game_id}"}, status=HTTPStatus.NOT_FOUND)
                    return

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()

                sent = 0
                with path.open("r", encoding="utf-8") as f:
                    while True:
                        line = f.readline()
                        if not line:
                            heartbeat = f": hb {int(time.time())}\n\n"
                            try:
                                self.wfile.write(heartbeat.encode("utf-8"))
                                self.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                return
                            time.sleep(1.0)
                            continue
                        line = line.strip()
                        if not line:
                            continue
                        sent += 1
                        frame = f"id: {sent}\ndata: {line}\n\n"
                        try:
                            self.wfile.write(frame.encode("utf-8"))
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            return

            def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
                body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


def _single(qs: dict[str, list[str]], key: str) -> str | None:
    values = qs.get(key, [])
    if not values:
        return None
    return values[0]
