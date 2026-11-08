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

A imutabilidade vale para o tipo atribuido pela triagem em diante. Prefixo
num issue ainda nao triado (com `needs-triage` e nenhum label de estado
posterior) e **sugestao** de quem o criou: a `issue-triage` o usa como
insumo, decide o tipo pelo proprio criterio e pode troca-lo, substituindo o
prefixo (nunca empilhando dois). `[SUB-TASK]` e excecao: nasce da
`issue-break-down` e nunca passa pela triagem. Reclassificar issue ja triado
continua fora: correcao vira issue nova (regra 2).

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
| `needs-refinement` | Falta lapidar requisitos / esclarecer a solicitacao | `/issue-refinement`, em rodadas: `go` dispara a primeira; cada resposta humana a uma pergunta dispara a proxima | `FBCA04` | Falta lapidar requisitos ou esclarecer a solicitacao |
| `needs-break-down` | Escopo entendido, falta quebrar em sub-tasks | `/issue-break-down` | `FBCA04` | Escopo entendido, falta quebrar em sub-tasks |
| `ready-for-agent` | Pronto para o agente executar: um pontual, ou um pai cujas sub-tasks o agente executa uma a uma, em cadeia, empilhando os PRs | Humano aplica o label `go` (skill `issue-remote-implement` no pontual; o planner do workflow num pai) | `0E8A16` | Pronto para o agente executar |
| `ready-for-human` | Unidade executavel exclusivamente humana; o agente so orienta | Execucao humana | `1D76DB` | Unidade executavel exclusivamente humana; o agente so orienta |
| `awaiting-pr-review` | Implementacao concluida pelo agente; PR aberto e pronto para analise | Humano revisa e faz merge do PR. Numa sub-task, o PR e uma camada da stack do pai: revisa-se a stack de baixo para cima. PR fechado sem merge devolve o issue a `ready-for-agent` (pontual e pai) ou a nenhum label (sub-task), pelo workflow (regra 2) | `5319E7` | Implementacao concluida pelo agente; PR aberto e pronto para analise |
| `wontfix` | Nao sera feito: rejeitado ou ja implementado. Terminal: a issue e fechada com esse label e vale como precedente de rejeicao | — | `FFFFFF` | Nao sera feito |
| `deferred` | Despriorizado: nao sera feito agora. Terminal como `wontfix`, mas a issue vale como referencia, nunca como precedente, e pode voltar | Nenhum. Reabrir e decisao humana (regra 4) | `CFD3D7` | Despriorizado: nao agora, pode voltar |

## Label de trabalho

`work-in-progress` nao e estado: nao diz o proximo passo da issue, e sim que
um worker esta atuando nela **agora**. Por isso convive com o label de estado
vigente, assim como o `awaiting-reply` (ver "Label de espera").

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `work-in-progress` | Worker em execucao nesta issue. Num pai com sub-tasks: a cadeia de sub-tasks esta rodando (ou esperando resposta numa sub-task) | O workflow do worker, no inicio e no fim da execucao — nenhuma skill o troca. Num pai, o planner o aplica no `go` e o tira quando a cadeia completa ou para | `D93F0B` | Worker em execucao nesta issue |

Issue com `work-in-progress` nao dispara outro worker: os gatilhos dos
workflows chamadores filtram por ele, e o workflow reutilizavel confere de
novo antes de comecar (guarda de concorrencia). Num pai, o label atravessa
varias runs: fica entre uma sub-task e a seguinte e enquanto uma sub-task
espera resposta humana. Para abandonar uma cadeia, o humano tira o label na
mao.

## Label de partida

`go` tambem nao e estado: e o "pode seguir" do humano. O estado diz em que
etapa a issue esta; o `go` diz que a etapa desse estado pode rodar agora. E o
unico sinal que inicia a implementacao, e o que destrava um estado aplicado
por token de workflow ou de agente (label aplicado por token nao gera
evento). Issue sem label de estado com `go` vai para a triagem, com uma
excecao: `[SUB-TASK]` nao tem label de estado por desenho, e o `go` nela
roda so ela (ver "Pai e sub-tasks").

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `go` | Pode seguir: roda a etapa do estado atual | Aplica: um humano. Remove: o workflow, ao comecar a rodada — nenhuma skill o toca | `3FB950` | Pode seguir: roda a etapa do estado atual |

## Label de volta

`undo` tambem nao e estado: e o "volta um passo" do humano. Desfaz a
**ultima mudanca de label de estado feita por uma etapa** (triagem,
refinamento ou quebra) e deixa o issue parado no estado de antes, esperando
`go`. Quem roda e o workflow `issue-undo.yml` (sem agente), destino
`issue-undo` do router.

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `undo` | Desfaz a ultima etapa: volta o issue ao estado anterior | Aplica: um humano. Remove: o workflow, ao comecar a reversao, como o `go` — nenhuma skill o toca | `E4E669` | Desfaz a ultima etapa: volta o issue ao estado anterior |

