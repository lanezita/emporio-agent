# Empório da Música: customer-service agent

A text-message agent for a fictional music store in Campo Grande/MS.
The agent is called **Tom**. It answers about products, prices, stock, orders and store rules.
It talks to customers in Brazilian Portuguese, in a friendly and short style, like WhatsApp.

Technical case for the AI Engineer role at Artefact. Main language: Python.

## Quick start

You need Python 3.10 or newer and a free Gemini API key.

```bash
# 1. Create a virtual environment and install the packages
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# 2. Add your key (free key: https://aistudio.google.com/apikey)
cp .env.example .env               # Windows: copy .env.example .env
# open .env and put your key in GEMINI_API_KEY

# 3. Chat with the agent
python -m emporio                  # add -v to see which tools the agent uses

# 4. Run the tests (no key needed)
python -m pytest
```

Useful options:

| Command | What it does |
|---|---|
| `python -m emporio -v` | Shows every tool call under the answer |
| `python -m emporio --session maria` | Saves the chat as "maria" and continues it next time |
| `python -m emporio --now 2026-03-14T15:00` | Freezes the clock (here: Saturday 15:00, store closed) |
| `python scripts/run_scenarios.py` | Runs the 5 example conversations and writes `examples/*.md` |
| `python -m emporio.data` | Prints the data-quality report |
| `GEMINI_MODEL=gemini-3.8-flash` in `.env` | Uses another model, no code change |

## How it works

```
 customer message
        |
        v
 +-------------+   system prompt: persona, rules, today's date, "store open?"
 |   Gemini    | <------------------------------------------------------------+
 +-------------+                                                               |
   |        |                                                                  |
   | text   | asks for a tool                                                  |
   v        v                                                                  |
 answer   +-----------------------------------------------+   result (JSON)    |
          | Python tools: search_products, simulate_payment,| ------------------+
          | get_shipping_info, get_order_status,            |
          | consult_policies, escalate_to_human             |
          +-----------------------------------------------+
              |                         |
        CSV data (cleaned)       store manual (PDF -> sections -> BM25)
```

The model decides **when** to call a tool. Python does **all the facts and the math**:
prices, discounts, installments, shipping, dates. The model only writes the final message.
This is how the agent follows the manual's rule: *never give price, stock or deadline without checking the system*.

| Tool | Use | Data source |
|---|---|---|
| `search_products` | Catalog, price, stock, promotions, alternatives | `products`, `categories`, `promotions` |
| `simulate_payment` | PIX price, installments, boleto | rules from manual §3 |
| `get_shipping_info` | Shipping cost and deadline by city | rules from manual §5 |
| `get_order_status` | Order status. Needs order number + e-mail or phone | `orders`, `order_items`, `customers` |
| `consult_policies` | Returns, warranty, hours, address, payment rules | the manual, by section |
| `escalate_to_human` | Complaints, returns, anything the agent cannot do | writes `runtime/handoffs.jsonl` |

## Technical decisions

### Agent approach: function calling with a hybrid data layer

I chose **native function calling** (the model returns a structured tool request, my code runs it).
The data layer is hybrid: **structured tools** for tables, **keyword retrieval (RAG)** for the manual.

- **Why not only RAG?** Prices, stock and order status must be exact and current. A table row is not a good text chunk.
- **Why not a text-to-SQL agent?** The model would write SQL over customer data. That can leak other people's orders and can join tables the wrong way. With tools, I control access, the identity check and the business rules.
- **Why not a ReAct prompt?** Native function calling gives structured arguments. It is more reliable than parsing text.
- **Why no LangChain or LangGraph?** There are 6 tools. A loop of about 25 lines (`_run_loop` in `emporio/agent.py`) is easier to read, test and debug. I would use LangGraph if the flow had many branches, long-running steps or a human approval step.

The loop is written by hand and not with the SDK's automatic mode. So I can log every tool call, stop after 6 steps, and test it with a fake server.

### Model and provider: Gemini 3.5 Flash-Lite (Google AI Studio)

- It is a **stable** model ID, it **supports function calling**, and Google's pricing page lists it as free of charge. These facts come from Google's docs (models, pricing and deprecations pages), read on 2 Nov 2026.
- The free tier means anyone can run this project without paying.
- Trade-off: Flash-Lite is the smallest tier. It is fast and cheap, but it can follow long instructions less well than a bigger model. Change `GEMINI_MODEL` to try a bigger one.
- I did not write rate-limit numbers here, because Google shows them only inside AI Studio and they change. The agent retries on temporary errors (429, 503) and shows a friendly message.
- I did not use `gemini-2.5-flash`. Google's docs say access to the 2.5 models is limited to users who already used them.

