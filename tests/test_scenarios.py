"""The example scenarios depend on real rows of the CSV files. This checks that they still match."""
from datetime import datetime

from emporio import config
from emporio.prompt import store_status
from emporio.scenarios import SCENARIOS
from emporio.tools import SessionState, build_tools


def scenario(prefix: str) -> dict:
    return next(s for s in SCENARIOS if s["slug"].startswith(prefix))


def tools_at(store, policies, tmp_path, moment: str):
    fixed = datetime.fromisoformat(moment).replace(tzinfo=config.STORE_TZ)
    funcs = build_tools(store, policies, SessionState("scenario"), now_fn=lambda: fixed, runtime_dir=tmp_path)
    return {f.__name__: f for f in funcs}


def test_between_three_and_five_unique_scenarios():
    assert 3 <= len(SCENARIOS) <= 5
    assert len({s["slug"] for s in SCENARIOS}) == len(SCENARIOS)


def test_store_hours_match_what_each_scenario_expects():
    open_now = {"01": True, "02": True, "03": False, "04": True, "05": True}
    for prefix, expected in open_now.items():
        status = store_status(datetime.fromisoformat(scenario(prefix)["now"]).replace(tzinfo=config.STORE_TZ))
        assert ("ABERTA" in status) == expected, prefix


def test_return_scenario_order_is_inside_the_regret_window(store, policies, tmp_path):
    t = tools_at(store, policies, tmp_path, scenario("04")["now"])
    order = t["get_order_status"](7, "leticia.rocha@jmail.com")
    assert order["verified"] and order["status"] == "delivered"
    assert order["days_since_estimated_delivery"] == 1          # "Recebi ontem" is consistent with the data


def test_delay_scenario_order_is_late(store, policies, tmp_path):
    t = tools_at(store, policies, tmp_path, scenario("05")["now"])
    order = t["get_order_status"](8, "(67) 99654-7821")
    assert order["verified"] and order["status"] == "shipped"
    assert order["days_since_estimated_delivery"] == 10 and "attention" in order


def test_neighbour_order_is_protected(store, policies, tmp_path):
    t = tools_at(store, policies, tmp_path, scenario("05")["now"])
    t["get_order_status"](8, "(67) 99654-7821")                  # Ana verifies her own order
    assert t["get_order_status"](10, "(67) 99654-7821")["verified"] is False   # but order 10 is not hers


def test_prices_mentioned_in_scenarios_exist(store, policies, tmp_path):
    t = tools_at(store, policies, tmp_path, scenario("02")["now"])
    assert t["search_products"](query="Takamine GD20")["products"][0]["final_price_text"] == "R$ 2.199,00"
    assert t["search_products"](query="Taylor 110e")["products"][0]["promotion"]["discount_percent"] == 8
    assert t["search_products"](query="Giannini GF-3D")["unavailable_matches"]
    assert t["search_products"](query="Yamaha C70")["products"][0]["final_price"] == 849.0
