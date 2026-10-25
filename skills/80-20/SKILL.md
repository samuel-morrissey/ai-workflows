---
name: 80-20
description: Modo Pareto — maior retorno com o menor esforço na tarefa dada
disable-model-invocation: true
argument-hint: <tarefa>
---

# 80/20 (Pareto)

Tarefa: $ARGUMENTS

Modo Pareto: entregar a maior parte do valor com a menor intervenção possível. O alvo é alavancagem, não completude — o usuário pediu explicitamente o ganho grande e barato, não a solução perfeita.

## Passos

1. **Diagnosticar antes de agir.** Levante as causas ou oportunidades reais — meça, leia o código, olhe dados; nada de chute — e ranqueie por impacto × esforço. Pronto quando: existe uma lista curta em que os 1–3 itens do topo explicam a maior parte do problema.
2. **Grelhar para montar o plano.** Rode uma sessão `/grilling` com o foco em Pareto: cada pergunta mira impacto × esforço — o que entrega o maior ganho com a menor intervenção, e o que pertence à cauda. O plano nasce da sessão, não antes dela; use o diagnóstico do passo 1 como matéria-prima das perguntas e recomendações. Pronto quando: o usuário confirmou o entendimento compartilhado, com topo (1–3 itens) e cauda definidos. Exceção: se a tarefa em $ARGUMENTS já pedir execução direta ("implementa", "faz direto", "analisa e aplica"), pule a sessão e siga para o passo 3.
3. **Agir só no topo da lista.** Implemente a menor mudança que captura esse impacto. Pronto quando: o ganho é verificável (medição, teste, número antes/depois) — não quando a solução está "completa".
4. **Parar no retorno decrescente.** Capturado o grosso do ganho, pare — mesmo enxergando melhorias possíveis. Elas pertencem à cauda.

## Entrega

- O que foi feito e o ganho, medido ou estimado.
- **A cauda deixada de fora**: os itens de baixo impacto que ficaram sem fazer, cada um com uma linha dizendo o que renderia e por que não valeu o esforço agora.
