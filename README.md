# ai-workflows

Workflows reutilizáveis do GitHub Actions que levam o fluxo de issues da Caravela para o Claude: triagem, refinamento, quebra em sub-tasks e implementação.

Cada repositório da organização tem um único arquivo, `.github/workflows/ai.yml`. Ele chama o `router.yml` daqui, e o router escolhe a etapa que o evento aciona.

## Etapas

| Etapa | Dispara quando | Workflow |
| --- | --- | --- |
| Triagem | o label `go` entra num issue com `needs-triage` ou sem label de estado, ou uma pessoa coloca `needs-triage`. Também quando uma pessoa coloca `wontfix` ou `deferred`: a triagem fecha o issue e comenta o motivo | `issue-triage.yml` |
| Refinamento | o label `go` entra num issue com `needs-refinement`, ou uma pessoa coloca `needs-refinement` | `issue-refinement.yml` |
| Quebra em sub-tasks | o label `go` entra num issue com `needs-break-down`, ou uma pessoa coloca `needs-break-down` | `issue-break-down.yml` |
| Implementação | o label `go` entra num issue com `ready-for-agent`. Num pontual, abre o PR dele. Num pai com sub-tasks, é o planner da cadeia: despacha uma sub-task por vez e empilha os PRs numa stack | `issue-remote-implement.yml` |
| Sub-task | o planner do pai despacha a próxima sub-task, o label `go` entra numa `[SUB-TASK]` (roda só ela), ou uma pessoa responde a uma pergunta dela | `issue-sub-task.yml` |
| Fechar sub-task | um PR é mergeado numa branch que não é a padrão. Fecha os issues do `Closes` do corpo, porque o GitHub só faz isso sozinho na branch padrão. Numa stack o GitHub já fechou; só o label `awaiting-pr-review` sai | `pr-merged.yml` |

Nenhuma etapa roda em issue com `work-in-progress`. Esse label marca que outro worker já está trabalhando no issue. Os workflows colocam e tiram esse label sozinhos. Num pai com sub-tasks ele fica durante a cadeia inteira (veja abaixo).

### O label `go`

`go` é o seu "pode seguir". Ele não diz em que etapa o issue está: isso é o label de estado (`needs-triage`, `needs-refinement`, `needs-break-down`, `ready-for-agent`). `go` diz que a etapa desse estado pode rodar agora. A etapa tira o `go` ao começar, e você coloca de novo quando quiser a próxima.

Por que ele existe: quando uma etapa troca o label sozinha (ex.: o refinamento termina e põe `needs-break-down`), ou quando um agente cria um issue já com `needs-triage`, o GitHub não dispara nada, porque label aplicado por token não gera evento. O `go` destrava esses casos. Na implementação ele é o único gatilho: `ready-for-agent` sozinho nunca inicia nada.

Um `go` colocado enquanto a etapa roda é descartado no fim dela, porque um label que já está no issue não pode ser colocado de novo. Coloque outro quando a rodada terminar. `go` num issue com `awaiting-pr-review`, fechado ou sem etapa para o estado dele não dispara nada; o próximo workflow que rodar nesse issue tira o label.

Quando a implementação termina e abre o PR, o issue troca `ready-for-agent` por `awaiting-pr-review`: a implementação acabou e o PR está pronto para análise.

### Issue com sub-tasks

A quebra cria `[SUB-TASK]`s ligadas ao issue pai, com bloqueios entre elas. Um único `go` no **pai** resolve todas:

1. Coloque `go` no pai. O pai ganha `work-in-progress`: a cadeia está rodando.
2. O agente implementa as sub-tasks **uma por vez**, na ordem dos bloqueios, cada uma numa run própria. A primeira nasce da `main`; cada seguinte nasce da branch da anterior, e o PR dela aponta para essa branch. A sub-task ganha `awaiting-pr-review` quando o PR abre.
3. A partir do segundo PR, os PRs entram numa [stack do GitHub](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs). O pai recebe um comentário de status, atualizado a cada rodada, com a camada, o PR e o estado de cada sub-task.
4. Quando toda sub-task tem PR, o PR do topo ganha `Closes #<pai>`, o pai troca `ready-for-agent` por `awaiting-pr-review` e o `work-in-progress` sai.
5. Revise a stack de baixo para cima e faça o merge pela interface do GitHub. Mergear uma camada do meio leva as de baixo junto; mergear o topo leva tudo. Cada camada que entra na `main` fecha a sub-task dela, e o topo fecha o pai. O GitHub rebaseia as camadas de cima sozinho.

Não existe mais branch de integração nem PR do pai: a stack faz esse papel, e cada camada vai para a `main` por si.

A cadeia para sozinha, e o `work-in-progress` sai do pai, quando a próxima sub-task é humana (`**Executor:** humano` no brief), quando ela está bloqueada por um issue de fora que ainda está aberto, quando uma rodada termina sem PR e sem pergunta (o comentário de status traz o link da run), ou quando os PRs não puderam ser empilhados. Resolva o que parou e coloque `go` no pai de novo: ele retoma de onde estava, porque o planner só olha o que ainda falta.

