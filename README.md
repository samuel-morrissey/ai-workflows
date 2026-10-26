# ai-workflows

Workflows reutilizáveis do GitHub Actions que levam o fluxo de issues da Caravela para o Claude: triagem, refinamento, quebra em sub-tasks e implementação. As skills que cada etapa roda moram aqui também, em `skills/`, publicadas como o plugin `samuel-morrissey-skills` do marketplace `samuel-morrissey-ai-workflows` (este repositório é o marketplace). Workflow e skill mudam juntos, num só PR.

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

## Skills

As skills do fluxo. Cada etapa dos workflows invoca a sua com o número do issue como argumento (`/samuel-morrissey-skills:issue-triage 42`).

### Etapas do fluxo

Na ordem em que um issue percorre o fluxo.

- **issue-triage** — triagem de um issue cru: investiga o código, atribui tipo (MAP/SPEC/pontual) e label de estado. Entrega issue pontual com brief pronto, MAP/SPEC para a próxima etapa, ou fecha como `wontfix` (já rejeitado ou implementado) ou `deferred` (despriorizado pelo humano).
- **issue-refinement** — refinamento assíncrono de um issue `needs-refinement`: investiga o código, pergunta em rodadas pelo próprio issue até a fronteira de decisões esvaziar, registra o refinamento em comentário e entrega o issue em `needs-break-down`.
- **issue-break-down** — quebra um issue `needs-break-down` em sub-tasks: fatias verticais que vão para produção sozinhas, cada uma com brief e critérios de aceite, ligadas ao pai como sub-issues com bloqueios nativos. Entrega o pai em `ready-for-agent` ou `ready-for-human`.
- **issue-remote-implement** — implementa um issue em uma rodada que termina em um PR: num pontual `ready-for-agent`, o PR dele; numa `[SUB-TASK]` despachada pelo workflow, o PR da camada dela na stack do pai. Desenvolve test-first nos critérios de aceite e passa por até duas rodadas de QA independente (`issue-qa`) antes de abrir o PR. Num pai com sub-tasks, quem orquestra (uma sub-task por vez, PRs empilhados) é o planner de `issue-remote-implement.yml`.
- **issue-qa** — analista de qualidade cego ao diff: executa o roteiro de QA do PR (Configurando o ambiente e Como testar) contra os critérios de aceite do issue, captura evidências antes/depois (prints, GIFs, saídas) e devolve um veredito por critério. Roda como subagente da `issue-remote-implement`; só critério de aceite reprova, e cada rodada nasce sem memória da anterior. Traz em [`EVIDENCIAS-PROJETO.md`](skills/issue-qa/EVIDENCIAS-PROJETO.md) o modelo da skill de projeto `evidencias` (veja [Evidências e QA](#evidências-e-qa)).

### Convenções do fluxo

Skills de apoio que as etapas acima seguem.

- **issue-labeling** — vocabulário canônico: tipos (MAP, SPEC, SUB-TASK e os pontuais), labels de estado (`needs-*`, `ready-for-*`, `awaiting-pr-review`, `wontfix`, `deferred`), labels de trabalho, espera e prioridade (`work-in-progress`, `awaiting-reply`, `priority`) e regras de transição.
- **issue-git-flow** — estrutura de git do fluxo: nome e base de cada branch, vínculo entre PR e issue ou sub-issue, a stack de PRs de um pai e como cada issue fecha.
- **issue-async-first** — trabalho assíncrono por essência: esgota tudo que não depende de humano, agrupa toda intervenção em uma única mensagem e, quando impeditiva, para deixando handoff completo.
- **grilling** — questionamento em lote: monta a fronteira de decisões em aberto, pergunta tudo de uma vez com recomendação e reserva fatos para investigação própria.

### Pull requests

- **to-pr** — abre um pull request, ou redige o texto recomendado para um existente.
- **remote-to-pr** — abre um PR em fluxo remoto e assíncrono, sem ninguém para responder: segue a `to-pr` inteira, monta Evidências e Critérios de aceite a partir do relatório da `issue-qa` e abre direto, sem perguntar.

### Utilitários

- **80-20** — modo Pareto: maior retorno com o menor esforço na tarefa dada.
- **setup-repo** — configura um repositório consumidor a partir do relatório do `doctor`: infere os comandos do projeto, redige a skill `evidencias`, levanta colisões de labels, pergunta tudo de uma vez e abre o PR no repositório alvo. Veja [Configurar um repositório](#configurar-um-repositório).
- **hello-issue** — skill de exemplo que valida a integração entre o marketplace e um repositório consumidor, publicando um comentário no issue informado.

### Usar as skills localmente

As mesmas skills servem no Claude Code da sua máquina. O marketplace é este repositório:

```
/plugin marketplace add samuel-morrissey/ai-workflows
/plugin install samuel-morrissey-skills@samuel-morrissey-ai-workflows
```

Quem tinha o marketplace antigo (`samuel-morrissey/claude-marketplace`) troca pelo novo: remova o antigo (`/plugin marketplace remove samuel-morrissey-claude-marketplace`) e rode os dois comandos acima. Em `settings.json`, a chave de `enabledPlugins` passa a ser `samuel-morrissey-skills@samuel-morrissey-ai-workflows`, e a entrada de `extraKnownMarketplaces` aponta para `samuel-morrissey/ai-workflows`.

### Publicar uma atualização

O que cada parte deste repositório alcança depois do merge em `main`:

| Parte | Quem usa | Chega quando |
| --- | --- | --- |
| `.github/workflows/*.yml` | os `ai.yml` dos consumidores, por `@main` | na próxima run, sem fazer nada |
| `scripts/doctor.py` | você, pelo checkout ou pelo `curl` de `main`; a skill `setup-repo`; o job `check-caller` | na próxima execução, sem fazer nada |
| `skills/*` e `.claude-plugin/` | o Claude Code da sua máquina, pelo plugin | só depois de subir a versão e atualizar o plugin |

O plugin é instalado por versão: o Claude Code guarda uma cópia do repositório no commit da versão em `.claude-plugin/plugin.json` e só troca essa cópia quando a versão muda. Por isso, todo PR que altera uma skill sobe a versão no `plugin.json` (patch para correção de texto, minor para skill nova ou comportamento novo). Sem isso, o `/plugin` update não traz nada.

Depois do merge de um PR que subiu a versão:

1. Rode `/plugin`, atualize o marketplace `samuel-morrissey-ai-workflows` e depois o plugin `samuel-morrissey-skills`.
2. Abra uma sessão nova. As skills são carregadas no início da sessão.
3. Confira a versão instalada com `/plugin`, ou em `~/.claude/plugins/installed_plugins.json`.

A cópia do `scripts/doctor.py` dentro do plugin fica congelada junto com ele. Rode o `doctor` sempre pelo checkout deste repositório ou pelo `curl` de `main`, como faz a skill `setup-repo`.

## O que um repositório precisa

Este repositório é público: qualquer repositório, de qualquer conta ou organização, chama os workflows daqui sem liberação de acesso. O que varia fica em quatro lugares, e nenhum deles é o `ai.yml`:

| Natureza | Onde mora | Exemplo |
| --- | --- | --- |
| Igual em todo repositório | `.github/workflows/ai.yml`, cópia idêntica do arquivo daqui | gatilhos, permissões, repasse de secrets |
| Do projeto | `.github/ai-workflows.yml`, versionado no repositório | `setup_commands`, `quality_checks`, `evidence_tools` |
| Do dono (conta ou organização) | variáveis e secrets do Actions | bucket de evidências, `CLAUDE_CODE_OAUTH_TOKEN` |
| Do ambiente de QA do projeto | secret `PROJECT_ENV` | chave de teste de um serviço sem emulador |

### Variáveis e secrets

Secrets e variáveis podem ficar na organização, com acesso a todos os repositórios, ou em cada repositório. Uma conta pessoal não tem nível de conta: lá tudo vai por repositório. O chamador repassa os secrets pelo nome; não use `secrets: inherit`, porque o GitHub só repassa secret de organização por `inherit` quando o reutilizável está no mesmo dono, e um consumidor em outra organização falha com "Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling".

| Nome | Tipo | Obrigatório | Para quê |
| --- | --- | --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | secret | sim | token do Claude Code, gerado com `claude setup-token` |
| `EVIDENCE_BUCKET` | variável | com bucket | destino das evidências, `s3://bucket[/prefixo]` |
| `EVIDENCE_PUBLIC_URL` | variável | com bucket | URL pública que corresponde à raiz do bucket |
| `EVIDENCE_ENDPOINT` | variável | fora da AWS | endpoint S3 do provedor (R2, MinIO) |
| `EVIDENCE_ACCESS_KEY_ID`, `EVIDENCE_SECRET_ACCESS_KEY` | secret | com bucket | credenciais do bucket |
| `PROJECT_ENV` | secret | não | um `.env` com o que o ambiente do QA exige (veja abaixo) |

Numa organização:

```
gh secret set CLAUDE_CODE_OAUTH_TOKEN --org caravelasistemas --visibility all
gh variable set EVIDENCE_BUCKET --org caravelasistemas --visibility all --body s3://evidencias
gh variable set EVIDENCE_PUBLIC_URL --org caravelasistemas --visibility all --body https://pub-xxxx.r2.dev
gh variable set EVIDENCE_ENDPOINT --org caravelasistemas --visibility all --body https://<account-id>.r2.cloudflarestorage.com
gh secret set EVIDENCE_ACCESS_KEY_ID --org caravelasistemas --visibility all
gh secret set EVIDENCE_SECRET_ACCESS_KEY --org caravelasistemas --visibility all
```

Se o secret ou a variável estiver com acesso só para alguns repositórios, inclua cada repositório novo em Settings da org → Secrets and variables → Actions → Repository access. Numa conta pessoal, troque `--org <org> --visibility all` por `-R <owner/repo>` e repita em cada repositório, inclusive neste, porque o `ai.yml` daqui roda nos issues deste repositório.

O `ai.yml` lê as três variáveis com `vars.EVIDENCE_*` e as passa ao router. Variável ausente resolve vazio, e as evidências vão como artifact da run.

### O arquivo `.github/ai-workflows.yml`

Os comandos do projeto, lidos por `issue-remote-implement.yml` e `issue-sub-task.yml` depois do checkout, antes de chamar o agente. Só escalares de texto e blocos literais (`|`), um comando por linha:

```yaml
# Comandos deste repositório para o fluxo de IA (samuel-morrissey/ai-workflows).
setup_commands: |
  npm ci
quality_checks: |
  npm run typecheck
  npm test
evidence_tools: |
  node
  npx playwright
  curl
```

- `setup_commands`: prepara o ambiente do projeto. O **workflow** roda esses comandos, na ordem declarada, antes de chamar o Claude. Sem eles, `quality_checks` roda num checkout sem dependências instaladas. Se um comando falhar, o job para ali e o Claude não é chamado. Precisa de uma versão específica de runtime? Resolva dentro desses comandos, porque o fluxo não escolhe versão. Uma mudança de `PATH` só chega ao Claude se for gravada em `$GITHUB_PATH`.
- `quality_checks`: os comandos de verificação do projeto. O **Claude** roda esses comandos antes de abrir o PR. Sem eles, o PR sai declarando que não houve verificação.
- `evidence_tools`: os prefixos de comando que o agente e o QA independente podem rodar para subir o projeto e capturar evidências. Liga o QA. Sem ele, o PR sai declarando que não houve QA. Veja [Evidências e QA](#evidências-e-qa).
- `evidence_bucket`, `evidence_public_url`, `evidence_endpoint`: aceitas também aqui, para um repositório que usa um bucket diferente do dono. Normalmente ficam nas variáveis.

Chave do arquivo vence o input de mesmo nome do `ai.yml`; chave ausente deixa o input valer; chave desconhecida gera aviso e é ignorada; valor que não é texto (lista, mapa, número) falha o job antes do agente, com o nome do arquivo no erro. Os inputs no `ai.yml` continuam aceitos para os repositórios já configurados, mas o caminho novo é o arquivo.

### O secret `PROJECT_ENV`

Alguns projetos só sobem com um serviço externo que não tem emulador (uma chave de teste do Clerk, por exemplo). Essas credenciais não cabem nos inputs nem no arquivo versionado. Coloque-as num único secret, `PROJECT_ENV`, no formato de um `.env`:

```
CLERK_SECRET_KEY=sk_test_...
DATABASE_URL=postgres://postgres:postgres@localhost:5432/app
```

Antes de `setup_commands`, o workflow lê cada linha `CHAVE=VALOR`, mascara o valor no log e grava a variável em `$GITHUB_ENV`. Daí ela chega a `setup_commands`, a `quality_checks`, ao agente e ao QA. Linhas vazias e comentários (`#`) são ignorados; `export ` no início é aceito; aspas que envolvem o valor inteiro são removidas; a linha é dividida só no primeiro `=`; linha sem `=` ou com nome inválido gera aviso e é pulada. Sem o secret, nada acontece.

## Configurar um repositório

O caminho curto é o `doctor`: ele confere cada item da seção anterior e corrige o que não exige decisão humana.

```
python3 scripts/doctor.py check <owner/repo>
python3 scripts/doctor.py fix <owner/repo>
```

O que exige decisão (os comandos do projeto, a skill `evidencias`, colisão de labels) fica com a skill `setup-repo`, que roda o `doctor`, lê o projeto, pergunta tudo de uma vez e abre o PR no repositório alvo:

```
/samuel-morrissey-skills:setup-repo <owner/repo>
```

Os passos abaixo são o mesmo caminho feito à mão.


1. Copie o chamador, sem alterar nada nele:

   ```
   mkdir -p .github/workflows
   gh api repos/samuel-morrissey/ai-workflows/contents/.github/workflows/ai.yml -q .content | base64 -d > .github/workflows/ai.yml
   ```

2. Crie `.github/ai-workflows.yml` com os comandos do projeto (modelo acima).

3. Confira as variáveis e os secrets do dono (tabela acima) e, se o QA precisar, o `PROJECT_ENV`.

4. Faça commit e push na branch padrão. Eventos de issue só disparam workflows que estão na branch padrão.

Quando o `ai.yml` daqui muda, cada cópia precisa ser atualizada, e o fluxo avisa sozinho: a cada label em issue ou comentário humano, o job `check-caller` do router compara o `ai.yml` do repositório com o modelo daqui e, se divergir, emite um aviso na run, mostra a diferença no job summary e abre no repositório um PR de atualização pelo `doctor` (branch `ai-workflows/doctor`; PR já aberto é atualizado, não duplicado). Igual ao modelo: nada acontece. O job não bloqueia as etapas, nunca falha a run e não tem input para ser desligado. Prefere fazer à mão? Repita o passo 1, sem nada a reaplicar, porque o arquivo não carrega valor do projeto. Foi o caso do `repository_dispatch`, que a cadeia de sub-tasks usa: um `ai.yml` sem ele implementa a primeira sub-task e para ali, sem empilhar nem seguir.

### Verificar e corrigir: o `doctor`

`scripts/doctor.py` verifica um repositório consumidor item por item e, com `fix`, corrige o que é seguro corrigir. Rodar duas vezes não muda nada na segunda: cada correção só acontece quando o item não está `ok`. Ele fala com o GitHub pelo `gh` e não tem dependência além do Python 3.

```
python3 scripts/doctor.py check caravelasistemas/caravela-www
python3 scripts/doctor.py fix caravelasistemas/caravela-www
python3 scripts/doctor.py check --all caravelasistemas samuel-morrissey
python3 scripts/doctor.py fix samuel-morrissey/life-os --only ai-yml,vars
```

| Item | Verifica | `fix` |
| --- | --- | --- |
| `ai-yml` | `.github/workflows/ai.yml` da branch padrão igual ao modelo daqui (`--ref`, padrão `main`) | abre um PR no repositório com o arquivo novo, na branch `ai-workflows/doctor`; se o `ai.yml` atual tem inputs inline em `with:`, o mesmo PR cria `.github/ai-workflows.yml` com eles. PR já aberto é atualizado, não duplicado, e um PR aberto de qualquer branch `ai-workflows/*` que já traga o modelo, como o da skill `setup-repo`, conta como resolvido até o merge |
| `config` | `.github/ai-workflows.yml` presente, só com chaves conhecidas e valores de texto | nada: sem arquivo e sem inputs inline, aponta a skill `setup-repo` |
| `secrets` | `CLAUDE_CODE_OAUTH_TOKEN`; `EVIDENCE_ACCESS_KEY_ID` e `EVIDENCE_SECRET_ACCESS_KEY` quando há bucket; `PROJECT_ENV` só informativo. Secret de organização com acesso ao repositório conta | grava no repositório os que faltam, com os valores do `config.env`, quando não há secret de organização |
| `vars` | `EVIDENCE_BUCKET`, `EVIDENCE_PUBLIC_URL`, `EVIDENCE_ENDPOINT` com os valores do `config.env` | grava na organização (dono organização) ou no repositório (dono conta) |
| `labels` | os 13 labels do fluxo da `issue-labeling`, com cor e descrição canônicas | cria os que faltam e corrige cor e descrição dos que divergem. Nunca apaga nem renomeia; colisões (`priority-*`, tipos como label) saem como nota para você decidir |
| `evidencias` | `.claude/skills/evidencias/SKILL.md` com as cinco seções do modelo | nada: aponta a skill `setup-repo` |
| `topic` | topic `ai-workflows` no repositório, que é o inventário do `--all` | adiciona |
| `bucket` | a URL pública responde HTTP | nada: só informativo |

Estados: `ok`, `falta`, `diverge`, `manual` (exige humano; o relatório traz o comando ou a skill) e `info`. Saída 0 quando tudo é `ok` ou `info`, 1 quando há algo a corrigir, 2 em erro de acesso. `--json` imprime o relatório em JSON, para a skill `setup-repo` e para o job do router. `--only item,item` restringe aos itens dados.

Os valores do dono vêm de um `.env` fora de qualquer repositório, `~/.config/ai-workflows/config.env` (ou o caminho em `AI_WORKFLOWS_CONFIG`):

```
CLAUDE_CODE_OAUTH_TOKEN=...
EVIDENCE_ACCESS_KEY_ID=...
EVIDENCE_SECRET_ACCESS_KEY=...
EVIDENCE_BUCKET=s3://evidencias
EVIDENCE_PUBLIC_URL=https://pub-xxxx.r2.dev
EVIDENCE_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
```

O GitHub não devolve o valor de um secret, então o `doctor` confirma a existência e regrava a partir do arquivo só quando falta. Variáveis são legíveis: aí ele compara o valor e reporta `diverge`. Sem o arquivo, ou sem a chave, o item sai como `manual` com o `gh secret set` ou `gh variable set` para fazer à mão. Num repositório sem build nem testes, crie `.github/ai-workflows.yml` só com comentários: é o jeito de dizer ao `doctor` que a ausência de comandos é decisão, não esquecimento.

Os testes das partes puras do script (leitor do arquivo de configuração, extração dos inputs inline, `config.env`, comparação e relatório) rodam com `python3 scripts/test_doctor.py`.

Os labels do fluxo (`needs-triage`, `ready-for-agent`, `awaiting-reply`, `awaiting-pr-review`, `deferred`, `priority`...) são criados de uma vez pelo `doctor fix`, com a cor e a descrição da `issue-labeling`. Sem o `doctor`, as skills criam os que faltarem na hora de aplicar, e os workflows criam `work-in-progress` e `go`. Um label que já existia com outra cor ou descrição só é corrigido pelo `doctor`: as skills nunca editam label.

## Evidências e QA

A seção **Evidências** do PR mostra o antes e o depois no nível de quem usa: print, GIF, saída de comando, resposta de endpoint. No fluxo remoto quem captura não é o agente que implementou, e sim um **QA independente**: a skill `issue-qa`, rodada como subagente antes do PR abrir. Ele recebe só os critérios de aceite do issue, o roteiro de teste que o desenvolvedor escreveu para o PR (Configurando o ambiente e Como testar) e um checkout da branch. Não lê o diff. Executa o roteiro, captura o antes (na base) e o depois (na branch), e devolve uma tabela com um veredito por critério. O PR sai com essa tabela em **Critérios de aceite** e com as capturas em **Evidências**.

O ciclo entre desenvolvedor e QA é limitado por regras fixas: no máximo duas rodadas de QA por run; só critério de aceite reprovado reabre o desenvolvedor (observações não); mesma falha nas duas rodadas, ou regressão entre elas, encerra o ciclo com o PR aberto mesmo assim, a tabela dizendo o que ficou em aberto e `awaiting-reply` no issue. O desenvolvedor não discute com o QA: corrige, ou declara no PR que não corrigiu e por quê. Cada rodada do QA nasce sem memória da anterior.

Tudo isso é **opcional por repositório** e liga pela chave `evidence_tools` de `.github/ai-workflows.yml`:

1. **O que o agente pode rodar** vai em `evidence_tools`, um prefixo por linha. Cada linha vira uma permissão na allowlist, como em `quality_checks`. Para um app web, em geral basta `node` (para um script que sobe o servidor, espera a porta, captura e encerra), `npx playwright` e `curl`. Para um CLI, o próprio binário e, se quiser gravação de terminal, `asciinema` e `agg`. Linhas que citam `playwright`, `ffmpeg`, `asciinema` ou `agg` fazem o workflow instalar essas ferramentas antes de chamar o agente; o runner `ubuntu-latest` já traz Chrome, Chromium e Firefox, e navegador headless não precisa de tela.

2. **Como capturar neste projeto** vai no próprio repositório, numa skill de projeto em `.claude/skills/evidencias/SKILL.md`: qual é a evidência ideal, como subir o app, porta, login de teste, seeds, como obter o antes e o que não fazer. O QA (e a `to-pr`, localmente) lê esse arquivo antes de capturar. Modelo em [`skills/issue-qa/EVIDENCIAS-PROJETO.md`](skills/issue-qa/EVIDENCIAS-PROJETO.md). Sem a skill, o QA segue um padrão por tipo de projeto (web, API, CLI, documento).

3. **Onde as evidências ficam.** O agente grava tudo numa pasta fora do workspace, que nunca é commitada. Depois da rodada, o workflow publica a pasta:

   - **Com bucket** (variáveis `EVIDENCE_BUCKET`, `EVIDENCE_PUBLIC_URL` e, fora da AWS, `EVIDENCE_ENDPOINT`, mais os secrets `EVIDENCE_ACCESS_KEY_ID` e `EVIDENCE_SECRET_ACCESS_KEY`; veja [Variáveis e secrets](#variáveis-e-secrets)): o workflow envia os arquivos para um prefixo imprevisível (`<repo>/<issue>/<run>-<aleatório>/`) decidido **antes** de chamar o agente, e passa a URL base a ele. Por isso o PR já nasce com as URLs finais e as imagens renderizam inline. Qualquer provedor compatível com S3 serve (S3, Cloudflare R2, MinIO, Backblaze). Configure o bucket com leitura pública e uma regra de ciclo de vida de 90 dias, que reproduz a retenção dos artifacts. Não use URL assinada: ela expira em no máximo 7 dias.
   - **Sem bucket**, ou quando o upload falha: a pasta vai como artifact `evidencias-<issue>` da run, e o PR linka a run. Artifact não renderiza inline: a URL exige login e devolve um zip. Quando o upload para o bucket falha depois de o PR já ter sido escrito, o workflow troca as URLs do bucket no corpo do PR pelo link da run.

   Exemplo com Cloudflare R2, numa organização:

   ```
   gh variable set EVIDENCE_BUCKET --org caravelasistemas --visibility all --body s3://evidencias
   gh variable set EVIDENCE_PUBLIC_URL --org caravelasistemas --visibility all --body https://pub-xxxx.r2.dev
   gh variable set EVIDENCE_ENDPOINT --org caravelasistemas --visibility all --body https://<account-id>.r2.cloudflarestorage.com
   gh secret set EVIDENCE_ACCESS_KEY_ID --org caravelasistemas --visibility all
   gh secret set EVIDENCE_SECRET_ACCESS_KEY --org caravelasistemas --visibility all
   ```

   E em `.github/ai-workflows.yml` do repositório:

   ```yaml
   evidence_tools: |
     node
     npx playwright
     curl
   ```

   O `ai.yml` repassa as variáveis e os secrets pelo nome (a cópia daqui já faz isso). Em repositório privado, só o bucket garante imagem inline: URL de arquivo do próprio repositório não renderiza em corpo de PR, porque o proxy de imagens do GitHub não autentica.

Custo: a run passa a rodar o agente desenvolvedor mais até dois subagentes de QA, cada um subindo o app. Num projeto com banco e seed pesado, meça uma run antes de ligar; o teto de turnos do agente subiu de 150 para 200 por causa do QA. Vídeo: o Playwright grava `.webm`, mas o GitHub só mostra player para vídeo enviado pela interface; o QA converte para GIF com ffmpeg, e o `.webm` fica no bucket ou no artifact.

## Testar

1. Abra um issue de teste e coloque o label `needs-triage` (ou só `go`: sem label de estado, o `go` vai para a triagem).
2. Abra a aba **Actions**. O workflow **AI** roda o job **issue-triage**, e o issue ganha `work-in-progress` enquanto ele roda.
3. No fim, o issue recebe um label de estado (`needs-*` ou `ready-for-*`) ou um comentário com perguntas. Se responder às perguntas no issue, a triagem roda de novo. Com label de estado novo, coloque `go` para a próxima etapa rodar.

Problemas comuns:

- **Erro de token:** o secret não chega ao repositório. Veja [Variáveis e secrets](#variáveis-e-secrets).
- **`Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling`:** o `ai.yml` usa `secrets: inherit` e o repositório está em outra organização. Passe o secret pelo nome, como no `ai.yml` daqui.
- **Erro ao buscar o workflow (`failed to fetch workflow` ou parecido, ou a execução falha em 0s):** o `uses` do `ai.yml` aponta para um caminho que não existe. Confira que ele aponta para `samuel-morrissey/ai-workflows/...@main`.
- **Todos os jobs aparecem como "skipped":** o evento não bateu com nenhuma etapa. Um label colocado antes do `ai.yml` existir não conta: tire o label e coloque de novo.

## Como funciona

- `ai.yml` (em cada repositório, idêntico ao daqui): declara os gatilhos (`on:`) e as permissões, que o GitHub exige no chamador, lê as variáveis do bucket e repassa os secrets pelo nome. Nenhum valor do projeto mora nele.
- `.github/ai-workflows.yml` (em cada repositório): os comandos do projeto. `issue-remote-implement.yml` e `issue-sub-task.yml` o leem depois do checkout e, quando existe, ele vence os inputs do `ai.yml`.
- `router.yml`: um job por etapa, mais o `check-caller`, que confere o `ai.yml` do chamador contra o modelo daqui e abre o PR de atualização quando ele diverge. O `if` do job decide se o evento é daquela etapa, e o `uses` chama o workflow dela, passando o secret pelo nome. Mudar uma regra aqui muda para todos os repositórios.
- `issue-*.yml`: cada etapa coloca `work-in-progress` no issue, consome o `go` e o `awaiting-reply`, roda o Claude com a skill da etapa (do plugin `samuel-morrissey-skills`, instalado deste repositório pela `claude-code-action`) e tira o `work-in-progress` no fim.
- `issue-remote-implement.yml` (pontual) e `issue-sub-task.yml`: antes do agente, leem `.github/ai-workflows.yml`, carregam o `PROJECT_ENV` em `$GITHUB_ENV`, montam a allowlist e o system prompt a partir de `quality_checks` e `evidence_tools`, decidem a pasta e as URLs das evidências e instalam as ferramentas de captura citadas; depois do agente, publicam a pasta de evidências no bucket (ou como artifact) e, se preciso, corrigem os links no PR.
- `.claude-plugin/` e `skills/`: o marketplace e o plugin. `marketplace.json` declara o marketplace `samuel-morrissey-ai-workflows` com um único plugin, `samuel-morrissey-skills`, cuja raiz é o próprio repositório (`plugin.json`, com as skills em `skills/`). As etapas instalam o plugin pela URL deste repositório, por isso a versão da skill que roda é sempre a da `main`.
- `issue-remote-implement.yml` num pai com sub-tasks não roda o Claude: é o planner. Lê as sub-issues, os bloqueios e os PRs (pela branch `sub-task-<n>`), empilha os PRs abertos ainda fora da stack, escolhe a próxima e a despacha ao `issue-sub-task.yml` por `repository_dispatch`. O worker roda o Claude e, no fim, devolve o controle ao pai pelo mesmo mecanismo, com o resultado da rodada. Toda essa leitura mora em `scripts/sub_tasks.py`, que os dois workflows baixam deste repositório na versão deles. O `repository_dispatch` criado com o `GITHUB_TOKEN` dispara workflow (é uma das duas exceções à regra do GitHub); é o que permite a cadeia andar sem um token extra.

Os `uses` apontam para `samuel-morrissey/ai-workflows/...@main`, e não para `./.github/workflows/...`. Em chamadas aninhadas, um caminho local é procurado no repositório do chamador, e não aqui.
