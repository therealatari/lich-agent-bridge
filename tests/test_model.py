import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lich_agent_bridge.errors import ConfigurationError, ModelError
from lich_agent_bridge.model import OpenAICompatibleChatModel, OpenAIResponsesModel


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class RecordingOpener:
    def __init__(self):
        self.request = None
        self.timeout = None

    def __call__(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        body = {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Stay alert."}],
                }
            ],
            "choices": [{"message": {"content": "Stay alert."}}],
        }
        return FakeResponse(json.dumps(body).encode())


class OpenAIResponsesModelTests(unittest.TestCase):
    def test_request_is_stateless_and_has_no_tools(self):
        opener = RecordingOpener()
        model = OpenAIResponsesModel(api_key="test-key", opener=opener)

        answer = model.respond(instructions="Be safe.", input_text="Recent events")

        payload = json.loads(opener.request.data)
        self.assertEqual(opener.request.full_url, "https://api.openai.com/v1/responses")
        self.assertFalse(payload["store"])
        self.assertNotIn("tools", payload)
        self.assertEqual(answer, "Stay alert.")

    def test_missing_key_fails_before_network(self):
        model = OpenAIResponsesModel(api_key="")
        with self.assertRaises(ConfigurationError):
            model.respond(instructions="x", input_text="y")

    def test_reasoning_effort_is_included_when_configured(self):
        opener = RecordingOpener()
        model = OpenAIResponsesModel(
            api_key="test-key", reasoning_effort="low", opener=opener
        )

        model.respond(instructions="Be safe.", input_text="Recent events")

        self.assertEqual(json.loads(opener.request.data)["reasoning"], {"effort": "low"})


class OpenAICompatibleChatModelTests(unittest.TestCase):
    def test_fake_local_server_uses_chat_completions_with_profile_model_and_effort(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - stdlib callback name
                received["path"] = self.path
                received["headers"] = dict(self.headers)
                length = int(self.headers["Content-Length"])
                received["payload"] = json.loads(self.rfile.read(length))
                response = json.dumps(
                    {"choices": [{"message": {"content": "Stay alert."}}]}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            model = OpenAICompatibleChatModel(
                model="llama-local",
                base_url=f"http://{host}:{port}/v1",
                reasoning_effort="medium",
                timeout=7,
            )
            answer = model.respond(
                instructions="Stay safe.", input_text="What happened?"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        payload = received["payload"]
        self.assertEqual(answer, "Stay alert.")
        self.assertEqual(received["path"], "/v1/chat/completions")
        self.assertEqual(payload["model"], "llama-local")
        self.assertEqual(payload["reasoning_effort"], "medium")
        self.assertEqual(payload["messages"][0]["content"], "Stay safe.")
        self.assertEqual(payload["messages"][1]["content"], "What happened?")
        self.assertNotIn("Authorization", received["headers"])

    def test_unavailable_or_malformed_local_server_fails_truthfully(self):
        class MalformedOpener:
            def __call__(self, _request, *, timeout):
                return FakeResponse(b'{"choices": []}')

        malformed = OpenAICompatibleChatModel(
            model="llama-local",
            base_url="http://127.0.0.1:8080/v1",
            opener=MalformedOpener(),
        )
        with self.assertRaisesRegex(ModelError, "no message text"):
            malformed.respond(instructions="x", input_text="y")

        unavailable = OpenAICompatibleChatModel(
            model="llama-local",
            base_url="http://127.0.0.1:8080/v1",
            opener=lambda _request, *, timeout: (_ for _ in ()).throw(OSError("offline")),
        )
        with self.assertRaisesRegex(ModelError, "could not be read"):
            unavailable.respond(instructions="x", input_text="y")


if __name__ == "__main__":
    unittest.main()
