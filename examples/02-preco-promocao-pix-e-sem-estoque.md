# Preço, PIX, promoção ativa e produto sem estoque

- **Objetivo:** Preço de tabela, desconto de PIX, regra de que PIX não soma com promoção e item sem estoque.
- **Data e hora simuladas:** 10/03/2026 14:00 (horário de Campo Grande)
- **Modelo:** `gemini-3.5-flash-lite`
- **Gerado por:** `scripts/run_scenarios.py` em 04/11/2026 10:39

---

**Tom:** Oi! Eu sou o Tom, assistente virtual do Empório da Música. Como posso te ajudar hoje?

**Cliente:** Quanto custa o Takamine GD20?

```text
ferramenta: search_products(include_unavailable=True, query='Takamine GD20')
```

**Tom:** O Takamine GD20 custa R$ 2.199,00 à vista ou a prazo. Se pagar no PIX, sai por R$ 2.089,05.

Quer conferir as opções de parcelamento ou saber o prazo de entrega para sua cidade?

**Cliente:** E se eu pagar no pix?

```text
ferramenta: simulate_payment(product_id=95, quantity=1)
```

**Tom:** No PIX tem 5% de desconto, então o valor fica R$ 2.089,05.

Posso te ajudar com mais alguma coisa?

**Cliente:** E o Taylor 110e? Vi que tava em promoção, no pix fica ainda mais barato né?

```text
ferramenta: search_products(query='Taylor 110e', include_unavailable=True)
```

**Tom:** O Taylor 110e está em promoção por R$ 5.519,08 (o preço original era R$ 5.999,00, com um desconto de 8%). Como ele já está com preço promocional, o desconto de PIX não se aplica sobre esse valor, tá? 

Posso te ajudar com mais alguma coisa?

**Cliente:** Tem o violão Giannini GF-3D aí?

```text
ferramenta: search_products(include_unavailable=True, query='Giannini GF-3D')
```

**Tom:** O Giannini GF-3D Dreadnought Sunburst está sem estoque no momento. 

Se quiser, temos algumas alternativas parecidas:
- Shelby SGD-195E Elétrico Aço Sunburst por R$ 799,00
- Tagima Dallas Tuner Aço Natural por R$ 749,00
- Yamaha C70 Nylon Natural por R$ 849,00

Gostaria de ver detalhes de alguma dessas opções?
