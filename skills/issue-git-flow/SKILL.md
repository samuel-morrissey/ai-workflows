---
name: issue-git-flow
description: Estrutura de git do fluxo de issues - nome e base de cada branch (pontual, pai com sub-tasks, sub-task), vinculo entre PR e issue ou sub-issue, e como cada issue fecha. Use ao criar branch, escolher a base de um PR ou vincular um PR a um issue do fluxo.
---

# Git flow

Branches, bases, vinculos e fechamento do fluxo de issues. O formato do
texto do PR nao mora aqui: e da `to-pr` (ou da `remote-to-pr`, em fluxo
remoto).

## Branches e bases

O nome e `<tipo>-<numero>`, com o prefixo de tipo do titulo em minusculas:
`bug-42`, `spec-181`, `sub-task-187`.

| Issue | Branch | Base do PR |
|---|---|---|
| Pontual sem sub-tasks | `<tipo>-<numero>` | branch padrao |
| Pai com sub-tasks (**branch de integracao**) | `<tipo>-<pai>` | branch padrao |
| Sub-task | `sub-task-<numero>` | a branch de integracao do pai |

A branch de integracao nasce da branch padrao no primeiro `/implement` do
pai e e publicada antes da primeira sub-task. Ela recebe os merges das
sub-tasks e nada mais: commit direto nela ou na branch padrao nao existe.

Toda branch nova nasce da ponta atualizada da sua base:

```bash
git fetch origin
git switch -c <branch> origin/<base>
```

## Vinculo entre PR e issue

O vinculo vai em linhas proprias, no topo do corpo do PR, antes de qualquer
secao:

| PR de | Linhas de vinculo |
|---|---|
| Pontual | `Closes #<issue>` |
| Sub-task | `Closes #<sub-task>` e `Parte de #<pai>` |
| Pai | `Closes #<pai>` |

O `Closes` no corpo nao basta: o GitHub so o le em PR para a branch padrao.
Num PR de sub-task, a base e a branch de integracao, e o `Closes` e
**ignorado** — o PR nao aparece em *Development* do issue. O `Closes` fica
mesmo assim: e por ele que o fechamento abaixo acha a sub-task.

Por isso, **todo PR do fluxo** recebe tambem o vinculo nativo pela API, logo
depois de aberto, qualquer que seja a base. Vincule o PR a cada issue que ele
fecha (`Closes`), nunca ao pai do `Parte de`:

```bash
pr_id=$(gh pr view <url> --json id --jq .id)
issue_id=$(gh issue view <issue> --json id --jq .id)
gh api graphql -f query='
  mutation($issue: ID!, $pr: ID!) {
    addCloseIssueReferences(input: {issueId: $issue, pullRequestIds: [$pr]}) {
      clientMutationId
    }
  }' -f issue="$issue_id" -f pr="$pr_id"
```

Confira depois: `gh pr view <url> --json closingIssuesReferences` lista o
issue, em qualquer base. Nao listou? Rode a mutation de novo e confira outra
vez. O vinculo nao muda o fechamento: fora da branch padrao, o merge
continua sem fechar o issue.

## Fechamento

| Issue | Fecha quando | Quem fecha |
|---|---|---|
| Pontual | o PR entra na branch padrao | o GitHub, pelo `Closes` |
| Sub-task | o PR entra na branch de integracao | o workflow que escuta PR mergeado, pelo `Closes` do corpo; o `/implement` seguinte do pai fecha o que tiver sobrado |
| Pai | o PR dele entra na branch padrao | o GitHub, pelo `Closes` |
