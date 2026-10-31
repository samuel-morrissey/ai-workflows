---
name: issue-async-first
description: Trabalho assincrono por essencia - esgotar tudo que nao depende de humano, agrupar toda necessidade de intervencao em uma unica mensagem no canal do contexto (issue, PR ou chat) e, quando impeditiva, parar deixando handoff completo para a proxima rodada. Use sempre que precisar de informacao, decisao ou acao humana durante uma tarefa.
---

# Async First

O trabalho e **assincrono por essencia**: o humano nao esta olhando agora.
Trabalhe como quem escreve para alguem que vai ler horas depois — e para um
agente que vai retomar sem memoria nenhuma.

## O canal

A mensagem vai no canal do contexto em que voce esta:

| Contexto | Canal |
|---|---|
| Issue | Comentario no issue |
| Pull Request | Comentario no PR |
| Sessao de chat | Mensagem final da resposta |

## Regras

1. **Esgote o trabalho antes de pedir intervencao.** Avance por todos os
   caminhos que nao dependem de humano ate o fim. So peca intervencao quando
   todo o trabalho independente estiver concluido.
2. **Uma unica mensagem, no final, com tudo.** Acumule as duvidas e
   necessidades que surgirem pelo caminho e envie-as juntas, em lote, no canal
   do contexto. Cada pergunta deve ser especifica e respondivel de forma
   assincrona.
3. **Intervencao impeditiva: pare e espere a resposta.** Impeditiva e a que
   bloqueia qualquer continuacao do trabalho. Envie a mensagem e encerre a
   rodada; a resposta humana dispara a proxima. Necessidade nao impeditiva
   apenas entra na mensagem final — o trabalho segue completo.

   Em issue ou PR, sinalize a espera com o label `awaiting-reply` (ver
   `issue-labeling`) logo depois de postar a mensagem, criando-o se faltar:

   ```bash
   gh label create awaiting-reply --color C5DEF5 \
     --description "Rodada encerrada com pergunta impeditiva; aguarda resposta humana" 2>/dev/null || true
   gh issue edit <numero> --add-label awaiting-reply   # em PR: gh pr edit
   ```

   So intervencao impeditiva leva o label. Quem o remove e o workflow, no
   inicio da proxima rodada — nao a skill.
4. **Handoff completo nos canais efemeros.** Em issue e PR a sessao morre com a
   rodada: quem continua e outro agente, sem memoria. A mensagem precisa
   carregar tudo que ele vai precisar:

   ```markdown
   ## Status

   **Feito:** o que foi concluido e decidido nesta rodada
   **Falta:** o que ainda nao foi feito e por que
   **Preciso de voce** (@responsavel): perguntas ou acoes, especificas
   **Ao responder:** o proximo passo com a resposta em maos
   ```

   Em issue, o `(@responsavel)` segue a "Mencao ao responsavel", abaixo.

   No chat a sessao e o contexto sao preservados — basta a pergunta, sem
   handoff.
5. **Em issue, marque o responsavel no pedido de acao.** Quem marcar nao e
   decisao sua: o workflow da rodada ja resolveu o responsavel e o informa no
   system prompt, numa frase que comeca por **"Responsavel:"**. Use-a como
   esta (ver "Mencao ao responsavel", abaixo).

## Mencao ao responsavel

Vale para todo comentario que deixa um issue esperando uma pessoa: o handoff
desta skill e o comentario final de etapa que espera o `go` (as skills de
cada etapa dizem em qual linha).

- **Com logins** (`Responsavel: @ana @bia ...`): marque **todos** eles, e so
  eles, na linha do pedido de acao. No handoff, essa linha e o **Preciso de
  voce**:

  ```markdown
  **Preciso de voce** (@ana @bia): perguntas ou acoes, especificas
  ```

- **Sem responsavel** (`Responsavel: sem responsavel ...`), ou sem a frase
  no system prompt: nao marque ninguem com `@`. Diga isso numa linha propria,
  logo abaixo do pedido de acao:

  ```markdown
  **Preciso de voce:** perguntas ou acoes, especificas
  **Responsavel:** nao ha responsavel identificavel; ninguem foi marcado.
  ```

Regras da mencao:

- So em comentario novo. Nunca edite um comentario existente para
  acrescentar `@`, nem poste um segundo comentario so para avisar: a mencao
  vai no proprio comentario que pede a acao.
- Bot ou agente nunca e marcado, mesmo que seja o autor do issue: numa
  `[SUB-TASK]`, o responsavel ja vem como o do pai.
- Nao procure outra pessoa (assignee, autor, quem aplicou o `go`) para
  marcar: a frase do workflow e a unica fonte.
- Encerramento terminal (`wontfix`, `deferred`) nao e espera: nao marca.
- No chat nao ha mencao. Em PR, a mencao segue a skill que comenta nele.

O criterio de uma boa mensagem assincrona: outro agente, lendo so o canal,
continua o trabalho sem pedir nada de novo.