Quando uma sub-task para numa pergunta, ela ganha `awaiting-reply` e o pai **continua** com `work-in-progress`: a cadeia está esperando você. Responda na sub-task; a resposta roda a sub-task de novo e a cadeia segue. Para abandonar uma cadeia no meio, tire o `work-in-progress` do pai na mão.

`go` numa `[SUB-TASK]` roda só ela: a branch nasce do topo da stack atual e o PR entra na stack, mas o planner não segue para a próxima. Serve para refazer uma sub-task (feche o PR dela antes) ou para andar uma de cada vez. Sub-task que já tem PR aberto, que é humana ou que está bloqueada por outra ainda sem PR não roda; o agente comenta o motivo.

Cada camada da stack precisa da camada de baixo para existir, por isso a ordem é fixa: um bloqueio só diz quem vem antes. Como cada sub-task enxerga o código de todas as anteriores, nenhuma precisa esperar merge para começar.

### Perguntas e respostas

Quando uma etapa para com uma pergunta, o issue ganha `awaiting-reply`: a vez é de um humano. Responda no issue: a resposta já dispara a próxima rodada da etapa, em qualquer estado, inclusive na implementação. O workflow tira o `awaiting-reply` quando a rodada seguinte começa.

Comentário só dispara etapa em issue com `awaiting-reply`. Fora disso, comente à vontade: nada roda. Comentários de bots e de PRs nunca disparam nada.

| Labels no issue | Quer dizer |
| --- | --- |
| `needs-triage` + `awaiting-reply` | esperando você responder |
| `needs-triage` + `work-in-progress` | Claude trabalhando agora |
| `needs-triage` sozinho | esperando `go` para a triagem rodar |
| `ready-for-agent` sozinho | esperando `go` para implementar |
| `ready-for-agent` + `awaiting-reply` | a implementação parou numa pergunta; responda no issue |
| `ready-for-agent` + `work-in-progress` | Claude implementando agora. Num pai com sub-tasks: a cadeia está rodando, ou esperando a resposta de uma sub-task com `awaiting-reply` |
| `[SUB-TASK]` + `awaiting-pr-review` | PR da sub-task aberto, na stack do pai |
| `[SUB-TASK]` + `awaiting-reply` | a sub-task parou numa pergunta; responda nela e a cadeia segue |
| `needs-refinement` + `awaiting-reply` | perguntas do refinamento esperando você |
| `needs-break-down` sozinho | esperando `go` para quebrar em sub-tasks |
| `awaiting-pr-review` | PR aberto, esperando revisão e merge |
| `wontfix` | fechado: não será feito. Um pedido igual é fechado como `wontfix` de novo |
| `deferred` | fechado: despriorizado. Pode ser reaberto; um pedido igual cita este issue e segue o fluxo |

Para tirar um issue do fluxo, coloque `wontfix` (não será feito) ou `deferred` (não agora). Comentar o motivo é opcional: a triagem roda, tira o label de estado anterior, fecha o issue e registra o motivo. Para retomar um `deferred`, reabra o issue, tire `deferred` e coloque de volta o label de estado que o comentário de fechamento registrou. Um `priority` colocado por você marca o issue como prioritário dentro do estado dele; as etapas também o colocam quando você decide a prioridade numa resposta.

## Configuração da organização (uma vez só)

Este repositório é público. Qualquer repositório, de qualquer conta ou organização, pode chamar os workflows daqui sem liberação de acesso.

O que precisa existir é o secret `CLAUDE_CODE_OAUTH_TOKEN` no lado do chamador. O workflow reutilizável roda no contexto do repositório que chama, e o `ai.yml` passa o secret pelo nome. Não use `secrets: inherit` no chamador: o GitHub só repassa secret de organização por `inherit` quando o reutilizável está no mesmo dono, e um consumidor em outra organização falha com "Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling". Gere o token com `claude setup-token` e cadastre:

- **Numa organização** (ex.: `caravelasistemas`), um secret de organização atende todos os repositórios dela:

  ```
  gh secret set CLAUDE_CODE_OAUTH_TOKEN --org caravelasistemas --visibility all
  ```

  Se o secret estiver com acesso só para alguns repositórios, inclua cada repositório novo em Settings da org → Secrets and variables → Actions → `CLAUDE_CODE_OAUTH_TOKEN` → Repository access.

- **Numa conta pessoal**, não existe secret de conta. Cadastre o secret em cada repositório, inclusive neste, porque o `ai.yml` daqui roda nos issues deste repositório:

  ```
  gh secret set CLAUDE_CODE_OAUTH_TOKEN -R samuel-morrissey/ai-workflows
  ```

## Configurar um repositório

