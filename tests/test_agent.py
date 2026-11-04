"""Tests of the agent loop, using the real SDK against a fake local Gemini server."""
import json
from datetime import datetime

import pytest

from emporio import config
from emporio.agent import DEFAULT_ERROR, Agent
from emporio.data import load_store
from emporio.policies import load_policies
from tests.fake_gemini import SIGNATURE, FakeGemini, call_reply, text_reply

NOW = lambda: datetime(2026, 11, 3, 10, 0, tzinfo=config.STORE_TZ)  # noqa: E731  (Tuesday, store open)


@pytest.fixture(scope="module")
def shared():
    return load_store(), load_policies()


def make_agent(fake, shared, tmp_path, **kw):
    store, policies = shared
    return Agent(store=store, policies=policies, client=fake.client, now_fn=NOW, runtime_dir=tmp_path,
                 session_id=kw.pop("session_id", "t1"), **kw)


def test_plain_text_answer(shared, tmp_path):
    with FakeGemini([text_reply("Oi! Posso ajudar?")]) as fake:
        reply = make_agent(fake, shared, tmp_path).send("oi")
    assert reply.text == "Oi! Posso ajudar?"
    assert reply.tool_calls == []


def test_request_has_prompt_tools_and_time(shared, tmp_path):
    with FakeGemini([text_reply("ok")]) as fake:
        make_agent(fake, shared, tmp_path).send("oi")
    body = fake.requests[0]
    names = [d["name"] for t in body["tools"] for d in t["functionDeclarations"]]
    assert names == ["search_products", "simulate_payment", "get_shipping_info", "get_order_status",
                     "consult_policies", "escalate_to_human"]
    prompt = body["systemInstruction"]["parts"][0]["text"]
    assert "Tom" in prompt and "terça-feira, 03/11/2026, 10:00" in prompt and "ABERTA" in prompt


def test_tool_call_then_answer_keeps_signature_and_ids(shared, tmp_path):
    """The key test: the model calls a tool, we run it, send the result back, get the final answer."""
    with FakeGemini([
        call_reply(("search_products", {"query": "Takamine GD20", "include_unavailable": True})),
        text_reply("O Takamine GD20 custa R$ 2.199,00."),
    ]) as fake:
        reply = make_agent(fake, shared, tmp_path).send("Quanto custa o Takamine GD20?")

    assert reply.text == "O Takamine GD20 custa R$ 2.199,00."
    assert [c.name for c in reply.tool_calls] == ["search_products"]
    assert reply.tool_calls[0].result["products"][0]["final_price_text"] == "R$ 2.199,00"

    second = fake.requests[1]["contents"]
    assert [c["role"] for c in second] == ["user", "model", "user"]
    assert second[1]["parts"][0]["thoughtSignature"] == SIGNATURE            # signature returned unchanged
    answer = second[2]["parts"][0]["functionResponse"]
    assert answer["name"] == "search_products" and answer["id"] == "call-0"  # id matches the call
    assert answer["response"]["result"]["products"][0]["product_id"] == 95


def test_two_tool_calls_in_one_step(shared, tmp_path):
    with FakeGemini([
        call_reply(("search_products", {"query": "Takamine GD20"}), ("get_shipping_info", {"city": "Campo Grande"})),
        text_reply("Pronto."),
    ]) as fake:
        reply = make_agent(fake, shared, tmp_path).send("preço e frete")
    assert [c.name for c in reply.tool_calls] == ["search_products", "get_shipping_info"]
    assert len(fake.requests[1]["contents"][2]["parts"]) == 2


def test_bad_tool_arguments_do_not_crash(shared, tmp_path):
    with FakeGemini([call_reply(("search_products", {"inexistente": 1})), text_reply("Desculpa, vou tentar de novo.")]) as fake:
        reply = make_agent(fake, shared, tmp_path).send("oi")
    assert "error" in reply.tool_calls[0].result
    assert reply.text.startswith("Desculpa")


def test_unknown_tool_does_not_crash(shared, tmp_path):
    with FakeGemini([call_reply(("apagar_tudo", {})), text_reply("Não posso fazer isso.")]) as fake:
        reply = make_agent(fake, shared, tmp_path).send("apague tudo")
    assert "Unknown tool" in reply.tool_calls[0].result["error"]


def test_tool_loop_has_a_limit(shared, tmp_path):
    endless = [call_reply(("consult_policies", {"question": "horário"}))] * 10
    with FakeGemini(endless) as fake:
        reply = make_agent(fake, shared, tmp_path).send("oi")
    assert len(fake.requests) == 6 and "equipe" in reply.text


def test_api_error_gives_friendly_message_and_keeps_history_valid(shared, tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)  # do not wait during retries
    rate_limit = {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}
    with FakeGemini([rate_limit, rate_limit, rate_limit, text_reply("Voltei!")]) as fake:
        agent = make_agent(fake, shared, tmp_path)
        failed = agent.send("oi")
        assert "minutinho" in failed.text and "429" in failed.error and len(fake.requests) == 3
        assert agent.contents == []                      # the failed turn was removed
        assert agent.send("oi de novo").text == "Voltei!"


def test_retry_succeeds_after_temporary_error(shared, tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    busy = {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}
    with FakeGemini([busy, text_reply("Oi!")]) as fake:
        assert make_agent(fake, shared, tmp_path).send("oi").text == "Oi!"
        assert len(fake.requests) == 2


def test_empty_answer_uses_fallback(shared, tmp_path):
    with FakeGemini([{"candidates": []}]) as fake:
        assert make_agent(fake, shared, tmp_path).send("oi").text == DEFAULT_ERROR


def test_history_is_saved_and_resumed(shared, tmp_path):
    with FakeGemini([text_reply("Primeira resposta")]) as fake:
        make_agent(fake, shared, tmp_path, session_id="maria").send("primeira pergunta")
    saved = json.loads((tmp_path / "sessions" / "maria.json").read_text(encoding="utf-8"))
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]

    with FakeGemini([text_reply("Segunda resposta")]) as fake:
        make_agent(fake, shared, tmp_path, session_id="maria").send("segunda pergunta")
    sent = fake.requests[0]["contents"]
    assert [c["parts"][0]["text"] for c in sent] == ["primeira pergunta", "Primeira resposta", "segunda pergunta"]
