# ai-workflows

Workflows reutilizáveis do GitHub Actions que levam o fluxo de issues da Caravela para o Claude: triagem, refinamento, quebra em sub-tasks e implementação. As skills que cada etapa roda moram aqui também, em `skills/`, publicadas como o plugin `samuel-morrissey-skills` do marketplace `samuel-morrissey-ai-workflows` (este repositório é o marketplace). Workflow e skill mudam juntos, num só PR.

Cada repositório da organização tem um único arquivo, `.github/workflows/ai.yml`. Ele chama o `router.yml` daqui, e o router escolhe a etapa que o evento aciona.

## Etapas

| Etapa | Dispara quando | Workflow |
| --- | --- | --- |
| Triagem | o label `go` entra num issue com `needs-triage` ou sem label de estado, ou uma pessoa coloca `needs-triage`. Também quando uma pessoa coloca `wontfix` ou `deferred`: a triagem fecha o issue e comenta o motivo | `issue-triage.yml` |
| Refinamento | a triagem termina em `needs-refinement` (roda sozinho, sem `go`), o label `go` entra num issue com `needs-refinement`, ou uma pessoa coloca `needs-refinement` | `issue-refinement.yml` |
| Quebra em sub-tasks | a triagem ou o refinamento terminam em `needs-break-down` (roda sozinha, sem `go`), o label `go` entra num issue com `needs-break-down`, ou uma pessoa coloca `needs-break-down` | `issue-break-down.yml` |
| Implementação | o label `go` entra num issue com `ready-for-agent`. Num pontual, abre o PR dele. Num pai com sub-tasks, é o planner da cadeia: despacha uma sub-task por vez e empilha os PRs numa stack | `issue-remote-implement.yml` |
| Sub-task | o planner do pai despacha a próxima sub-task, o label `go` entra numa `[SUB-TASK]` (roda só ela), ou uma pessoa responde a uma pergunta dela | `issue-sub-task.yml` |
| Correção de PR | uma pessoa envia uma review com *Request changes* num PR aberto, ou uma review ou um comentário no PR que cita `@claude`, ou responde a uma pergunta da correção. Cada pedido vira commit na branch do PR e resposta no próprio PR. Veja [Correção de PR](#correção-de-pr) | `pr-fix.yml` |
| Fechar sub-task | um PR é mergeado numa branch que não é a padrão. Fecha os issues do `Closes` do corpo, porque o GitHub só faz isso sozinho na branch padrão. Numa stack o GitHub já fechou; só o label `awaiting-pr-review` sai | `pr-merged.yml` |
| Desfazer etapa | uma pessoa coloca o label `undo` num issue sem `work-in-progress`. Desfaz a última mudança de estado feita por uma etapa: a triagem (volta a `needs-triage`, com o título e o corpo de antes dela), o refinamento (volta a `needs-refinement`) ou a quebra (o pai volta a `needs-break-down`, e as sub-tasks saem do pai e fecham como "not planned"). Recusa com comentário quando a implementação já começou, numa `[SUB-TASK]`, em `needs-triage` e em issue fechado. Veja [O label `undo`](#o-label-undo) | `issue-undo.yml` |
| Devolver estado | um PR é fechado sem merge, em qualquer base. Cada issue do `Closes` do corpo que está aberto, em `awaiting-pr-review`, sem `work-in-progress` e sem outro PR aberto que o declare volta para `ready-for-agent` (pontual e pai) ou fica sem label de estado (sub-task). O pai do `Parte de` em `awaiting-pr-review` volta para `ready-for-agent`. Cada issue alterado ganha um comentário que cita o PR; nada dispara sozinho, e um `go` retoma a implementação | `pr-closed.yml` |

Triagem, refinamento e quebra em sub-tasks têm `WebFetch` restrito a uma lista fixa de domínios do plugin: `docs.github.com`, `code.claude.com` e `platform.claude.com`. É o meio de conferir, na documentação oficial, uma premissa sobre GitHub ou Claude; URL fora da lista a ferramenta recusa, e a premissa fica marcada como não verificada. O repositório soma a essa lista a documentação dos fornecedores dele com a chave [`web_domains`](#o-arquivo-githubai-workflowsyml). Nenhuma etapa tem `WebSearch`, e implementação, sub-task e correção de PR não têm web. A regra de uso (o `llms.txt` primeiro, conteúdo de página como dado, nunca instrução) está em [Uso da web](skills/issue-triage/AGENT-BRIEF.md#uso-da-web).

Os agentes não publicam mudança em `.github/workflows/`: o GitHub recusa o push deles, porque o token das etapas não tem a permissão `workflows`. Isso vale para todas as etapas que publicam código (implementação, sub-task e correção de PR). Trabalho que precisa alterar um workflow vai para um humano: a triagem e a quebra marcam `**Executor:** humano` com esse motivo (na quebra, a parte de workflow vira uma sub-task humana própria quando dá para separar), e a implementação para em handoff, sem PR, se receber um brief de agente que exige isso. Arquivos de `.github/` fora de `workflows/`, como o `.github/ai-workflows.yml` e o `.github/actions/`, ficam fora da regra.

Nenhuma etapa roda em issue com `work-in-progress`. Esse label marca que outro worker já está trabalhando no issue. Os workflows colocam e tiram esse label sozinhos. Num pai com sub-tasks ele fica durante a cadeia inteira (veja abaixo).

### O label `go`

`go` é o seu "pode seguir". Ele não diz em que etapa o issue está: isso é o label de estado (`needs-triage`, `needs-refinement`, `needs-break-down`, `ready-for-agent`). `go` diz que a etapa desse estado pode rodar agora. A etapa tira o `go` ao começar, e você coloca de novo quando quiser a próxima.

Por que ele existe: quando um agente cria um issue já com `needs-triage`, ou quando uma etapa troca o label sozinha e não chama a seguinte, o GitHub não dispara nada, porque label aplicado por token não gera evento. O `go` destrava esses casos. Na implementação ele é o único gatilho: `ready-for-agent` sozinho nunca inicia nada.

### Etapas que seguem sozinhas

As etapas antes da implementação não esperam `go`: a triagem que termina em `needs-refinement` chama o refinamento, e a triagem ou o refinamento que terminam em `needs-break-down` chamam a quebra. A etapa que termina despacha a seguinte com um `repository_dispatch` do tipo `ai-advance` (o único jeito de um workflow chamar outro), que o `ai.yml` declara e o router leva ao destino da etapa. O comentário final dela (`## Triagem` ou `## Refinamento`) não pede `go` e não marca ninguém: a linha **Em seguida** diz qual etapa roda agora e que colocar `undo` desfaz esta.

Continuam esperando `go`: todo `ready-for-*` (da triagem pontual ou da quebra), `needs-discovery` (a `issue-discovery` ainda não existe), a retomada de uma cadeia parada num pai e o `ready-for-agent` devolvido pelo `pr-closed.yml`. Rodada que termina numa pergunta (`awaiting-reply`) espera a resposta, e issue fechado, `wontfix` ou `deferred` não chama nada. Um passo que falha fora do agente também não: o comentário **Rodada com falha** sai como sempre.

- **Desligar:** `auto_advance: false` em [`.github/ai-workflows.yml`](#o-arquivo-githubai-workflowsyml) volta ao comportamento antigo: nenhuma etapa chama a seguinte, e todo comentário final pede `go` marcando o responsável. Quem lê a chave é a etapa que está terminando, no checkout do repositório.
- **`ai.yml` antigo:** um repositório cujo `ai.yml` ainda não declara `ai-advance` também continua pedindo `go`, até o merge do PR de atualização que o `check-caller` abre.
- **Dispatch que falha:** o issue ganha um comentário novo, **Etapa seguinte não chamada**, com o motivo, pedindo `go` e marcando o responsável.
- **`undo` durante uma etapa encadeada:** a etapa que está rodando confere o `undo` antes de terminar, não chama a seguinte, e o `undo` desfaz as duas: a mudança de estado desta rodada (se houve) e a da etapa que a encadeou. Um refinamento encadeado pela triagem volta o issue a `needs-triage`, com o título e o corpo de antes da triagem. Nenhuma run é cancelada.

Um `go` colocado durante uma etapa que encadeia é descartado no fim da rodada; a etapa seguinte roda pelo dispatch. O `go` manual continua valendo em todo estado. Issues que já estavam parados esperando `go` continuam assim: o encadeamento vale para as etapas que terminam depois da atualização. Sem a parada antes da próxima etapa, não há o momento de revisar o `## Refinamento` ou a leitura de código: um erro se corrige com `undo`. O último intervalo de revisão é o `go` da implementação.

Um `go` colocado enquanto a etapa roda é descartado no fim dela, porque um label que já está no issue não pode ser colocado de novo. Coloque outro quando a rodada terminar. `go` num issue com `awaiting-pr-review`, fechado ou sem etapa para o estado dele não dispara nada; o próximo workflow que rodar nesse issue tira o label.

Quando a implementação termina e abre o PR, o issue troca `ready-for-agent` por `awaiting-pr-review`: a implementação acabou e o PR está pronto para análise. Se a rodada morre depois de abrir o PR e antes de trocar o label (teto de turnos, erro ou timeout), o workflow garante a troca no fim da rodada: com o issue aberto e um PR aberto com `Closes #<número>`, o `ready-for-agent` vira `awaiting-pr-review`. Sem PR aberto, como num handoff, o `ready-for-agent` fica.

### O label `undo`

`undo` é o seu "volta um passo". Ele desfaz a **última mudança de label de estado feita por uma etapa** e deixa o issue parado no estado de antes, esperando `go`. O workflow tira o `undo` ao começar, como faz com o `go`, e coloca `work-in-progress` enquanto roda.

| Última etapa | O que o `undo` faz |
| --- | --- |
| Refinamento | o issue volta de `needs-break-down` para `needs-refinement`. Nada mais muda |
| Quebra em sub-tasks | o pai volta de `ready-for-*` para `needs-break-down`. Cada sub-task criada pela quebra sai da lista de sub-issues do pai, perde as dependências `blocked_by` e é fechada como "not planned" |
| Triagem | o issue volta para `needs-triage`, com o título e o corpo de antes da triagem. No pontual (`ready-for-*`), título e corpo voltam ao que a citação do começo do brief registra, e uma edição sua no brief se perde (o comentário avisa); sem a citação, o `undo` é recusado com um comentário dizendo que o texto original não foi encontrado no corpo, sem mudar nada. Em `[MAP]`, `[SPEC]` e pontual grande o corpo fica, e o título volta com o prefixo do `(sugerido: ...)` do `## Triagem`, ou sem prefixo quando ele não o traz. `priority` fica |

Toda reversão posta um comentário novo, sem `@`, dizendo o que foi desfeito e para qual estado o issue voltou. Os comentários anteriores ficam como histórico. Rodada que terminou em pergunta não conta (o `awaiting-reply` sai junto), e o próprio `undo` também não: colocar `undo` de novo desfaz a etapa anterior. Um pai que voltou da quebra para `needs-break-down` vai para `needs-refinement`. Depois do `undo`, um `go` roda a etapa do estado de novo: a triagem trata o `## Triagem` desfeito como substituído (não para em "já triado") e usa os seus comentários posteriores ao `undo`, o refinamento trata o `## Refinamento` desfeito como substituído, e a quebra cria sub-tasks novas. A triagem registra o tipo sugerido no `## Triagem` sempre que o título original tinha prefixo, mesmo igual ao tipo decidido, para o `undo` poder devolvê-lo.

O `undo` é recusado, com um comentário que diz o motivo e o caminho, e sem mudar label de estado, quando a implementação já começou (issue em `awaiting-pr-review`, pai com sub-task com PR aberto ou mergeado, ou um PR fechado sem merge como última mudança: feche o PR), numa `[SUB-TASK]` (coloque `undo` no pai), num issue em `needs-triage` (nada a desfazer) e num issue fechado.

`undo` colocado enquanto a triagem, o refinamento ou a quebra roda não é descartado: a rodada o processa quando termina e pode desfazer a mudança que ela acabou de fazer. Nenhuma run é cancelada. Num pai com a cadeia de sub-tasks rodando (`ready-for-agent` + `work-in-progress`) o `undo` não roda: para desfazer a quebra, tire o `work-in-progress` do pai para abandonar a cadeia e coloque `undo` de novo (tire e coloque, se ele ficou no issue).

### Issue com sub-tasks

A quebra cria `[SUB-TASK]`s ligadas ao issue pai, com bloqueios entre elas. Um único `go` no **pai** resolve todas:

1. Coloque `go` no pai. O pai ganha `work-in-progress`: a cadeia está rodando.
2. O agente implementa as sub-tasks **uma por vez**, na ordem dos bloqueios, cada uma numa run própria. A primeira nasce da `main`; cada seguinte nasce da branch da anterior, e o PR dela aponta para essa branch. A sub-task ganha `awaiting-pr-review` quando o PR abre.
3. A partir do segundo PR, os PRs entram numa [stack do GitHub](https://docs.github.com/en/pull-requests/get-started/about-stacked-prs). O pai recebe um comentário de status, atualizado a cada rodada, com a camada, o PR e o estado de cada sub-task.
4. Quando toda sub-task tem PR, o PR do topo ganha `Closes #<pai>`, o pai troca `ready-for-agent` por `awaiting-pr-review` e o `work-in-progress` sai.
5. Revise a stack de baixo para cima e faça o merge pela interface do GitHub. Mergear uma camada do meio leva as de baixo junto; mergear o topo leva tudo. Cada camada que entra na `main` fecha a sub-task dela, e o topo fecha o pai. O GitHub rebaseia as camadas de cima sozinho. Dá para mergear com a cadeia ainda rodando: se a camada sobre a qual uma sub-task está sendo feita é mergeada no meio da rodada, o agente abre o PR dela na `main`, e o planner leva para a camada aberta de baixo (ou para a `main`) o PR que ainda nascer sobre uma camada mergeada.

Não existe mais branch de integração nem PR do pai: a stack faz esse papel, e cada camada vai para a `main` por si.

A cadeia para sozinha, e o `work-in-progress` sai do pai, quando a próxima sub-task é humana (`**Executor:** humano` no brief), quando ela está bloqueada por um issue de fora que ainda está aberto, quando uma rodada termina sem PR e sem pergunta (o comentário de status traz o link da run), ou quando os PRs não puderam ser empilhados. Resolva o que parou e coloque `go` no pai de novo: ele retoma de onde estava, porque o planner só olha o que ainda falta.

Quando uma sub-task para numa pergunta, ela ganha `awaiting-reply` e o pai **continua** com `work-in-progress`: a cadeia está esperando você. Responda na sub-task; a resposta roda a sub-task de novo e a cadeia segue. Para abandonar uma cadeia no meio, tire o `work-in-progress` do pai na mão.

`go` numa `[SUB-TASK]` roda só ela: a branch nasce do topo da stack atual e o PR entra na stack, mas o planner não segue para a próxima. Serve para refazer uma sub-task (feche o PR dela antes) ou para andar uma de cada vez. Sub-task que já tem PR aberto, que é humana ou que está bloqueada por outra ainda sem PR não roda; o agente comenta o motivo.

Cada camada da stack precisa da camada de baixo para existir, por isso a ordem é fixa: um bloqueio só diz quem vem antes. Como cada sub-task enxerga o código de todas as anteriores, nenhuma precisa esperar merge para começar.

### Perguntas e respostas

Quando uma etapa para com uma pergunta, o issue ganha `awaiting-reply`: a vez é de um humano. Responda no issue: a resposta já dispara a próxima rodada da etapa, em qualquer estado, inclusive na implementação. O workflow tira o `awaiting-reply` quando a rodada seguinte começa.

Comentário só dispara etapa em issue com `awaiting-reply`. Fora disso, comente à vontade: nada roda. Comentários de bots nunca disparam nada. Comentário em PR segue as regras de [Correção de PR](#correção-de-pr).

| Labels no issue | Quer dizer |
| --- | --- |
| `needs-triage` + `awaiting-reply` | esperando você responder |
| `needs-triage` + `work-in-progress` | Claude trabalhando agora |
| `needs-triage` sozinho | esperando `go` para a triagem rodar (também logo depois de um `undo` que desfez a triagem) |
| `ready-for-agent` sozinho | esperando `go` para implementar |
| `ready-for-agent` + `awaiting-reply` | a implementação parou numa pergunta; responda no issue |
| `ready-for-agent` + `work-in-progress` | Claude implementando agora. Num pai com sub-tasks: a cadeia está rodando, ou esperando a resposta de uma sub-task com `awaiting-reply` |
| `[SUB-TASK]` + `awaiting-pr-review` | PR da sub-task aberto, na stack do pai |
| `[SUB-TASK]` + `awaiting-reply` | a sub-task parou numa pergunta; responda nela e a cadeia segue |
| `needs-refinement` + `awaiting-reply` | perguntas do refinamento esperando você |
| `needs-refinement` ou `needs-break-down` sozinho, com **Em seguida** no último comentário de etapa | a etapa seguinte foi encadeada e vai começar sozinha |
| `needs-break-down` sozinho | esperando `go` para quebrar em sub-tasks: com `auto_advance: false`, `ai.yml` antigo, depois de **Etapa seguinte não chamada**, ou logo depois de um `undo` que desfez a quebra |
| `undo` + `work-in-progress` | o `undo` chegou durante a rodada; ela o processa quando terminar |
| `awaiting-pr-review` | PR aberto, esperando revisão e merge |
| `wontfix` | fechado: não será feito. Um pedido igual é fechado como `wontfix` de novo |
| `deferred` | fechado: despriorizado. Pode ser reaberto; um pedido igual cita este issue e segue o fluxo |

Para tirar um issue do fluxo, coloque `wontfix` (não será feito) ou `deferred` (não agora). Comentar o motivo é opcional: a triagem roda, tira o label de estado anterior, fecha o issue e registra o motivo. Para retomar um `deferred`, reabra o issue, tire `deferred` e coloque de volta o label de estado que o comentário de fechamento registrou. Um `priority` colocado por você marca o issue como prioritário dentro do estado dele; as etapas também o colocam quando você decide a prioridade numa resposta.

### Correção de PR

Na revisão de um PR aberto, peça a mudança no próprio PR. A correção roda com qualquer uma destas ações:

- uma review com **Request changes**. O corpo e todos os comentários de linha da review formam o pedido;
- uma review (**Comment** ou **Approve**) cujo corpo cita `@claude`;
- um comentário no PR que cita `@claude`, por exemplo "@claude resolva os conflitos" ou "@claude o lint quebrou depois do merge";
- qualquer comentário no PR quando ele tem `awaiting-reply`: é a resposta a uma pergunta da correção.

Comentário de linha avulso (**Add single comment**) não dispara: junte os comentários numa review. Comentário sem `@claude` também não dispara, por isso a conversa entre pessoas no PR não aciona nada.

A correção roda em qualquer PR aberto do repositório, do fluxo ou de uma pessoa. PR de fork é recusado, com um comentário: a rodada executaria o código do fork com os secrets do repositório.

Na rodada, o Claude:

1. lê o pedido, o PR e os critérios de aceite dos issues que o PR fecha;
2. faz um commit por pedido na branch do PR. Conflito com a base se resolve com merge da base na branch, nunca com rebase ou force push;
3. roda a bateria de `quality_checks` e, quando um pedido muda a tela ou o comportamento, o QA independente;
4. atualiza as seções do corpo do PR que a rodada mudou (só em PR que segue o modelo da `to-pr`);
5. responde a cada comentário de linha na thread dele e deixa um comentário **Correção** no PR, com o que foi feito, o que não foi e por quê.

Pedido ambíguo ou que muda um critério de aceite não vira código: vira pergunta, e o PR ganha `awaiting-reply`. Responda no PR, sem precisar de `@claude`.

O push da correção usa o `GITHUB_TOKEN`, e o GitHub não dispara workflows a partir dele: o CI do PR não roda sozinho depois da correção. Dê o play manualmente (feche e reabra o PR, ou dispare o workflow de CI). Mudança em `.github/workflows/` também fica fora: o token da rodada não pode fazer push desses arquivos.

### Notificação

Quando o fluxo para e só anda com uma pessoa, o comentário que pede a ação marca o **responsável** do issue com `@`. Os pontos de espera que marcam hoje:

| Ponto de espera | Comentário | Onde vai o `@` |
| --- | --- | --- |
| Pergunta impeditiva (handoff) na triagem, na quebra, na implementação e na sub-task | `## Status`, com `awaiting-reply` | na linha **Preciso de você** |
| Rodada de perguntas do refinamento | `## Refinamento — rodada N`, com `awaiting-reply` | na linha **Ao responder** |
| Fim da triagem, esperando `go` (`ready-for-*` e `needs-discovery`; `needs-refinement` e `needs-break-down` só com `auto_advance: false` ou `ai.yml` antigo) | `## Triagem` | na linha **Próximo passo** |
| Fim do refinamento, esperando `go` (`needs-break-down`, só com `auto_advance: false` ou `ai.yml` antigo) | `## Refinamento` final | na linha **Próximo passo** |
| Fim da quebra, esperando `go` (`ready-for-*`), mesmo quando a quebra rodou encadeada | `## Quebra` | na linha **Próximo passo** |
| Etapa seguinte que não pôde ser chamada (dispatch que falha, `undo` recusado na rodada) | **Etapa seguinte não chamada**, novo no issue, pedindo `go` | na linha **Próximo passo** |
| Passo que falha fora do agente | **Rodada com falha** (veja [Testar](#testar)) | na linha **Responsável** |
| PR aberto pela implementação ou pela sub-task (`awaiting-pr-review`) | nenhum: é um pedido de review | em `reviewRequests` do PR; `@` num comentário no PR só se o pedido falhar |
| Handoff da correção de PR (`awaiting-reply` no PR) | `## Status`, no PR | na linha **Preciso de você**, para quem disparou a rodada |
| Cadeia de um pai parada (falha ao empilhar, rodada sem PR e sem pergunta, sub-task humana ou bloqueio externo) | `## Cadeia parada`, novo no pai, com o motivo e o `go` para retomar | na linha **Responsável**, o responsável do pai |
| Stack de um pai completa (`awaiting-pr-review` no pai) | `## Stack completa`, novo no pai, pedindo a revisão de baixo para cima | na linha **Responsável**, o responsável do pai |

A menção vai no próprio comentário que pede a ação, nunca num segundo comentário só para avisar, e só em comentário novo: nenhuma etapa edita um comentário existente para acrescentar `@`. Encerramento em `wontfix` ou `deferred` não é espera e não marca ninguém. A etapa que encadeia (a triagem ou o refinamento que chamam a seguinte sozinhos, veja [Etapas que seguem sozinhas](#etapas-que-seguem-sozinhas)) também não é espera: o comentário final dela não marca ninguém, e a menção fica para a próxima etapa que parar esperando uma pessoa. Handoff no chat continua sem menção.

**Na cadeia de um pai**, o comentário de status do planner é editado a cada rodada e não leva `@`. O aviso é outro comentário, sempre novo: o planner (`issue-remote-implement.yml`) resolve o responsável do pai no passo **Resolver responsavel do pai** e posta **Cadeia parada** em toda parada, mesmo repetindo o motivo de uma anterior, e **Stack completa** quando o pai ganha `awaiting-pr-review`. Despachar a próxima sub-task, esperar a resposta numa sub-task ou esperar um worker não gera aviso: na espera por resposta, quem avisa é o handoff da sub-task. Pai fora da cadeia (o worker de um `go` direto numa sub-task voltando) só tem o status atualizado. Sem responsável, o aviso sai do mesmo jeito e diz que não há responsável identificável. Se a resolução ou o aviso falharem, a rodada segue, e o status e os labels ficam como ficariam sem o aviso.

**No PR**, o aviso é um pedido de review. Ao abrir o PR, a `remote-to-pr` pede review de cada responsável do issue, um login por vez, e confere em `reviewRequests`. O corpo do PR não leva `@`. Com vários assignees, o review é pedido a todos; quem já é reviewer fica como está, sem erro nem pedido duplicado. Se o pedido falhar para alguém (por exemplo, usuário sem acesso ao repositório), um comentário no PR marca com `@` só quem falhou, avisando que o PR espera revisão. O PR continua aberto e a rodada segue até o fim, com `awaiting-pr-review`. Sem responsável, nenhum review é pedido e o comentário **Implement** no issue diz que não há responsável identificável. Numa stack, cada camada pede review assim que o PR dela abre, ao responsável herdado do pai. A rodada que só atualiza o corpo de um PR existente (correção de PR) não pede review de novo. Se a rodada morrer entre abrir o PR e pedir o review, o review fica sem pedir; o issue ganha `awaiting-pr-review` do mesmo jeito.

Quem a etapa marca não é decisão do agente. Antes de cada rodada de agente num issue (`issue-triage.yml`, `issue-refinement.yml`, `issue-break-down.yml`, `issue-remote-implement.yml` e `issue-sub-task.yml`), o passo **Resolver responsavel** (action `responsible`) roda a resolução abaixo, com `default_responsible` lido do checkout do repositório, e entrega ao agente, no system prompt, uma frase `Responsavel:` com os logins a marcar ou "sem responsavel". A skill marca exatamente esses logins. Se a resolução falhar, a rodada segue como "sem responsável", com um aviso no log da run.

O responsável é resolvido por `scripts/responsible.py`, sempre da mesma forma. A primeira regra que acha uma pessoa vence:

1. Os **assignees** do issue. Vale para todo issue, inclusive os criados por bot. Com vários assignees, todos são marcados.
2. O **autor** do issue, se for uma pessoa.
3. Se o autor é bot ou agente:
   - numa `[SUB-TASK]`, o responsável do **pai** (a sub-issue nativa, ou a linha `Parte de #<pai>`), resolvido pelas mesmas regras;
   - em outro issue, o campo **`Responsável: @usuario`** do corpo (veja abaixo);
   - por último, a chave **`default_responsible`** de `.github/ai-workflows.yml`.
4. Nenhuma regra achou uma pessoa: **sem responsável**. O comentário diz que não há responsável identificável e não marca ninguém. Não é erro: a rodada segue como seguiria.

Bot ou agente nunca é marcado: conta como bot a conta do tipo `Bot` ou com login terminado em `[bot]`. Quem colocou o último `go` não conta como responsável. Se a resolução falhar (API indisponível, por exemplo), o comentário sai mesmo assim, sem menção.

**Exceção, a correção de PR:** quando o `pr-fix` para numa pergunta no PR, e também na falha de uma rodada dele, o aviso vai para quem disparou a rodada, ou seja, o autor da review ou do comentário que cita `@claude` (ou que respondeu ao handoff), mesmo que não seja o responsável do issue. O `pr-fix.yml` lê esse login do evento e o passa ao agente no system prompt, numa frase `Quem disparou a rodada:`. Bot, ou evento sem autor, não é marcado: o handoff diz que não identificou quem disparou. O responsável do issue não é marcado nesses casos.

#### O campo `Responsável:` (para agentes de fora do fluxo)

Um agente ou bot de fora do fluxo que abre issue com `needs-triage` diz quem responde por ele com uma linha própria no corpo, em qualquer posição:

```
Responsável: @usuario
```

- A linha tem só o campo e um login do GitHub, com `@`. `Responsavel:` sem acento e `**Responsável:** @usuario` em negrito também valem. No meio de uma frase, não vale.
- Mais de uma linha: vale a primeira.
- O campo só é lido quando o autor do issue é bot ou agente e não há assignee. Num issue aberto por uma pessoa, o autor vem antes.
- Login de bot, ou que não existe, é ignorado, e vale a regra seguinte (`default_responsible`).
- Dentro do fluxo, quem cria issue é a `issue-break-down`, e só `[SUB-TASK]`: essas herdam o responsável do pai e não precisam do campo.

## Skills

O marketplace `samuel-morrissey-ai-workflows` tem um plugin:

- **`samuel-morrissey-skills`**, com raiz neste repositório e as skills em `skills/`: as skills do fluxo, descritas abaixo.

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
- **remote-to-pr** — abre um PR, ou atualiza o corpo de um PR existente, em fluxo remoto e assíncrono, sem ninguém para responder: segue a `to-pr` inteira, monta Evidências e Critérios de aceite a partir do relatório da `issue-qa` e aplica direto, sem perguntar.
- **pr-fix** — corrige um PR aberto a partir de uma review ou de um comentário: um commit por pedido na branch do PR, bateria de qualidade, QA quando a tela ou o comportamento muda, resposta a cada pedido no PR. Veja [Correção de PR](#correção-de-pr).

### Utilitários

- **80-20** — modo Pareto: maior retorno com o menor esforço na tarefa dada.
- **setup-repo** — configura um repositório consumidor a partir do relatório do `doctor`: infere os comandos do projeto, redige a skill `evidencias`, levanta colisões de labels e os fornecedores para `web_domains` (também num repositório já configurado), pergunta tudo de uma vez e abre o PR no repositório alvo. Veja [Configurar um repositório](#configurar-um-repositório).
- **hello-issue** — skill de exemplo que valida a integração entre o marketplace e um repositório consumidor, publicando um comentário no issue informado.

### Usar as skills localmente

As mesmas skills servem no Claude Code da sua máquina. O marketplace é este repositório:

```
/plugin marketplace add samuel-morrissey/ai-workflows
/plugin install samuel-morrissey-skills@samuel-morrissey-ai-workflows
```

O plugin `life-os` (o servidor MCP do Life OS e as skills `second-brain`, `teach-me` e `teacher-helper`) saiu deste marketplace e mora no repositório do Life OS, que é o marketplace dele. Quem o instalou daqui o desinstala (`/plugin uninstall life-os@samuel-morrissey-ai-workflows`) e reinstala de lá, como diz o [README do plugin](https://github.com/samuel-morrissey/life-os/blob/main/plugins/life-os/README.md):

```
/plugin marketplace add samuel-morrissey/life-os
/plugin install life-os@samuel-morrissey-life-os
```

Quem tinha o marketplace antigo (`samuel-morrissey/claude-marketplace`) troca pelo novo: remova o antigo (`/plugin marketplace remove samuel-morrissey-claude-marketplace`) e rode os dois comandos acima. Em `settings.json`, a chave de `enabledPlugins` passa a ser `samuel-morrissey-skills@samuel-morrissey-ai-workflows`, e a entrada de `extraKnownMarketplaces` aponta para `samuel-morrissey/ai-workflows`.

### Publicar uma atualização

O que cada parte deste repositório alcança depois do merge em `main`:

| Parte | Quem usa | Chega quando |
| --- | --- | --- |
| `.github/workflows/*.yml` | os `ai.yml` dos consumidores, por `@main` | na próxima run, sem fazer nada |
| `scripts/doctor.py` | você, pelo checkout ou pelo `curl` de `main`; a skill `setup-repo`; o job `check-caller` | na próxima execução, sem fazer nada |
| `skills/*` e `.claude-plugin/` | o Claude Code da sua máquina, pelo plugin `samuel-morrissey-skills` | só depois de subir a versão e atualizar o plugin |

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
| Do projeto | `.github/ai-workflows.yml`, versionado no repositório | `setup_commands`, `quality_checks`, `evidence_tools`, `default_responsible`, `web_domains` |
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
| `AI_RUNS_ON` | variável | não | label do runner dos jobs; sem ela, `ubuntu-latest` (veja abaixo) |

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

### Runner self-hosted

Sem configuração, todo job roda em `ubuntu-latest`, o runner do GitHub. Num repositório privado isso gasta minutos de Actions, e com o limite de gasto atingido os jobs nem começam. A variável `AI_RUNS_ON` troca o runner de todas as etapas pelo label de um runner self-hosted:

```
gh variable set AI_RUNS_ON --org caravelasistemas --visibility all --body vps
gh variable set AI_RUNS_ON --repo samuel-morrissey/life-os --body vps
```

O chamador repassa a variável como o input `runs_on` do router, que a repassa a cada etapa. Apagar a variável volta para `ubuntu-latest`, sem mudar arquivo nenhum.

O que muda num runner self-hosted:

- **Só em repositório privado.** Num repositório público, um PR de fork rodaria código de terceiros na sua máquina. Este repositório é público e fica em `ubuntu-latest`, onde os minutos são gratuitos.
- **Um job por runner.** Uma rodada longa do agente segura o runner, e o CI do mesmo repositório (ou da mesma organização) espera na fila. Mais runners com o mesmo label resolvem.
- **A imagem traz menos ferramentas.** O fluxo usa `gh`, `git`, `jq`, `python3`, `curl`, `openssl`, `sudo` e, com bucket, `aws`. O Node é instalado pelo próprio fluxo quando o runner não tem `npm`. O que `setup_commands`, `quality_checks` e `evidence_tools` do projeto usam além disso precisa existir na imagem ou ser instalado em `setup_commands`.
- **Conta pessoal não tem runner de conta.** Cada repositório pessoal precisa do próprio runner registrado; numa organização, um runner serve a todos os repositórios.

### O arquivo `.github/ai-workflows.yml`

Os comandos do projeto, lidos por `issue-remote-implement.yml`, `issue-sub-task.yml` e `pr-fix.yml` depois do checkout, antes de chamar o agente; o responsável padrão, lido pelas etapas de issue antes do agente e por todas as etapas na falha de rodada; e a documentação dos fornecedores, lida pela triagem, pelo refinamento e pela quebra antes do agente. Só escalares de texto e blocos literais (`|`), um comando por linha:

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
web_domains: |
  https://docs.asaas.com/reference
# auto_advance: false  # descomente para as etapas voltarem a esperar `go`
```

- `setup_commands`: prepara o ambiente do projeto. O **workflow** roda esses comandos, na ordem declarada, antes de chamar o Claude. Sem eles, `quality_checks` roda num checkout sem dependências instaladas. Se um comando falhar, o job para ali e o Claude não é chamado. Precisa de uma versão específica de runtime? Resolva dentro desses comandos, porque o fluxo não escolhe versão. Uma mudança de `PATH` só chega ao Claude se for gravada em `$GITHUB_PATH`.
- `quality_checks`: os comandos de verificação do projeto. O **Claude** roda esses comandos antes de abrir o PR. Sem eles, o PR sai declarando que não houve verificação.
- `evidence_tools`: os prefixos de comando que o agente e o QA independente podem rodar para subir o projeto e capturar evidências. Liga o QA. Sem ele, o PR sai declarando que não houve QA. Veja [Evidências e QA](#evidências-e-qa).
- `evidence_bucket`, `evidence_public_url`, `evidence_endpoint`: aceitas também aqui, para um repositório que usa um bucket diferente do dono. Normalmente ficam nas variáveis.
- `default_responsible`: um login do GitHub (`fulano` ou `"@fulano"`), marcado quando um issue não tem responsável: autor bot, sem assignee, sem pai e sem o campo `Responsável:`. É a última regra da [Notificação](#notificação). Sem a chave, esses issues ficam sem responsável, sem erro. Todas as etapas a leem do checkout, inclusive triagem, refinamento e quebra.
- `web_domains`: a documentação dos fornecedores do projeto, que a triagem, o refinamento e a quebra podem ler com `WebFetch`, além da lista fixa do plugin (`docs.github.com`, `code.claude.com`, `platform.claude.com`). Só essas três etapas a usam: implementação, sub-task e correção de PR seguem sem web. Bloco `|`, uma entrada por linha, e cada entrada é uma destas:
  - um domínio (`docs.asaas.com`): libera o domínio;
  - uma **URL de entrada** `https://` (`https://docs.asaas.com/reference`): libera o host da URL e chega ao agente, no system prompt, como ponto de partida. O agente começa pelo `llms.txt` do domínio, quando existe, depois pela URL de entrada, e segue os links dela em vez de adivinhar caminhos.

  Cada domínio é liberado uma vez só, mesmo repetido ou já na lista fixa; duas URLs no mesmo domínio liberam um domínio e as duas vão ao agente. O domínio casa só com ele mesmo: `api.asaas.com` é outra linha. O passo **Ler dominios da web** (action `web-domains`) lê a chave do checkout. Linha vazia ou só comentário (`#`) é ignorada. Linha inválida é ignorada com um aviso no log da run, e as outras valem: esquema que não é `https://`, curinga `*`, espaço no meio, aspas, crase, cifrão, barra invertida, host vazio ou domínio sem ponto. Lista ou mapa YAML falha a rodada antes do agente. Sem a chave vale só a lista fixa, sem aviso. O `doctor` acusa a linha inválida no item `config` (`diverge`) e, com o arquivo válido e sem a chave, dá `info` no mesmo item, apontando a skill `setup-repo`.

  Quem propõe a chave é a skill `setup-repo`, também num repositório que já está todo `ok`: ela levanta os fornecedores externos do projeto (dependências, APIs e gateways no código, ADRs, `CONTEXT.md`), deixa de fora o que a lista fixa já cobre, escolhe para cada um a documentação oficial (o `llms.txt` primeiro, quando existe), confere com `curl` que a URL não redireciona para outro host e, no mesmo host, usa o destino final. A lista entra na pergunta única, com o motivo de cada entrada, e o setup só acrescenta as entradas que faltam, sem reescrever as outras chaves nem remover as do humano. Repositório sem fornecedor externo fica sem a chave: o `info` volta nas próximas rodadas do `doctor`, e isso é repetição, não erro.
- `auto_advance`: `auto_advance: false` desliga o encadeamento das etapas antes da implementação (veja [Etapas que seguem sozinhas](#etapas-que-seguem-sozinhas)): a triagem e o refinamento não chamam mais a etapa seguinte, e todo comentário final volta a pedir `go` marcando o responsável. Sem a chave, ou com qualquer outro valor, as etapas encadeiam. Quem lê é a etapa que está terminando (passo **Ler encadeamento**, action `advance`), no checkout; o `if` do router não lê arquivo. É a única chave booleana do arquivo: a implementação a ignora, sem aviso, e o `doctor` a reconhece.

Chave do arquivo vence o input de mesmo nome do `ai.yml`; chave ausente deixa o input valer; chave desconhecida gera aviso e é ignorada; valor que não é texto (lista, mapa, número) falha o job antes do agente, com o nome do arquivo no erro, menos em `auto_advance`, que é booleana. Os inputs no `ai.yml` continuam aceitos para os repositórios já configurados, mas o caminho novo é o arquivo.

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

O que exige decisão (os comandos do projeto, a skill `evidencias`, colisão de labels, os `web_domains` dos fornecedores) fica com a skill `setup-repo`, que roda o `doctor`, lê o projeto, pergunta tudo de uma vez, aplica o `doctor fix` e só então abre o PR no repositório alvo, com o texto coerente com o que já foi corrigido:

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
| `config` | `.github/ai-workflows.yml` presente, só com chaves conhecidas e valores de texto, e `web_domains` sem linha que o workflow ignora (linha inválida: `diverge`); sem a chave `web_domains`, `info` | nada: sem arquivo e sem inputs inline, aponta a skill `setup-repo`; sem `web_domains`, o `info` aponta a skill `setup-repo`, que propõe a chave com os fornecedores do projeto |
| `secrets` | `CLAUDE_CODE_OAUTH_TOKEN`; `EVIDENCE_ACCESS_KEY_ID` e `EVIDENCE_SECRET_ACCESS_KEY` quando há bucket; `PROJECT_ENV` só informativo. Secret de organização com acesso ao repositório conta | grava no repositório os que faltam, com os valores do `config.env`, quando não há secret de organização |
| `vars` | `EVIDENCE_BUCKET`, `EVIDENCE_PUBLIC_URL`, `EVIDENCE_ENDPOINT` com os valores do `config.env` | grava na organização (dono organização) ou no repositório (dono conta) |
| `labels` | os 14 labels do fluxo da `issue-labeling`, com cor e descrição canônicas | cria os que faltam e corrige cor e descrição dos que divergem. Nunca apaga nem renomeia; colisões (`priority-*`, tipos como label) saem como nota para você decidir |
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

Os testes das partes puras do script (leitor do arquivo de configuração, extração dos inputs inline, `config.env`, comparação e relatório) rodam com `python3 scripts/test_doctor.py`, que também inclui os de `scripts/test_workflows.py` (o passo de comentário de falha dos workflows reutilizáveis, rodado num bash com um `gh` falso) e os das outras suítes listadas em [Testar](#testar).

Os labels do fluxo (`needs-triage`, `ready-for-agent`, `awaiting-reply`, `awaiting-pr-review`, `deferred`, `priority`...) são criados de uma vez pelo `doctor fix`, com a cor e a descrição da `issue-labeling`. Sem o `doctor`, as skills criam os que faltarem na hora de aplicar, e os workflows criam `work-in-progress`, `go` e `undo`. Um label que já existia com outra cor ou descrição só é corrigido pelo `doctor`: as skills nunca editam label.

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

Custo: a run passa a rodar o agente desenvolvedor mais até dois subagentes de QA, cada um subindo o app. Num projeto com banco e seed pesado, meça uma run antes de ligar; o teto de turnos do agente subiu de 150 para 250 por causa do QA. Vídeo: o Playwright grava `.webm`, mas o GitHub só mostra player para vídeo enviado pela interface; o QA converte para GIF com ffmpeg, e o `.webm` fica no bucket ou no artifact.

## Métricas

Toda run das 7 etapas (`issue-triage`, `issue-refinement`, `issue-break-down`, `issue-remote-implement`, `issue-sub-task`, `pr-fix` e `pr-merged`) mede o próprio tempo. O penúltimo passo do job, **Registrar metricas da rodada** (action `metrics`; no `pr-merged`, que não tem `round-failure`, o último), roda com `if: always()` e `continue-on-error: true`: sai também quando o agente falha ou estoura os turnos, e nunca muda o resultado da run. Ele lê os passos do job pela API de jobs da run (`actions: read`, como a `round-failure`), soma as durações (`started_at`/`completed_at`) e publica o resultado em dois lugares. Nenhum comentário vai para o issue ou o PR.

- **Summary do job** (`$GITHUB_STEP_SUMMARY`, na página da run): uma tabela com os quatro grupos, sempre as mesmas linhas e na mesma ordem, mais o total do job até o passo de métricas e a conclusão do job até ali. Duas runs da mesma etapa ficam lado a lado.
- **Artifact `metrics`**, com um `metrics.json` de esquema fixo: `schema_version`, `etapa`, `numero` (issue ou PR, `null` quando não foi resolvido), `run` (`id` e `attempt`), `job` (`nome`, `conclusao` e `segundos` até o passo de métricas), `grupos` (lista na ordem fixa, cada um com `nome`, `estado` e `segundos`), `agente` (a sessão do agente; veja abaixo) e `avisos`. Num re-run, o artifact da tentativa anterior é substituído, e o `attempt` diz de qual tentativa ele é.

Os grupos:

| Grupo | O que soma |
|---|---|
| `preparo` | checkout, resolução do alvo, guarda de concorrência, `work-in-progress`, consumo do `go`, resolução do responsável, leitura de `web_domains`, download do planner e o *Set up job* do Actions |
| `ambiente` | a composite `agent-env` (**Preparar ambiente do agente**) |
| `agente` | o passo `anthropics/claude-code-action@v1`, só a duração do passo do Actions |
| `pos-agente` | `publish-evidence`, redes de segurança de label, remoção do `work-in-progress`, os passos do planner da cadeia (**Entrar na cadeia**, **Planejar e empilhar**, **Resolver responsavel do pai**, **Decidir e agir**, **Devolver o controle ao pai**) e, no `pr-merged`, o fechamento dos issues |

Cada grupo sai como duração ou num destes estados:

- `pulado`: o grupo existe na etapa, mas nenhum passo dele rodou (handoff, `skip` da guarda de concorrência, o lado pontual numa run de pai);
- `n/a`: o grupo não existe na etapa: `ambiente` na triagem, no refinamento e na quebra; `ambiente` e `agente` no `pr-merged`;
- `n/d`: a API de jobs não respondeu, a resposta veio ilegível ou nenhum job casou. O summary traz um aviso e o passo termina sem erro.

### Sessão do agente

Nas 6 etapas com agente, o passo `anthropics/claude-code-action@v1` tem `id: claude`, e o passo de métricas recebe o `execution_file` dele (`steps.claude.outputs.execution_file`: as mensagens da sessão, com o evento final `result`) e o mesmo `--max-turns` do `claude_args` da etapa (50 na triagem, 80 no refinamento, 100 na quebra, 250 na implementação, na sub-task e no `pr-fix`). O objeto `agente` do `metrics.json` e a seção **Sessão do agente** do summary trazem, sempre com todas as chaves:

| Campo | De onde vem |
|---|---|
| `estado` | `medido` (havia evento `result`), `parcial` (sessão sem `result`: estouro ou falha da action), `n/d`, `pulado` ou `n/a` |
| `duracao_ms`, `duracao_api_ms` | `duration_ms` e `duration_api_ms` do `result` |
| `turnos` | `num_turns` do `result` |
| `max_turns` | o `--max-turns` configurado na etapa |
| `fim` | o `subtype` do `result`: `success`, `error_max_turns`, `error_during_execution`... |
| `tokens` | `entrada`, `saida`, `cache_leitura` e `cache_criacao`, do `usage` do `result` |
| `ferramentas` | chamadas por nome de ferramenta (`Bash`, `Read`, `Edit`, `Agent`...) na sessão principal: só as mensagens sem `parent_tool_use_id`, então o que um subagente chama não entra |
| `custo_usd` | `total_cost_usd` do `result`. É **informativo**: com token OAuth não reflete cobrança |
| `subagentes` | a quebra por subagente (abaixo) |

Campo que a sessão não trouxe sai `n/d`. Sem `execution_file`, ou com o arquivo ilegível ou truncado, todos os campos da sessão saem `n/d` (menos o `max_turns`, que é da config), o summary avisa e o passo termina sem erro. Uma sessão sem `result` publica a contagem de ferramentas das mensagens que houver, com aviso. Quando o grupo `agente` é `pulado` (o pai no `issue-remote-implement`, o `skip` da guarda) ou `n/a` (o `pr-merged`), o `agente` vem com esse estado em todos os campos. O `schema_version` continua `1`: o `agente` era reservado, e campos novos entram sempre presentes; ele sobe quando o esquema mudar de forma incompatível.

#### Subagentes

Cada chamada à ferramenta `Agent` (o QA da `issue-qa`, uma exploração...) vira uma entrada da lista `subagentes`, na ordem em que aparece no `execution_file`, e uma linha da tabela **Subagentes** do summary. Tudo sai das mensagens da sessão: as do subagente trazem `parent_tool_use_id` com o id da chamada, e o `tool_result` com esse id fecha a chamada.

| Campo | De onde vem |
|---|---|
| `descricao` | o `description` da chamada |
| `tipo` | o `subagent_type` da chamada; `n/d` quando ela não traz |
| `turnos` | mensagens do assistente com `parent_tool_use_id` igual ao id da chamada (eventos com o mesmo `message.id` contam uma vez) |
| `duracao_ms` | do `timestamp` da mensagem que fez a chamada ao da mensagem com o `tool_result`; `n/d` se uma das duas não tem `timestamp`, ou se não há `tool_result`. Nada é estimado |
| `concluido` | `true` quando há `tool_result`; `false` numa chamada cortada no meio (`error_max_turns`, falha do subagente), que entra com os turnos que houver |

Subagentes em paralelo têm uma linha cada, e um subagente chamado por outro tem a própria linha, contando só as mensagens do próprio id (não há árvore). Sessão sem `Agent`: a lista é vazia e a tabela aparece com uma linha "nenhum". Sem `execution_file` legível, a lista sai `n/d`; com o grupo `agente` `pulado` ou `n/a`, sai nesse estado.

O próprio passo de métricas e o `round-failure` rodam depois da leitura e não entram na soma. O job lido é o deste runner; sem ele, o da etapa pelo nome, e nunca o `check-caller` do router. O mapeamento passo → grupo de cada etapa mora em [`.github/actions/metrics/metrics.py`](.github/actions/metrics/metrics.py): um passo novo ou renomeado num workflow precisa entrar lá, e o teste falha enquanto não entrar.

### Comparar runs

O `scripts/metrics.py` junta os artifacts `metrics` das últimas runs de um repositório numa tabela por etapa, sem baixar artifact por artifact. Ele usa o `gh` já autenticado (precisa ler as Actions do repositório):

```bash
python3 scripts/metrics.py samuel-morrissey/ai-workflows            # últimas 50 runs
python3 scripts/metrics.py samuel-morrissey/ai-workflows --runs 200 # ou -n 200
```

Para cada etapa com métricas, a saída traz quantas runs entraram e uma linha por grupo (`preparo`, `ambiente`, `agente`, `pos-agente`) e por métrica numérica da sessão (duração, tempo de API, turnos, os quatro tokens e o custo informativo), com quantos valores a linha usou, a mediana e o p90 (pelo posto mais próximo: o valor na posição ⌈0,9·n⌉ da lista ordenada; com uma run só, os dois são o próprio valor):

```
### issue-sub-task: 3 runs

| Linha | Valores | Mediana | p90 |
|---|---|---|---|
| preparo | 3 | 21s | 34s |
| ambiente | 3 | 1m 12s | 1m 40s |
...
| sessão: custo (informativo) | 3 | US$ 2.1043 | US$ 3.0071 |
```

- `pulado`, `n/a` e `n/d` não entram na conta da célula; uma célula sem nenhum valor medido sai `n/d`.
- Ficam de fora, com a contagem em **Fora da conta** no fim da saída: runs sem artifact `metrics` (anteriores à feature, com o artifact expirado, ou de workflows que não são etapas), com `schema_version` que o script não conhece e com o `metrics.json` ilegível. Nada disso interrompe o resto.
- Num re-run, a run conta uma vez, com o artifact mais novo.
- A saída é estável: etapas na ordem das 7 etapas e linhas sempre na mesma ordem, para comparar duas execuções com um `diff`.
- Sem nenhuma métrica nas runs consideradas, o script diz que não há métricas e sai com 0. Com o `gh` falhando (sem autenticação, repositório inexistente), imprime `erro:` com a mensagem do `gh` e sai com 1.

## Testar

Os testes dos scripts e dos passos dos workflows rodam sem rede e sem `gh` com `python3 scripts/test_doctor.py`, que importa as outras suítes: `scripts/test_workflows.py`, `scripts/test_sub_tasks.py`, `scripts/test_responsible.py`, `scripts/test_undo.py` (o destino `issue-undo` do router, a reversão da triagem, do refinamento e da quebra e as recusas do `undo`, com um GitHub falso), `scripts/test_advance.py` (o encadeamento: os destinos do router para o `ai-advance`, o tipo novo no `ai.yml` e o `doctor` apontando a cópia antiga, a leitura de `auto_advance`, o dispatch da etapa seguinte e o comentário que pede `go` quando ele falha, e o `undo` durante uma etapa encadeada, com um GitHub falso) e `scripts/test_metrics.py` (o passo de métricas nas 7 etapas: posição e condição, todo passo com grupo no mapeamento, o `id:` da action e o `execution_file` e o `--max-turns` repassados, e o `run` da action num bash com uma API de jobs falsa, inclusive fora do ar, e com sessões de exemplo: `success`, `error_max_turns`, sem `result`, ausente ou ilegível, com subagentes concluídos, cortados, em paralelo, aninhados e sem `timestamp`; e o `scripts/metrics.py` da [comparação entre runs](#comparar-runs), com um `gh` falso servindo runs e artifacts: mediana e p90 por grupo e por métrica da sessão, células só com estados, runs sem artifact, com `schema_version` desconhecido ou ilegíveis, re-runs, a flag `--runs`, sem métricas e com o `gh` falhando).

Para testar o fluxo de ponta a ponta:

1. Abra um issue de teste e coloque o label `needs-triage` (ou só `go`: sem label de estado, o `go` vai para a triagem).
2. Abra a aba **Actions**. O workflow **AI** roda o job **issue-triage**, e o issue ganha `work-in-progress` enquanto ele roda.
3. No fim, o issue recebe um label de estado (`needs-*` ou `ready-for-*`) ou um comentário com perguntas. Se responder às perguntas no issue, a triagem roda de novo. Com label de estado novo, coloque `go` para a próxima etapa rodar.

Problemas comuns:

- **Erro de token:** o secret não chega ao repositório. Veja [Variáveis e secrets](#variáveis-e-secrets).
- **`Secret CLAUDE_CODE_OAUTH_TOKEN is required, but not provided while calling`:** o `ai.yml` usa `secrets: inherit` e o repositório está em outra organização. Passe o secret pelo nome, como no `ai.yml` daqui.
- **Erro ao buscar o workflow (`failed to fetch workflow` ou parecido, ou a execução falha em 0s):** o `uses` do `ai.yml` aponta para um caminho que não existe. Confira que ele aponta para `samuel-morrissey/ai-workflows/...@main`.
- **Todos os jobs aparecem como "skipped":** o evento não bateu com nenhuma etapa. Um label colocado antes do `ai.yml` existir não conta: tire o label e coloque de novo.
- **Rodada com falha:** quando um passo falha fora do agente (configuração inválida em `.github/ai-workflows.yml`, `setup_commands` que falha, secret inválido, falha ao instalar o plugin ou ao baixar o planner, ou a própria action do agente), o `work-in-progress` sai e o workflow deixa no issue um comentário **Rodada com falha**, com a etapa, o nome do passo que falhou, o link da run e o `@` do responsável (na correção de PR, de quem disparou a rodada; veja [Notificação](#notificação)). O label de estado não muda. Veja o log da run, corrija a causa e aplique `go` de novo. Uma falha antes de o número do issue ser resolvido não tem onde comentar: só a aba **Actions** mostra.

## Como funciona

- `ai.yml` (em cada repositório, idêntico ao daqui): declara os gatilhos (`on:`) e as permissões, que o GitHub exige no chamador, lê as variáveis do bucket e repassa os secrets pelo nome. Nenhum valor do projeto mora nele.
- `.github/ai-workflows.yml` (em cada repositório): os comandos do projeto. `issue-remote-implement.yml` e `issue-sub-task.yml` o leem depois do checkout e, quando existe, ele vence os inputs do `ai.yml`.
- `router.yml`: um job por etapa, mais o `check-caller`, que confere o `ai.yml` do chamador contra o modelo daqui e abre o PR de atualização quando ele diverge. O `if` do job decide se o evento é daquela etapa, e o `uses` chama o workflow dela, passando o secret pelo nome. Mudar uma regra aqui muda para todos os repositórios.
- `pr-merged.yml` e `pr-closed.yml`: os dois destinos do PR fechado, sem agente, só com `gh`. Os dois leem os `Closes`/`Fixes`/`Resolves` do corpo do PR. O `pr-merged.yml` fecha os issues quando o merge é fora da branch padrão. O `pr-closed.yml`, no PR fechado sem merge, devolve o `awaiting-pr-review` ao estado de antes do PR, a exceção da regra 2 da `issue-labeling`.
- `issue-undo.yml`: o destino do label `undo`, sem agente, só com `gh`. A regra mora em `scripts/undo.py`, pela action `undo`: a última etapa sai dos comentários de etapa do issue (`## Triagem`, `## Refinamento`, `## Quebra`), e cada comentário de reversão a cancela. A triagem, o refinamento e a quebra chamam a mesma action no fim da rodada (passo "Processar undo da rodada"), para o `undo` que chegou durante ela. É a outra exceção da regra 2 da `issue-labeling`.
- `pr-fix.yml`: a correção de PR. Resolve o PR do evento (recusa PR fechado ou de fork), coloca `work-in-progress` no PR, faz o checkout da head com histórico completo e roda o Claude com a skill `pr-fix`, com as mesmas actions de ambiente e de evidências da implementação.
- `issue-*.yml`: cada etapa coloca `work-in-progress` no issue, consome o `go` e o `awaiting-reply`, roda o Claude com a skill da etapa (do plugin `samuel-morrissey-skills`, instalado deste repositório pela `claude-code-action`) e tira o `work-in-progress` no fim. Se algum passo falha, o último passo (`if: failure()`, action `round-failure`) comenta no issue a etapa, o passo que falhou, lido da run pela API com `actions: read`, o link da run e a menção ao responsável, resolvido por `scripts/responsible.py` (que vem junto com a action, na mesma ref); a run continua marcada como falha.
- `issue-remote-implement.yml` (pontual) e `issue-sub-task.yml`: antes do agente, o `issue-sub-task.yml` troca o checkout para a base da sub-task (a branch do topo da stack), para o setup instalar o que a sub-task herda; os dois leem `.github/ai-workflows.yml`, carregam o `PROJECT_ENV` em `$GITHUB_ENV`, montam a allowlist e o system prompt a partir de `quality_checks` e `evidence_tools`, decidem a pasta e as URLs das evidências e instalam as ferramentas de captura citadas (action `agent-env`); depois do agente, publicam a pasta de evidências no bucket (ou como artifact) e, se preciso, corrigem os links no PR (action `publish-evidence`).
- `.github/actions/`: as composite actions comuns aos workflows: `agent-env`, `publish-evidence`, `responsible` (o responsável do issue, resolvido antes do agente e entregue a ele no system prompt), `metrics` (o tempo da rodada por grupo de passos; veja [Métricas](#métricas)), `round-failure` e `undo` (a reversão do label `undo`, por `scripts/undo.py`). Cada passo compartilhado mora num lugar só; os workflows as chamam pelo caminho completo (`samuel-morrissey/ai-workflows/.github/actions/<nome>@main`).
- `.claude-plugin/` e `skills/`: o marketplace e o plugin do fluxo. `marketplace.json` declara o marketplace `samuel-morrissey-ai-workflows` com um plugin, `samuel-morrissey-skills`, cuja raiz é o próprio repositório (`plugin.json`, com as skills em `skills/`). As etapas o instalam pela URL deste repositório, por isso a versão da skill que roda é sempre a da `main`.
- `issue-remote-implement.yml` num pai com sub-tasks não roda o Claude: é o planner. Lê as sub-issues, os bloqueios e os PRs (pela branch `sub-task-<n>`), empilha os PRs abertos ainda fora da stack, escolhe a próxima e a despacha ao `issue-sub-task.yml` por `repository_dispatch`. O worker roda o Claude e, no fim, devolve o controle ao pai pelo mesmo mecanismo, com o resultado da rodada. Toda essa leitura mora em `scripts/sub_tasks.py`, que os dois workflows baixam deste repositório na versão deles. O `repository_dispatch` criado com o `GITHUB_TOKEN` dispara workflow (é uma das duas exceções à regra do GitHub); é o que permite a cadeia andar sem um token extra.

Os `uses` apontam para `samuel-morrissey/ai-workflows/...@main`, e não para `./.github/workflows/...` ou `./.github/actions/...`. Em chamadas aninhadas, um caminho local é procurado no repositório do chamador, e não aqui.
