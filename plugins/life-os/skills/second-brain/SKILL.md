---
name: second-brain
description: O método de uso do Conhecimento do Life OS, o acervo pessoal do usuário (notas, tarefas, lacunas, termos do Glossário, Documentos e tipos de Documento, sob Escopos). Use sempre que for ler, buscar, criar, editar, comentar ou arquivar algo no acervo do Life OS, ou antes de chamar qualquer ferramenta mcp__plugin_life-os_life-os__* do Conhecimento, inclusive em pedidos como "o que anotei sobre X", "quais tarefas tenho", "crie uma lacuna", "organize o acervo". Confere a conexão, chama guide e get_method e segue o método que o servidor devolve. Não cobre Cursos e Aulas, que são da teach-me.
argument-hint: "[pedido sobre o acervo]"
---

Esta skill é a porta de entrada do Conhecimento do Life OS. Ela não traz o
método: o servidor MCP do Life OS o serve na ferramenta `get_method`, versionado
com o próprio servidor. Você confere a conexão, busca o método e o segue.

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
responda ao usuário com o texto de [`conexao.md`](conexao.md), neste
diretório.

## 2. Chamar `guide`

Chame `mcp__plugin_life-os_life-os__guide`, sem parâmetros. Ele diz o que é o
Life OS, os dois contextos, os Escopos e o que cada ferramenta faz.

## 3. Chamar `get_method`

Chame `mcp__plugin_life-os_life-os__get_method` com `context: "conhecimento"`.
Ele devolve o método do Conhecimento em markdown.

Se o servidor não tem `get_method` (a ferramenta não aparece, ou a chamada
responde que ela não existe), é uma versão antiga do servidor em produção.
Diga ao usuário que o servidor ainda não tem a ferramenta `get_method` e que,
nessa versão, o método vem no próprio `guide`; siga então o texto do `guide`
como o método. Não monte o método de memória nem por conta própria.

## 4. Seguir o método

O texto que `get_method` devolve é o método desta sessão: siga-o inteiro, a
começar pelo ritual de entrada que ele descreve (o `guide` dele já foi
chamado; siga dali). Esta skill não repete nem resume o método, e nada aqui
vale contra ele.

## Pedido que também envolve o Aprendizado

Cursos e Aulas, o Professor e o scratch de ensino são do contexto de
Aprendizado, que não é desta skill. Num pedido que mistura os dois, cubra a
parte do acervo por este método e diga ao usuário que a parte do Aprendizado é
da skill `teach-me` deste plugin (`/life-os:teach-me <curso> <pedido>`).
