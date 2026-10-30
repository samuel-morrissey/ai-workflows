---
name: pr-fix
description: Corrige um PR aberto a partir de uma acao humana nele - review com Request changes, review ou comentario que cita @claude, ou resposta a um handoff da correcao. Cada pedido vira commit na branch do PR e resposta no proprio PR; conflito de merge, CI vermelho, copy e layout incluidos. Roda dentro do workflow pr-fix.
argument-hint: "[numero-do-pr]"
arguments: pr
disable-model-invocation: true
allowed-tools: Bash(gh pr view:*) Bash(gh pr diff:*) Bash(gh pr comment:*) Bash(gh pr edit:*) Bash(gh pr checks:*) Bash(gh run list:*) Bash(gh run view:*) Bash(gh issue view:*) Bash(gh issue edit:*) Bash(gh label create:*) Bash(gh api:*) Bash(git status:*) Bash(git branch:*) Bash(git switch:*) Bash(git checkout:*) Bash(git fetch:*) Bash(git merge:*) Bash(git add:*) Bash(git commit:*) Bash(git push:*) Bash(git diff:*) Bash(git log:*) Bash(git show:*) Bash(git config:*) Bash(git worktree:*) Read Grep Glob Edit Write Agent
---

# PR Fix

A rodada evolui **um PR que ja existe**. Todo commit vai na branch do PR,
por cima do que ja esta la: o historico so cresce, a base nao muda e o PR
continua o mesmo. O merge e a aprovacao sao do humano.

A unidade de trabalho e o **pedido**: uma mudanca ou uma resposta que o
humano pediu — um comentario de linha da review, um item do corpo da review,
uma frase do comentario no PR. A rodada termina quando todo pedido tem
resposta no PR.

O texto do corpo do PR e da skill `remote-to-pr` (ramo *PR existente*). O QA
independente e da skill `issue-qa`, rodada como subagente. Travou em algo
que so o humano resolve? Siga as skills `grilling` e `issue-async-first`,
com o PR como canal.

## Argumento

`$pr` — o numero do PR. Se estiver vazio, **pare e informe** que a skill
precisa do numero do PR.

## O que o workflow informa

O system prompt traz tres frases. Use os fatos delas como estao:

- **"Correcao de PR:"** — o numero, a head, a base, o **gatilho**
  (`review <id>` ou `comentario <id>`) e os issues que o PR fecha (ou
  `nenhum`). O workflow ja fez o checkout da head, com historico completo.
- **"Verificacao de qualidade:"** — os comandos da bateria, na ordem em que
  rodam. "Nenhum comando liberado": siga sem bateria e declare isso.
- **"Evidencias:"** — a pasta de evidencias (fora do workspace, nunca
  commitada), a publicacao (URL base do bucket, ou artifact da run) e as
  ferramentas liberadas para captura. Sem ferramentas, o QA nao roda.

## Passos

1. **Leia o gatilho, o PR e o contrato.**

   ```bash
   gh pr view $pr --json number,title,body,author,headRefName,baseRefName,labels,mergeable,comments,reviews,closingIssuesReferences
   ```

   - Gatilho `review <id>`: o corpo da review e os comentarios de linha dela
     (cada um com `id`, `path`, `line` e `body`):

     ```bash
     gh api repos/{owner}/{repo}/pulls/$pr/reviews/<id>
     gh api repos/{owner}/{repo}/pulls/$pr/reviews/<id>/comments
     ```

   - Gatilho `comentario <id>`: `gh api repos/{owner}/{repo}/issues/comments/<id>`.
     Se o PR tem um handoff `## Status` seu sem resposta anterior, este
     comentario e a resposta: retome do **Ao responder** do handoff.
   - Cada issue que o PR fecha: `gh issue view <n> --json title,body`. Os
     criterios de aceite dele sao o contrato que a correcao preserva.

   Pronto quando voce sabe o texto exato de cada pedido e de onde ele veio.

