---
name: issue-labeling
description: Vocabulario canonico do fluxo de issues - tipos (MAP, SPEC, SUB-TASK e os pontuais BUG/FEAT/REFACTOR/DOCS/INFRA/TASK), labels de estado (needs-*, ready-for-*, awaiting-pr-review, wontfix, deferred), labels de trabalho, espera e prioridade (work-in-progress, awaiting-reply, priority) e regras de transicao. Use ao aplicar, trocar ou interpretar um label ou prefixo de tipo em um issue.
---

# Labeling

> **Skill ainda nao criada:** `issue-discovery` e citada neste arquivo como
> proximo passo, mas ainda nao existe neste plugin. Ao indica-la, avise que
> nao e possivel usar a skill referenciada porque ela ainda nao foi criada.

Referencia canonica de tipos e labels do fluxo de issues. Toda skill que mexe
em labels segue este vocabulario.

## Tipos

O tipo e um **prefixo no titulo** (`[MAP] ...`) e diz o que a issue **e**.
O tipo e **imutavel**: um `[MAP]` nunca vira `[SPEC]` — ele gera filhos.

| Prefixo | Significado |
|---|---|
| `[MAP]` | Ideia nebulosa, sem arestas definidas. Nao se sabe o que sera desenvolvido |
| `[SPEC]` | Recorte de produto ja conhecido, requisitos por lapidar. Bloco de entrega deployavel |
| `[BUG]` | Pontual: comportamento errado a corrigir. O brief pede reproducao e causa |
| `[FEAT]` | Pontual: funcionalidade nova e bem delimitada (ampla seria `[SPEC]`) |
| `[REFACTOR]` | Pontual: mudanca interna sem alterar comportamento visivel |
| `[DOCS]` | Pontual: somente documentacao |
| `[INFRA]` | Pontual: CI, workflows, build, tooling, configuracao de repo |
| `[TASK]` | Pontual generica — fallback quando nenhum pontual acima encaixa |
| `[SUB-TASK]` | Unidade executavel de trabalho, que vira um PR. Filha de um pai; ver "Pai e sub-tasks" |

`[BUG]`, `[FEAT]`, `[REFACTOR]`, `[DOCS]`, `[INFRA]` e `[TASK]` sao os
**tipos pontuais**: no fluxo se comportam de forma identica (mesmos labels de
estado, transicoes e formato de brief), e onde outra skill diz "tipo pontual"
qualquer um deles vale. Escolha sempre o mais especifico — `[TASK]` e o
ultimo recurso, nunca a primeira opcao.

## Labels de estado

O estado e um **label** e diz o **proximo passo** da issue. **Cor** e
**Descricao** sao os valores canonicos para criar o label (ver regra 5).

| Label | Significado | Proximo passo | Cor | Descricao |
|---|---|---|---|---|
| `needs-triage` | Issue crua aguardando triagem. Aplicado por humano (ou issue template) | `/issue-triage` | `FBCA04` | Issue crua aguardando triagem |
| `needs-discovery` | Falta descobrir os limites do que se quer construir | `/issue-discovery` | `FBCA04` | Falta descobrir os limites do que se quer construir |
| `needs-refinement` | Falta lapidar requisitos / esclarecer a solicitacao | `/issue-refinement`, em rodadas: cada comentario humano dispara a proxima | `FBCA04` | Falta lapidar requisitos ou esclarecer a solicitacao |
| `needs-break-down` | Escopo entendido, falta quebrar em sub-tasks | `/issue-break-down` | `FBCA04` | Escopo entendido, falta quebrar em sub-tasks |
| `ready-for-agent` | Pronto para o agente executar: um pontual, ou um pai cujas sub-tasks o agente executa uma a uma | Humano comenta `/implement` (skill `issue-remote-implement`) | `0E8A16` | Pronto para o agente executar |
| `ready-for-human` | Unidade executavel exclusivamente humana; o agente so orienta | Execucao humana | `1D76DB` | Unidade executavel exclusivamente humana; o agente so orienta |
| `awaiting-pr-review` | Implementacao concluida pelo agente; PR aberto e pronto para analise | Humano revisa e faz merge do PR. Em sub-task, depois comenta `/implement` no pai | `5319E7` | Implementacao concluida pelo agente; PR aberto e pronto para analise |
| `wontfix` | Nao sera feito: rejeitado ou ja implementado. Terminal: a issue e fechada com esse label e vale como precedente de rejeicao | — | `FFFFFF` | Nao sera feito |
| `deferred` | Despriorizado: nao sera feito agora. Terminal como `wontfix`, mas a issue vale como referencia, nunca como precedente, e pode voltar | Nenhum. Reabrir e decisao humana (regra 4) | `CFD3D7` | Despriorizado: nao agora, pode voltar |

## Label de trabalho

`work-in-progress` nao e estado: nao diz o proximo passo da issue, e sim que
um worker esta atuando nela **agora**. Por isso convive com o label de estado
vigente, assim como o `awaiting-reply` (ver "Label de espera").

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `work-in-progress` | Worker em execucao nesta issue | O workflow do worker, no inicio e no fim da execucao — nenhuma skill o troca | `D93F0B` | Worker em execucao nesta issue |

Issue com `work-in-progress` nao dispara outro worker: os gatilhos dos
workflows chamadores filtram por ele, e o workflow reutilizavel confere de
novo antes de comecar (guarda de concorrencia).

## Label de espera

`awaiting-reply` tambem nao e estado: diz que a ultima rodada terminou em uma
pergunta impeditiva e que a vez agora e de um humano. Convive com o label de
estado vigente, como o `work-in-progress`.

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `awaiting-reply` | Rodada encerrada com pergunta impeditiva; aguarda resposta humana | Aplica: a skill que posta o handoff, conforme a `issue-async-first`. Remove: o workflow, no inicio da proxima rodada | `C5DEF5` | Rodada encerrada com pergunta impeditiva; aguarda resposta humana |

