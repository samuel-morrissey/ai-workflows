# ai-workflows

Workflows reutilizáveis do GitHub Actions que levam o fluxo de issues da Caravela para o Claude: triagem, refinamento, quebra em sub-tasks e implementação.

Cada repositório da organização tem um único arquivo, `.github/workflows/ai.yml`. Ele chama o `router.yml` daqui, e o router escolhe a etapa que o evento aciona.

## Etapas

| Etapa | Dispara quando | Workflow |
| --- | --- | --- |
| Triagem | o label `needs-triage` entra no issue, ou uma pessoa comenta num issue que ainda tem `needs-triage`. Também quando uma pessoa coloca `wontfix` ou `deferred`: a triagem fecha o issue e comenta o motivo | `issue-triage.yml` |
| Refinamento | o label `needs-refinement` entra no issue, ou uma pessoa comenta num issue que tem `needs-refinement` | `issue-refinement.yml` |
| Quebra em sub-tasks | o label `needs-break-down` entra no issue, ou uma pessoa comenta num issue que tem `needs-break-down` | `issue-break-down.yml` |
| Implementação | uma pessoa comenta `/implement` num issue com `ready-for-agent` | `issue-remote-implement.yml` |
| Fechar sub-task | um PR é mergeado numa branch que não é a padrão (a branch do pai). Fecha os issues do `Closes` do corpo, porque o GitHub só faz isso sozinho na branch padrão | `pr-merged.yml` |

Nenhuma etapa roda em issue com `work-in-progress`. Esse label marca que outro worker já está trabalhando no issue. Os workflows colocam e tiram esse label sozinhos.

Quando uma etapa troca o label sozinha (ex.: o refinamento termina e põe `needs-break-down`), o GitHub não dispara a etapa seguinte. Comente no issue para ela rodar. Esse comentário é o seu "pode seguir".

Quando o `/implement` termina e abre o PR, o issue troca `ready-for-agent` por `awaiting-pr-review`: a implementação acabou e o PR está pronto para análise. Um novo `/implement` nesse issue não dispara nada.

### Issue com sub-tasks

A quebra cria `[SUB-TASK]`s ligadas ao issue pai, com bloqueios entre elas. O `/implement` é sempre comentado no **pai**, uma vez por PR:

1. Comente `/implement` no pai. O agente abre o PR da primeira sub-task sem bloqueio para a branch do pai, e a sub-task ganha `awaiting-pr-review`.
2. Revise e faça o merge do PR da sub-task.
3. O merge fecha a sub-task sozinho. Comente `/implement` no pai de novo: o agente abre o PR da próxima.
4. Quando todas fecharem, o próximo `/implement` abre o PR do pai para a `main`, e o pai ganha `awaiting-pr-review`.

Quando uma etapa para com uma pergunta, o issue ganha `awaiting-reply`: a vez é de um humano. Responda no issue. Na triagem, no refinamento e na quebra, a resposta já dispara a próxima rodada. No `/implement`, responda e comente `/implement` de novo. O workflow tira o `awaiting-reply` quando a rodada seguinte começa.

| Labels no issue | Quer dizer |
| --- | --- |
| `needs-triage` + `awaiting-reply` | esperando você responder |
| `needs-triage` + `work-in-progress` | Claude trabalhando agora |
| `needs-triage` sozinho | esperando a triagem rodar |
| `ready-for-agent` sozinho | esperando alguém comentar `/implement` |
| `ready-for-agent` + `work-in-progress` | Claude implementando agora |
| `needs-refinement` + `awaiting-reply` | perguntas do refinamento esperando você |
| `needs-break-down` sozinho | comente no issue para quebrar em sub-tasks |
| `awaiting-pr-review` | PR aberto, esperando revisão e merge |
| `wontfix` | fechado: não será feito. Um pedido igual é fechado como `wontfix` de novo |
| `deferred` | fechado: despriorizado. Pode ser reaberto; um pedido igual cita este issue e segue o fluxo |

Comentários de bots e de PRs não disparam nada.

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

Os labels do fluxo (`needs-triage`, `ready-for-agent`, `awaiting-reply`, `awaiting-pr-review`, `deferred`, `priority`...) não precisam ser criados antes. As skills criam os que faltarem, e os workflows criam o `work-in-progress`.

## Testar

1. Abra um issue de teste e coloque o label `needs-triage`.
2. Abra a aba **Actions**. O workflow **AI** roda o job **issue-triage**, e o issue ganha `work-in-progress` enquanto ele roda.
3. No fim, o issue recebe um label de estado (`needs-*` ou `ready-for-*`) ou um comentário com perguntas. Se responder às perguntas no issue, a triagem roda de novo.

Problemas comuns:

- **Erro de token:** o secret não chega ao repositório. Veja a configuração da organização.
- **`Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling`:** o `ai.yml` usa `secrets: inherit` e o repositório está em outra organização. Passe o secret pelo nome, como no `ai.yml` daqui.
- **Erro ao buscar o workflow (`failed to fetch workflow` ou parecido, ou a execução falha em 0s):** o `uses` do `ai.yml` aponta para um caminho que não existe. Confira que ele aponta para `samuel-morrissey/ai-workflows/...@main`.
- **Todos os jobs aparecem como "skipped":** o evento não bateu com nenhuma etapa. Um label colocado antes do `ai.yml` existir não conta: tire o label e coloque de novo.

## Como funciona

- `ai.yml` (em cada repositório): declara os gatilhos (`on:`) e as permissões. O GitHub exige que esses dois fiquem no chamador.
- `router.yml`: um job por etapa. O `if` do job decide se o evento é daquela etapa, e o `uses` chama o workflow dela, passando o secret pelo nome. Mudar uma regra aqui muda para todos os repositórios.
- `issue-*.yml`: cada etapa coloca `work-in-progress` no issue, roda o Claude com a skill da etapa (do marketplace `samuel-morrissey/claude-marketplace`) e tira o label no fim.

Os `uses` apontam para `samuel-morrissey/ai-workflows/...@main`, e não para `./.github/workflows/...`. Em chamadas aninhadas, um caminho local é procurado no repositório do chamador, e não aqui.
