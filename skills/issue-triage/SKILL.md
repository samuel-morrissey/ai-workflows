---
name: issue-triage
description: Triagem de um issue cru - investiga o codigo, atribui tipo (MAP/SPEC/tipo pontual) e label de estado, entrega issue pontual com brief pronto para agente ou humano (ou needs-break-down quando grande demais para uma sessao unica) e MAP/SPEC com leitura de codigo para a proxima etapa, ou fecha como wontfix se ja rejeitado ou ja implementado, ou como deferred se o humano despriorizou.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh issue edit:*) Bash(gh issue comment:*) Bash(gh issue close:*) Bash(gh label list:*) Bash(gh label create:*) Read Grep Glob WebFetch(domain:docs.github.com) WebFetch(domain:code.claude.com) WebFetch(domain:platform.claude.com)
---

# Triage

> **Skill ainda nao criada:** `issue-discovery` e citada neste arquivo como
> proximo passo, mas ainda nao existe neste plugin. Ao indica-la, avise que
> nao e possivel usar a skill referenciada porque ela ainda nao foi criada.

Caracteriza um issue cru e o entrega pronto para a proxima etapa: investiga o
codigo, atribui **tipo + label de estado** e registra o que descobriu.

- Issue **pontual** (tipos `[BUG]`, `[FEAT]`, `[REFACTOR]`, `[DOCS]`,
  `[INFRA]` ou, como fallback, `[TASK]`) sai com **brief completo** no corpo
  e `ready-for-agent` ou `ready-for-human` — pronto para `/issue-remote-implement` ou
  execucao humana.
- Pontual **grande demais para uma sessao unica** (de agente ou de trabalho
  humano) sai com `needs-break-down` e leitura de codigo — pronto para
  `/issue-break-down`.
- `[MAP]`/`[SPEC]` saem com uma **leitura de codigo** em comentario —
  pre-digestao superficial para `/issue-discovery` ou `/issue-refinement`.
- Solicitacao ja rejeitada ou ja implementada fecha como `wontfix`.
- Solicitacao que o humano despriorizou fecha como `deferred`: fora do fluxo
  por agora, reabrivel.

O criterio de classificacao e **grau de definicao, nao complexidade**.

