# life-os

Plugin do Claude Code que liga um agente ao Life OS: registra o servidor MCP do Life OS e traz as skills dos dois contextos do app, Conhecimento e Aprendizado. Com ele instalado, basta exportar o token para o agente ler e gravar no Life OS.

Mora no marketplace `samuel-morrissey-ai-workflows`, ao lado do `samuel-morrissey-skills`, e tem a própria versão em `.claude-plugin/plugin.json`.

## O que ele instala

- **O servidor MCP `life-os`**, declarado em [`.mcp.json`](.mcp.json): `type: http`, na URL de produção do Life OS (`https://life-os-psi-woad-65.vercel.app/api/mcp`), com o token no cabeçalho `Authorization: Bearer ${LIFE_OS_MCP_TOKEN}`. No `/mcp`, ele aparece como `plugin:life-os:life-os`, e as ferramentas como `mcp__plugin_life-os_life-os__<ferramenta>` (por exemplo, `mcp__plugin_life-os_life-os__guide`).
- **As skills**, invocadas com o prefixo `life-os:`. Ainda a entrar; cada uma chega numa versão seguinte do plugin:
  - `second-brain` (Conhecimento): a porta de entrada sempre que o agente vai usar o Life OS. Automática pela descrição e também manual (`/life-os:second-brain`).
  - `teacher-helper` (o Desenvolvedor, antes `professor-developer`): só manual, chamada pela `teach-me` quando o Catálogo não expressa um visual. Roda só com o life-os como diretório atual.
  - `teach-me` (o Professor): só manual, com o Curso como primeiro argumento (`/life-os:teach-me <curso> <pedido>`).

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

## Publicar uma atualização

Todo PR que muda uma skill deste plugin ou o `.mcp.json` sobe a versão em `.claude-plugin/plugin.json` (patch para correção de texto, minor para skill nova ou comportamento novo). Depois do merge, rode `/plugin`, atualize o marketplace `samuel-morrissey-ai-workflows` e depois o plugin `life-os`, e abra uma sessão nova.
