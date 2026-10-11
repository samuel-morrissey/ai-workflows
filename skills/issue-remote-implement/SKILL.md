---
name: issue-remote-implement
description: Implementa um issue ready-for-agent - num pontual, abre o PR dele; num pai com sub-tasks, fecha as ja integradas e abre o PR da proxima sub-task sem bloqueio, ou o PR do pai quando todas fecharam. Desenvolve test-first nos criterios de aceite e roda as verificacoes de qualidade. Verificacao vermelha nao vira PR.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue comment:*) Bash(gh issue edit:*) Bash(gh issue close:*) Bash(gh label create:*) Bash(gh api:*) Bash(gh pr list:*) Bash(gh pr create:*) Bash(gh pr view:*) Bash(git status:*) Bash(git branch:*) Bash(git checkout:*) Bash(git switch:*) Bash(git fetch:*) Bash(git pull:*) Bash(git add:*) Bash(git commit:*) Bash(git push:*) Bash(git diff:*) Bash(git log:*) Bash(git config:*) Read Grep Glob Edit Write
---

# Implement

Cada rodada termina em **no maximo um PR aberto**. O merge e a revisao nao
sao daqui: o humano revisa, faz o merge e comenta `/implement` de novo para a
proxima rodada.

O alvo do `/implement` e sempre o issue com `ready-for-agent`:

- **pontual sem sub-tasks**: a rodada implementa o proprio issue;
- **pai com sub-tasks**: a rodada escolhe o que fazer, entre a proxima
  sub-task sem bloqueio e o PR do pai.

Branch, base, fechamento e formato de PR estao em [GIT-FLOW.md](GIT-FLOW.md).
Leia antes do passo 3.

Decisao a montante, execucao a jusante: o brief ja diz **o que** (criterios
de aceite) e **onde** (a fronteira em que cada criterio se observa). Voce nao
redesenha o plano: transforma o brief em codigo verificado.

Travou em algo que so o humano resolve (decisao de produto que o brief nao
cobre, acesso faltando, verificacao que nao fica verde dentro do escopo)?
Siga as skills `grilling` e `issue-async-first`: handoff completo no issue
alvo do `/implement`, `awaiting-reply` aplicado, e encerre sem abrir PR.
Termine a mensagem com: "responda e comente `/implement` aqui para retomar".

## Argumento

`$issue` — o numero do issue que recebeu o `/implement`.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue.

## Verificacao de qualidade

Os comandos de verificacao (typecheck, lint, testes) chegam por uma destas
vias, nesta ordem de preferencia:

1. **Informados pelo workflow.** O system prompt traz "Verificacao de
   qualidade: ... comandos: ..." com o que o chamador liberou. Rode
   exatamente esses, na ordem dada.
2. **Descobertos no repositorio.** Sem lista informada, procure em
   `package.json` (scripts), `Makefile`, CLAUDE.md ou na config de CI. Rode
   so o que o ambiente permitir.
3. **Nenhum.** Nao achou, ou o ambiente nao deixa rodar: siga sem
   verificacao e **declare isso** no comentario do PR. Nunca afirme que
   verificou o que nao rodou.

## Passos

1. **Leia o issue e confira se esta apto:**

   ```bash
   gh issue view $issue --json number,title,body,labels,state,url,comments
   gh api "repos/{owner}/{repo}/issues/$issue/sub_issues" \
     --jq '.[] | {number, title, state, labels: [.labels[].name]}'
   ```

   Apto exige label `ready-for-agent`. `[SUB-TASK]` nunca e alvo: comente
   apontando o pai e pare. Fora disso, comente o estado atual e pare.

   Leia tambem os comentarios: handoffs e respostas humanas de rodadas
   anteriores valem. O corpo e lido **agora**: se o humano editou o brief
   antes de comentar `/implement`, vale a versao editada.

   Sem sub-issues, e um **pontual**: a unidade da rodada e o proprio issue.
   Siga para o passo 3. Com sub-issues, siga para o passo 2.

2. **Pai: escolha a unidade da rodada.**

   1. **Feche as sub-tasks ja integradas.** Para cada sub-task aberta, procure
      PR mergeado que a feche:

      ```bash
      gh pr list --state merged --search "Closes #<sub>" --json number,baseRefName
      ```

      PR mergeado na branch de integracao do pai: feche a sub-task com
      `gh issue close <sub> --comment "Integrada em <branch> pelo #<pr>."`.

   2. **Todas fechadas:** a unidade e o **PR do pai**. Se ja existe PR aberto
      da branch de integracao, comente apontando-o e pare. Senao, rode a
      verificacao (passo 5) na branch de integracao atualizada e siga para o
      passo 6.

   3. **Senao, escolha a proxima sub-task.** E a primeira, na ordem das
      sub-issues, que esta aberta, sem `awaiting-pr-review` (sem PR
      esperando revisao), sem bloqueio aberto e cujo brief nao diz
      **Executor: humano**:

      ```bash
      gh api "repos/{owner}/{repo}/issues/<sub>/dependencies/blocked_by" --jq '.[] | {number, state}'
      ```

   4. **Nenhuma disponivel:** comente no pai o que esta esperando (PRs em
      revisao, bloqueios, sub-tasks humanas) e pare. E espera de revisao, nao
      pergunta: sem `awaiting-reply`.

   Os criterios de aceite da rodada vem do corpo da sub-task escolhida.