Siga o vocabulario da skill `issue-labeling` (tipos, labels de estado e regras de
transicao). Invoque-a antes de aplicar qualquer label. Os formatos de brief e
de leitura de codigo estao em [AGENT-BRIEF.md](AGENT-BRIEF.md) — leia antes
de escrever qualquer um dos dois. Ao usar web, siga
[Uso da web](AGENT-BRIEF.md#uso-da-web).

Precisou de informacao ou decisao humana em qualquer passo? Siga a skill
`issue-async-first`: uma unica mensagem no issue, com handoff completo, e encerre a
rodada.

**Mencao ao responsavel.** Todo comentario que deixa o issue esperando uma
pessoa marca o responsavel, como diz a "Mencao ao responsavel" da
`issue-async-first`: o workflow o informa no system prompt, numa frase que
comeca por "Responsavel:". No handoff, a mencao vai no **Preciso de voce**.
No `## Triagem` que troca `needs-triage` por um estado seguinte, vai na
linha do **Proximo passo**, no mesmo comentario: `**Proximo passo**
(@fulano): ...`. Sem responsavel, nada de `@`: a linha **Responsavel:** diz
que nao ha responsavel identificavel. O fechamento em `wontfix` ou
`deferred` nao marca ninguem.

**Encadeamento.** A triagem que termina em `needs-refinement` ou
`needs-break-down` chama a etapa seguinte sozinha, sem `go`. Quem diz se
isso vale nesta rodada e o workflow, no system prompt, numa frase que
comeca por "Encadeamento:":

- **ligado**: o `## Triagem` desses dois estados nao espera ninguem. Ele
  nao pede `go` e nao marca ninguem: no lugar do **Proximo passo**, leva a
  linha **Em seguida:**, que diz qual etapa roda agora e que aplicar o
  label `undo` desfaz esta triagem (passos 5 e 6.3). A mencao fica para a
  etapa seguinte, quando ela parar numa pergunta ou num `ready-for-*`;
- **desligado**, ou sem a frase: o comentario pede `go` e marca o
  responsavel, como sempre.

`needs-discovery`, `ready-for-*`, o handoff (`awaiting-reply`) e o
fechamento nunca encadeiam: seguem as regras de sempre, qualquer que seja a
frase.

## Argumento

`$issue` — o numero do issue a triar.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue.

## Passos

1. **Leia o issue:**

   ```bash
   gh issue view $issue --json number,title,body,labels,state,url,comments
   ```

   Se o comando falhar, reporte o erro exato e pare. Este comando e a fonte de
   dados sobre o issue — nada de `gh repo view` ou `git remote`. O codigo, por
   sua vez, se investiga no checkout (passo 3).

   **Fora do fluxo por decisao humana?** O issue carrega `wontfix` ou
   `deferred`, ou um comentario humano o rejeita ou despriorizou ("fica para
   depois", "sem prioridade agora"). Complete o fechamento da regra 4 da
   `issue-labeling`: aplique o label que falta (removendo o label de estado
   atual e `priority`), feche e comente:

   ```markdown
   ## Triagem

   **Resultado:** `wontfix` ou `deferred` — por decisao humana
   **Estado ao adiar:** <o label de estado que a issue tinha> (so em `deferred`)
   **Por que:** <o motivo do comentario humano, ou o significado do label>
   ```

   Encerramento terminal, sem mencao ao responsavel. Pare: fim da triagem.

   Se o issue ja tem label de estado posterior a `needs-triage`
   (`needs-discovery`, `needs-refinement`, `needs-break-down`, `ready-for-*`,
   `awaiting-pr-review`), ele ja foi triado: comente informando o estado
   atual e pare, sem alterar titulo nem labels (o fluxo so anda para
   frente). Titulo com `[SUB-TASK]` tambem esta fora da triagem (a sub-task
   nasce da `issue-break-down`, sem label de estado por desenho): comente e
   pare do mesmo jeito.

   Fora isso, um prefixo de tipo no titulo **nao** quer dizer que o issue
   foi triado: enquanto ele carrega `needs-triage` e nenhum label de estado
   posterior, o prefixo e uma **sugestao** de quem o criou (o **tipo
   sugerido**). Siga a triagem normal (passos 2 a 6): o tipo sugerido e o
   texto do humano entram como insumo da classificacao, mas o tipo e
   decidido pelo criterio do passo 4 (grau de definicao). Prefixo fora do
   vocabulario (`[CHORE]`, `[Bug]`, `bug:`) nao e tipo sugerido: e parte do
   titulo cru.

   Ao aplicar o titulo (passos 5 e 6), **substitua** o prefixo entre
   colchetes no comeco do titulo, se houver, pelo tipo decidido: nunca
   empilhe dois prefixos (`[FEAT] [BUG] ...`). Tipo decidido igual ao
   sugerido: o prefixo fica como esta. O comentario de triagem registra o
   tipo sugerido na linha **Tipo:** sempre que o titulo original tinha um
   prefixo de tipo, mesmo igual ao tipo decidido: `` `[SPEC]` (sugerido:
   `[FEAT]`) `` quando trocou, com o **Por que:** dizendo o motivo, e
   `` `[SPEC]` (sugerido: `[SPEC]`) `` quando ficou. E por essa linha que o
   `undo` da triagem devolve o titulo de antes dela. Titulo original sem
   prefixo de tipo: nada de `(sugerido: ...)`. Em handoff (`awaiting-reply`),
   o titulo nao muda, como em qualquer handoff.

   **Rodando de novo depois de um `undo`.** Um comentario `## Undo` que
   desfez a triagem (ver "Label de volta" da `issue-labeling`) devolve o
   issue a `needs-triage`, com o titulo e o corpo de antes dela, e marca o
   `## Triagem` anterior a ele como **substituido**: ele nao conta como "ja
   triado" nem e o resultado vigente, e esta rodada classifica o issue de
   novo, do zero, e escreve um `## Triagem` novo. O titulo e o corpo de
   agora sao os originais; o `## Triagem` desfeito e a leitura de codigo
   dele sao contexto, nao decisao. Todo comentario humano posterior ao
   `undo` (o motivo de refazer a triagem) entra como insumo da
   classificacao.

   `needs-triage` e o label de entrada: quem o aplica e um humano, e e esta
   skill quem o remove ao concluir. Em todo `--add-label` abaixo, inclua
   `--remove-label needs-triage` na mesma operacao (regra 1 da `issue-labeling`)
   e, se o humano decidiu prioridade no corpo ou em comentario,
   `--add-label priority` (secao "Label de prioridade" da `issue-labeling`).

2. **Procure precedente `wontfix` e referencia `deferred`:**

   ```bash
   gh issue list --state closed --label wontfix --json number,title,body --limit 50
   gh issue list --state closed --label deferred --json number,title,body --limit 50
   ```

   Compare por **conceito**, nao pelas palavras do titulo.

   Issue `deferred` igual nao e rejeicao: guarde o numero e siga. Ele entra
   no **Por que:** do comentario de triagem como referencia, com a opcao de
   reabrir a issue adiada no lugar desta — decisao do humano.

   Se a solicitacao ja foi rejeitada antes, comente:

   ```markdown
   ## Triagem

   **Resultado:** `wontfix` — ja rejeitado em #<precedente>
   **Por que:** <motivo em uma ou duas frases>
   ```

   Depois aplique o label `wontfix` (removendo `needs-triage`) e feche o issue.
   Fim da triagem.

3. **Investigue o codigo.** O checkout do repositorio esta disponivel: use
   `Read`/`Grep`/`Glob` para mapear como o pedido se relaciona com o codigo
   atual — o que ja existe, contratos e conceitos envolvidos (nomes reais),
   riscos. Fato que o codigo responde e obrigacao sua descobrir; ao humano so
   chegam decisoes.

   Ressalva: um trade-off de correcao, em que a solucao admite um resultado
   incorreto conhecido, **nao** e fato do codigo, mesmo com precedente no
   codigo ou num ADR. E decisao de tolerancia a risco: o precedente mostra
   que alguem fez assim, nao que um humano aceitou o custo. Um trade-off
   desses so entra no brief como aceito com a fonte de aceite que o
   AGENT-BRIEF.md define; sem ela, e pendente (passo 6.4).

   Se o pedido ja existe implementado, e `wontfix`: comente apontando onde o
   comportamento vive, aplique o label e feche, como no passo 2.

4. **Classifique** pelo grau de definicao:

   | Natureza | Sinal caracteristico | Resultado |
   |---|---|---|
   | Nebulosa | Nao se sabe o que se pretende desenvolver; ideia sem arestas | `[MAP]` + `needs-discovery` — passo 5 |
   | Definida, porem ampla | Complexa, mas ja se sabe o que se quer | `[SPEC]` + `needs-refinement` — passo 5 |
   | Pontual | Alteracao bem delimitada (bug, feature pequena, docs, infra…) | tipo pontual + brief completo — passo 6 |

   Se o corpo do issue nao da elementos para escolher entre as tres naturezas,
   a intervencao e impeditiva: comente seguindo o handoff da `issue-async-first`,
   aplique `awaiting-reply` e pare, sem aplicar tipo nem label de estado. O
   proximo comentario humano dispara nova rodada desta skill.

5. **Caminho `[MAP]`/`[SPEC]`** — aplique prefixo no titulo e label de estado:

   ```bash
   gh issue edit $issue --title "[TIPO] titulo original" \
     --add-label "needs-..." --remove-label needs-triage
   ```

   "titulo original" e o titulo sem o prefixo sugerido, se havia (passo 1).

   Depois comente, incluindo a leitura de codigo do passo 3 no formato do
   AGENT-BRIEF.md:

   ```markdown
   ## Triagem

   **Tipo:** `[MAP]` ou `[SPEC]` (sugerido: `[X]`) — o "(sugerido: ...)" sempre que o titulo original tinha prefixo
   **Estado:** `needs-discovery` ou `needs-refinement`
   **Por que:** <uma ou duas frases>
   **Proximo passo** (@responsavel): `/issue-discovery`, ou aplique o label `go` para `/issue-refinement`

   ### Leitura do codigo
   <formato do AGENT-BRIEF.md>
   ```

   Com o encadeamento ligado e o issue em `needs-refinement`, a linha do
   **Proximo passo** da lugar a esta, sem `@` nem pedido de `go`:

   ```markdown
   **Em seguida:** o `/issue-refinement` roda sozinho, sem `go`, a partir desta triagem. Aplique o label `undo` para desfazer esta triagem.
   ```

   `needs-discovery` continua com o **Proximo passo** e a mencao: a
   `/issue-discovery` nao roda sozinha.

   A leitura e superficial de proposito: um mapa para a proxima etapa, nao um
   requisito fechado. Com o encadeamento, o refinamento comeca logo depois
   deste comentario: o que estiver errado aqui se corrige com o `undo`.

6. **Caminho pontual** — o issue sai executavel:

   1. **Escolha o tipo pontual** na tabela da `issue-labeling`: `[BUG]`, `[FEAT]`,
      `[REFACTOR]`, `[DOCS]` ou `[INFRA]` — o mais especifico que encaixar.
      `[TASK]` e fallback: so quando nenhum dos outros descreve o issue.
      Abaixo, `[TIPO]` e o tipo escolhido.

   2. Aprofunde a investigacao do passo 3 ate o nivel de brief: comportamento
      atual, casos de borda, criterios verificaveis.

   3. **Grande demais para uma sessao unica** de agente ou de trabalho humano
      (nao cabe em um PR / um bloco de trabalho)? O tipo continua o mesmo,
      mas o proximo passo e quebrar, nao executar:

      ```bash
      gh issue edit $issue --title "[TIPO] titulo original" \
        --add-label needs-break-down --remove-label needs-triage
      ```

      Comente como no passo 5 (incluindo a leitura de codigo), com
      **Estado:** `needs-break-down` e **Proximo passo** (@responsavel):
      aplique o label `go` para `/issue-break-down`. Com o encadeamento
      ligado, no lugar do **Proximo passo**, sem `@` nem pedido de `go`:

      ```markdown
      **Em seguida:** o `/issue-break-down` roda sozinho, sem `go`, a partir desta triagem. Aplique o label `undo` para desfazer esta triagem.
      ```

      Fim da triagem — o brief e trabalho do `/issue-break-down`, nao desta skill.

   4. Sobrou lacuna que so o humano responde (escolha de produto, prioridade,
      intencao — e a fronteira de um criterio **so quando e escolha de
      desenho**, nao fato do codigo; ver AGENT-BRIEF.md)? A intervencao e
      impeditiva: invoque a skill `grilling`, monte
      a fronteira de perguntas e envie uma unica rodada dentro do handoff da
      `issue-async-first`, aplique `awaiting-reply` e pare sem aplicar tipo nem
      label de estado — o proximo comentario humano dispara nova rodada.

      Aceitar que a solucao **admita um resultado incorreto conhecido**
      (errar num caso que se consegue apontar) tambem e decisao que so o
      humano toma, mas o desfecho e outro: **nao** vira `awaiting-reply`. O
      pontual segue para o brief (6.5) e sai em `ready-for-*`, com o
      trade-off no grupo **Trade-offs pendentes de aceite** dos "Casos de
      borda", com alternativas e recomendacao (AGENT-BRIEF.md). O humano
      decide editando o brief antes do `go`. Trade-off com aceite que vale
      (fonte citada, conforme o AGENT-BRIEF.md) vai para os decididos.

   5. Nao sobrou: escreva o brief no corpo do issue, no formato e principios
      do AGENT-BRIEF.md, preservando **titulo e texto originais** do issue
      como citacao logo no comeco do corpo. O titulo citado e o titulo como
      estava, com o prefixo sugerido, se havia. Mantenha a citacao no
      formato do AGENT-BRIEF.md: e dela que o `undo` da triagem tira o
      titulo e o corpo de volta:

      ```bash
      gh issue edit $issue --body-file - <<'EOF'
      ...brief...
      EOF
      ```

   6. Aplique titulo e label. Com o original preservado na citacao, o titulo
      pode ser reescrito para algo mais claro — sempre com um unico prefixo,
      o `[TIPO]` escolhido, no lugar do sugerido (passo 1). O label e `ready-for-agent`, ou `ready-for-human`
      pelo criterio de executor do AGENT-BRIEF.md:

      ```bash
      gh issue edit $issue --title "[TIPO] titulo claro" \
        --add-label "ready-for-..." --remove-label needs-triage
      ```

   7. Comente:

      ```markdown
      ## Triagem

      **Tipo:** `[TIPO]` (sugerido: `[X]`) — o tipo pontual aplicado; o "(sugerido: ...)" sempre que o titulo original tinha prefixo
      **Estado:** `ready-for-agent` ou `ready-for-human`
      **Por que:** <uma ou duas frases, incluindo a escolha do executor>
      **Seams:** <as fronteiras dos criterios de aceite, em uma linha>
      **Proximo passo** (@responsavel): aplique o label `go` para o agente implementar, ou execucao humana
      **Antes do `go`:** discordou de fronteira, criterio ou escopo?
      Edite o brief no corpo — o implement le o corpo na hora de rodar.
      ```

      Em todo `## Triagem` que deixa o issue esperando `go` (este, o
      `needs-discovery` do passo 5 e, com o encadeamento desligado, os
      `needs-refinement` e `needs-break-down` dos passos 5 e 6.3), o
      `(@responsavel)` sao os logins da frase "Responsavel:" do system
      prompt. O `## Triagem` que encadeia (linha **Em seguida:**) nao marca
      ninguem. Sem responsavel, a linha fica
      `**Proximo passo:** ...` sem `@`, seguida de `**Responsavel:** nao ha
      responsavel identificavel; ninguem foi marcado.`

      O `ready-for-agent` **nao** inicia a implementacao: quem da o "vai" e
      o humano, aplicando o label `go`. O intervalo entre os dois e a
      confirmacao das seams.

7. Responda ao usuario com a classificacao aplicada e a URL do issue.

A triagem esta completa quando o issue esta em exatamente um destes estados:

- `[MAP]`/`[SPEC]` + um label `needs-*` (sem `needs-triage`) + comentario com
  justificativa e leitura de codigo;
- tipo pontual + um label `ready-for-*` (sem `needs-triage`) + brief no corpo
  + comentario de justificativa;
- tipo pontual + `needs-break-down` (sem `needs-triage`) + comentario com
  justificativa e leitura de codigo — grande demais para uma sessao unica;
- fechado como `wontfix` (precedente, ja implementado ou decisao humana) ou
  como `deferred` (decisao humana), com o comentario da regra 4 da
  `issue-labeling`;
- comentario de perguntas aguardando resposta humana, sem tipo, ainda com
  `needs-triage` e com `awaiting-reply` — o `needs-triage` faz a resposta
  humana disparar nova rodada, e o `awaiting-reply` mostra que a vez e do
  humano.

## Fora de escopo

- Refinar `[MAP]`/`[SPEC]`, quebrar em sub-tasks ou implementar.
- Alterar o corpo de issue `[MAP]`/`[SPEC]` (a leitura de codigo e
  comentario).
- Executar codigo, testes ou reproducao de bugs (investigacao e so leitura).
- Triar Pull Requests.
- Reclassificar issue ja triado, com label de estado posterior a
  `needs-triage` (correcao vira issue nova). O prefixo de um issue ainda nao
  triado e sugestao, e trocar esse prefixo faz parte da triagem (passo 1).
