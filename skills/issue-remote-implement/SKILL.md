---
name: issue-remote-implement
description: Implementa um issue do fluxo em uma rodada que termina em um PR - num pontual ready-for-agent, o PR dele para a branch padrao; numa [SUB-TASK] despachada pelo workflow (modo sub-task), o PR da camada dela na stack do pai. Desenvolve test-first nos criterios de aceite, roda as verificacoes de qualidade e passa por ate duas rodadas de QA independente (issue-qa) antes do PR. Verificacao vermelha nao vira PR. Num pai com sub-tasks quem orquestra e o workflow, nao esta skill.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue comment:*) Bash(gh issue edit:*) Bash(gh issue close:*) Bash(gh label create:*) Bash(gh api:*) Bash(gh pr list:*) Bash(gh pr create:*) Bash(gh pr edit:*) Bash(gh pr view:*) Bash(git status:*) Bash(git branch:*) Bash(git checkout:*) Bash(git switch:*) Bash(git fetch:*) Bash(git pull:*) Bash(git add:*) Bash(git commit:*) Bash(git push:*) Bash(git diff:*) Bash(git log:*) Bash(git config:*) Bash(git worktree:*) Read Grep Glob Edit Write Agent
---

# Implement

Cada rodada termina em **no maximo um PR aberto**. O merge e a revisao nao
sao daqui: o humano revisa e faz o merge.

A unidade da rodada e sempre um issue so, de dois tipos:

- **pontual** (`ready-for-agent`, sem sub-issues): a rodada implementa o
  proprio issue, com PR para a branch padrao;
- **sub-task** (`[SUB-TASK]`, em **modo sub-task**): a rodada implementa a
  sub-task como mais uma camada da stack do pai, com PR para a branch da
  camada de baixo.

Um **pai com sub-tasks nunca e alvo desta skill**: quem escolhe a proxima
sub-task, despacha cada uma numa run propria e empilha os PRs e o workflow
(`issue-remote-implement.yml`, o planner, e `issue-sub-task.yml`, o worker,
em `samuel-morrissey/ai-workflows`). Esta skill so ve uma sub-task de cada
vez.

Branch, base, vinculo e fechamento seguem a skill `issue-git-flow`. Invoque-a
antes do passo 2. O texto do PR e da skill `remote-to-pr`. O QA independente
do passo 5 e da skill `issue-qa`, rodada como subagente.

Decisao a montante, execucao a jusante: o brief ja diz **o que** (criterios
de aceite) e **onde** (a fronteira em que cada criterio se observa). Voce nao
redesenha o plano: transforma o brief em codigo verificado.

Travou em algo que so o humano resolve (decisao de produto que o brief nao
cobre, acesso faltando, verificacao que nao fica verde dentro do escopo)?
Siga as skills `grilling` e `issue-async-first`: handoff completo no issue
alvo, `awaiting-reply` aplicado, e encerre sem abrir PR. Termine a mensagem
com: "responda aqui para retomar: a resposta ja dispara a proxima rodada".

## Argumento

`$issue` — o numero do issue alvo: o pontual que recebeu o `go`, ou a
sub-task que o workflow despachou.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue.

## Modo sub-task

O workflow que despacha uma sub-task avisa pelo system prompt, numa frase
que comeca por **"Modo sub-task:"**, e traz dois fatos que voce **usa como
estao, sem recalcular**:

- o **pai** (`#<pai>`);
- a **base**: a branch de onde `sub-task-<numero>` nasce e para onde o PR
  aponta. E o topo atual da stack do pai (a branch do PR aberto mais alto)
  ou a branch padrao, quando a sua camada e a primeira.

O que muda em relacao ao pontual, e so isso:

- a branch nasce de `origin/<base>`, nao da branch padrao, e o PR tem base
  `<base>`;
- as linhas de vinculo do PR sao `Closes #<sub-task>` e `Parte de #<pai>`;
- o label `awaiting-pr-review` vai na sub-task; o pai nao muda;
- o comentario de fim de rodada vai so na sub-task: o status do pai e um
  comentario do planner, atualizado por ele a cada rodada;
- o empilhamento no stack do GitHub e do planner, depois que o PR existe.
  Nao crie nem altere stack, e nunca troque a base de um PR ja empilhado: o
  GitHub recusa.

Uma `[SUB-TASK]` **sem** o aviso de modo sub-task nao e alvo: comente que a
sub-task roda pelo workflow (label `go` nela, ou `go` no pai para a cadeia
inteira) e pare.

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

## Evidencias e QA

O workflow informa, no system prompt, numa frase que comeca por
**"Evidencias:"**, tres fatos que voce usa como estao:

- a **pasta de evidencias**: onde toda captura (png, gif, webm, txt) e o
  relatorio do QA sao gravados. Fica fora do workspace e nunca e commitada;
