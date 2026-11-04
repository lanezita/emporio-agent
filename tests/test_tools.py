"""Tests of the tools: prices, stock, payment, shipping, orders, privacy. No LLM involved."""
import json

from emporio.config import DATA_DIR

# ------------------------------------------------------------------ products and prices


def test_violoes_ate_1000(tools):
    r = tools["search_products"](category="Violões", max_price=1000, limit=15)
    assert r["total_matches"] == 12
    assert all(p["category"] == "Violões" and p["final_price"] <= 1000 for p in r["products"])
    assert all(p["availability"] == "disponível" for p in r["products"])
    names = [p["name"] for p in r["products"]]
    assert "Giannini GF-3D Dreadnought Sunburst" not in names          # out of stock
    assert "Shelby SN-7C 7 Cordas Nylon Natural" not in names          # discontinued
    prices = [p["final_price"] for p in r["products"]]
    assert prices == sorted(prices)                                    # cheapest first


def test_takamine_gd20_price_and_pix(tools):
    p = tools["search_products"](query="Takamine GD20")["products"][0]
    assert p["list_price_text"] == "R$ 2.199,00" and p["final_price_text"] == "R$ 2.199,00"
    assert "promotion" not in p                                        # its only promotion is inactive
    assert p["pix_price_text"] == "R$ 2.089,05"


def test_model_code_search_ignores_dashes_and_case(tools):
    assert tools["search_products"](query="gd20")["products"][0]["product_id"] == 95
    ids = [p["product_id"] for p in tools["search_products"](query="martin d28")["products"]]
    assert ids[:1] == [93]


def test_active_promotion_shows_original_percent_and_final_price(tools):
    p = tools["search_products"](query="Taylor 110e")["products"][0]
    assert p["promotion"] == {"name": "Desconto Exclusivo", "discount_percent": 8.0,
                              "price_from": "R$ 5.999,00", "price_to": "R$ 5.519,08"}
    assert p["final_price_text"] == "R$ 5.519,08"
    assert "sem desconto extra de PIX" in p["pix_price_text"]


def test_expired_promotion_is_not_applied(tools):
    # Promotion 4 (12% on the Takamine GD20) exists but is_active = 0.
    assert "promotion" not in tools["search_products"](query="Takamine GD20")["products"][0]


def test_price_filter_uses_promotional_price(tools):
    # Kalani KAL-700T: R$ 359,00 with an active 10% promotion -> R$ 323,10
    r = tools["search_products"](category="Ukuleles", max_price=330)
    assert "Kalani KAL-700T Tenor Natural" in [p["name"] for p in r["products"]]


def test_out_of_stock_product_returns_status_and_alternatives(tools):
    r = tools["search_products"](query="Giannini GF-3D")
    assert r["products"] == []
    assert r["unavailable_matches"][0]["availability"] == "sem estoque no momento"
    alts = r["alternatives"]
    assert alts and all(a["availability"] == "disponível" and a["category"] == "Violões" for a in alts)

def test_asking_for_one_unavailable_product_also_returns_alternatives(tools):
    # The prompt tells the agent to use include_unavailable=true for a specific product.
    r = tools["search_products"](query="Giannini GF-3D", include_unavailable=True)
    assert r["products"][0]["availability"] == "sem estoque no momento"
    alts = r["alternatives"]
    assert alts and all(a["availability"] == "disponível" and a["category"] == "Violões" for a in alts)


def test_asking_for_one_unavailable_product_also_returns_alternatives(tools):
    # The prompt tells the agent to use include_unavailable=true for a specific product.
    r = tools["search_products"](query="Giannini GF-3D", include_unavailable=True)
    assert r["products"][0]["availability"] == "sem estoque no momento"
    alts = r["alternatives"]
    assert alts and all(a["availability"] == "disponível" and a["category"] == "Violões" for a in alts)


