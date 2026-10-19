# claude-marketplace

Marketplace pessoal de plugins para o Claude Code.

## Instalar

```
/plugin marketplace add samuel-morrissey/claude-marketplace
/plugin install samuel-morrissey-skills@samuel-morrissey-claude-marketplace
```

## Plugins

- **samuel-morrissey-skills** — skills e workflows: triagem de issues/PRs, abertura de PRs e utilitarios de automacao para GitHub Actions.

## Skills

### Fluxo de issues

Etapas, na ordem em que um issue percorre o fluxo. Cada skill recebe o
numero do issue como argumento.

- **issue-triage** — triagem de um issue cru: investiga o codigo, atribui tipo (MAP/SPEC/pontual) e label de estado. Entrega issue pontual com brief pronto, MAP/SPEC para a proxima etapa, ou fecha como `wontfix` (ja rejeitado ou implementado) ou `deferred` (despriorizado pelo humano).
- **issue-refinement** — refinamento assincrono de um issue `needs-refinement`: investiga o codigo, pergunta em rodadas pelo proprio issue ate a fronteira de decisoes esvaziar, registra o refinamento em comentario e entrega o issue em `needs-break-down`.
- **issue-break-down** — quebra um issue `needs-break-down` em sub-tasks: fatias verticais que vao para producao sozinhas, cada uma com brief e criterios de aceite, ligadas ao pai como sub-issues com bloqueios nativos. Entrega o pai em `ready-for-agent` ou `ready-for-human`.
- **issue-remote-implement** — implementa um issue em uma rodada que termina em um PR: num pontual `ready-for-agent`, o PR dele; numa `[SUB-TASK]` despachada pelo workflow, o PR da camada dela na stack do pai. Desenvolve test-first nos criterios de aceite. Num pai com sub-tasks, quem orquestra (uma sub-task por vez, PRs empilhados) e o workflow de `ai-workflows`.

### Convencoes do fluxo

Skills de apoio que as etapas acima seguem.

- **issue-labeling** — vocabulario canonico: tipos (MAP, SPEC, SUB-TASK e os pontuais), labels de estado (`needs-*`, `ready-for-*`, `awaiting-pr-review`, `wontfix`, `deferred`), labels de trabalho, espera e prioridade (`work-in-progress`, `awaiting-reply`, `priority`) e regras de transicao.
- **issue-git-flow** — estrutura de git do fluxo: nome e base de cada branch, vinculo entre PR e issue ou sub-issue, a stack de PRs de um pai e como cada issue fecha.
- **issue-async-first** — trabalho assincrono por essencia: esgota tudo que nao depende de humano, agrupa toda intervencao em uma unica mensagem e, quando impeditiva, para deixando handoff completo.
- **grilling** — questionamento em lote: monta a fronteira de decisoes em aberto, pergunta tudo de uma vez com recomendacao e reserva fatos para investigacao propria.

### Pull requests

- **to-pr** — abre um pull request, ou redige o texto recomendado para um existente.
- **remote-to-pr** — abre um PR em fluxo remoto e assincrono, sem ninguem para responder: segue a `to-pr` inteira e abre direto, sem perguntar.

### Utilitarios

- **80-20** — modo Pareto: maior retorno com o menor esforco na tarefa dada.
- **hello-issue** — skill de exemplo que valida a integracao entre o marketplace e um repositorio consumidor, publicando um comentario no issue informado.
