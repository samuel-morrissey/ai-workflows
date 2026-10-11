---
name: issue-triage
description: Triagem de um issue cru - investiga o codigo, atribui tipo (MAP/SPEC/tipo pontual) e label de estado, entrega issue pontual com brief pronto para agente ou humano (ou need-break-down quando grande demais para uma sessao unica) e MAP/SPEC com leitura de codigo para a proxima etapa, ou fecha como wontfix se ja rejeitado ou ja implementado.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh issue edit:*) Bash(gh issue comment:*) Bash(gh issue close:*) Bash(gh label list:*) Bash(gh label create:*) Read Grep Glob
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
  humano) sai com `need-break-down` e leitura de codigo — pronto para
  `/issue-break-down`.
- `[MAP]`/`[SPEC]` saem com uma **leitura de codigo** em comentario —
  pre-digestao superficial para `/issue-discovery` ou `/issue-refinement`.
- Solicitacao ja rejeitada ou ja implementada fecha como `wontfix`.

O criterio de classificacao e **grau de definicao, nao complexidade**.

Siga o vocabulario da skill `issue-labeling` (tipos, labels de estado e regras de
transicao). Invoque-a antes de aplicar qualquer label. Os formatos de brief e
de leitura de codigo estao em [AGENT-BRIEF.md](AGENT-BRIEF.md) — leia antes
de escrever qualquer um dos dois.

Precisou de informacao ou decisao humana em qualquer passo? Siga a skill
`issue-async-first`: uma unica mensagem no issue, com handoff completo, e encerre a
rodada.

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

   Se o titulo ja tem prefixo de tipo ou o issue ja tem label de estado
   posterior a `need-triage` (`need-discovery`, `need-refinement`,
   `need-break-down`, `ready-for-*`, `awaiting-pr-review`, `wontfix`), ele ja
   foi triado: comente informando o estado atual e pare (o fluxo so anda
   para frente).

   `need-triage` e o label de entrada: quem o aplica e um humano, e e esta
   skill quem o remove ao concluir. Em todo `--add-label` abaixo, inclua
   `--remove-label need-triage` na mesma operacao (regra 1 da `issue-labeling`).

2. **Procure precedente `wontfix`:**

   ```bash
   gh issue list --state closed --label wontfix --json number,title,body --limit 50
   ```

   Compare por **conceito**, nao pelas palavras do titulo. Se a solicitacao ja
   foi rejeitada antes, comente:

   ```markdown
   ## Triagem

   **Resultado:** `wontfix` — ja rejeitado em #<precedente>
   **Por que:** <motivo em uma ou duas frases>
   ```

   Depois aplique o label `wontfix` (removendo `need-triage`) e feche o issue.
   Fim da triagem.

3. **Investigue o codigo.** O checkout do repositorio esta disponivel: use
   `Read`/`Grep`/`Glob` para mapear como o pedido se relaciona com o codigo
   atual — o que ja existe, contratos e conceitos envolvidos (nomes reais),
   riscos. Fato que o codigo responde e obrigacao sua descobrir; ao humano so
   chegam decisoes.

   Se o pedido ja existe implementado, e `wontfix`: comente apontando onde o
   comportamento vive, aplique o label e feche, como no passo 2.

4. **Classifique** pelo grau de definicao:

   | Natureza | Sinal caracteristico | Resultado |
   |---|---|---|
   | Nebulosa | Nao se sabe o que se pretende desenvolver; ideia sem arestas | `[MAP]` + `need-discovery` — passo 5 |
   | Definida, porem ampla | Complexa, mas ja se sabe o que se quer | `[SPEC]` + `need-refinement` — passo 5 |
   | Pontual | Alteracao bem delimitada (bug, feature pequena, docs, infra…) | tipo pontual + brief completo — passo 6 |

   Se o corpo do issue nao da elementos para escolher entre as tres naturezas,
   a intervencao e impeditiva: comente seguindo o handoff da `issue-async-first`,
   aplique `awaiting-reply` e pare, sem aplicar tipo nem label de estado. O
   proximo comentario humano dispara nova rodada desta skill.