def test_asking_for_one_unavailable_product_also_returns_alternatives(tools):
    # The prompt tells the agent to use include_unavailable=true for a specific product.
    r = tools["search_products"](query="Giannini GF-3D", include_unavailable=True)
    assert r["products"][0]["availability"] == "sem estoque no momento"
    alts = r["alternatives"]
    assert alts and all(a["availability"] == "disponível" and a["category"] == "Violões" for a in alts)


def test_available_product_search_has_no_alternatives(tools):
    r = tools["search_products"](query="Taylor 110e", include_unavailable=True)
    assert "alternatives" not in r

def test_discontinued_and_coming_soon_are_not_sellable_even_with_stock(tools, store):
    assert store.products[136].stock > 0 and store.products[130].stock > 0   # the data has stock...
    for query, status in [("Ibanez Bass 2X", "descontinuado"), ("Kala KA-ABP-CTG", "em breve")]:
        r = tools["search_products"](query=query)
        assert r["products"] == [] and status in r["unavailable_matches"][0]["availability"]


def test_empty_category_explains_what_the_store_has(tools):
    r = tools["search_products"](query="flauta")
    assert r["products"] == []
    empty = [c["category"] for c in r["catalog_summary"] if c["available_products"] == 0]
    assert "Instrumentos de Sopro (Madeiras)" in empty


def test_unknown_category_lists_valid_ones(tools):
    r = tools["search_products"](category="Acessórios")
    assert "error" in r and "Violões" in r["valid_categories"]


def test_plural_and_accents_in_category(tools):
    for text in ["violoes", "VIOLÃO", "ukulele", "teclado"]:
        assert "error" not in tools["search_products"](category=text, limit=1), text


# ------------------------------------------------------------------ payment


def test_pix_discount_on_regular_price(tools):
    r = tools["simulate_payment"](95)
    assert r["pix"] == {"discount": "5%", "total": "R$ 2.089,05"}
    assert r["credit_card"]["max_installments"] == 12 and r["combined_payment_allowed"] is True


def test_no_pix_discount_on_promotional_price(tools):
    r = tools["simulate_payment"](94)
    assert r["has_promotion"] and "Sem desconto extra de PIX" in r["pix"] and r["total"] == "R$ 5.519,08"


def test_installment_minimums(tools):
    # R$ 349,90: 4x = 87,48 (min 80) is fine, 5x = 69,98 is below the R$ 80 minimum
    r = tools["simulate_payment"](120)
    assert r["credit_card"]["max_installments"] == 4
    # R$ 159,90: 3x = 53,30 is fine, 4x = 39,98 is not
    assert tools["simulate_payment"](119)["credit_card"]["max_installments"] == 3
    # R$ 599,90 (Yamaha C40): 6x = 99,98 is fine (min 80), 7x = 85,70 is below R$ 100
    assert tools["simulate_payment"](81)["credit_card"]["max_installments"] == 6


def test_cannot_simulate_unavailable_product(tools):
    assert "error" in tools["simulate_payment"](96)
    assert "error" in tools["simulate_payment"](9999)


# ------------------------------------------------------------------ shipping


def test_local_shipping_rule(tools):
    assert tools["get_shipping_info"]("campo grande", 95)["shipping"] == "grátis"        # R$ 2.199
    cheap = tools["get_shipping_info"]("Campo Grande", 119)                              # R$ 159,90
    assert cheap["shipping"] == "R$ 35,00" and cheap["deadline"] == "1 a 3 dias úteis"
    assert tools["get_shipping_info"]("Campo Grande", 119, 4)["shipping"] == "grátis"    # 4 x 159,90 = 639,60


def test_other_city_has_carriers_but_no_invented_price(tools):
    r = tools["get_shipping_info"]("Dourados", 95)
    assert {c["name"] for c in r["carriers"]} == {"PAC (Correios)", "SEDEX (Correios)", "Jadlog (.package)"}
    assert "shipping" not in r and "NÃO tem o valor" in r["price"]


def test_large_item_flag(tools):
    assert "large_item" in tools["get_shipping_info"]("Dourados", 139)      # acoustic drum kit
    assert "large_item" not in tools["get_shipping_info"]("Dourados", 95)