### Retrieval for the manual: sections + BM25

The manual is 8 pages. I split it by heading (about 26 sections) and search with BM25, a classic keyword ranking (`emporio/policies.py`).

- No embeddings: no extra API call, no cost, same result every time, and easy to test.
- The LLM writes the search words, so it can use the manual's vocabulary. A small synonym list helps (`devolver` -> `devolução`).
- The tests check 10 customer questions against the right section.
- Limit: keyword search does not understand meaning. With a bigger manual I would add embeddings (hybrid search).

### Prompt strategy

The system prompt (`emporio/prompt.py`) has clear blocks: persona, tone, when to use each tool, golden rules, out-of-scope, known contradictions.

- **Persona:** Tom, informal but professional ("a friend who knows music"), as the manual asks in §7.1.
- **Date, time and "is the store open?"** are calculated in Python and written in the prompt. The model never guesses them.
- **Tool routing is written in the prompt**, with a hard rule: no price, stock, deadline or order data from memory.
- **Manual contradictions** are listed in the prompt, so the agent behaves the same every time (see "Assumptions").

### Interface, history and data

- **Interface:** command line. The focus is the agent, as the case says.
- **History:** each chat is saved in `runtime/sessions/<name>.json`. When you resume, the agent reloads the visible messages. It does *not* reload old tool results or the identity check, on purpose: the customer must verify again.
- **Data handling:** standard `csv` module and dataclasses (no pandas, the data is tiny). Spaces are trimmed, empty cells become `None`, the `specs` JSON is parsed. I do not silently "fix" bad rows. `python -m emporio.data` reports them.

## Problems I found in the data and the manual

| Problem | What the agent does |
|---|---|
| Orders 3 and 20: total is different from the sum of the items | Shows the recorded total. Never recomputes it. |
| Product 130 is `coming_soon` but has stock 2. Product 136 is `discontinued` but has stock 13 | Status wins: not available. The manual (§7.3) says to offer equivalents. |
| Product 96 is `active` with stock 0 | Says "out of stock" and suggests similar available products |
| Categories "Sopro" and "Cordas Orquestrais" have no products | Says the store has none now and shows what it has |
| The manual says "more than 300 instruments", the catalog has 65 | Talks only about what the system shows |
| Customers 11 and 43 have the same e-mail | Reported. Identity check compares with the order's owner only. |
| Only an *estimated* delivery date exists | The return window counts from the real delivery, so the agent asks when the customer received it |
| Promotions have no start/end dates | `is_active` is the only source of truth. Expired promotions are never offered. |
| Two phone numbers: (67) 3341-4444 and (67) 3321-4500 | Uses 3341-4444 (cover and company data, 2 places) |
| The e-mail has an accent in §1.2 (`empóriodamusica`), which is not a valid address | Uses `contato@emporiodamusica.com.br` from the cover |
| Payment table says "credit: min installment R$ 100", §3.1 says R$ 50 / 80 / 100 by range | Uses §3.1 (more specific). See Assumptions. |

## Assumptions

The case says to assume a reasonable reading and document it. These are mine:

1. **Orders are online (distance) sales.** So the 7-day right of regret (§4.1) applies. The agent still asks when the customer received the product.
2. **Order status meaning.** `pending` = received, waiting confirmation. `confirmed` = confirmed, being prepared. `shipped` = on the way. The CSV does not explain them.
3. **"Metropolitan region of Campo Grande"** (§5.1) has no city list. I treat only Campo Grande as local. Other cities get Correios/Jadlog options and no invented price. The team confirms the rest.
4. **Installments:** I use §3.1: 2x-3x min R$ 50 per installment (my reading of "except below R$ 50"), 4x-6x min R$ 80, 7x-12x min R$ 100.
5. **Promotions:** if a product has more than one active promotion, the biggest one applies (they are not cumulative, §6.2). The PIX 5% never applies on a promotional price.
6. **A "stuck" order:** a not-final order older than 15 days, or past its estimated date, gets a warning for the agent to offer a human follow-up. The 15 days are my choice.
7. **Partner stores:** the manual asks to suggest them "when possible". No store is listed, so the agent suggests none.
8. **Holidays** are not in the data. The agent says that the team confirms special dates.
9. **Time zone:** America/Campo_Grande.

