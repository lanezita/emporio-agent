"""The agent: a loop that lets Gemini call our tools until it has an answer.

Flow of one customer message (send):
    1. Add the message to the history.
    2. Ask Gemini. If it answers with text, we are done.
    3. If it asks for tools, run them here in Python, add the results to the history, go to 2.
We write this loop ourselves (instead of using the SDK's automatic mode) so we can
log every tool call, limit the number of steps, and test it with a fake client.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

from google import genai
from google.genai import errors, types

from . import config
from .data import Store, load_store
from .policies import PolicyIndex, load_policies
from .prompt import build_system_prompt
from .tools import SessionState, build_tools

MAX_TOOL_STEPS = 6   # stop a runaway loop
RETRIES = 3          # for temporary API errors (rate limit, overload)

FRIENDLY_ERRORS = {
    429: "Estou com muitas conversas ao mesmo tempo agora. Pode mandar de novo daqui a um minutinho?",
}
DEFAULT_ERROR = "Tive um problema técnico para responder agora. Pode tentar de novo em instantes?"


@dataclass
class ToolCall:
    name: str
    args: dict
    result: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None  # technical detail, only for the developer


class Agent:
    def __init__(self, store: Store | None = None, policies: PolicyIndex | None = None, client=None,
                 model: str | None = None, session_id: str | None = None, now_fn=config.now,
                 runtime_dir=config.RUNTIME_DIR):
        self.store = store or load_store()
        self.policies = policies or load_policies()
        self._client = client            # created on first use, so tests do not need an API key
        self.model = model or config.MODEL
        self.now_fn = now_fn
        self.runtime_dir = runtime_dir
        self.session_id = session_id or self.now_fn().strftime("%Y%m%d-%H%M%S")
        self.state = SessionState(session_id=self.session_id)
        self.tools = build_tools(self.store, self.policies, self.state, now_fn=now_fn, runtime_dir=runtime_dir)
        self._by_name = {f.__name__: f for f in self.tools}

        self.contents: list[types.Content] = []   # what we send to Gemini (full fidelity)
        self.messages: list[dict] = []            # what we save to disk (readable transcript)
        self._load()

    # ------------------------------------------------------------------ public

    def send(self, user_text: str) -> Reply:
        checkpoint = len(self.contents)
        self.contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        calls: list[ToolCall] = []
        try:
            text = self._run_loop(calls)
        except errors.APIError as e:
            del self.contents[checkpoint:]  # forget this turn, so the history stays valid
            return Reply(FRIENDLY_ERRORS.get(e.code, DEFAULT_ERROR), calls, error=f"{type(e).__name__} {e.code}: {e.message}")

        self.messages.append({"role": "user", "text": user_text, "time": self.now_fn().isoformat(timespec="seconds")})
        self.messages.append({
            "role": "assistant", "text": text, "time": self.now_fn().isoformat(timespec="seconds"),
            "tool_calls": [{"name": c.name, "args": c.args, "result": _short(c.result)} for c in calls],
        })
        self._save()
        return Reply(text, calls)

    # ------------------------------------------------------------------ the loop

    def _run_loop(self, calls: list[ToolCall]) -> str:
        for _ in range(MAX_TOOL_STEPS):
            response = self._generate()
            if not response.candidates or not response.candidates[0].content:
                return DEFAULT_ERROR  # blocked or empty answer
            content = response.candidates[0].content
            self.contents.append(content)  # keep it exactly as received (it may carry thought signatures)

            requested = response.function_calls or []
            if not requested:
                text = "".join(p.text for p in content.parts if p.text and not p.thought).strip()
                return text or DEFAULT_ERROR

            answers = []
            for call in requested:
                args = dict(call.args or {})
                result = self._run_tool(call.name, args)
                calls.append(ToolCall(call.name, args, result))
                answers.append(types.Part(function_response=types.FunctionResponse(
                    id=call.id, name=call.name, response={"result": result})))
            self.contents.append(types.Content(role="user", parts=answers))

        return "Desculpa, me enrolei aqui. Vou pedir para a equipe te ajudar com isso."

    def _run_tool(self, name: str, args: dict) -> dict:
        tool = self._by_name.get(name)
        if tool is None:
            return {"error": f"Unknown tool '{name}'."}
        try:
            return tool(**args)
        except Exception as e:  # bad arguments from the model must not crash the chat
            return {"error": f"{type(e).__name__}: {e}"}

    def _generate(self):
        config_ = types.GenerateContentConfig(
            system_instruction=build_system_prompt(self.now_fn()),
            tools=self.tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        delay = 2
        for attempt in range(RETRIES):
            try:
                return self.client.models.generate_content(model=self.model, contents=self.contents, config=config_)
            except errors.APIError as e:
                if e.code not in (429, 500, 503, 504) or attempt == RETRIES - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    @property
    def client(self):
        if self._client is None:
            self._client = genai.Client()  # reads GEMINI_API_KEY from the environment
        return self._client

    # ------------------------------------------------------------------ history on disk

    @property
    def _path(self):
        return self.runtime_dir / "sessions" / f"{self.session_id}.json"

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"session_id": self.session_id, "messages": self.messages}
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load(self):
        """Resume a saved chat. We restore only the visible messages, not the old tool calls."""
        if not self._path.exists():
            return
        self.messages = json.loads(self._path.read_text(encoding="utf-8"))["messages"]
        for m in self.messages:
            role = "user" if m["role"] == "user" else "model"
            self.contents.append(types.Content(role=role, parts=[types.Part(text=m["text"])]))


def _short(result: dict, limit: int = 600) -> str:
    text = json.dumps(result, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