Lendo os labels juntos:

- `needs-triage` + `awaiting-reply` — esperando o humano responder;
- `needs-triage` + `work-in-progress` — worker atuando agora;
- `needs-triage` sozinho — esperando a triagem rodar.

## Label de prioridade

`priority` tambem nao e estado: diz que o humano decidiu que esta issue vem
antes das outras no mesmo estado. Convive com o label de estado vigente.

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `priority` | Prioridade decidida pelo humano; esta issue vem antes das demais no mesmo estado | Aplica: um humano, ou a skill que troca o label de estado, na mesma operacao, quando o humano decidiu prioridade (no corpo, em comentario ou em resposta a pergunta). Remove: um humano, ou a skill que aplica `deferred` | `B60205` | Prioridade decidida pelo humano |

Prioridade e decisao de produto: nenhuma skill a infere. Sem decisao humana
registrada no issue, sem label.

## Pai e sub-tasks

A `issue-break-down` transforma um issue em **pai** de `[SUB-TASK]`s, ligadas
como sub-issues nativas do GitHub, com bloqueios como dependencias nativas
(`blocked_by`). Os labels se dividem assim:

- **O pai carrega o estado.** Sai da quebra com `ready-for-*` e fica nele
  enquanto as sub-tasks andam. O `/implement` e comentado no pai, nunca na
  sub-task.
- **A sub-task nasce sem label de estado.** "Pode ser feita agora" se le dos
  bloqueios, nao de label: e a primeira sub-task aberta, na ordem das
  sub-issues, sem bloqueio aberto e sem PR em revisao.
- **A sub-task so ganha `awaiting-pr-review`,** quando o PR dela (para a
  branch de integracao do pai) fica pronto. O merge desse PR a fecha (ver
  `issue-git-flow`).
- **O pai so ganha `awaiting-pr-review`** quando todas as sub-tasks estao
  fechadas e o PR dele, da branch de integracao para a `main`, fica pronto.

Lendo os labels de um pai:

- pai `ready-for-agent` + sub-task `awaiting-pr-review`: PR da sub-task
  esperando revisao e merge; depois, `/implement` no pai;
- pai `ready-for-agent` sem sub-task em revisao: comente `/implement` no pai;
- pai `awaiting-pr-review`: PR final esperando revisao e merge na `main`.

## Regras

1. **Um label de estado por vez.** Ao mover a issue de estagio, remova o label
   de estado atual e aplique o novo na mesma operacao.
2. **O fluxo so anda para frente:**
   `needs-triage → needs-discovery → needs-refinement → needs-break-down →
   ready-for-* → awaiting-pr-review` e, por fim, issue fechada (merge do PR ou
   fechamento manual). `awaiting-pr-review` so vem de `ready-for-agent` (ou,
   numa sub-task, de nenhum label): e a `issue-remote-implement` que o aplica
   ao abrir o PR. `wontfix` e `deferred` podem vir de qualquer estagio:
   tirar a issue do fluxo e decisao humana a qualquer momento (regra 4).
   Correcao de
   classificacao ou problema pos-merge vira **issue nova** vinculada — o label
   de uma issue existente permanece no estagio em que esta.
3. **Quem troca o label e a skill que conclui o estagio.** Cada skill entrega a
   issue ja no estado que a proxima skill espera.
4. **`wontfix` e `deferred` fecham.** Os dois sao terminais: aplique o label
   (removendo o label de estado anterior e o `priority`, se houver) e feche a
   issue no mesmo passo, com um comentario que explica o motivo. A diferenca
   esta no que a issue fechada vale depois:

   | | `wontfix` | `deferred` |
   |---|---|---|
   | Motivo | Rejeitado, ou ja implementado | Despriorizado: nao agora, talvez depois |
   | O comentario registra | Os precedentes | O estado em que a issue estava ao adiar |
   | Vale como | Precedente: pedido igual fecha como `wontfix` | Referencia: pedido igual cita a issue e segue o fluxo normal |
   | Volta? | Nao | Sim: o humano reabre, remove `deferred` e reaplica o estado registrado |

   Um humano pode aplicar qualquer um dos dois direto na issue, com ou sem
   comentario. A skill que ler a issue nesse estado completa o fechamento:
   remove o label de estado anterior e o `priority`, fecha se ainda esta
   aberta e comenta o motivo (citando o comentario humano, se houver) e, em
   `deferred`, o estado ao adiar. Depois para: a issue esta fora do fluxo.
5. **Label inexistente no repositorio: crie antes de aplicar.** Use a **Cor**
   e a **Descricao** da linha do label na tabela, exatamente — nunca um texto
   escrito a mao. Vale tambem para todo `gh label create` escrito em outra
   skill:

   ```bash
   gh label create "needs-discovery" --color FBCA04 \
     --description "Falta descobrir os limites do que se quer construir"
   ```

   `gh issue edit --add-label` falha se o label nao existe — criar primeiro
   evita perder a rodada. Label que ja existe com cor ou descricao diferentes
   nao e editado: a padronizacao vale para a criacao.
6. **`work-in-progress`, `awaiting-reply` e `priority` ficam fora destas
   regras.** Nao sao labels de estado — ver as secoes "Label de trabalho",
   "Label de espera" e "Label de prioridade" acima. Nenhum dos tres conta
   como label de estado nem e trocado junto com ele. Nenhuma skill aplica ou
   remove `work-in-progress`; o `awaiting-reply` so e aplicado pela skill que
   encerra a rodada com pergunta impeditiva; o `priority` segue a secao
   "Label de prioridade".