O que cada `undo` desfaz:

- **refinamento**: o issue volta de `needs-break-down` a `needs-refinement`.
  Nada mais muda;
- **quebra**: o pai volta de `ready-for-*` a `needs-break-down`. Cada
  sub-task criada pela quebra sai da lista de sub-issues do pai, perde as
  dependencias `blocked_by` e e fechada como "not planned" (a ja fechada
  fica fechada);
- **triagem**: ainda nao suportado. O `undo` cuja ultima etapa e a triagem
  e recusado com um comentario, sem mudar nada.

Rodada que terminou em pergunta nao mudou o estado e nao conta: o `undo`
desfaz a mudanca anterior a ela, e o `awaiting-reply` sai junto. As
mudancas do proprio `undo` tambem nao contam: aplicar `undo` de novo desfaz
a etapa anterior a ja desfeita (um pai que voltou da quebra a
`needs-break-down` vai a `needs-refinement`). A ultima etapa sai dos
comentarios de etapa do issue (`## Triagem`, `## Refinamento`, `## Quebra`),
e cada reversao posta um comentario novo dizendo o que foi desfeito e para
qual estado o issue voltou, sem `@`. Os comentarios anteriores ficam como
historico.

O `undo` e recusado, com um comentario que diz o motivo e o caminho e sem
mudar label de estado, quando:

- a implementacao comecou: issue em `awaiting-pr-review`, pai com alguma
  sub-task com PR aberto ou mergeado, ou a ultima mudanca de estado foi a
  devolucao do `pr-closed.yml`. Caminho: fechar o PR sem merge;
- o issue e `[SUB-TASK]`, esta em `needs-triage` (nada a desfazer) ou esta
  fechado.

Com `work-in-progress`, o `undo` nao roda na hora e nao e descartado: a
rodada de triagem, refinamento ou quebra que esta rodando o processa ao
terminar, e ele pode desfazer a mudanca que essa rodada acabou de fazer.
Nenhuma run e cancelada. Num pai com a cadeia de sub-tasks viva
(`ready-for-agent` + `work-in-progress`) ele nao roda: para desfazer a
quebra, tire o `work-in-progress` do pai para abandonar a cadeia (ver
"Label de trabalho") e aplique `undo` de novo.

## Label de espera

`awaiting-reply` tambem nao e estado: diz que a ultima rodada terminou em uma
pergunta impeditiva e que a vez agora e de um humano. Convive com o label de
estado vigente, como o `work-in-progress`.

| Label | Significado | Quem aplica e remove | Cor | Descricao |
|---|---|---|---|---|
| `awaiting-reply` | Rodada encerrada com pergunta impeditiva; aguarda resposta humana | Aplica: a skill que posta o handoff, conforme a `issue-async-first`. Remove: o workflow, no inicio da proxima rodada | `C5DEF5` | Rodada encerrada com pergunta impeditiva; aguarda resposta humana |

Lendo os labels juntos:

- `needs-triage` + `awaiting-reply` — esperando o humano responder; a
  resposta dispara a proxima rodada;
- `needs-triage` + `work-in-progress` — worker atuando agora;
- `needs-triage` sozinho — esperando `go` para a triagem rodar;
- `needs-refinement` + `work-in-progress` + `undo` — o `undo` chegou durante
  a rodada e sera processado quando ela terminar;
- `needs-break-down` sozinho, logo depois de um comentario `## Undo` — a
  quebra foi desfeita; esperando `go` para quebrar de novo.

## Labels em PR

Num PR, so os dois labels que nao sao estado valem, com o mesmo significado:
`work-in-progress` (a correcao do `pr-fix` esta rodando no PR) e
`awaiting-reply` (a correcao parou numa pergunta; qualquer comentario humano
no PR dispara a proxima rodada). Quem aplica e remove e o mesmo do issue.
PR nao recebe label de estado nem `go`: o estado da implementacao continua
no issue (`awaiting-pr-review`), e a correcao parte de uma review ou de um
comentario que cita `@claude`.

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
(`blocked_by`). A implementacao de um pai e uma **cadeia**: o workflow
implementa as sub-tasks uma por vez, cada uma numa run, e empilha os PRs
numa stack do GitHub (ver `issue-git-flow`). Os labels se dividem assim:

- **O pai carrega o estado.** Sai da quebra com `ready-for-*` e fica nele
  enquanto as sub-tasks andam. Um `go` no pai inicia a cadeia inteira; o
  pai ganha `work-in-progress` enquanto ela roda.
- **A sub-task nasce sem label de estado.** A ordem vem dos bloqueios e da
  ordem das sub-issues; a proxima e a primeira sem PR cujos bloqueadores ja
  tem PR ou fecharam. Um bloqueio so diz quem vem antes: cada camada enxerga
  o codigo de todas as anteriores, sem esperar merge.