5. **Caminho `[MAP]`/`[SPEC]`** — aplique prefixo no titulo e label de estado:

   ```bash
   gh issue edit $issue --title "[TIPO] titulo original" \
     --add-label "need-..." --remove-label need-triage
   ```

   Depois comente, incluindo a leitura de codigo do passo 3 no formato do
   AGENT-BRIEF.md:

   ```markdown
   ## Triagem

   **Tipo:** `[MAP]` ou `[SPEC]`
   **Estado:** `need-discovery` ou `need-refinement`
   **Por que:** <uma ou duas frases>
   **Proximo passo:** `/issue-discovery` ou `/issue-refinement`

   ### Leitura do codigo
   <formato do AGENT-BRIEF.md>
   ```

   A leitura e superficial de proposito: um mapa para a proxima etapa, nao um
   requisito fechado.

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
        --add-label need-break-down --remove-label need-triage
      ```

      Comente como no passo 5 (incluindo a leitura de codigo), com
      **Estado:** `need-break-down` e **Proximo passo:** `/issue-break-down`.
      Fim da triagem — o brief e trabalho do `/issue-break-down`, nao desta skill.

   4. Sobrou lacuna que so o humano responde (escolha de produto, prioridade,
      intencao — e a fronteira de um criterio **so quando e escolha de
      desenho**, nao fato do codigo; ver AGENT-BRIEF.md)? A intervencao e
      impeditiva: invoque a skill `grilling`, monte
      a fronteira de perguntas e envie uma unica rodada dentro do handoff da
      `issue-async-first`, aplique `awaiting-reply` e pare sem aplicar tipo nem
      label de estado — o proximo comentario humano dispara nova rodada.

   5. Nao sobrou: escreva o brief no corpo do issue, no formato e principios
      do AGENT-BRIEF.md, preservando **titulo e texto originais** do issue
      como citacao logo no comeco do corpo:

      ```bash
      gh issue edit $issue --body-file - <<'EOF'
      ...brief...
      EOF
      ```

   6. Aplique titulo e label. Com o original preservado na citacao, o titulo
      pode ser reescrito para algo mais claro — sempre com o prefixo
      `[TIPO]` escolhido. O label e `ready-for-agent`, ou `ready-for-human`
      pelo criterio de executor do AGENT-BRIEF.md:

      ```bash
      gh issue edit $issue --title "[TIPO] titulo claro" \
        --add-label "ready-for-..." --remove-label need-triage
      ```

   7. Comente:

      ```markdown
      ## Triagem

      **Tipo:** `[TIPO]` (o tipo pontual aplicado)
      **Estado:** `ready-for-agent` ou `ready-for-human`
      **Por que:** <uma ou duas frases, incluindo a escolha do executor>
      **Seams:** <as fronteiras dos criterios de aceite, em uma linha>
      **Proximo passo:** comente `/implement` para o agente implementar, ou execucao humana
      **Antes do `/implement`:** discordou de fronteira, criterio ou escopo?
      Edite o brief no corpo — o implement le o corpo na hora de rodar.
      ```

      O `ready-for-agent` **nao** inicia a implementacao: quem da o "vai" e
      o humano, comentando `/implement`. O intervalo entre os dois e a
      confirmacao das seams.

7. Responda ao usuario com a classificacao aplicada e a URL do issue.

A triagem esta completa quando o issue esta em exatamente um destes estados:

- `[MAP]`/`[SPEC]` + um label `need-*` (sem `need-triage`) + comentario com
  justificativa e leitura de codigo;
- tipo pontual + um label `ready-for-*` (sem `need-triage`) + brief no corpo
  + comentario de justificativa;
- tipo pontual + `need-break-down` (sem `need-triage`) + comentario com
  justificativa e leitura de codigo — grande demais para uma sessao unica;
- fechado como `wontfix` (precedente ou ja implementado);
- comentario de perguntas aguardando resposta humana, sem tipo, ainda com
  `need-triage` e com `awaiting-reply` — o `need-triage` faz a resposta
  humana disparar nova rodada, e o `awaiting-reply` mostra que a vez e do
  humano.

## Fora de escopo

- Refinar `[MAP]`/`[SPEC]`, quebrar em sub-tasks ou implementar.
- Alterar o corpo de issue `[MAP]`/`[SPEC]` (a leitura de codigo e
  comentario).
- Executar codigo, testes ou reproducao de bugs (investigacao e so leitura).
- Triar Pull Requests.
- Reclassificar issue ja triado (correcao vira issue nova).