- a **publicacao**: a URL base em que cada arquivo da pasta estara publico
  depois da rodada (bucket), ou o link da run em que a pasta sera anexada
  como artifact. Com bucket, o PR referencia imagem por
  `![nome](<url-base>/<arquivo>)`; com artifact, cita o arquivo pelo nome e
  linka a run;
- as **ferramentas liberadas** para captura e QA: os prefixos de comando
  que a allowlist aceita alem de git e gh (ex.: `node`, `npx playwright`,
  `curl`). Vazio quer dizer que o repositorio consumidor nao liberou nada, e
  o QA do passo 5 nao roda.

Quem captura evidencia e o QA, nao voce. As Evidencias do PR sao as
capturas da ultima rodada dele.

## Passos

1. **Leia o issue e confira se esta apto:**

   ```bash
   gh issue view $issue --json number,title,body,labels,state,url,comments
   gh api "repos/{owner}/{repo}/issues/$issue/sub_issues" --jq 'length'
   ```

   - **Pontual:** apto exige label `ready-for-agent`, issue aberto e
     nenhuma sub-issue. Com sub-issues e um pai: comente que a
     implementacao de um pai e orquestrada pelo workflow (basta o `go` no
     pai) e pare.
   - **Sub-task:** apto exige titulo `[SUB-TASK]`, issue aberto e o aviso de
     modo sub-task no system prompt. Ja existe PR aberto da branch
     `sub-task-$issue`? Comente apontando-o e pare: esta skill nao itera em
     PR existente.
   - Fora disso, comente o estado atual e pare.

   Issue com `wontfix` ou `deferred`: complete o fechamento da regra 4 da
   `issue-labeling` e pare.

   Leia tambem os comentarios: handoffs e respostas humanas de rodadas
   anteriores valem. O corpo e lido **agora**: se o humano editou o brief
   antes de aplicar o `go`, vale a versao editada. Numa sub-task, o pai e
   contexto: leia o brief dele e o comentario `## Quebra` para entender onde
   a sua fatia entra, sem ampliar o escopo dela.

   Os criterios de aceite da rodada vem do corpo do issue alvo.

2. **Crie a branch** conforme a `issue-git-flow`: pontual nasce da branch
   padrao; sub-task nasce da base do modo sub-task. Garanta identidade de
   commit antes do primeiro commit:

   ```bash
   git config user.name "claude"
   git config user.email "noreply@anthropic.com"
   ```

   Branch remota com o mesmo nome e sem PR aberto e sobra de uma rodada
   anterior (PR fechado sem merge, run interrompida): a sua branch nova a
   substitui no push, com `git push --force-with-lease -u origin <branch>`.
   Branch de outra pessoa nao existe nesse nome: o nome e do fluxo.

3. **Implemente, test-first, um criterio de aceite por vez.** Os criterios da
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
   codigo ao redor. Numa sub-task, o codigo das camadas de baixo ja esta na
   sua branch: construa em cima dele, nao o reescreva.

4. **Verifique.** Antes de abrir o PR, rode a bateria completa dos comandos
   da secao "Verificacao de qualidade", uma vez, ao final. Resultado:

   - **Verde:** siga para o QA (passo 5).
   - **Vermelho causado pela sua mudanca:** corrija e rode de novo.
   - **Vermelho fora do escopo da unidade** (ja quebrado antes de voce
     chegar, ou exige decisao que o brief nao cobre): nao abra PR. Faca push
     da branch para nao perder o trabalho, handoff `issue-async-first` no
     issue alvo com o erro exato colado e o que falta, e encerre a rodada.

   PR com verificacao vermelha nao existe nesta skill.

