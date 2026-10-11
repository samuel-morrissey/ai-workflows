---
name: issue-labeling
description: Vocabulario canonico do fluxo de issues - tipos (MAP, SPEC, SUB-TASK e os pontuais BUG/FEAT/REFACTOR/DOCS/INFRA/TASK), labels de estado (need-*, ready-for-*, awaiting-pr-review, wontfix), label de trabalho (work-in-progress) e regras de transicao. Use ao aplicar, trocar ou interpretar um label ou prefixo de tipo em um issue.
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

O estado e um **label** e diz o **proximo passo** da issue.

| Label | Significado | Proximo passo | Cor |
|---|---|---|---|
| `need-triage` | Issue crua aguardando triagem. Aplicado por humano (ou issue template) | `/issue-triage` | `FBCA04` |
| `need-discovery` | Falta descobrir os limites do que se quer construir | `/issue-discovery` | `FBCA04` |
| `need-refinement` | Falta lapidar requisitos / esclarecer a solicitacao | `/issue-refinement`, em rodadas: cada comentario humano dispara a proxima | `FBCA04` |
| `need-break-down` | Escopo entendido, falta quebrar em sub-tasks | `/issue-break-down` | `FBCA04` |
| `ready-for-agent` | Pronto para o agente executar: um pontual, ou um pai cujas sub-tasks o agente executa uma a uma | Humano comenta `/implement` (skill `issue-remote-implement`) | `0E8A16` |
| `ready-for-human` | Unidade executavel exclusivamente humana; o agente so orienta | Execucao humana | `1D76DB` |
| `awaiting-pr-review` | Implementacao concluida pelo agente; PR aberto e pronto para analise | Humano revisa e faz merge do PR. Em sub-task, depois comenta `/implement` no pai | `5319E7` |
| `wontfix` | Nao sera feito. Terminal: a issue e fechada com esse label | — | `FFFFFF` |

## Label de trabalho

`work-in-progress` nao e estado: nao diz o proximo passo da issue, e sim que
um worker esta atuando nela **agora**. Por isso convive com o label de estado
vigente, assim como o `awaiting-reply` (ver "Label de espera").

| Label | Significado | Quem aplica e remove | Cor |
|---|---|---|---|
| `work-in-progress` | Worker em execucao nesta issue | O workflow do worker, no inicio e no fim da execucao — nenhuma skill o troca | `D93F0B` |

Issue com `work-in-progress` nao dispara outro worker: os gatilhos dos
workflows chamadores filtram por ele, e o workflow reutilizavel confere de
novo antes de comecar (guarda de concorrencia).

## Label de espera

`awaiting-reply` tambem nao e estado: diz que a ultima rodada terminou em uma
pergunta impeditiva e que a vez agora e de um humano. Convive com o label de
estado vigente, como o `work-in-progress`.

| Label | Significado | Quem aplica e remove | Cor |
|---|---|---|---|
| `awaiting-reply` | Rodada encerrada com pergunta impeditiva; aguarda resposta humana | Aplica: a skill que posta o handoff, conforme a `issue-async-first`. Remove: o workflow, no inicio da proxima rodada | `C5DEF5` |

Lendo os labels juntos:

- `need-triage` + `awaiting-reply` — esperando o humano responder;
- `need-triage` + `work-in-progress` — worker atuando agora;
- `need-triage` sozinho — esperando a triagem rodar.

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
  branch de integracao do pai) fica pronto. O `/implement` seguinte do pai a
  fecha depois do merge.
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
   `need-triage → need-discovery → need-refinement → need-break-down →
   ready-for-* → awaiting-pr-review` e, por fim, issue fechada (merge do PR ou
   fechamento manual). `awaiting-pr-review` so vem de `ready-for-agent` (ou,
   numa sub-task, de nenhum label): e a `issue-remote-implement` que o aplica
   ao abrir o PR. Correcao de
   classificacao ou problema pos-merge vira **issue nova** vinculada — o label
   de uma issue existente permanece no estagio em que esta.
3. **Quem troca o label e a skill que conclui o estagio.** Cada skill entrega a
   issue ja no estado que a proxima skill espera.
4. **`wontfix` fecha.** Aplique o label e feche a issue no mesmo passo, com um
   comentario explicando o motivo e vinculando precedentes.
5. **Label inexistente no repositorio: crie antes de aplicar.** Use a cor da
   tabela e o significado como descricao:

   ```bash
   gh label create "need-discovery" --color FBCA04 \
     --description "Falta descobrir os limites do que se quer construir"
   ```

   `gh issue edit --add-label` falha se o label nao existe — criar primeiro
   evita perder a rodada.
6. **`work-in-progress` e `awaiting-reply` ficam fora destas regras.** Nao
   sao labels de estado — ver as secoes "Label de trabalho" e "Label de
   espera" acima. Nenhum dos dois conta como label de estado nem e trocado
   junto com ele. Nenhuma skill aplica ou remove `work-in-progress`; o
   `awaiting-reply` so e aplicado pela skill que encerra a rodada com
   pergunta impeditiva.