# ------------------------------------------------------------------ orders and privacy


def test_order_with_email_any_case(tools):
    r = tools["get_order_status"](1, "PEDRO.OLIVEIRA@jmail.com")
    assert r["verified"] and r["customer_first_name"] == "Pedro" and r["status"] == "delivered"
    assert r["items"] == [{"name": "Martin D-28 Dreadnought Natural", "quantity": 1}]
    assert r["total"] == "R$ 11.499,00" and r["payment"] == "PIX"


def test_order_with_phone_in_different_formats(tools):
    for phone in ["(67) 99654-7821", "67996547821", "+55 67 99654-7821"]:
        assert tools["get_order_status"](8, phone)["verified"], phone


def test_wrong_contact_and_missing_order_look_the_same(tools):
    wrong = tools["get_order_status"](1, "outro@jmail.com")
    missing = tools["get_order_status"](999, "pedro.oliveira@jmail.com")
    assert wrong == missing and wrong["verified"] is False       # no hint about which orders exist


def test_short_phone_is_not_accepted(tools):
    assert not tools["get_order_status"](8, "7821")["verified"]


def test_no_personal_data_is_returned(tools):
    text = json.dumps(tools["get_order_status"](1, "pedro.oliveira@jmail.com"), ensure_ascii=False)
    assert "pedro.oliveira" not in text and "(67)" not in text and "Oliveira" not in text


def test_lock_after_three_failures_and_reset_after_success(tools, state):
    for _ in range(2):
        tools["get_order_status"](1, "errado@x.com")
    assert tools["get_order_status"](1, "pedro.oliveira@jmail.com")["verified"]      # success resets the counter
    assert state.failed_verifications == 0
    for _ in range(3):
        tools["get_order_status"](1, "errado@x.com")
    locked = tools["get_order_status"](1, "pedro.oliveira@jmail.com")                # even the right data is refused now
    assert locked["verified"] is False and locked["locked"] is True


def test_delivered_order_warns_that_only_estimated_date_exists(tools):
    r = tools["get_order_status"](1, "pedro.oliveira@jmail.com")
    assert "ESTIMADA" in r["return_info"] and r["days_since_estimated_delivery"] == 374


def test_stuck_orders_get_an_attention_flag(tools):
    shipped = tools["get_order_status"](8, "anacarol.ferreira@coldmail.com")         # shipped, estimate long gone
    assert shipped["status"] == "shipped" and "attention" in shipped
    assert "attention" not in tools["get_order_status"](1, "pedro.oliveira@jmail.com")


def test_cancelled_order_shows_the_reason(tools, store):
    owner = store.customers[store.orders[17].customer_id]
    r = tools["get_order_status"](17, owner.email)
    assert r["status"] == "cancelled" and r["notes"] == "Pedido cancelado pelo cliente antes do processamento"
    assert "attention" not in r and "return_info" not in r


def test_escalation_is_logged(tools, tmp_path):
    r = tools["escalate_to_human"]("reclamacao", "Pedido 8 atrasado", "ana@x.com")
    assert r["ticket"].startswith("ATD-")
    line = json.loads((tmp_path / "handoffs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["category"] == "reclamacao" and line["summary"] == "Pedido 8 atrasado"


# ------------------------------------------------------------------ the code must match the manual


def test_business_rules_in_code_match_the_manual_text():
    """If someone edits the manual, this test tells us the constants in tools.py need review."""
    manual = (DATA_DIR / "politicas_da_loja.md").read_text(encoding="utf-8")
    for fragment in ["5% de desconto", "R$ 500,00", "R$ 35,00", "R$ 2.000,00", "R$ 50,00", "R$ 80,00",
                     "R$ 100,00", "7 (sete) dias", "30 (trinta) dias", "1 a 3 dias úteis", "5 a 12 dias úteis",
                     "2 a 5 dias úteis", "3 a 8 dias úteis", "24 horas úteis"]:
        assert fragment in manual, fragment