5. **QA independente.** So roda quando o system prompt lista ferramentas
   liberadas. Sem elas, pule este passo e registre, para o PR: "Sem QA
   independente: o workflow nao liberou ferramentas de captura
   (evidence_tools)".

   O QA e cego ao diff e julga so os criterios de aceite; voce nao discute
   com ele. O orcamento e fixo: **duas rodadas**, e nada reabre uma
   terceira.

   1. **Push da branch**, para o QA poder voltar ao head por nome e para
      nada se perder.
   2. **Escreva o roteiro** em `<pasta de evidencias>/como-testar.md`: as
      secoes *Configurando o ambiente* e *Como testar* exatamente como irao
      no PR, no formato do `TEMPLATE.md` da `to-pr`. E a unica instrucao que
      o QA recebe sobre como chegar na funcionalidade.
   3. **Rodada 1.** Use a ferramenta Agent com o prompt abaixo, preenchido,
      sem acrescentar nada sobre a implementacao:

      ```
      Invoque a skill issue-qa e siga-a ate o fim com estes dados:
      - Issue: #<numero>
      - Head: <branch> | Base: <base>
      - Rodada: 1
      - Roteiro: <pasta>/como-testar.md
      - Pasta de evidencias: <pasta>
      - Publicacao: <frase de publicacao do system prompt>
      - Ferramentas liberadas: <lista do system prompt>
      Nao leia o diff, os commits nem o codigo-fonte. Devolva so o caminho do relatorio.
      ```

      Leia `<pasta>/qa-1.md`.
   4. **Decida pela tabela**, e so por ela:
      - todo criterio `passou` → siga ao passo 6 com a rodada 1 como
        evidencia;
      - **Ambiente falhou** → corrija o roteiro (e o codigo, se o problema e
        real: um comando que o PR deveria ter criado), uma vez;
      - algum criterio `falhou` → corrija o codigo como no passo 3
        (test-first, no criterio reprovado), rode a bateria do passo 4 de
        novo, commit e push.
      Observacoes nao reabrem nada.
   5. **Rodada 2**, com o mesmo prompt, mudando so `Rodada: 2` e lendo o
      roteiro atualizado. Leia `<pasta>/qa-2.md`. Qualquer resultado encerra
      o QA.
   6. **Desfecho da rodada 2:**
      - todo criterio `passou` → passo 6;
      - criterio reprovado nas duas rodadas, criterio que passou na 1 e
        falhou na 2 (regressao), ou Ambiente falhou nas duas → **nao corrija
        mais**. Siga ao passo 6 e abra o PR mesmo assim: a tabela da rodada 2
        vai no PR com uma linha "Nao corrigido: <motivo>" por criterio
        reprovado. Depois do passo 8, faca o handoff da `issue-async-first`
        no issue alvo, com `awaiting-reply`, dizendo quais criterios ficaram
        em aberto e o que voce tentou. O humano decide no PR.

   Diante de um criterio reprovado voce tem duas saidas: corrige, ou declara
   no PR que nao corrigiu e por que. "O QA testou errado" nao e uma
   terceira: se ele errou, a declaracao fica no PR e o humano ve.

6. **Abra o PR com a skill `remote-to-pr`**, passando a head (a branch da
   unidade), a base da `issue-git-flow` (branch padrao no pontual; a base
   do modo sub-task na sub-task) e o caminho do relatorio da ultima rodada
   do QA (ou o motivo de nao ter rodado).

7. **Marque a unidade como em revisao.** Crie o label antes, se nao existir:

   ```bash
   gh label create awaiting-pr-review --color 5319E7 \
     --description "Implementacao concluida pelo agente; PR aberto e pronto para analise" 2>/dev/null || true
   ```

   - Pontual: troque `ready-for-agent` por `awaiting-pr-review` no issue
     alvo, na mesma operacao.
   - Sub-task: aplique `awaiting-pr-review` na sub-task. O pai nao muda:
     quem o move e o planner, quando toda sub-task tiver PR.

8. **Comente no issue da unidade:**

   ```markdown
   ## Implement

   **PR:** <url>
   **Criterios cobertos:** <lista curta mapeando criterio → teste e onde foi coberto>
   **Verificacao:** <comandos rodados e resultado — ou "nenhuma: <motivo>">
   **QA:** <rodadas e resultado: "1 rodada, todos os criterios passaram" | "2 rodadas, c2 em aberto" — ou "nao rodou: <motivo>">
   **Atencao:** o CI nao roda sozinho em PR aberto pelo agente — de o play
   manualmente (feche e reabra o PR, ou dispare o workflow de CI).
   ```

   Numa sub-task, acrescente uma linha: "Camada da stack de #<pai>, sobre
   `<base>`. O planner empilha e segue para a proxima." Nao comente no pai.

A rodada esta completa quando existe exatamente um PR novo da branch da
unidade para a base da `issue-git-flow`, cujo corpo comeca pelas linhas de
vinculo dela, vinculado ao issue da unidade pela API (aparece em
*Development* do issue), cujo diff cobre todos os criterios de aceite da
unidade com teste na fronteira de cada um, cuja verificacao esta verde (ou
declarada ausente, com motivo), cujo QA passou em ate duas rodadas (ou foi
declarado ausente, ou ficou em aberto com os criterios nomeados no PR e
handoff no issue), e a unidade esta com `awaiting-pr-review` e o comentario
com o link. O outro fim valido e o handoff com `awaiting-reply` sem PR.

## Fora de escopo

- Fazer merge, aprovar ou iterar em PR ja existente.
- Commit ou push direto na branch padrao ou na branch de outra camada.
- Mais de um PR por rodada.
- Terceira rodada de QA, ou replica ao relatorio do QA.
- Capturar evidencia por conta propria: quem captura e o QA.
- Escolher a proxima sub-task, despachar outra rodada, criar ou alterar
  stack, trocar a base de um PR: tudo isso e do workflow.
- Alterar labels, titulo ou corpo de issues. Excecoes: os labels do passo 7
  e aplicar `awaiting-reply` ao encerrar com handoff.
- Substituir o CI do PR: a verificacao local e o primeiro filtro; o CI
  continua sendo o juiz final.
- Redesenhar o plano: fronteiras e escopo vem do brief. Discordou? Handoff,
  nao improviso.
- Issues `ready-for-human` e sub-tasks humanas: nelas o agente no maximo
  orienta.
