"""The tools the LLM can call (function calling).

Rule of this file: the LLM decides WHEN to call a tool, but all facts and all
arithmetic (prices, discounts, installments, shipping, dates) are computed here
in plain Python. The model only writes the final message.

The docstrings are important: the SDK sends them to the model as the tool description.
"""
import json
from dataclasses import dataclass, field
from datetime import date

from . import config
from .data import Product, Store
from .policies import PolicyIndex, section_titles
from .text import brl, fold, money, similar, stem, tokens

# ---- Business rules written down from the manual (a test checks that these numbers are in the PDF text) ----
PIX_DISCOUNT = 0.05                 # 3. Formas de Pagamento
MIN_INSTALLMENT = {(1, 3): 50.0, (4, 6): 80.0, (7, 12): 100.0}  # 3.1 (see README: our reading of 3.1)
COMBINED_PAYMENT_ABOVE = 2000.0     # 3.1
FREE_SHIPPING_ABOVE = 500.0         # 5.1
LOCAL_SHIPPING_FEE = 35.0           # 5.1
LOCAL_CITIES = {"campo grande"}     # 5.1 says "metropolitan region"; the manual does not list cities
LARGE_ITEMS = ("bateria acustica", "piano", "contrabaixo")  # 5.2
REGRET_DAYS = 7                     # 4.1
DEFECT_DAYS = 30                    # 4.2
STALE_ORDER_DAYS = 15               # our choice: not in the manual (see README)

ORDER_STATUS = {
    "pending": "Pedido recebido, aguardando confirmação",
    "confirmed": "Pedido confirmado, em preparação (ainda não foi enviado)",
    "shipped": "Pedido enviado, a caminho do cliente",
    "delivered": "Pedido entregue",
    "cancelled": "Pedido cancelado",
}


@dataclass
class SessionState:
    """What the tools remember during one chat."""
    session_id: str = "local"
    failed_verifications: int = 0
    tickets: list = field(default_factory=list)


# ------------------------------------------------------------------ product helpers

def availability_text(p: Product) -> str:
    if p.status == "discontinued":
        return "descontinuado (não faz mais parte do catálogo)"
    if p.status == "coming_soon":
        return "em breve (ainda não disponível para compra)"
    if p.stock <= 0:
        return "sem estoque no momento"
    return "disponível"


def price_block(store: Store, p: Product) -> dict:
    """Prices as the manual wants them (6.2): promo shown with the original price and the percent."""
    promo = store.active_promotion(p.id)
    block = {"list_price_text": brl(p.price)}
    if promo:
        final = money(p.price * (1 - promo.discount_percent / 100))
        block["promotion"] = {
            "name": promo.name,
            "discount_percent": promo.discount_percent,
            "price_from": brl(p.price),
            "price_to": brl(final),
        }
        block["final_price"] = float(final)
        block["pix_price_text"] = "sem desconto extra de PIX (preço já promocional, regra 6.2)"
    else:
        block["final_price"] = p.price
        block["pix_price_text"] = brl(float(money(p.price * (1 - PIX_DISCOUNT))))
    block["final_price_text"] = brl(block["final_price"])
    return block


def describe(store: Store, p: Product) -> dict:
    return {
        "product_id": p.id,
        "name": p.name,
        "category": p.category,
        "availability": availability_text(p),
        "units_in_stock": p.stock if p.available else 0,
        **price_block(store, p),
        "description": p.description,
        "specs": p.specs,
    }


def _alternatives(store: Store, p: Product, n: int = 3) -> list[dict]:
    """Available products of the same category with the closest price."""
    pool = [q for q in store.products.values() if q.available and q.category_id == p.category_id and q.id != p.id]
    pool.sort(key=lambda q: abs(price_block(store, q)["final_price"] - p.price))
    return [describe(store, q) for q in pool[:n]]


def _search_text(p: Product) -> tuple[set[str], set[str], str, str]:
    """Words of the whole product, words of the name, and two 'compact' strings without spaces.

    The compact strings let the query 'd28' find 'D-28', and 'gd20' find 'GD20'.
    """
    text = " ".join([p.name, p.category, p.description, " ".join(str(v) for v in p.specs.values())])
    words = set(tokens(text)) | {stem(t) for t in tokens(text)}
    name_words = set(tokens(p.name)) | {stem(t) for t in tokens(p.name)}
    return words, name_words, "".join(tokens(text)), "".join(tokens(p.name))


# ------------------------------------------------------------------ the tools

