---
name: remote-to-pr
description: Abre um PR em fluxo remoto e assincrono, sem ninguem para responder - segue a to-pr inteira (formato, estilo da casa, vinculos) e abre direto, sem perguntar. Use para abrir PR dentro de um workflow, como no /implement.
---

# Remote to PR

A `to-pr` e a fonte unica do **formato** do PR. Esta skill so a adapta a um
fluxo remoto: ninguem esta olhando, entao nada espera resposta. Mudou o
formato na `to-pr`? Vale aqui na proxima execucao, sem tocar neste arquivo.

## Passos

1. **Invoque a skill `to-pr`** e siga o ramo *create* dela por inteiro:
   leitura do range, estilo da casa, evidencias, `TEMPLATE.md`, regra de
   ghostwriter e barra de exaustividade sobre o diff. As substituicoes
   abaixo valem por cima dela, e so elas.

   As **Evidencias** vem da verificacao que quem chamou ja rodou (na
   `issue-remote-implement`, a bateria do passo 5): cole a saida dessa
   rodada, o teste que falhava e agora passa. Rode de novo so o que falta
   para fechar o par antes/depois.

2. **Base e head vem de quem chamou.** Quem chama ja definiu a base pela
   `issue-git-flow`. Use o par recebido, sem resolver pela branch padrao.

3. **Vinculos pela `issue-git-flow`.** As linhas de vinculo do topo do corpo
   seguem a tabela dela. Elas substituem a tabela de vinculos da `to-pr`,
   inclusive o `Parte de #<pai>` da sub-task. Depois de abrir, faca o
   vinculo nativo pela API (`addCloseIssueReferences`) e confira
   `closingIssuesReferences`, como a `issue-git-flow` manda — sempre,
   qualquer que seja a base.

4. **Sem "mostrar e perguntar".** O passo de imprimir o rascunho e esperar
   resposta vira: abra o PR direto, com o rascunho final.

   ```bash
   git push -u origin <head>
   gh pr create --base <base> --head <head> --title "<titulo>" --body-file <arquivo-temporario>
   ```

   O humano revisa o PR, nao o rascunho. Ponto em que a `to-pr` perguntaria
   (referencia ambigua, idioma da casa diferente)? Decida pelo melhor
   palpite e registre a decisao numa linha do comentario que quem chamou
   posta no issue.

5. **Autoria.** Titulo e corpo seguem a regra de ghostwriter da `to-pr`: o
   corpo termina na ultima secao de conteudo, sem rodape "Generated with",
   sem link de sessao e sem mencao a agente. Excecao do fluxo remoto: os
   **commits** podem levar o trailer `Co-Authored-By`.

6. Devolva a URL do PR para quem chamou.

Pronto quando o PR esta aberto da head para a base recebidas, o corpo comeca
pelas linhas de vinculo da `issue-git-flow`, o `closingIssuesReferences` do
PR lista cada issue do `Closes`, segue o `TEMPLATE.md` da `to-pr`
e termina na ultima secao de conteudo.
