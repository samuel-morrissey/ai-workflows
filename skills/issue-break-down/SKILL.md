---
name: issue-break-down
description: Quebra um issue needs-break-down em sub-tasks - fatias verticais que vao para producao sozinhas, cada uma com brief e criterios de aceite, ligadas ao pai como sub-issues com bloqueios nativos, e entrega o pai em ready-for-agent ou ready-for-human.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh issue create:*) Bash(gh issue edit:*) Bash(gh issue comment:*) Bash(gh issue close:*) Bash(gh label list:*) Bash(gh label create:*) Bash(gh api:*) Bash(gh pr list:*) Bash(gh pr view:*) Bash(git log:*) Read Grep Glob
---

# Break down

Transforma um issue de escopo entendido em **sub-tasks**: cada uma vira um
PR, cabe numa sessao de agente e pode ir para producao sozinha. O pai vira o
alvo da implementacao (label `go` no pai): o workflow executa as sub-tasks
uma a uma, na ordem dos bloqueios, cada uma numa run, e empilha os PRs numa
stack do GitHub em que cada camada nasce da anterior (ver `issue-git-flow`).

Siga estas skills:

- `issue-labeling`: tipos, labels e transicoes. Invoque antes de mexer em
  label.
- `issue-async-first`: intervencao humana.

O formato de brief esta em [AGENT-BRIEF.md](../issue-triage/AGENT-BRIEF.md).
Leia antes de escrever a primeira sub-task.

## Argumento

`$issue` — o numero do issue a quebrar.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue.

## Passos

1. **Leia o issue e confira se esta apto:**

   ```bash
   gh issue view $issue --json number,title,body,labels,state,url,comments
   gh api "repos/{owner}/{repo}/issues/$issue/sub_issues" --jq '.[].number'
   ```

   Apto exige label `needs-break-down` e nenhuma sub-issue ainda. Fora disso,
   comente o estado atual e pare. Isso evita duplicar sub-tasks numa rodada
   repetida.

   Issue com `wontfix` ou `deferred`: complete o fechamento da regra 4 da
   `issue-labeling` e pare.

   A fonte do escopo depende do tipo:

   - `[SPEC]`: o comentario `## Refinamento` e o contrato;
   - tipo pontual: o corpo e a leitura de codigo do `## Triagem`.

   Respostas humanas posteriores (de um handoff desta skill) tambem valem.

2. **Investigue o codigo ate o nivel de brief.** Para cada parte do escopo:
   onde vive hoje, quais contratos mudam, quais dados existentes ficam
   inconsistentes e quais telas e funcoes leem o que muda. Pronto quando toda
   secao do escopo tem um lugar no codigo e um criterio verificavel.

3. **Fatie.** Cada sub-task e uma **fatia vertical**: passa por todas as
   camadas que o comportamento dela precisa (regra, funcao de servidor, tela,
   docs) e entrega algo observavel. Para cada fatia, teste:

   - **Vai para producao sozinha.** Depois do merge dela, e antes das
     seguintes, o sistema funciona. Comportamento antigo que ainda nao foi
     trocado continua igual. Ex.: com uma trilha so, o evento se comporta
     como hoje.
   - **Caminho antes da mudanca.** Se a fatia B cria um estado que so a fatia
     A sabe tratar, A vem antes. Ex.: o fluxo de pagar reserva sem pedido vem
     antes do checkout que comeca a criar reservas sem pedido.
   - **Migracao junto de quem precisa dela.** A migracao de dados entra na
     fatia que primeiro depende do dado no formato novo.
   - **Docs junto de quem muda o conceito.** Glossario e ADR entram na fatia
     que muda o conceito, nao numa fatia de docs no fim.
   - **Cabe num PR revisavel.** Fatia que precisa de varias sessoes de agente
     se divide de novo.

   Escolha o menor numero de fatias que passa em todos os testes. Bloqueio
   so onde ha dependencia real: fatias independentes ficam em paralelo.

   Ficou uma decisao de produto que o escopo nao cobre? Ela e impeditiva:
   pergunte seguindo `grilling` e `issue-async-first`, aplique `awaiting-reply`
   e pare sem criar sub-task. O label continua `needs-break-down`.

4. **Crie as sub-tasks**, na ordem de execucao. Titulo `[SUB-TASK] <o que a
   fatia entrega>`. O corpo segue o brief completo do AGENT-BRIEF.md, trocando
   a citacao do original por uma linha que liga ao pai:

   ```markdown
   Parte de #<pai> (<secoes do refinamento que esta fatia cobre, com link>).
   ```

   Sub-task nasce **sem label de estado**. Quem marca o progresso dela e a
   implementacao (ver `issue-labeling`).

   ```bash
   gh issue create --title "[SUB-TASK] ..." --body-file - <<'EOF'
   ...brief...
   EOF
   ```

5. **Ligue ao pai e marque os bloqueios** com os mecanismos nativos do GitHub.
   Os dois pedem o **id de banco** do issue, nao o numero:

   ```bash
   id() { gh api "repos/{owner}/{repo}/issues/$1" --jq .id; }
   gh api --method POST "repos/{owner}/{repo}/issues/$issue/sub_issues" -F sub_issue_id=$(id <sub>)
   gh api --method POST "repos/{owner}/{repo}/issues/<sub>/dependencies/blocked_by" -F issue_id=$(id <bloqueador>)
   ```

   Adicione as sub-issues na ordem de execucao: a implementacao desempata por
   essa ordem. Como cada camada da stack enxerga o codigo das anteriores, um
   bloqueio so precisa dizer quem vem antes; nao marque bloqueio onde a
   ordem das sub-issues ja basta.

6. **Entregue o pai pronto para executar.** O label vai no **pai**:

   - `ready-for-agent`, se ao menos uma sub-task e de agente;
   - `ready-for-human`, se todas sao humanas (criterio de executor do
     AGENT-BRIEF.md).

   ```bash
   gh issue edit $issue --add-label ready-for-agent --remove-label needs-break-down
   ```

   Comente no pai:

   ```markdown
   ## Quebra

   | Ordem | Sub-task | Bloqueada por |
   |---|---|---|
   | 1 | #<n> <titulo curto> | — |
   | 2 | #<n> <titulo curto> | #<n> |

   **Por que nessa ordem:** <o que cada bloqueio protege, em uma ou duas frases>
   **Proximo passo:** aplique o label `go` neste issue. O agente implementa
   as sub-tasks uma por vez, nessa ordem, e empilha os PRs numa stack; este
   issue recebe um comentario de status a cada rodada.
   **Antes do `go`:** discordou de uma fatia? Edite o corpo da
   sub-task. O implement le o corpo na hora de rodar.
   ```

7. Responda com a URL do comentario e a lista de sub-tasks.

A quebra esta completa quando o pai tem `ready-for-*` no lugar de
`needs-break-down`, toda sub-task esta ligada a ele como sub-issue na ordem de
execucao, todo bloqueio real esta marcado como dependencia nativa, toda
secao do escopo esta coberta por ao menos uma sub-task, e o comentario
`## Quebra` esta postado.

## Fora de escopo

- Implementar, criar branch ou abrir PR.
- Aplicar label de estado nas sub-tasks.
- Mudar o escopo decidido no refinamento. Discordou? Handoff, nao improviso.