3. **Crie a branch** conforme o GIT-FLOW.md. Sub-task: garanta antes a branch
   de integracao do pai, criando e publicando se nao existir. Garanta
   identidade de commit antes do primeiro commit:

   ```bash
   git config user.name "claude"
   git config user.email "noreply@anthropic.com"
   ```

4. **Implemente, test-first, um criterio de aceite por vez.** Os criterios da
   unidade sao o contrato, e cada um nomeia a fronteira (seam) onde o
   comportamento se observa: funcao publica, endpoint, comando, tela. Para
   cada criterio:

   1. escreva o teste **na fronteira que o criterio nomeia** e veja falhar;
   2. implemente o minimo que o faz passar;
   3. rode o typecheck e o arquivo de teste que mexeu (nao a suite inteira).

   Criterio sem fronteira nomeada: use a fronteira mais externa que o codigo
   oferece para aquele comportamento e anote a escolha para o comentario do
   PR. Repositorio sem infra de teste: implemente cobrindo os criterios, rode
   o que existir (typecheck, lint) e anote isso tambem. Em nenhum dos dois
   casos voce para para perguntar: a fronteira e fato do codigo, nao decisao.

   Commits pequenos com mensagem clara. Estilo: o codigo novo le como o
   codigo ao redor.

5. **Verifique.** Antes de abrir o PR, rode a bateria completa dos comandos
   da secao "Verificacao de qualidade", uma vez, ao final. Resultado:

   - **Verde:** siga para o PR.
   - **Vermelho causado pela sua mudanca:** corrija e rode de novo.
   - **Vermelho fora do escopo da unidade** (ja quebrado antes de voce
     chegar, ou exige decisao que o brief nao cobre): nao abra PR. Faca push
     da branch para nao perder o trabalho, handoff `issue-async-first` no
     issue alvo com o erro exato colado e o que falta, e encerre a rodada.

   PR com verificacao vermelha nao existe nesta skill.

6. **Abra o PR** com a base e o formato do GIT-FLOW.md.

7. **Marque a unidade como em revisao.** Crie o label antes, se nao existir:

   ```bash
   gh label create awaiting-pr-review --color 5319E7 \
     --description "Implementacao concluida pelo agente; PR aberto e pronto para analise" 2>/dev/null || true
   ```

   - Pontual ou PR do pai: troque `ready-for-agent` por `awaiting-pr-review`
     no issue alvo, na mesma operacao.
   - Sub-task: aplique `awaiting-pr-review` na sub-task. O pai continua
     `ready-for-agent`.

8. **Comente no issue da unidade:**

   ```markdown
   ## Implement

   **PR:** <url>
   **Criterios cobertos:** <lista curta mapeando criterio → teste e onde foi coberto>
   **Verificacao:** <comandos rodados e resultado — ou "nenhuma: <motivo>">
   **Atencao:** o CI nao roda sozinho em PR aberto pelo agente — de o play
   manualmente (feche e reabra o PR, ou dispare o workflow de CI).
   ```

   Sub-task: comente tambem no pai, em uma linha: "#<sub> em revisao no
   <url>. Depois do merge, comente `/implement` aqui para a proxima."

A rodada esta completa quando existe exatamente um PR novo da branch da
unidade para a base do GIT-FLOW.md, cujo corpo comeca com `Closes #<unidade>`,
cujo diff cobre todos os criterios de aceite da unidade com teste na
fronteira de cada um, cuja verificacao esta verde (ou declarada ausente, com
motivo), e a unidade esta com `awaiting-pr-review` e o comentario com o link.
Os outros fins validos sao: comentario explicando por que nao ha unidade
disponivel, ou handoff com `awaiting-reply`.

## Fora de escopo

- Fazer merge, aprovar ou iterar em PR ja existente.
- Commit ou push direto na `main` ou na branch de integracao.
- Mais de um PR por rodada.
- Alterar labels, titulo ou corpo de issues. Excecoes: os labels do passo 7,
  fechar sub-task integrada (passo 2) e aplicar `awaiting-reply` ao encerrar
  com handoff.
- Substituir o CI do PR: a verificacao local e o primeiro filtro; o CI
  continua sendo o juiz final.
- Redesenhar o plano: fronteiras e escopo vem do brief. Discordou? Handoff,
  nao improviso.
- Issues `ready-for-human` e sub-tasks humanas: nelas o agente no maximo
  orienta.
