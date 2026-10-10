# ai-workflows

Workflows reutilizáveis do GitHub Actions que levam o fluxo de issues da Caravela para o Claude: triagem e implementação.

Cada repositório da organização tem um único arquivo, `.github/workflows/ai.yml`. Ele chama o `router.yml` daqui, e o router escolhe a etapa que o evento aciona.

## Etapas

| Etapa | Dispara quando | Workflow |
| --- | --- | --- |
| Triagem | o label `need-triage` entra no issue, ou uma pessoa comenta num issue que ainda tem `need-triage` | `issue-triage.yml` |
| Implementação | uma pessoa comenta `/implement` num issue com `ready-for-agent` | `issue-remote-implement.yml` |

Nenhuma etapa roda em issue com `work-in-progress`. Esse label marca que outro worker já está trabalhando no issue. Os workflows colocam e tiram esse label sozinhos.

Quando o `/implement` termina e abre o PR, o issue troca `ready-for-agent` por `awaiting-pr-review`: a implementação acabou e o PR está pronto para análise. Um novo `/implement` nesse issue não dispara nada.

Quando uma etapa para com uma pergunta, o issue ganha `awaiting-reply`: a vez é de um humano. Responda no issue. Na triagem, a resposta já dispara a próxima rodada. No `/implement`, responda e comente `/implement` de novo. O workflow tira o `awaiting-reply` quando a rodada seguinte começa.

| Labels no issue | Quer dizer |
| --- | --- |
| `need-triage` + `awaiting-reply` | esperando você responder |
| `need-triage` + `work-in-progress` | Claude trabalhando agora |
| `need-triage` sozinho | esperando a triagem rodar |
| `ready-for-agent` sozinho | esperando alguém comentar `/implement` |
| `ready-for-agent` + `work-in-progress` | Claude implementando agora |
| `awaiting-pr-review` | PR aberto, esperando revisão e merge |

Comentários de bots e de PRs não disparam nada.

## Configuração da organização (uma vez só)

1. **Liberar os workflows para a organização.** Este repositório é privado, e um repositório privado não compartilha workflows por padrão:

   ```
   gh api -X PUT repos/caravelasistemas/ai-workflows/actions/permissions/access -f access_level=organization
   ```

   Ou pela tela: Settings → Actions → General → Access → "Accessible from repositories in the 'caravelasistemas' organization".

2. **Secret `CLAUDE_CODE_OAUTH_TOKEN` na organização.** Gere o token com `claude setup-token` e cadastre:

   ```
   gh secret set CLAUDE_CODE_OAUTH_TOKEN --org caravelasistemas --visibility all
   ```

   Se o secret estiver com acesso só para alguns repositórios, inclua cada repositório novo em Settings da org → Secrets and variables → Actions → `CLAUDE_CODE_OAUTH_TOKEN` → Repository access.

## Configurar um repositório

1. Copie o chamador para o repositório:

   ```
   mkdir -p .github/workflows
   gh api repos/caravelasistemas/ai-workflows/contents/.github/workflows/ai.yml -q .content | base64 -d > .github/workflows/ai.yml
   ```

2. Ajuste os inputs no fim do arquivo. Descomente o bloco `with:` e preencha os dois, um comando por linha:

   - `setup_commands`: prepara o ambiente do projeto (por exemplo `npm ci`). O **workflow** roda esses comandos, na ordem declarada, antes de chamar o Claude. Sem eles, `quality_checks` roda num checkout sem dependências instaladas. Se um comando falhar, o job para ali e o Claude não é chamado. Precisa de uma versão específica de runtime? Resolva dentro desses comandos, porque o fluxo não escolhe versão. Uma mudança de `PATH` só chega ao Claude se for gravada em `$GITHUB_PATH`. Sem esses comandos, nenhuma preparação roda.
   - `quality_checks`: os comandos de verificação do projeto. O **Claude** roda esses comandos antes de abrir o PR. Sem eles, o PR sai declarando que não houve verificação.

3. Faça commit e push na branch padrão. Eventos de issue só disparam workflows que estão na branch padrão.

Os labels do fluxo (`need-triage`, `ready-for-agent`, `awaiting-reply`, `awaiting-pr-review`...) não precisam ser criados antes. As skills criam os que faltarem, e os workflows criam o `work-in-progress`.

## Testar

1. Abra um issue de teste e coloque o label `need-triage`.
2. Abra a aba **Actions**. O workflow **AI** roda o job **issue-triage**, e o issue ganha `work-in-progress` enquanto ele roda.
3. No fim, o issue recebe um label de estado (`need-*` ou `ready-for-*`) ou um comentário com perguntas. Se responder às perguntas no issue, a triagem roda de novo.

Problemas comuns:

- **Erro de token:** o secret não chega ao repositório. Veja o passo 2 da configuração da organização.
- **Erro ao buscar o workflow (`failed to fetch workflow` ou parecido):** falta liberar o acesso. Veja o passo 1 da configuração da organização.
- **Todos os jobs aparecem como "skipped":** o evento não bateu com nenhuma etapa. Um label colocado antes do `ai.yml` existir não conta: tire o label e coloque de novo.

## Como funciona

- `ai.yml` (em cada repositório): declara os gatilhos (`on:`) e as permissões. O GitHub exige que esses dois fiquem no chamador.
- `router.yml`: um job por etapa. O `if` do job decide se o evento é daquela etapa, e o `uses` chama o workflow dela. Mudar uma regra aqui muda para todos os repositórios.
- `issue-*.yml`: cada etapa coloca `work-in-progress` no issue, roda o Claude com a skill da etapa (do marketplace `samuel-morrissey/claude-marketplace`) e tira o label no fim.

Os `uses` apontam para `caravelasistemas/ai-workflows/...@main`, e não para `./.github/workflows/...`. Em chamadas aninhadas, um caminho local é procurado no repositório do chamador, e não aqui.
