---
name: remote-to-pr
description: Abre um PR em fluxo remoto e assincrono, sem ninguem para responder - segue a to-pr inteira (formato, estilo da casa, vinculos), monta Evidencias e Criterios de aceite a partir do relatorio do QA e abre direto, sem perguntar. Use para abrir PR dentro de um workflow, como na issue-remote-implement.
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

   A **Qualidade de codigo** vem da verificacao que quem chamou ja rodou
   (na `issue-remote-implement`, a bateria do passo 5): um comando por
   linha, com o resultado dessa rodada. Nao rode a bateria de novo. Nada
   rodou? Use a declaracao da secao, com o motivo que quem chamou deu.

   As **Evidencias** seguem o criterio da `to-pr`: comparacao antes/depois
   no nivel do usuario e/ou visual, nunca a saida da bateria. No fluxo
   remoto quem capturou foi o QA (skill `issue-qa`), e quem chamou passa o
   caminho do relatorio da ultima rodada (`qa-<n>.md`). Use as capturas
   `antes`/`depois` dele, referenciadas como a *Publicacao* do system prompt
   manda: com bucket, `![c1 antes](<url-base>/qa2-c1-antes.png)` e
   `![c1 depois](<url-base>/qa2-c1-depois.png)`; com artifact, o nome do
   arquivo e o link da run onde o artifact `evidencias-<issue>` fica. O
   runner tem navegador headless, Playwright e ffmpeg quando o consumidor os
   libera: "sem tela" nao e motivo de declaracao. A declaracao so vale quando
   o QA nao rodou (nenhuma ferramenta liberada) ou a mudanca nao tem nada
   observavel; nos dois casos, diga qual evidencia voce anexaria.

   A subsecao **Criterios de aceite** da secao QA e a tabela da ultima
   rodada do QA, com a coluna Evidencia trocada pelas referencias
   publicadas, mais a linha da rodada e do Ambiente. Criterio reprovado que
   a `issue-remote-implement` decidiu nao corrigir leva, na mesma celula,
   "Nao corrigido: <motivo>". QA que nao rodou usa a declaracao do
   `TEMPLATE.md`, com o motivo que quem chamou deu.

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
PR lista cada issue do `Closes`, segue o `TEMPLATE.md` da `to-pr`, as
Evidencias e os Criterios de aceite vem do relatorio do QA (ou declaram por
que nao) e termina na ultima secao de conteudo.
