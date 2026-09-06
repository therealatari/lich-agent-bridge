class RecordingModel:
    backend = "recording-test"
    configured = True

    def __init__(self, answer: str = "A careful read-only answer."):
        self.answer = answer
        self.calls: list[dict[str, str]] = []

    def respond(self, *, instructions: str, input_text: str) -> str:
        self.calls.append({"instructions": instructions, "input_text": input_text})
        return self.answer