1. Copie o chamador para o repositório:

   ```
   mkdir -p .github/workflows
   gh api repos/samuel-morrissey/ai-workflows/contents/.github/workflows/ai.yml -q .content | base64 -d > .github/workflows/ai.yml
   ```

2. Ajuste os inputs no fim do arquivo. Descomente o bloco `with:` e preencha os dois, um comando por linha:

   - `setup_commands`: prepara o ambiente do projeto (por exemplo `npm ci`). O **workflow** roda esses comandos, na ordem declarada, antes de chamar o Claude. Sem eles, `quality_checks` roda num checkout sem dependências instaladas. Se um comando falhar, o job para ali e o Claude não é chamado. Precisa de uma versão específica de runtime? Resolva dentro desses comandos, porque o fluxo não escolhe versão. Uma mudança de `PATH` só chega ao Claude se for gravada em `$GITHUB_PATH`. Sem esses comandos, nenhuma preparação roda.
   - `quality_checks`: os comandos de verificação do projeto. O **Claude** roda esses comandos antes de abrir o PR. Sem eles, o PR sai declarando que não houve verificação.

3. Faça commit e push na branch padrão. Eventos de issue só disparam workflows que estão na branch padrão.

Quando o `ai.yml` daqui ganha um gatilho novo, a cópia de cada repositório precisa ser atualizada (repita o passo 1 e reaplique os inputs). Foi o caso do `repository_dispatch`, que a cadeia de sub-tasks usa: um `ai.yml` sem ele implementa a primeira sub-task e para ali, sem empilhar nem seguir.

Os labels do fluxo (`needs-triage`, `ready-for-agent`, `awaiting-reply`, `awaiting-pr-review`, `deferred`, `priority`...) não precisam ser criados antes. As skills criam os que faltarem, e os workflows criam `work-in-progress` e `go`. Como o `go` é você quem coloca, ele só existe depois da primeira etapa rodar no repositório; para tê-lo desde o início, crie antes:

```
gh label create go --color 3FB950 --description "Pode seguir: roda a etapa do estado atual"
```

## Testar

1. Abra um issue de teste e coloque o label `needs-triage` (ou só `go`: sem label de estado, o `go` vai para a triagem).
2. Abra a aba **Actions**. O workflow **AI** roda o job **issue-triage**, e o issue ganha `work-in-progress` enquanto ele roda.
3. No fim, o issue recebe um label de estado (`needs-*` ou `ready-for-*`) ou um comentário com perguntas. Se responder às perguntas no issue, a triagem roda de novo. Com label de estado novo, coloque `go` para a próxima etapa rodar.

Problemas comuns:

- **Erro de token:** o secret não chega ao repositório. Veja a configuração da organização.
- **`Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling`:** o `ai.yml` usa `secrets: inherit` e o repositório está em outra organização. Passe o secret pelo nome, como no `ai.yml` daqui.
- **Erro ao buscar o workflow (`failed to fetch workflow` ou parecido, ou a execução falha em 0s):** o `uses` do `ai.yml` aponta para um caminho que não existe. Confira que ele aponta para `samuel-morrissey/ai-workflows/...@main`.
- **Todos os jobs aparecem como "skipped":** o evento não bateu com nenhuma etapa. Um label colocado antes do `ai.yml` existir não conta: tire o label e coloque de novo.

## Como funciona

- `ai.yml` (em cada repositório): declara os gatilhos (`on:`) e as permissões. O GitHub exige que esses dois fiquem no chamador.
- `router.yml`: um job por etapa. O `if` do job decide se o evento é daquela etapa, e o `uses` chama o workflow dela, passando o secret pelo nome. Mudar uma regra aqui muda para todos os repositórios.
- `issue-*.yml`: cada etapa coloca `work-in-progress` no issue, consome o `go` e o `awaiting-reply`, roda o Claude com a skill da etapa (do marketplace `samuel-morrissey/claude-marketplace`) e tira o `work-in-progress` no fim.
- `issue-remote-implement.yml` num pai com sub-tasks não roda o Claude: é o planner. Lê as sub-issues, os bloqueios e os PRs (pela branch `sub-task-<n>`), empilha os PRs abertos ainda fora da stack, escolhe a próxima e a despacha ao `issue-sub-task.yml` por `repository_dispatch`. O worker roda o Claude e, no fim, devolve o controle ao pai pelo mesmo mecanismo, com o resultado da rodada. Toda essa leitura mora em `scripts/sub_tasks.py`, que os dois workflows baixam deste repositório na versão deles. O `repository_dispatch` criado com o `GITHUB_TOKEN` dispara workflow (é uma das duas exceções à regra do GitHub); é o que permite a cadeia andar sem um token extra.

Os `uses` apontam para `samuel-morrissey/ai-workflows/...@main`, e não para `./.github/workflows/...`. Em chamadas aninhadas, um caminho local é procurado no repositório do chamador, e não aqui.
