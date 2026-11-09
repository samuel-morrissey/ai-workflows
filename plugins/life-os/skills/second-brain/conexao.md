# Verificação de conexão com o Life OS

Texto que as skills do plugin `life-os` (`second-brain` e `teach-me`)
devolvem ao usuário quando as ferramentas `mcp__plugin_life-os_life-os__*` não
aparecem ou respondem 401.
Responda com ele e pare, sem chamar outra ferramenta do servidor:

```
Não consegui falar com o servidor MCP do Life OS: as ferramentas
mcp__plugin_life-os_life-os__* não estão disponíveis nesta sessão, ou
responderam 401 (não autorizado).

Para conectar:

1. Exporte o token no shell que abre o Claude Code, numa linha de um arquivo
   fora do git que o shell carrega:
   export LIFE_OS_MCP_TOKEN=...
2. Gere o token no Life OS, em Configurações > Acesso por MCP, se ainda não
   tem um para esta máquina.
3. Remova o servidor life-os antigo do escopo user, se houver um: ele vence o
   do plugin.
   claude mcp remove life-os -s user

Depois, abra uma sessão nova do Claude Code e confira no /mcp que aparece
plugin:life-os:life-os conectado.
```
