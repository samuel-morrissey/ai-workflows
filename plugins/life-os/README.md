# life-os

Plugin do Claude Code que liga um agente ao Life OS: registra o servidor MCP do Life OS e traz as skills dos dois contextos do app, Conhecimento e Aprendizado. Com ele instalado, basta exportar o token para o agente ler e gravar no Life OS.

Mora no marketplace `samuel-morrissey-ai-workflows`, ao lado do `samuel-morrissey-skills`, e tem a própria versão em `.claude-plugin/plugin.json`.

## O que ele instala

- **O servidor MCP `life-os`**, declarado em [`.mcp.json`](.mcp.json): `type: http`, na URL de produção do Life OS (`https://life-os-psi-woad-65.vercel.app/api/mcp`), com o token no cabeçalho `Authorization: Bearer ${LIFE_OS_MCP_TOKEN}`. No `/mcp`, ele aparece como `plugin:life-os:life-os`, e as ferramentas como `mcp__plugin_life-os_life-os__<ferramenta>` (por exemplo, `mcp__plugin_life-os_life-os__guide`).
- **As skills**, em [`skills/`](skills/), invocadas com o prefixo `life-os:`:
  - [`second-brain`](skills/second-brain/SKILL.md) (Conhecimento): a porta de entrada sempre que o agente vai usar o acervo. Carrega sozinha; veja [A second-brain](#a-second-brain).
  - [`teacher-helper`](skills/teacher-helper/SKILL.md) (o Desenvolvedor, antes `professor-developer`): veja [A teacher-helper](#a-teacher-helper).
  - Ainda a entrar, numa versão seguinte: `teach-me` (o Professor), só manual, com o Curso como primeiro argumento (`/life-os:teach-me <curso> <pedido>`).

## Instalar

```
/plugin marketplace add samuel-morrissey/ai-workflows
/plugin install life-os@samuel-morrissey-ai-workflows
```

Quem já tem o marketplace adicionado roda só o segundo comando. Em `settings.json`, a chave de `enabledPlugins` é `life-os@samuel-morrissey-ai-workflows`.

## O token

1. No Life OS, abra **Configurações > Acesso por MCP** e gere um token. Gere um por agente ou por máquina, para poder revogar um sem derrubar os outros.
2. Guarde-o numa linha de um arquivo fora do git que o seu shell carrega (por exemplo, um `~/.secrets` lido pelo `~/.bashrc` ou `~/.zshrc`):

   ```sh
   export LIFE_OS_MCP_TOKEN=...
   ```

3. Abra um terminal novo, ou recarregue o shell, antes de abrir o Claude Code: ele lê a variável quando inicia.

O token nunca entra em repositório nenhum, nem neste.

**Sem o token**, o Claude Code carrega o servidor mesmo assim, com o texto `${LIFE_OS_MCP_TOKEN}` literal no cabeçalho, e a autenticação falha sem erro claro (o `claude mcp list` mostra um aviso sobre a variável ausente). Se o servidor não conecta ou as ferramentas respondem 401, confira primeiro se `LIFE_OS_MCP_TOKEN` está exportado no shell que abriu o Claude Code.

### Outro ambiente

`LIFE_OS_MCP_URL` só serve para apontar o servidor a outro ambiente, como um Life OS local ou um deploy de preview. Definida, ela vale no lugar da URL de produção:

```sh
export LIFE_OS_MCP_URL=http://localhost:3000/api/mcp
```

Para o uso normal, não a defina.

## Remover o servidor antigo

Um servidor `life-os` de escopo user ou project, com a mesma URL, vence o do plugin, e o `/mcp` passa a mostrar esse no lugar do `plugin:life-os:life-os`. Quem configurou o Life OS à mão antes do plugin o remove:

```sh
claude mcp list
claude mcp remove life-os -s user
```

Se ele estiver no `.mcp.json` de um projeto, use `-s project` dentro do projeto, ou tire a entrada do arquivo.

## Conferir

Numa sessão nova do Claude Code, com `LIFE_OS_MCP_TOKEN` exportado:

1. Rode `/mcp`: ele lista `plugin:life-os:life-os` como conectado.
2. Peça ao agente para chamar a ferramenta `mcp__plugin_life-os_life-os__guide`: ela responde com a apresentação do Life OS e das ferramentas dele.

Se o servidor aparece sem o prefixo `plugin:life-os:`, é o servidor antigo vencendo; veja [Remover o servidor antigo](#remover-o-servidor-antigo).

## A second-brain

A porta de entrada do Conhecimento: notas, tarefas, lacunas, Glossário e Documentos, sob Escopos. Ela não traz o método de uso; o servidor o serve na ferramenta `get_method`, versionado com ele. A skill:

1. confere a conexão: se as ferramentas `mcp__plugin_life-os_life-os__*` não aparecem ou respondem 401, para e diz os três passos ([O token](#o-token), gerar o token em **Configurações > Acesso por MCP** e [Remover o servidor antigo](#remover-o-servidor-antigo)), sem chamar outra ferramenta;
2. chama `guide`;
3. chama `get_method` com `context: "conhecimento"`;
4. segue o texto devolvido como o método da sessão, a começar pelo ritual de entrada dele.

Carrega sozinha: sem `disable-model-invocation`, o agente a usa sempre que o pedido envolve o acervo ("o que anotei sobre X", "crie uma lacuna") ou uma ferramenta do Conhecimento. Também roda à mão:

```
/life-os:second-brain <pedido sobre o acervo>
```

Num servidor sem `get_method`, ela diz que a ferramenta falta e segue o método que o `guide` dessa versão traz. Cursos e Aulas ficam com a `teach-me`.

## A teacher-helper

O Desenvolvedor do contexto de Aprendizado. Quando o Catálogo não expressa um visual que a Aula precisa, o Professor (a skill `teach-me`, ou a `/professor` do learnings até ela chegar) a chama como subagente com uma spec de significado: a Aula, o que o visual transmite, os dados e se o padrão é reutilizável. Ela constrói o Esboço como componente React em `src/contexts/aprendizado/sketches/` do life-os, registra-o em `sketches/index.ts`, passa pela bateria de testes, abre o PR do Esboço e devolve ao Professor só a tag e o que ela significa. Nunca toca o Catálogo nem promove Esboço a Componente.

Só manual, e só com o checkout do life-os (`samuel-morrissey/life-os`, ou um worktree dele) como diretório atual, porque edita os arquivos de lá, roda os testes de lá e depende do deploy dele na Vercel:

```
cd <checkout do life-os>
/life-os:teacher-helper <spec do Professor>
```

Fora do life-os, ela para antes de qualquer edição e responde que só roda lá e como rodar. Enquanto isso, o Professor abre a Solicitação de Esboço como issue no life-os.

## Publicar uma atualização

Todo PR que muda uma skill deste plugin ou o `.mcp.json` sobe a versão em `.claude-plugin/plugin.json` (patch para correção de texto, minor para skill nova ou comportamento novo). Depois do merge, rode `/plugin`, atualize o marketplace `samuel-morrissey-ai-workflows` e depois o plugin `life-os`, e abra uma sessão nova.
