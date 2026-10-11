# Git flow

Branches, bases e PRs do `/implement`.

## Branches

O nome e `<tipo>-<numero>`, com o prefixo de tipo do titulo em minusculas:
`bug-42`, `spec-181`, `sub-task-187`.

| Issue | Branch | Base do PR |
|---|---|---|
| Pontual sem sub-tasks | `<tipo>-<numero>` | `main` |
| Pai com sub-tasks (**branch de integracao**) | `<tipo>-<pai>` | `main` |
| Sub-task | `sub-task-<numero>` | a branch de integracao do pai |

A branch de integracao nasce de `main` no primeiro `/implement` do pai e e
publicada antes da primeira sub-task. Ela recebe os merges das sub-tasks e
nada mais: commit direto nela ou na `main` nao existe.

Toda branch nova nasce da ponta atualizada da sua base:

```bash
git fetch origin
git switch -c <branch> origin/<base>
```

## Fechamento

O GitHub so fecha issue por palavra-chave (`Closes #n`) quando o PR entra na
branch **padrao**. Merge de sub-task na branch de integracao **nao** fecha a
sub-task. Por isso o `/implement` fecha, no inicio de cada rodada do pai, as
sub-tasks cujo PR ja entrou na branch de integracao. O PR do pai fecha o pai
ao entrar na `main`.

## PR

Titulo: o titulo do issue, sem o prefixo de tipo.

```markdown
Closes #<issue>
Parte de #<pai>          (so em sub-task)

## O que muda
<comportamento novo, por criterio de aceite>

## Como verificar
<comandos rodados e resultado; passos manuais que o revisor deve fazer>
```

O PR do pai lista as sub-tasks que ele entrega (`#n — titulo`) em
"O que muda", e reune os passos de deploy e migracao das sub-tasks em
"Como verificar".
