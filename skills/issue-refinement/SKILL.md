---
name: issue-refinement
description: Refinamento assincrono de um issue need-refinement - investiga o codigo, pergunta em rodadas pelo issue (grilling) ate a fronteira de decisoes esvaziar, registra o refinamento em comentario e entrega o issue em need-break-down.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue list:*) Bash(gh issue edit:*) Bash(gh issue comment:*) Bash(gh label list:*) Bash(gh label create:*) Bash(gh pr list:*) Bash(gh pr view:*) Bash(git log:*) Bash(git show:*) Read Grep Glob
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
- **refinamento**: o comentario final, e o issue vai para `need-break-down`.

Siga estas skills:

- `issue-labeling`: tipos, labels e transicoes. Invoque antes de mexer em
  label.
- `grilling`: fronteira, formato das perguntas e recomendacao.
- `issue-async-first`: canal, handoff e `awaiting-reply`.

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

   Apto exige titulo `[SPEC]` e label `need-refinement`. Fora disso, comente o
   estado atual e pare (o fluxo so anda para frente).

2. **Reconstrua o estado da conversa.** Ela vive nos comentarios:

   - o `## Triagem` traz a leitura de codigo e o "Em aberto";
   - cada `## Refinamento — rodada N` traz as decisoes ate ali e as perguntas
     daquela rodada;
   - os comentarios humanos depois da ultima rodada sao as **respostas**.

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

   **Ao responder:** responda aqui mesmo, citando o numero (ex.: "7 ok, 8 vai
   de B"). Seu comentario dispara a proxima rodada.
   ```

   O "Decidido ate aqui" e acumulado de proposito: a proxima rodada le so
   ele, sem reconstruir a conversa inteira. Depois de postar, aplique
   `awaiting-reply` (ver `issue-async-first`). O label de estado continua
   `need-refinement`. Fim da rodada.

6. **Fronteira vazia: escreva o refinamento.** Comente com o formato da
   secao "Refinamento", troque o label e pare:

   ```bash
   gh label create need-break-down --color FBCA04 \
     --description "Escopo entendido, falta quebrar em sub-tasks" 2>/dev/null || true
   gh issue edit $issue --add-label need-break-down --remove-label need-refinement
   ```

   Prioridade decidida pelo humano vira o label `priority` na mesma operacao.

7. Responda com a URL do comentario postado e o estado do issue.

A rodada esta completa quando o issue tem um comentario novo desta rodada e
esta em exatamente um destes estados:

- `need-refinement` + `awaiting-reply`, com a rodada de perguntas postada;
- `need-break-down`, com o comentario `## Refinamento` postado.

## Refinamento

O comentario final e o contrato da `issue-break-down`. Siga os principios
de [AGENT-BRIEF.md](../issue-triage/AGENT-BRIEF.md): duravel, comportamental e
com nomes reais de conceitos e contratos.

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
```

Agrupe por **tema**, nao por pergunta: decisoes de rodadas diferentes sobre
o mesmo conceito ficam juntas. Toda decisao do "Decidido ate aqui" aparece em
algum tema.

## Fora de escopo

- Quebrar em sub-tasks ou implementar.
- Editar o corpo do issue: o texto original fica como o humano escreveu.
- Decidir pelo humano: escolha de produto sem resposta volta como pergunta,
  com recomendacao.