2. **Liste os pedidos.** Um item por pedido, com a origem (id do comentario
   de linha, ou "corpo da review", ou "comentario <id>") e o tipo, pela
   tabela **Tipos de pedido** abaixo. O PR com `mergeable: CONFLICTING`
   ganha um pedido `conflito` mesmo que ninguem o tenha escrito: sem ele o
   PR nao entra.

   Pedido com duas leituras que mudam o codigo de formas diferentes, ou que
   muda um criterio de aceite do issue, e **pedido em aberto**: entra na
   lista, nao no codigo, e vai para o handoff do passo 9. Os outros seguem.

3. **Prepare a branch.**

   ```bash
   git config user.name "claude"
   git config user.email "noreply@anthropic.com"
   git fetch origin
   git status
   ```

   A head local esta igual a `origin/<head>`. Trate o pedido `conflito`
   primeiro: os outros se apoiam no codigo ja integrado.

4. **Atenda cada pedido**, um por vez, como a tabela manda para o tipo dele.
   Um commit por pedido, com mensagem que diz o que mudou e cita a origem
   (ex.: "Ajusta o texto do botao de envio (review 123, comentario 456)").
   O codigo novo le como o codigo ao redor. Pedido `comportamento` segue
   test-first, na fronteira que o criterio nomeia.

   Pronto quando todo pedido fora dos *em aberto* tem um commit ou uma
   resposta escrita para o passo 8.

5. **Rode a bateria completa**, uma vez, no fim:

   - **Verde:** siga.
   - **Vermelho causado pelos seus commits:** corrija e rode de novo.
   - **Vermelho que ja estava vermelho na head antes da rodada** e que
     nenhum pedido cita: registre o erro exato para o comentario do passo 8
     e siga. A rodada corrige pedidos, e esse nao e um.

6. **QA, so quando a rodada mudou o que o usuario ve.** Rode quando algum
   pedido e `layout` ou `comportamento`, o PR fecha um issue com criterios
   de aceite e o system prompt lista ferramentas. Fora disso, pule e
   registre por que.

   O roteiro e o QA do PR: escreva em `<pasta>/como-testar.md` as secoes
   *Configurando o ambiente* e *Como testar* do corpo atual, atualizadas
   pelo que a rodada mudou. Faca push (passo 7) antes, para o QA chegar na
   head por nome. Use a ferramenta Agent com este prompt, preenchido, sem
   nada sobre a correcao:

   ```
   Invoque a skill issue-qa e siga-a ate o fim com estes dados:
   - Issue: #<numero>
   - Head: <head> | Base: <base>
   - Rodada: 1
   - Roteiro: <pasta>/como-testar.md
   - Pasta de evidencias: <pasta>
   - Publicacao: <frase de publicacao do system prompt>
   - Ferramentas liberadas: <lista do system prompt>
   Nao leia o diff, os commits nem o codigo-fonte. Devolva so o caminho do relatorio.
   ```

   Decida pela tabela de `<pasta>/qa-1.md`, e so por ela. Criterio `falhou`
   por causa da rodada: corrija test-first, rode a bateria, commit, push e
   faca a rodada 2 com o mesmo prompt (`Rodada: 2`). A rodada 2 encerra o
   QA, qualquer que seja o resultado; criterio ainda reprovado vira
   "Nao corrigido: <motivo>" no PR e entra no handoff do passo 9.

7. **Push na branch do PR:**

   ```bash
   git push origin HEAD:<head>
   ```

   Push recusado porque a branch andou durante a rodada: `git fetch origin`,
   `git merge origin/<head>`, a bateria de novo e push de novo.