## Safety and privacy

- **Identity check:** order data is shown only if the customer gives the order number *and* the e-mail or phone of that order. Wrong data and unknown orders get the *same* answer, so nobody can discover which orders exist. After 3 failures the tool locks and offers a human.
- **The tools never return** the customer's e-mail, phone or other orders.
- **Rules live in code, not only in the prompt.** Even if the model is tricked, the order tool still refuses, and the PIX/promotion math is still right.
- **Prompt injection:** the prompt tells the agent to ignore requests to change rules or reveal instructions. Scenario 5 tests a "give me 50% discount" attempt and a request for a neighbour's order.
- **The agent cannot** cancel, refund or change anything. It registers a ticket for the team (answer within 24 business hours, §7.3).

## Tests

`python -m pytest` runs 74 tests in about 8 seconds, with no API key and no internet.

- `test_tools.py`: prices, promotions, stock, PIX, installments, shipping, identity check, privacy. One test checks that the numbers in the code (R$ 35, R$ 500, 5%, deadlines) are written in the manual text, to catch drift.
- `test_agent.py`: the agent loop with the **real SDK** against a small **fake Gemini server** (`tests/fake_gemini.py`). It checks the request (tools, system prompt), that the model's thought signature and call ids return unchanged, retries, API errors, the step limit and history saving.
- `test_policies_data_prompt.py`: policy search, data cleaning, store hours at the edge times.
- `test_scenarios.py`: the example conversations still match the CSV rows they use.

What the tests do **not** prove: how the real model behaves. For that, read the example conversations.

## Example conversations

`examples/` has 5 conversations, created by running the real model with `scripts/run_scenarios.py`:

| File | What it shows |
|---|---|
| `01-catalogo-e-parcelamento.md` | Catalog search with price filter, recommendation, installments |
| `02-preco-promocao-pix-e-sem-estoque.md` | Price, PIX, active promotion (no PIX on top), out-of-stock item |
| `03-endereco-horario-e-frete.md` | Address and hours with the store closed, shipping local vs other city |
| `04-arrependimento-devolucao.md` | **Non-trivial:** identity check, real order data, 7-day policy, ticket |
| `05-pedido-atrasado-escopo-e-seguranca.md` | **Non-trivial:** late order, accessory, off-topic, discount trick, someone else's order |

Each file has a simulated date, so store hours and order dates make sense (the data is from 2025/2026).

## Known limitations and what I would do with more time

- **Not a real WhatsApp bot.** Next step: a small FastAPI webhook for the WhatsApp Business API, with a real queue for human hand-off (today it is a `.jsonl` file).
- **No automatic quality evaluation.** I have deterministic tests and 5 conversations. With more time: a set of ~50 test questions scored by rules plus an LLM judge, run at every change.
- **Keyword retrieval only.** Embeddings or hybrid search if the manual grows.
- **Weak identity check.** E-mail or phone is enough for a prototype. A real system needs a one-time code (OTP).
- **Long chats are not trimmed or summarized.** Fine for short support chats.
- **Personal data in logs.** `runtime/` has chat logs. Production needs a retention policy (LGPD).
- **No stock reservation, payment or order creation.** The agent only answers and hands off.
- **Smallest model tier.** It may still make mistakes with unusual questions. A bigger model, or a second "check" step before sending, would reduce this.
- **Tools as an MCP server.** The six tools could be exposed with the Model Context Protocol, so other agents can reuse them.

## How I used AI assistants

I used **Claude** (Anthropic, model Claude Sonnet 5.5, in the Claude Code environment) as my coding assistant.

**What Claude did:**
- Read the case PDF, the CSV files and the manual, and looked for problems in the data.
- Proposed the architecture and wrote the first version of the code, the tests and this README.
- Checked the current Gemini models and the SDK documentation before choosing the model.

**What I did:**
- I decided to use the Gemini free tier. I also decided how we worked: Claude built the prototype, and I ran it and studied it.
- I installed the project and ran the 74 tests on my computer.
- I talked to the agent with my own Gemini API key and tested it with real questions.
- After these tests, I applied the fixes in the code and in the prompt. I also ran the five example conversations with the real model.

**How the work was checked:** 74 automated tests, including tests with the real SDK against a fake local server, and the 5 conversations created with the real model.
