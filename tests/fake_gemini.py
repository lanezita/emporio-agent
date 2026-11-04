"""A tiny fake of the Gemini REST API, to test the agent with the REAL google-genai SDK.

It listens on localhost, records every request, and answers with scripted replies.
No internet and no API key needed.
"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from google import genai
from google.genai import types

SIGNATURE = base64.b64encode(b"fake-thought-signature").decode()


def text_reply(text: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP", "index": 0}]}


def call_reply(*calls: tuple[str, dict]) -> dict:
    """A reply where the model asks to run one or more tools."""
    parts = []
    for i, (name, args) in enumerate(calls):
        part = {"functionCall": {"id": f"call-{i}", "name": name, "args": args}}
        if i == 0:
            part["thoughtSignature"] = SIGNATURE  # Gemini 3 sends this; it must come back unchanged
        parts.append(part)
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP", "index": 0}]}


class FakeGemini:
    """Use as a context manager. `replies` is a list of dicts (or callables taking the request body)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 (name required by http.server)
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                reply = outer.replies.pop(0) if outer.replies else text_reply("(sem mais respostas no roteiro)")
                if callable(reply):
                    reply = reply(body)
                data = json.dumps(reply).encode()
                self.send_response(200 if "error" not in reply else reply["error"]["code"])
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()

    @property
    def client(self) -> genai.Client:
        url = f"http://127.0.0.1:{self.server.server_port}"
        return genai.Client(api_key="test-key", http_options=types.HttpOptions(base_url=url))
