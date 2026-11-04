"""Tests of the policy search, the data cleaning and the store-hours logic."""
from datetime import datetime

import pytest

from emporio import config
from emporio.prompt import build_system_prompt, store_status

# ------------------------------------------------------------------ policy search


@pytest.mark.parametrize("question, expected_section", [
    ("quero devolver, me arrependi da compra", "4.1 Direito de Arrependimento"),
    ("produto veio com defeito", "4.2 Trocas por Defeito"),
    ("vocês abrem sábado?", "2. Horário de Funcionamento"),
    ("posso parcelar em 10x?", "3.1 Regras de Parcelamento"),
    ("qual o endereço da loja", "1.2 Dados da Empresa"),
    ("desconto no pix em promoção", "6.2 Regras de Promoções"),
    ("como funciona a garantia legal", "8.1 Garantia Legal"),
    ("vocês vendem cordas e palhetas", "1. Sobre a Empório da Música"),
    ("código de rastreamento", "5.3 Código de Rastreamento"),
    ("meus dados e LGPD", "9. Privacidade"),
])
def test_policy_search_finds_the_right_section(policies, question, expected_section):
    top = policies.search(question)[0]["section"]
    assert expected_section in top, f"{question!r} -> {top!r}"


def test_policy_search_returns_nothing_for_off_topic(policies):
    assert policies.search("qual é a capital da França") == []


def test_manual_is_split_in_sections(policies):
    assert 20 <= len(policies.chunks) <= 40
    assert all(c.text.strip() for c in policies.chunks)


# ------------------------------------------------------------------ data


def test_data_loaded(store):
    assert (len(store.products), len(store.orders), len(store.customers)) == (65, 20, 50)
    assert [p.id for p in store.promotions if p.active] == [12, 14, 19, 24]


def test_data_is_consistent(store):
    for o in store.orders.values():
        assert o.customer_id in store.customers
        assert all(pid in store.products for pid, _ in o.items)
    assert all(p.category in store.categories.values() for p in store.products.values())


def test_quality_report_finds_the_known_problems(store):
    text = "\n".join(store.issues)
    assert "Order 3: total 3450.00 differs" in text and "Order 20: total 1400.00 differs" in text
    assert "Product 130" in text and "Product 136" in text
    assert "Customers 11 and 43 share" in text
    assert "no products" in text and "ESTIMATED" in text


def test_empty_cells_become_none(store):
    assert store.orders[9].tracking_code is None and store.orders[9].notes is None
    assert store.orders[1].tracking_code == "BRAB1234567BR"


def test_highest_active_promotion_wins(store):
    assert store.active_promotion(94).discount_percent == 8
    assert store.active_promotion(95) is None          # only an inactive promotion


# ------------------------------------------------------------------ store hours and prompt


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=config.STORE_TZ)


@pytest.mark.parametrize("moment, expected", [
    ("2026-11-02T08:59", "FECHADA agora. Próxima abertura: hoje às 9:00"),   # Monday before opening
    ("2026-11-02T09:00", "ABERTA"),
    ("2026-11-02T17:59", "ABERTA"),
    ("2026-11-02T18:00", "FECHADA agora. Próxima abertura: amanhã às 9:00"),
    ("2026-11-06T18:30", "Próxima abertura: amanhã às 9:00"),                # Friday evening -> Saturday
    ("2026-11-07T12:59", "ABERTA"),                                          # Saturday
    ("2026-11-07T13:00", "Próxima abertura: segunda-feira às 9:00"),         # Saturday closes at 13:00
    ("2026-11-08T11:00", "Próxima abertura: amanhã às 9:00"),                # Sunday
])
def test_store_status(moment, expected):
    assert expected in store_status(at(moment))


def test_prompt_contains_clock_and_rules():
    prompt = build_system_prompt(at("2026-11-07T14:00"))
    assert "sábado, 07/11/2026, 14:00" in prompt and "FECHADA" in prompt
    for must in ["search_products", "simulate_payment", "get_order_status", "consult_policies",
                 "escalate_to_human", "(67) 3341-4444", "APÓS O RECEBIMENTO"]:
        assert must in prompt, must