- **A sub-task ganha `awaiting-pr-review`** quando o PR dela abre. Ganha
  `awaiting-reply` quando a rodada dela para numa pergunta; a resposta roda
  a sub-task de novo e a cadeia segue.
- **Cada camada pede review assim que o PR dela abre** (`remote-to-pr`): o
  PR de cada camada da stack pede review do responsavel do pai, herdado
  pela sub-task, com `@` num comentario no PR quando o pedido falha. A
  revisao anda de baixo para cima enquanto a cadeia ainda roda.
- **`go` numa sub-task roda so ela**, como mais uma camada da stack. Nao
  roda sub-task com PR aberto, humana ou bloqueada por outra ainda sem PR.
- **O pai ganha `awaiting-pr-review`** quando toda sub-task tem PR: a stack
  esta completa, o topo carrega `Closes #<pai>` e o `work-in-progress` sai.
  O merge do topo fecha o pai.

Lendo os labels de um pai:

- pai `ready-for-agent` sozinho: aplique `go` para iniciar (ou retomar) a
  cadeia;
- pai `ready-for-agent` + `work-in-progress`: cadeia rodando. Se uma
  sub-task esta com `awaiting-reply`, a cadeia espera a resposta nela;
- pai `awaiting-pr-review`: stack completa, esperando revisao e merge.

O comentario de status do planner, no pai, mostra a camada, o PR e o estado
de cada sub-task e por que a cadeia parou, quando parou. Ele e editado a
cada rodada, sem `@`, e editar nao notifica ninguem. Por isso, com o pai em
cadeia, o planner posta tambem um **comentario novo no pai** que marca o
responsavel do pai em dois momentos:

- **cadeia parada** (falha ao empilhar, rodada sem PR e sem pergunta,
  sub-task humana ou bloqueio externo): traz o motivo e pede `go` no pai
  para retomar. Toda parada gera um aviso novo, mesmo repetindo o motivo;
- **stack completa** (o pai ganha `awaiting-pr-review`): pede a revisao da
  stack de baixo para cima.

Despacho da proxima e espera (resposta numa sub-task, worker rodando) nao
avisam: na espera por resposta, quem avisa e o handoff da sub-task. Sem
responsavel, o aviso sai mesmo assim e diz isso. Pai fora da cadeia so tem
o status atualizado.

## Regras

1. **Um label de estado por vez.** Ao mover a issue de estagio, remova o label
   de estado atual e aplique o novo na mesma operacao.
2. **O fluxo so anda para frente:**
   `needs-triage → needs-discovery → needs-refinement → needs-break-down →
   ready-for-* → awaiting-pr-review` e, por fim, issue fechada (merge do PR ou
   fechamento manual). `awaiting-pr-review` so vem de `ready-for-agent` (ou,
   numa sub-task, de nenhum label): a `issue-remote-implement` o aplica ao
   abrir o PR, e o planner o aplica no pai quando a stack completa.
   **Excecao: PR fechado sem merge volta um passo.** O workflow
   `pr-closed.yml` (sem agente) devolve `awaiting-pr-review` a
   `ready-for-agent` no pontual e no pai, ou a nenhum label na sub-task, e
   comenta apontando o PR fechado. Vale para cada issue do `Closes` do PR
   que esta aberto, em `awaiting-pr-review`, sem `work-in-progress` e sem
   outro PR aberto que o declare, e para o pai do `Parte de` que esta em
   `awaiting-pr-review`. Nada dispara sozinho: um `go` retoma a
   implementacao (no pai, a cadeia).
   **Excecao: o label `undo` volta uma etapa.** O workflow `issue-undo.yml`
   (sem agente) desfaz a ultima mudanca de estado feita por uma etapa: o
   refinamento (`needs-break-down` volta a `needs-refinement`) ou a quebra
   (`ready-for-*` volta a `needs-break-down`, e as sub-tasks da quebra saem
   do pai e fecham como "not planned"). Implementacao comecada, `[SUB-TASK]`,
   `needs-triage` e issue fechado recusam; ver "Label de volta". Nada dispara
   sozinho: um `go` roda a etapa do estado de novo.
   `wontfix` e `deferred` podem vir de qualquer estagio:
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
   nao e editado por skill: a padronizacao vale para a criacao. Quem cria
   a tabela inteira de uma vez e corrige os existentes e o `doctor`
   (`scripts/doctor.py fix <owner/repo> --only labels`).
6. **`work-in-progress`, `awaiting-reply` e `priority` ficam fora destas
   regras.** Nao sao labels de estado — ver as secoes "Label de trabalho",
   "Label de espera" e "Label de prioridade" acima. Nenhum dos tres conta
   como label de estado nem e trocado junto com ele. Nenhuma skill aplica ou
   remove `work-in-progress`; o `awaiting-reply` so e aplicado pela skill que
   encerra a rodada com pergunta impeditiva; o `priority` segue a secao
   "Label de prioridade". `go` e `undo` tambem nao sao estado: so um humano
   os aplica e so o workflow os remove.