def build_tools(store: Store, policies: PolicyIndex, state: SessionState, now_fn=config.now,
                runtime_dir=config.RUNTIME_DIR) -> list:
    """Create the tool functions. They are closures over the data, so the model never sees the data object.

    The tools have no return annotation on purpose: without it the SDK does not send a
    response schema, so we send only what the model needs (name, description, parameters).
    """

    def search_products(query: str = "", category: str = "", min_price: float = 0, max_price: float = 0,
                        include_unavailable: bool = False, limit: int = 8):
        """Search the product catalog. Use it for ANY question about price, stock, models or recommendations.

        Never state a price or availability that did not come from this tool.

        Args:
            query: Brand, model or keywords in Portuguese, e.g. "Takamine GD20" or "aço elétrico". Do not put prices here.
            category: One catalog category, e.g. "Violões", "Guitarras", "Ukuleles", "Baixos",
                "Baterias e Percussão", "Teclados e Pianos". Leave empty to search everything.
            min_price: Minimum price in reais, using the final (promotional) price. 0 means no minimum.
            max_price: Maximum price in reais, using the final (promotional) price. 0 means no maximum.
            include_unavailable: Set true when the customer asks about ONE specific product, so you can tell
                the real status (out of stock, discontinued, coming soon).
            limit: Maximum number of products (default 8, maximum 15).
        """
        limit = max(1, min(int(limit or 8), 15))

        cat_ids = None
        if category.strip():
            wanted = {stem(t) for t in tokens(category)}
            cat_ids = {cid for cid, name in store.categories.items()
                       if any(similar(w, stem(t)) for w in wanted for t in tokens(name))}
            if not cat_ids:
                return {"error": f"Category '{category}' does not exist.",
                        "valid_categories": list(store.categories.values())}

        terms = [stem(t) for t in tokens(query)]
        scored = []
        for p in store.products.values():
            if cat_ids is not None and p.category_id not in cat_ids:
                continue
            words, name_words, all_compact, name_compact = _search_text(p)
            score, ok = 0, True
            for t in terms:
                in_name = any(similar(t, w) for w in name_words) or (len(t) >= 3 and t in name_compact)
                in_doc = any(similar(t, w) for w in words) or (len(t) >= 3 and t in all_compact)
                if not in_doc:
                    ok = False
                    break
                score += 3 if in_name else 1
            if not ok:
                continue
            final = price_block(store, p)["final_price"]
            if min_price and final < min_price:
                continue
            if max_price and final > max_price:
                continue
            scored.append((score, final, p))

        scored.sort(key=lambda x: (-x[0], x[1]))
        matches = [p for _, _, p in scored]
        shown = matches if include_unavailable else [p for p in matches if p.available]

        if not query.strip() and cat_ids is None and not max_price and not min_price:
            return {"catalog_summary": _catalog_summary(store)}
        if shown:
            result = {"total_matches": len(shown), "products": [describe(store, p) for p in shown[:limit]]}
            if not any(p.available for p in shown):  # asked for a specific product that cannot be bought now
                result["alternatives"] = _alternatives(store, shown[0])
                result["message"] = "O produto existe, mas não pode ser comprado agora. Explique o status e sugira as alternativas."
            return result
        if matches:  # the product exists, but cannot be bought now
            return {"products": [],
                    "unavailable_matches": [describe(store, p) for p in matches[:3]],
                    "alternatives": _alternatives(store, matches[0]),
                    "message": "O produto existe, mas não pode ser comprado agora. Explique o status e sugira as alternativas."}
        return {"products": [], "message": "Nenhum produto encontrado com esses critérios.",
                "catalog_summary": _catalog_summary(store)}

    def simulate_payment(product_id: int, quantity: int = 1):
        """Calculate how the customer can pay for a product: PIX price, installments, boleto.

        Use it whenever the customer asks about PIX, installments ("parcelar", "10x") or the payment method.
        The PIX discount is NOT applied on promotional prices (manual 6.2); this tool already knows that.

        Args:
            product_id: The product_id returned by search_products.
            quantity: Number of units (default 1).
        """
        p = store.products.get(int(product_id))
        if not p:
            return {"error": f"Product {product_id} not found."}
        if not p.available:
            return {"error": f"{p.name} is not available now ({availability_text(p)})."}
        quantity = max(1, int(quantity))
        block = price_block(store, p)
        total = float(money(block["final_price"] * quantity))

        installments = []
        for n in range(1, 13):
            parcel = float(money(total / n))
            minimum = next(v for (lo, hi), v in MIN_INSTALLMENT.items() if lo <= n <= hi)
            if n == 1 or parcel >= minimum:
                installments.append({"installments": n, "installment_value": brl(parcel)})

        result = {
            "product": p.name,
            "quantity": quantity,
            "total": brl(total),
            "has_promotion": "promotion" in block,
            "debit_or_boleto": f"{brl(total)} à vista (boleto compensa em até 3 dias úteis)",
            "credit_card": {"max_installments": installments[-1]["installments"], "options": installments,
                            "interest": "sem juros"},
            "combined_payment_allowed": total > COMBINED_PAYMENT_ABOVE,
        }
        if "promotion" in block:
            result["pix"] = "Sem desconto extra de PIX: o preço já é promocional (regra 6.2)."
            result["promotion"] = block["promotion"]
        else:
            result["pix"] = {"discount": "5%", "total": brl(float(money(total * (1 - PIX_DISCOUNT))))}
        return result

    def get_shipping_info(city: str, product_id: int = 0, quantity: int = 1):
        """Delivery cost and deadline for a city, optionally for a specific product.

        Args:
            city: Delivery city, e.g. "Campo Grande" or "Dourados". Ask the customer if unknown.
            product_id: Optional product_id, to compute the free-shipping rule and detect large items.
            quantity: Number of units (default 1).
        """
        subtotal, large, name = None, False, None
        if product_id:
            p = store.products.get(int(product_id))
            if not p:
                return {"error": f"Product {product_id} not found."}
            subtotal = float(money(price_block(store, p)["final_price"] * max(1, int(quantity))))
            large = any(k in fold(p.name) for k in LARGE_ITEMS)
            name = p.name

        if fold(city).strip() in LOCAL_CITIES:
            info = {"region": "Campo Grande (entrega local por motoboy próprio)", "deadline": "1 a 3 dias úteis",
                    "note": "O cliente recebe uma ligação antes da entrega."}
            if subtotal is None:
                info["rule"] = f"Frete grátis acima de {brl(FREE_SHIPPING_ABOVE)}; abaixo disso, taxa fixa de {brl(LOCAL_SHIPPING_FEE)}."
            else:
                free = subtotal > FREE_SHIPPING_ABOVE
                info.update(product=name, subtotal=brl(subtotal),
                            shipping=("grátis" if free else brl(LOCAL_SHIPPING_FEE)))
            return info

        info = {
            "region": f"{city} (fora de Campo Grande: Correios ou Jadlog)",
            "carriers": [
                {"name": "PAC (Correios)", "deadline": "5 a 12 dias úteis"},
                {"name": "SEDEX (Correios)", "deadline": "2 a 5 dias úteis"},
                {"name": "Jadlog (.package)", "deadline": "3 a 8 dias úteis"},
            ],
            "all_include": "rastreamento e seguro",
            "price": "O valor é calculado pelo CEP, peso e dimensões do produto no fechamento do pedido. "
                     "Você NÃO tem o valor: não invente.",
            "note": "Se a cidade pertencer à região metropolitana de Campo Grande, a equipe confirma a regra local.",
        }
        if name:
            info["product"] = name
        if large:
            info["large_item"] = "Instrumento de grande porte: pode exigir frete especial com cotação individual."
        return info

    def get_order_status(order_id: int, contact: str):
        """Look up an order. It only works if the customer proves identity.

        Ask the customer for the order number AND the e-mail or phone used in the purchase.
        Never show order data without a successful result from this tool.

        Args:
            order_id: The order number.
            contact: E-mail or phone (with area code) registered on that order.
        """
        if state.failed_verifications >= 3:
            return {"verified": False, "locked": True,
                    "message": "Muitas tentativas sem sucesso. Não tente de novo: ofereça atendimento humano (escalate_to_human)."}

        order = store.orders.get(int(order_id))
        customer = store.customers.get(order.customer_id) if order else None
        if not (customer and _contact_matches(customer, contact)):
            state.failed_verifications += 1
            # Same answer if the order does not exist or the contact is wrong: do not leak anything.
            return {"verified": False, "message": "Não foi possível confirmar este pedido com os dados informados."}

        state.failed_verifications = 0  # an honest typo should not lock the customer out for good
        today = now_fn().date()
        result = {
            "verified": True,
            "customer_first_name": customer.name.split()[0],
            "order_id": order.id,
            "status": order.status,
            "status_text": ORDER_STATUS.get(order.status, order.status),
            "order_date": order.date,
            "days_since_order": (today - date.fromisoformat(order.date)).days,
            "items": [{"name": store.products[pid].name, "quantity": q} for pid, q in order.items],
            "total": brl(order.total),
            "payment": _payment_label(order.payment_method),
            "tracking_code": order.tracking_code,
            "estimated_delivery": order.estimated_delivery,
            "notes": order.notes,
            "today": today.isoformat(),
            "date_info": "O sistema só tem a data do pedido e a PREVISÃO de entrega. Não tem a data de envio, "
             "a data real de entrega nem histórico de rastreio. Nunca diga desde quando foi enviado, "
             "em que dia foi entregue ou se houve atualização. "
             "Para devolução, só vale a data de recebimento que o CLIENTE informar.",
            }
        
        if order.estimated_delivery:
            result["days_since_estimated_delivery"] = (today - date.fromisoformat(order.estimated_delivery)).days
        stuck = order.status in ("pending", "confirmed", "shipped") and (
            result["days_since_order"] > STALE_ORDER_DAYS or result.get("days_since_estimated_delivery", 0) > 0)
        if stuck:
            result["attention"] = (
                "O pedido está neste status há mais tempo do que o esperado. Informe os dados do sistema com "
                "transparência, NÃO invente o motivo e ofereça encaminhar para a equipe (escalate_to_human).")
        if order.status == "delivered":
            result["return_info"] = (
                f"O sistema só tem a data ESTIMADA de entrega, não a data real de recebimento. "
                f"Arrependimento: {REGRET_DAYS} dias corridos após o recebimento. "
                f"Defeito: {DEFECT_DAYS} dias após a compra. Peça a data real em que o cliente recebeu.")
        return result

    def consult_policies(question: str):
        """Search the store manual: returns, exchange, warranty, payment rules, shipping, hours, address,
        phone, promotions rules, privacy. Use it BEFORE answering any question about store rules.

        Args:
            question: Keywords in Portuguese using the manual's words, e.g. "devolução arrependimento prazo",
                "garantia defeito", "horário sábado", "endereço telefone".
        """
        found = policies.search(question)
        if not found:
            return {"results": [], "message": "Nada encontrado no manual para essa pergunta. Não invente: "
                    "diga que vai confirmar com a equipe (escalate_to_human).",
                    "available_sections": section_titles(policies)}
        return {"results": found}

    def escalate_to_human(category: str, summary: str, customer_contact: str = ""):
        """Register a request for the human team. Use it for: complaints, starting a return/cancellation/refund,
        a defect claim, an order problem, or any question the manual does not answer.
        You cannot cancel, refund or change anything yourself.
        For a return, call it only after the customer said when they received the order and clearly asked to open the return.

        Args:
            category: One of "reclamacao", "devolucao", "cancelamento", "defeito", "pedido", "outro".
            summary: What the customer needs, in one or two clear sentences (order number if known).
            customer_contact: Phone or e-mail the team can use to answer, if the customer gave one.
        """
        moment = now_fn()
        ticket = f"ATD-{moment:%y%m%d-%H%M%S}-{len(state.tickets) + 1}"
        record = {"ticket": ticket, "time": moment.isoformat(timespec="seconds"), "session": state.session_id,
                  "category": category, "summary": summary, "customer_contact": customer_contact}
        state.tickets.append(record)
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with open(runtime_dir / "handoffs.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"ticket": ticket,
                "message": "Pedido registrado. A equipe responde em até 24 horas úteis (manual 7.3). "
                           "Diga ao cliente o número do protocolo."}

    return [search_products, simulate_payment, get_shipping_info, get_order_status, consult_policies,
            escalate_to_human]


# ------------------------------------------------------------------ small private helpers

def _catalog_summary(store: Store) -> list[dict]:
    summary = []
    for cid, name in store.categories.items():
        items = [p for p in store.products.values() if p.category_id == cid and p.available]
        if items:
            prices = [price_block(store, p)["final_price"] for p in items]
            summary.append({"category": name, "available_products": len(items),
                            "from": brl(min(prices)), "to": brl(max(prices))})
        else:
            summary.append({"category": name, "available_products": 0})
    return summary


def _digits(text: str) -> str:
    return "".join(c for c in text if c.isdigit())


def _contact_matches(customer, contact: str) -> bool:
    contact = (contact or "").strip().lower()
    if "@" in contact:
        return contact == customer.email.lower()
    digits = _digits(contact)
    return len(digits) >= 10 and _digits(customer.phone).endswith(digits[-11:])


def _payment_label(method: str) -> str:
    if method.startswith("credit_"):
        return f"Cartão de crédito em {method.split('_')[1]}"
    return {"pix": "PIX", "boleto": "Boleto", "debit": "Cartão de débito"}.get(method, method)
