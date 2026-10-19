---
name: issue-git-flow
description: Estrutura de git do fluxo de issues - nome e base de cada branch (pontual, sub-task como camada da stack do pai), vinculo entre PR e issue ou sub-issue, a stack de PRs de um pai e como cada issue fecha. Use ao criar branch, escolher a base de um PR, vincular um PR a um issue do fluxo ou ler a stack de um pai.
---

# Git flow

Branches, bases, vinculos, stack e fechamento do fluxo de issues. O formato
do texto do PR nao mora aqui: e da `to-pr` (ou da `remote-to-pr`, em fluxo
remoto).

## Branches e bases

O nome e `<tipo>-<numero>`, com o prefixo de tipo do titulo em minusculas:
`bug-42`, `feat-181`, `sub-task-187`.

| Issue | Branch | Base do PR |
|---|---|---|
| Pontual | `<tipo>-<numero>` | branch padrao |
| Primeira sub-task de um pai | `sub-task-<numero>` | branch padrao |
| Sub-tasks seguintes | `sub-task-<numero>` | a branch da **camada de baixo**: a sub-task anterior na stack |

Um pai com sub-tasks **nao tem branch nem PR proprio**: os PRs das sub-tasks
formam uma stack (abaixo), e cada camada vai para a branch padrao por si.
Quem diz qual e a camada de baixo de uma sub-task e o workflow, no modo
sub-task da `issue-remote-implement`: e a branch do PR aberto mais alto da
stack do pai, ou a branch padrao quando nao ha PR aberto. A skill usa a base
recebida, sem recalcular.

Toda branch nova nasce da ponta atualizada da sua base:

```bash
git fetch origin
git switch -c <branch> origin/<base>
```

O `fetch` importa mais numa stack: quando uma camada de baixo entra na branch
padrao, o GitHub rebaseia as de cima e os SHAs delas mudam. A base de uma
camada nova e sempre a ponta remota de agora.

## Vinculo entre PR e issue

O vinculo vai em linhas proprias, no topo do corpo do PR, antes de qualquer
secao:

| PR de | Linhas de vinculo |
|---|---|
| Pontual | `Closes #<issue>` |
| Sub-task | `Closes #<sub-task>` e `Parte de #<pai>` |
| Topo da stack (acrescentado pelo planner) | `Closes #<pai>`, acima das outras |

O `Closes` no corpo so e lido pelo GitHub em PR para a branch padrao. Numa
camada acima da primeira, a base e outra branch, e o `Closes` fica
**ignorado ate a camada chegar a branch padrao**: quando a stack sobe, o
GitHub retargeta a camada para a branch padrao e o `Closes` passa a valer,
inclusive numa camada que entra junto com as de baixo. O `Closes` fica
sempre: e por ele que a sub-task fecha e que o planner acha o PR dela.

Por isso, **todo PR do fluxo** recebe tambem o vinculo nativo pela API, logo
depois de aberto, qualquer que seja a base: assim ele aparece em
*Development* do issue antes de chegar a branch padrao. Vincule o PR a cada
issue que ele fecha (`Closes`), nunca ao pai do `Parte de`.

Rode tres comandos soltos, sem variavel de shell nem `$(...)`: a allowlist
do workflow libera `gh api`, `gh pr view` e `gh issue view` so como comando
que comeca por eles.

1. Pegue o id do PR: `gh pr view <url> --json id --jq .id`.
2. Pegue o id do issue: `gh issue view <issue> --json id --jq .id`.
3. Vincule, colando os dois ids:

   ```bash
   gh api graphql -f query='mutation { addCloseIssueReferences(input: {issueId: "<id-do-issue>", pullRequestIds: ["<id-do-pr>"]}) { clientMutationId } }'
   ```

Confira depois: `gh pr view <url> --json closingIssuesReferences` lista o
issue, em qualquer base. Nao listou? Rode a mutation de novo e confira outra
vez.

## Stack de um pai

Os PRs das sub-tasks de um pai formam uma
[stack do GitHub](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs):
uma cadeia linear em que a camada 1 aponta para a branch padrao e cada
camada seguinte aponta para a branch da anterior. A ordem das camadas e a
ordem em que os PRs foram abertos, que o planner escolhe pela ordem dos
bloqueios.

O que vale saber ao ler ou mexer numa stack:

- **Quem empilha e o planner** (`issue-remote-implement.yml`), pela API
  REST, depois que o PR existe. A skill que abre o PR nao cria stack.
- **A API nao retargeta.** Para entrar numa stack, o PR ja precisa ter como
  base a branch da camada de baixo. E o modo sub-task que garante isso.
- **Base travada.** PR empilhado nao aceita troca de base (`gh pr edit
  --base` falha). Camada errada se desfaz fechando o PR e refazendo a
  sub-task.
- **A stack tem um numero** na mesma sequencia dos issues e PRs do
  repositorio (ex.: stack #8 entre o PR #7 e o PR #9). Nao e issue nem PR:
  nao comente nem vincule nele.
- **Merge e pela interface do GitHub**, de baixo para cima. Mergear uma
  camada do meio leva as de baixo junto; mergear o topo leva tudo. O merge
  sincrono da API e o `gh pr merge` sao recusados em PR empilhado.
- **O GitHub rebaseia as camadas de cima** quando uma de baixo entra, e os
  SHAs mudam. Branch local fica para tras: `git fetch` antes de qualquer
  coisa.

Para ler a stack de um PR: `gh api repos/{owner}/{repo}/pulls/<n> --jq .stack`
(numero, posicao e tamanho; `null` fora de stack). Para listar as stacks:
`gh api repos/{owner}/{repo}/stacks`.

## Fechamento

| Issue | Fecha quando | Quem fecha |
|---|---|---|
| Pontual | o PR entra na branch padrao | o GitHub, pelo `Closes` |
| Sub-task | a camada dela entra na branch padrao, sozinha ou junto com as de cima | o GitHub, pelo `Closes` (o workflow que escuta PR mergeado so tira o `awaiting-pr-review` que sobrou) |
| Pai | o topo da stack entra na branch padrao | o GitHub, pelo `Closes #<pai>` que o planner pos no topo |
