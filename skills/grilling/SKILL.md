---
name: grilling
description: Questionamento em lote para lapidar uma solicitacao ou decisao - monta a fronteira de decisoes em aberto, pergunta tudo de uma vez com recomendacao, e reserva fatos para investigacao propria. Use ao extrair detalhes ou stress-testar uma ideia antes de escrever requisitos.
---

# Grilling

Extrair do humano as decisoes que faltam para uma solicitacao parar de
balancar — as perguntas que derrubariam o trabalho depois de pronto, feitas
antes de comecar.

## Fatos sao seus; decisoes sao do humano

Antes de formular qualquer pergunta, investigue: o que o ambiente responde
(codigo, issues, configuracao, historico) e obrigacao sua descobrir. So chega
ao humano o que e genuinamente dele — escolha de produto, prioridade,
tolerancia a risco, intencao.

## A fronteira

Pense nas decisoes em aberto como uma arvore: cada resposta destrava outras
perguntas. A **fronteira** e o conjunto de perguntas que ja podem ser feitas
agora, sem chutar respostas que ainda nao vieram.

- Pergunte a fronteira **inteira em uma unica rodada** — em canal assincrono,
  dentro do handoff da skill `issue-async-first`.
- Pergunta que depende de outra ainda aberta pertence a proxima rodada, nao a
  esta.
- So entram perguntas que **mudam o que sera construido**; curiosidade nao
  entra.

## Formato

Numere as perguntas e de sempre sua recomendacao — e o que permite o humano
responder em segundos ("1 e 2 ok, 3 vai de B"):

```markdown
**Q1 — <titulo curto>:** <pergunta especifica; com opcoes quando ajudar>
➡️ Recomendacao: <sua recomendacao e por que, em uma frase>
```

## Fim

O grilling termina quando a fronteira esvazia: toda decisao visitada, nada
assumido em silencio. Recebeu respostas? Recompute a fronteira — respostas
novas destravam (ou criam) perguntas — e repita ate esvaziar.