8. **Responda no PR.**

   - **Corpo:** invoque a `remote-to-pr` no ramo *PR existente*, passando o
     numero do PR, a lista de pedidos feitos com os commits, a bateria do
     passo 5 e o relatorio do QA (ou o motivo de nao ter rodado).
   - **Cada comentario de linha** recebe uma resposta na thread dele:

     ```bash
     gh api -X POST repos/{owner}/{repo}/pulls/$pr/comments/<id>/replies -f body="<resposta>"
     ```

     Resposta de pedido feito: o que mudou e o commit (`abc1234`). Resposta
     de pedido nao feito: o motivo, em uma frase. Comentario que e resposta
     de outro (tem `in_reply_to_id`): responda na thread do comentario de
     topo, com o id dele.
   - **Comentario final**, um so, no PR:

     ```markdown
     ## Correcao

     **Gatilho:** <review <id> | comentario <id>>
     **Feito:** <um item por pedido feito: pedido → commit>
     **Nao feito:** <um item por pedido nao feito: pedido → motivo> (ou "nada")
     **Verificacao:** <comandos e resultado — ou "nenhuma: <motivo>">
     **QA:** <rodadas e resultado — ou "nao rodou: <motivo>">
     **Atencao:** o CI nao roda sozinho depois deste push — de o play
     manualmente (feche e reabra o PR, ou dispare o workflow de CI).
     ```

     Pedido do corpo da review ou do comentario geral responde aqui, no
     **Feito** ou no **Nao feito**.

9. **Handoff, quando ha pedido em aberto.** Siga a `issue-async-first` com
   o PR como canal: uma mensagem `## Status` com todos os pedidos em aberto,
   cada um como pergunta especifica, depois do comentario final. Aplique o
   label de espera no PR:

   ```bash
   gh label create awaiting-reply --color C5DEF5 \
     --description "Rodada encerrada com pergunta impeditiva; aguarda resposta humana" 2>/dev/null || true
   gh issue edit $pr --add-label awaiting-reply
   ```

   Termine a mensagem com: "responda aqui para retomar: qualquer comentario
   neste PR ja dispara a proxima rodada".

A rodada esta completa quando todo pedido da lista tem resposta no PR —
feito, com o commit, ou nao feito, com o motivo, ou em aberto no handoff —,
os commits estao em `origin/<head>`, a bateria rodou (ou foi declarada
ausente) e o comentario `## Correcao` esta no PR.

## Tipos de pedido

| Tipo | Como reconhecer | Como atender |
|---|---|---|
| `texto` | Copy, mensagem de erro, rotulo, documentacao | Edite o texto onde ele nasce (arquivo de traducao, constante, template), e todas as ocorrencias do mesmo texto. |
| `layout` | Espacamento, alinhamento, cor, ordem, responsividade | Edite o estilo ou o componente. Conta para o QA do passo 6. |
| `conflito` | `mergeable: CONFLICTING`, ou o pedido cita conflito | `git merge origin/<base>`. Em cada conflito, preserve a intencao dos dois lados; os criterios de aceite do issue desempatam. Commit do merge com a lista dos arquivos resolvidos na mensagem. |
| `gate` | CI vermelho citado ou visivel no PR | Leia o log: `gh run list --branch <head> --json databaseId,name,conclusion,headSha` e `gh run view <id> --log-failed`. Reproduza com o comando da bateria equivalente, corrija e confirme verde localmente. Check de fora do Actions: use o que `gh pr checks $pr` mostrar. |
| `comportamento` | Muda o que o usuario ou um criterio observa | Test-first na fronteira do criterio: teste falhando, minimo que passa, teste do arquivo. Conta para o QA do passo 6. |
| `pergunta` | O humano pergunta por que, ou pede explicacao | Responda na thread com o motivo, lido do codigo ou do issue. Sem commit, a menos que a resposta revele um erro: entao ele vira outro pedido. |

Pedido que muda arquivo em `.github/workflows/`: o push e recusado pelo
GitHub (o token da rodada nao tem a permissao `workflows`). Responda como
nao feito, com esse motivo, e deixe o resto da rodada seguir.

## Fora de escopo

- Abrir PR novo, trocar a base, reescrever historico (rebase, amend de
  commit ja publicado, force push), fazer merge do PR ou aprova-lo.
- Mudar criterio de aceite, escopo ou desenho que o issue define: e pedido
  em aberto, com handoff.
- Labels alem do `awaiting-reply` do handoff; titulo e corpo de issues.
- Substituir o CI: a bateria local e o primeiro filtro, o CI continua sendo
  o juiz final.
