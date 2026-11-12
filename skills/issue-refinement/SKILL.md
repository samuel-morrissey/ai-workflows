---
name: issue-refinement
description: Refinamento assincrono de um issue needs-refinement - investiga o codigo, pergunta em rodadas pelo issue (grilling) ate a fronteira de decisoes esvaziar, registra o refinamento em comentario e entrega o issue em needs-break-down.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh issue edit:*) Bash(gh issue comment:*) Bash(gh issue close:*) Bash(gh label list:*) Bash(gh label create:*) Bash(gh pr list:*) Bash(gh pr view:*) Bash(git log:*) Bash(git show:*) Read Grep Glob WebFetch(domain:docs.github.com) WebFetch(domain:code.claude.com) WebFetch(domain:platform.claude.com)
---

# Refinement

Leva um `[SPEC]` de "recorte conhecido, requisitos por lapidar" a **requisitos
fechados**: toda decisao de produto tomada pelo humano, todo fato conferido no
codigo, nada assumido em silencio. A saida e o comentario `## Refinamento`,
que a `issue-break-down` usa para quebrar em sub-tasks.

O refinamento anda em **rodadas**. Cada rodada roda sem memoria da anterior:
o issue e a unica memoria. Cada rodada termina de um de dois jeitos:

- **pergunta**: um comentario com a proxima fronteira de perguntas, e a
  rodada para;
- **refinamento**: o comentario final, e o issue vai para `needs-break-down`.

Siga estas skills:

- `issue-labeling`: tipos, labels e transicoes. Invoque antes de mexer em
  label.
- `grilling`: fronteira, formato das perguntas e recomendacao.
- `issue-async-first`: canal, handoff, `awaiting-reply` e a mencao ao
  responsavel.

