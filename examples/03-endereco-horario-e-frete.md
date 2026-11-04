# Endereço, horário (loja fechada) e frete

- **Objetivo:** Informações da loja, horário com a loja fechada e cálculo de frete local e para outra cidade.
- **Data e hora simuladas:** 14/03/2026 15:00 (horário de Campo Grande)
- **Modelo:** `gemini-3.5-flash-lite`
- **Gerado por:** `scripts/run_scenarios.py` em 04/11/2026 10:40

---

**Tom:** Oi! Eu sou o Tom, assistente virtual do Empório da Música. Como posso te ajudar hoje?

**Cliente:** Boa tarde, qual o endereço da loja? Vocês estão abertos agora?

```text
ferramenta: consult_policies(question='endereço loja contato funcionamento')
```

**Tom:** Nossa loja física fica na Rua 14 de Maio, 3200, no Centro de Campo Grande - MS.

No momento estamos fechados, pois hoje é sábado e nosso atendimento presencial funciona das 09:00 às 13:00. Abrimos novamente na segunda-feira às 09:00, mas sigo por aqui para te ajudar no que precisar! 

Precisa de alguma informação sobre nossos instrumentos?

**Cliente:** E domingo, abre?

```text
ferramenta: consult_policies(question='domingo feriados funcionamento')
```

**Tom:** Não, aos domingos e feriados a loja fica fechada. Funcionamos de segunda a sexta-feira, das 09:00 às 18:00, e aos sábados, das 09:00 às 13:00.

Posso te ajudar com mais alguma dúvida?

**Cliente:** Quanto fica o frete de um ukulele Shelby SU-21S pra Campo Grande? E pra Dourados?

```text
ferramenta: search_products(query='ukulele Shelby SU-21S')
ferramenta: get_shipping_info(city='Campo Grande', product_id=119)
ferramenta: get_shipping_info(product_id=119, city='Dourados')
```

**Tom:** Para Campo Grande, o frete do ukulele Shelby SU-21S sai por R$ 35,00, com entrega feita por motoboy em 1 a 3 dias úteis.

Já para Dourados, o valor do frete depende do CEP exato e é calculado na hora do fechamento do pedido, com opções pelos Correios (PAC ou SEDEX) e Jadlog. 

Posso te ajudar com mais alguma coisa?
