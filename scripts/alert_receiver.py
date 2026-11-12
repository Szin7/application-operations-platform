"""Receive local alert notifications for delivery checks."""

import json
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

events = deque(maxlen=100)


class AlertReceiver(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"status": "ok"})
        elif self.path == "/events":
            self.reply(200, list(events))
        else:
            self.reply(404, {"detail": "Not found"})

    def do_POST(self):
        if self.path != "/alerts":
            self.reply(404, {"detail": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.reply(400, {"detail": "Invalid content length"})
            return

        if not 0 < length <= 65536:
            self.reply(413, {"detail": "Expected a body of 1 to 65536 bytes"})
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except ValueError, UnicodeError:
            self.reply(400, {"detail": "Invalid JSON"})
            return

        if (
            not isinstance(payload, dict)
            or payload.get("status") not in ("firing", "resolved")
            or not isinstance(payload.get("alerts"), list)
            or not payload["alerts"]
            or not all(isinstance(alert, dict) for alert in payload["alerts"])
        ):
            self.reply(400, {"detail": "Invalid alert notification"})
            return

        event = {
            "id": uuid4().hex,
            "received_at": datetime.now(UTC).isoformat(),
            "notification": payload,
        }
        events.append(event)
        print(json.dumps(event), flush=True)
        self.reply(200, {"status": "received", "id": event["id"]})

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    with HTTPServer(("0.0.0.0", 8080), AlertReceiver) as server:
        print("Alert receiver listening on port 8080.", flush=True)
        server.serve_forever()