Os dois fins de rodada esperam uma pessoa, e os dois marcam o responsavel
que o workflow informa no system prompt (frase "Responsavel:"; ver "Mencao
ao responsavel" da `issue-async-first`): a rodada de perguntas na linha **Ao
responder**, o `## Refinamento` final na linha **Proximo passo**. A mencao
vai no proprio comentario, nunca num comentario a parte nem numa edicao.
Sem responsavel, nenhum `@`: a linha **Responsavel:** diz que nao ha
responsavel identificavel. O fechamento em `wontfix` ou `deferred` nao
marca ninguem.

**Encadeamento.** O refinamento que termina em `needs-break-down` chama a
quebra sozinho, sem `go`. Quem diz se isso vale nesta rodada e o workflow,
no system prompt, numa frase que comeca por "Encadeamento:". Ligado, o
`## Refinamento` final nao espera ninguem: nao pede `go`, nao marca
ninguem e, no lugar do **Proximo passo**, leva a linha **Em seguida:**
(formato abaixo). Desligado, ou sem a frase, ele pede `go` e marca o
responsavel, como sempre. A rodada de perguntas nunca encadeia: ela para
esperando a resposta. Esta rodada tambem pode ter sido chamada pela
triagem, sem `go`: o fluxo dela e o mesmo.

## Argumento

`$issue` — o numero do issue a refinar.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue.

## Passos

1. **Leia o issue inteiro:**

   ```bash
   gh issue view $issue --json number,title,body,labels,state,url,comments
   ```

   Se o comando falhar, reporte o erro exato e pare.

   Apto exige titulo `[SPEC]` e label `needs-refinement`. Fora disso, comente o
   estado atual e pare (o fluxo so anda para frente).

   Issue com `wontfix` ou `deferred`: complete o fechamento da regra 4 da
   `issue-labeling` e pare.

2. **Reconstrua o estado da conversa.** Ela vive nos comentarios:

   - o `## Triagem` traz a leitura de codigo e o "Em aberto";
   - cada `## Refinamento — rodada N` traz as decisoes ate ali e as perguntas
     daquela rodada;
   - os comentarios humanos depois da ultima rodada sao as **respostas**.

   **Rodando de novo depois de um `undo`.** Um comentario `## Undo` que
   desfez o refinamento (ver "Label de volta" da `issue-labeling`) marca o
   `## Refinamento` anterior a ele como **substituido**: ele nao e mais o
   contrato, e esta rodada escreve um novo. As decisoes da conversa (o
   "Decidido ate aqui" das rodadas e o proprio `## Refinamento` desfeito)
   continuam valendo, a menos que um comentario humano posterior ao `undo`
   as mude; esses comentarios entram como insumo, como respostas. Sem
   pergunta nova na fronteira, a rodada vai direto ao refinamento (passo 6).

   Mapeie cada resposta para a pergunta dela. "ok", "LGTM" ou "resto ok"
   aceitam a recomendacao. Resposta fora das opcoes vale como decisao,
   inclusive com as regras novas que ela trouxer. Resposta ambigua volta como
   pergunta na proxima rodada. Pronto quando toda pergunta da ultima rodada
   tem uma decisao ou esta marcada para voltar.

3. **Volte ao codigo antes de perguntar.** Investigue com `Read`/`Grep`/`Glob`
   o que as decisoes novas tocam: contratos, fluxos e dados que mudam com
   elas. Toda resposta pode revelar uma premissa que o codigo confirma ou
   derruba. Exemplo: "pedido mistura lotes" so e barato se o preco ja vive no
   ingresso. Fato que o codigo responde e seu; registre-o no comentario como
   **o que o codigo mostrou**.

4. **Recompute a fronteira** (ver `grilling`). Respostas novas destravam e
   criam perguntas. Toda decisao em aberto conta: comportamento, dados
   existentes (migracao), quem pode fazer o que, o que a tela diz, como
   convive com o trabalho em andamento (PRs abertos que o recorte toca) e
   prioridade.

5. **Fronteira com perguntas: poste a rodada e pare.** Numere as perguntas
   seguindo a contagem das rodadas anteriores (a rodada 2 comeca em Q7 se a 1
   acabou em Q6), para o humano citar qualquer uma sem ambiguidade:

   ```markdown
   ## Refinamento — rodada <N>

   ### Decidido ate aqui
   - **Q1 — <titulo>:** <decisao>
   - ...todas as rodadas, acumulado

   ### O que o codigo mostrou
   <fatos novos que mudam o quadro; omita se nao houver>

   ### Perguntas
   **Q<n> — <titulo>:** <pergunta; com opcoes A/B quando ajudar>
   ➡️ Recomendacao: <recomendacao e por que, em uma frase>

   **Ao responder** (@responsavel): responda aqui mesmo, citando o numero
   (ex.: "7 ok, 8 vai de B"). Seu comentario dispara a proxima rodada.
   ```

   Esta rodada e o handoff do refinamento: o **Ao responder** faz as vezes
   do **Preciso de voce** e leva a mencao. Sem responsavel, a linha fica
   sem `@` e ganha, logo abaixo, `**Responsavel:** nao ha responsavel
   identificavel; ninguem foi marcado.`

   O "Decidido ate aqui" e acumulado de proposito: a proxima rodada le so
   ele, sem reconstruir a conversa inteira. Depois de postar, aplique
   `awaiting-reply` (ver `issue-async-first`). O label de estado continua
   `needs-refinement`. Fim da rodada.

6. **Fronteira vazia: escreva o refinamento.** Comente com o formato da
   secao "Refinamento", troque o label e pare:

   ```bash
   gh label create needs-break-down --color FBCA04 \
     --description "Escopo entendido, falta quebrar em sub-tasks" 2>/dev/null || true
   gh issue edit $issue --add-label needs-break-down --remove-label needs-refinement
   ```

   Prioridade decidida pelo humano vira o label `priority` na mesma operacao
   (secao "Label de prioridade" da `issue-labeling`).

   Com o encadeamento ligado, o workflow chama a quebra logo depois desta
   rodada: o comentario diz isso e cita o `undo`, sem pedir `go` nem marcar
   ninguem (formato da secao "Refinamento"). Com ele desligado, pede `go` e
   marca o responsavel.

7. Responda com a URL do comentario postado e o estado do issue.

A rodada esta completa quando o issue tem um comentario novo desta rodada e
esta em exatamente um destes estados:

- `needs-refinement` + `awaiting-reply`, com a rodada de perguntas postada;
- `needs-break-down`, com o comentario `## Refinamento` postado.

## Refinamento

O comentario final e o contrato da `issue-break-down`. Siga os principios
de [AGENT-BRIEF.md](../issue-triage/AGENT-BRIEF.md): duravel, comportamental e
com nomes reais de conceitos e contratos. Premissa sobre comportamento de
terceiro, aqui e nos comentarios de rodada, segue a secao
[Premissa externa](../issue-triage/AGENT-BRIEF.md#premissa-externa): marcada
como nao verificada, ou com o URL da fonte oficial consultada. Ao usar web,
siga [Uso da web](../issue-triage/AGENT-BRIEF.md#uso-da-web).

```markdown
## Refinamento

<uma ou duas frases: o recorte e o que muda. Prioridade, se decidida.>

### 1. <tema>
<decisoes deste tema, como comportamento observavel: quem faz o que, o que
o sistema aceita e recusa, o que a tela mostra>

### 2. <tema>
...

### Dados existentes
<migracao, ou por que nao precisa>

### Documentacao a atualizar
<glossario, ADR nova ou revisada>

### Fora do escopo
<o que NAO muda, com todas as letras>

**Proximo passo** (@responsavel): aplique o label `go` neste issue para a
quebra em sub-tasks.
```

Sem responsavel, o **Proximo passo** fica sem `@` e ganha, logo abaixo,
`**Responsavel:** nao ha responsavel identificavel; ninguem foi marcado.`

Com o encadeamento ligado, a linha do **Proximo passo** da lugar a esta,
sem `@` nem pedido de `go`:

```markdown
**Em seguida:** o `/issue-break-down` roda sozinho, sem `go`, a partir deste refinamento. Aplique o label `undo` para desfazer este refinamento.
```

Some o intervalo para revisar o `## Refinamento` antes da quebra: um
recorte errado se corrige com o `undo`, que devolve o issue a
`needs-refinement`.

Agrupe por **tema**, nao por pergunta: decisoes de rodadas diferentes sobre
o mesmo conceito ficam juntas. Toda decisao do "Decidido ate aqui" aparece em
algum tema.

## Fora de escopo

- Quebrar em sub-tasks ou implementar.
- Editar o corpo do issue: o texto original fica como o humano escreveu.
- Decidir pelo humano: escolha de produto sem resposta volta como pergunta,
  com recomendacao.
