# Modelo: skill de projeto `evidencias`

Copie para `.claude/skills/evidencias/SKILL.md` no repositorio do projeto e
preencha. A `issue-qa` (e a `to-pr`, localmente) leem este arquivo antes de
capturar qualquer evidencia. Ele diz o que e evidencia ideal **neste**
projeto e como chegar nela. O que o agente pode executar continua sendo
decidido pelo input `evidence_tools` do workflow: um comando citado aqui e
ausente de la nao roda.

```markdown
---
name: evidencias
description: Como capturar evidencias de uso neste projeto - o que mostrar, como subir o app, dados e logins de teste, e o que nao fazer. Use antes de capturar prints, gravacoes ou saidas para um PR.
---

# Evidencias deste projeto

## Evidencia ideal

<O que um revisor precisa ver para entender uma mudanca aqui. Ex.: print da
tela inteira em 1280x800, tema claro; para fluxo com mais de um passo, GIF
de ate 15 s. Para endpoints, a resposta JSON completa com o status.>

## Como subir

<Comandos, na ordem, para ter o app respondendo. Porta e URL base. Tempo
tipico ate a porta responder. Ex.:>

    npm run dev -- --port 3100      # responde em http://localhost:3100 em ~10 s

Prefira um script unico que sobe, espera a porta, captura e encerra, rodado
com `node` (liberado em evidence_tools).

## Dados e acesso

<Seeds a rodar, usuario e senha de teste, variaveis de ambiente locais. Nada
de credencial real: valores de desenvolvimento apenas.>

## Antes

<Como obter o estado anterior a mudanca. O padrao e `git switch --detach
origin/<base>` no mesmo checkout. Se o projeto precisa de `git worktree`
(ex.: build demorado), diga aqui e como apontar o comando de subida para
outra pasta.>

## Limites

<O que nao fazer: URLs externas, acoes que disparam e-mail ou cobranca,
tabelas que nao podem ser limpas, telas fora do escopo do fluxo.>
```
