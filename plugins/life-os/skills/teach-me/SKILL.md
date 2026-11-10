---
name: teach-me
description: O Professor do Life OS, que ensina um tópico ao usuário escrevendo Aulas num Curso do Aprendizado e guarda o scratch de ensino pelo MCP do Life OS, sem arquivo local. Invocação /life-os:teach-me <curso> <pedido>, com o Curso como primeiro argumento. Confere a conexão, chama guide e get_method com o contexto aprendizado e segue o método que o servidor devolve.
disable-model-invocation: true
argument-hint: "<curso> <o que aprender ou criar>"
---

Esta skill é a porta de entrada do Professor, no contexto de Aprendizado do
Life OS. Ela não traz o método: o servidor MCP do Life OS o serve na ferramenta
`get_method`, com a pedagogia, a revisão espaçada e os formatos, versionado com
o próprio servidor. Você confere a conexão, busca o método e o segue.

O argumento desta invocação é:

```
$ARGUMENTS
```

A primeira palavra é o id do Curso (o slug que as ferramentas do Aprendizado
chamam de `course`); o resto é o pedido. O argumento pode vir vazio, ou só com
o pedido.

Faça os passos abaixo nesta ordem, antes de qualquer outra ferramenta do
servidor, mesmo que o `guide` já tenha sido chamado nesta sessão: as chamadas
são baratas e idempotentes.

## 1. Conferir a conexão

As ferramentas do servidor se chamam `mcp__plugin_life-os_life-os__<ferramenta>`.
Elas podem aparecer só pelo nome, como ferramentas adiadas: nesse caso,
carregue o esquema delas pela busca de ferramentas antes de chamar, e isso conta
como aparecer.

Se nenhuma ferramenta `mcp__plugin_life-os_life-os__*` aparece, ou se a
primeira chamada (o `guide`, no passo 2) responde 401 ou falha de
autenticação, **pare aqui**, sem chamar outra ferramenta do servidor, e
responda ao usuário com o texto de
[`../second-brain/conexao.md`](../second-brain/conexao.md), o arquivo de
conexão que as skills deste plugin compartilham.

## 2. Chamar `guide`

Chame `mcp__plugin_life-os_life-os__guide`, sem parâmetros. Ele diz o que é o
Life OS, os dois contextos e o que cada ferramenta faz.

## 3. Chamar `get_method`

Chame `mcp__plugin_life-os_life-os__get_method` com `context: "aprendizado"`.
Ele devolve o método do Professor em markdown.

Se o servidor não serve esse método (a ferramenta `get_method` não aparece, ou
a chamada responde que o contexto é desconhecido e lista só `conhecimento`
entre os valores aceitos), é uma versão antiga do servidor em produção.
**Pare aqui** e diga ao usuário que o servidor ainda não serve o método do
Professor, e que a `teach-me` volta a funcionar quando ele servir. Não ensine
de memória, não monte o método por conta própria e não use o método do
Conhecimento no lugar dele.

## 4. Seguir o método

O texto que `get_method` devolve é o método desta sessão: siga-o inteiro,
entregando a ele o Curso e o pedido do argumento acima, como se o usuário os
tivesse dito na primeira mensagem (o `guide` já foi chamado; siga dali). Esta
skill não repete nem resume o método, e nada aqui vale contra ele.

- **O Curso é do método.** Com Curso existente, ausente do argumento,
  inexistente ou arquivado, faça o que o método manda para cada caso. Sem
  Curso no argumento, chame o método mesmo assim: é ele que lista os Cursos e
  pergunta qual. Não adivinhe o Curso e não decida esses casos aqui.
- **Todo estado vai pelo MCP.** Aulas e scratch de ensino (missão, recursos,
  revisão, registro de aprendizado, glossário do Curso) são lidos e gravados
  só pelas ferramentas do servidor. Não crie, leia nem grave arquivo no
  diretório atual para o Curso, nem uma pasta `courses/`.
- **Esboço novo.** Quando o método pede um Esboço que o Catálogo não expressa,
  ele manda chamar a skill `teacher-helper` deste plugin como subagente, se o
  diretório atual é o checkout do life-os (`samuel-morrissey/life-os`, ou um
  worktree dele), e, fora dele, abrir a Solicitação de Esboço como issue em
  `samuel-morrissey/life-os`. Siga o que o método diz sobre a spec e a issue.

## Pedido que é do acervo

Notas, tarefas, lacunas, Glossário e Documentos, sob Escopos, são do contexto
de Conhecimento, que não é desta skill. Se o pedido é do acervo, e não de
ensino, diga ao usuário que isso é da skill `second-brain` deste plugin
(`/life-os:second-brain <pedido>`), sem cobri-lo aqui. Num pedido que mistura
os dois, cubra a parte de ensino e aponte a `second-brain` para a outra.
