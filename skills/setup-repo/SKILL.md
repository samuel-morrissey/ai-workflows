---
name: setup-repo
description: Configura um repositorio consumidor do fluxo de issues a partir do relatorio do doctor - infere os comandos do projeto, redige a skill evidencias, levanta colisoes de labels, pergunta tudo de uma vez e abre o PR no repositorio alvo. Use para ligar um repositorio novo ao fluxo ou para completar um parcialmente configurado.
argument-hint: "[owner/repo]"
arguments: repo
disable-model-invocation: true
allowed-tools: Bash(python3:*) Bash(gh api:*) Bash(gh repo view:*) Bash(gh repo clone:*) Bash(gh pr create:*) Bash(gh pr view:*) Bash(gh pr list:*) Bash(gh label list:*) Bash(curl:*) Bash(git:*) Read Grep Glob Write Edit
---

# Setup repo

Liga um repositorio ao fluxo de issues com o minimo de decisao humana. O
`doctor` (`scripts/doctor.py` deste plugin) resolve o que e deterministico;
esta skill resolve o resto: **o que o projeto precisa** (comandos, skill
`evidencias`, labels), que exige ler o projeto e decidir.

Divisao de trabalho, para nao duplicar nada:

| Quem | Faz |
|---|---|
| `doctor check` | diz o que falta, diverge ou exige humano |
| esta skill | infere comandos, redige a skill `evidencias`, propoe mapeamento de labels, pergunta, abre o PR com os arquivos |
| `doctor fix --only secrets,vars,labels,topic` | secrets, variaveis, os labels do fluxo (cria e corrige) e topic, antes do PR; o `ai.yml` fica fora porque o PR desta skill ja o traz |

Nao escreva arquivo que o `doctor` reporta `ok`. Nao decida sozinho o que e
pergunta (passo 5). Nao rode o fluxo no repositorio alvo para validar.

## Argumento

`owner/repo`. Sem argumento, use o repositorio do checkout atual
(`gh repo view --json nameWithOwner`). Sem nenhum dos dois, pare e peca.

## Passos

1. **Rode o doctor e leia o relatorio.** Baixe sempre a versao de `main`
   para uma pasta temporaria e rode a partir dela:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/samuel-morrissey/ai-workflows/main/scripts/doctor.py -o "$TMPDIR/doctor.py"
   python3 -I "$TMPDIR/doctor.py" check <owner/repo> --json
   ```

   Nao use o `scripts/doctor.py` que esta ao lado desta skill: e a copia
   congelada na versao instalada do plugin, e o `doctor` muda com mais
   frequencia que o plugin. A unica excecao e a sessao aberta no proprio
   checkout do `ai-workflows`, onde `scripts/doctor.py` e o codigo em
   desenvolvimento. Nos passos seguintes, `doctor` e o arquivo baixado.

   Saida 2 (sem acesso, repositorio inexistente ou arquivado): pare e
   reporte o erro, sem tentar contornar. Saida 0: diga que o repositorio ja
   esta configurado e termine. Guarde os itens que nao estao `ok`: sao o
   unico escopo desta rodada.

2. **Leia o projeto.** Pela API (`gh api repos/{owner}/{repo}/contents/...`),
   sem clonar ainda. O que procurar e o que cada achado diz:

   | Achado | Diz |
   |---|---|
   | `package.json` + lockfile | gerenciador (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`, `bun install`) e os scripts de `lint`, `typecheck`/`tsc`, `test`, `build`, `check` |
   | `.nvmrc`, `.node-version`, `engines.node`, `packageManager` | versao do runtime: entra em `setup_commands` (ex.: `npx --yes n 22` com `$GITHUB_PATH`, ou `corepack enable`) |
   | `.github/workflows/*.yml` existentes | o que a CI ja roda e como prepara o ambiente: copie os comandos, nao reinvente |
   | `pyproject.toml`, `requirements*.txt`, `Makefile`, `go.mod`, `Cargo.toml`, `Gemfile`, `composer.json` | o equivalente de instalacao, lint, teste e build daquela toolchain |
   | `firebase.json` com `hosting.public`, so HTML em `public/` ou `docs/`, sem manifesto | **site estatico**: sem setup, sem checks; `evidence_tools` com um servidor estatico (`npx serve`, `python3 -m http.server`) mais `npx playwright` e `curl` |
   | `docker-compose*.yml` | servicos que o QA precisa subir no runner (Postgres, Redis, MinIO): entram em `setup_commands` via `docker compose up -d <servicos>`, com espera pela porta |
   | `.env.example` | variaveis que o app exige para subir. Separe as que tem valor local (banco em `localhost`) das que exigem segredo de servico externo |
   | servico externo sem emulador (Clerk, Auth0, Stripe sem `stripe-mock`, provedor de e-mail) | o QA so sobe com `PROJECT_ENV`; se nao houver chave de teste, o QA fica desligado (`evidence_tools` vazio) |
   | `supabase/`, `firebase.json` com `emulators`, `.devcontainer/setup.sh` | existe caminho local para o backend: use-o no `setup_commands` como o `life-os` (`supabase start`) e o `lumeeiro-app` (`firebase setup:emulators`) fazem |
   | `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `README` | como o time descreve subir e testar; vale mais que a inferencia |

   Daqui saem tres propostas: `setup_commands`, `quality_checks` e
   `evidence_tools`, um comando por linha, e a resposta a "o QA precisa de
   `PROJECT_ENV`?". Regras:

   - `quality_checks` sao os mesmos da CI quando ela existe. Nao adicione
     check que o projeto nao roda hoje.
   - `setup_commands` roda antes do agente e falha o job se falhar: so o
     que e pre-condicao, nada opcional.
   - `evidence_tools` sao **prefixos** de comando liberados ao agente, nao
     um roteiro. `node`, `npx playwright` e `curl` cobrem a maioria dos
     apps web; CLI entra com o proprio binario.
   - Prefira um script unico do projeto que sobe, espera a porta, captura
     e encerra (ex.: `npm run evidencias`), quando ele existe ou quando o
     projeto ja tem onde colocar um.

   Proponha tambem a chave `default_responsible`: o login do GitHub marcado
   quando um issue nao tem responsavel humano (autor bot ou agente, sem
   assignee, sem pai e sem o campo `Responsável: @usuario`; ordem completa
   na secao Notificacao do README). A proposta e quem mais aparece como
   autor ou assignee dos issues recentes do repositorio
   (`gh api "repos/{owner}/{repo}/issues?state=all&per_page=50"`), ou o dono,
   quando o dono e uma conta pessoal. Sem a chave, issue de bot sem
   responsavel fica sem mencao, sem erro.

3. **Redija a skill `evidencias`** quando o `doctor` a reportou `manual` ou
   `diverge`. Modelo em `skills/issue-qa/EVIDENCIAS-PROJETO.md` deste plugin
   (ou pela mesma URL raw do passo 1). Preencha as cinco secoes com o que o
   passo 2 descobriu: evidencia ideal para este tipo de produto, comando de
   subida com porta e tempo tipico, dados e login de teste (so valores de
   desenvolvimento), como obter o antes, e os limites. Secao que voce nao
   consegue preencher pelo repositorio vira pergunta, nao invencao.

4. **Levante as colisoes de labels.** O item `labels` do relatorio lista o
   que colide com o vocabulario da `issue-labeling` (`priority-*`, tipos
   como label). Para cada uma, proponha: manter o label do repositorio e
   nao usar o do fluxo, trocar pelo do fluxo, ou usar os dois. Labels
   existentes nunca sao editados nem apagados por esta skill.

5. **Pergunte tudo de uma vez**, seguindo a `grilling`: uma unica mensagem,
   cada pergunta com a sua recomendacao e o motivo em uma frase. Fatos
   verificaveis no repositorio nao sao pergunta. O que costuma ser:

   - os tres blocos de comandos propostos, para confirmar ou ajustar;
   - o `default_responsible` proposto, ou nenhum;
   - QA ligado agora ou depois, e `PROJECT_ENV` ou nao, com o custo em uma
     frase (o agente mais ate dois QAs, cada um subindo o app);
   - bucket: usar o do dono (variaveis ja existem) ou nenhum (artifact);
   - o mapeamento de cada colisao de label;
   - secoes da skill `evidencias` que ficaram em aberto.

   Repositorio sem colisao, sem servico externo e com CI clara pode
   terminar com uma pergunta so: "confirma?". Nao invente perguntas para
   parecer completo.

6. **Aplique.** Com as respostas:

   1. Clone raso o repositorio numa pasta temporaria e crie a branch
      `ai-workflows/setup` a partir da branch padrao.
   2. Escreva o que o relatorio pediu e as respostas definiram:
      `.github/workflows/ai.yml` (copia exata do modelo, baixado de
      `samuel-morrissey/ai-workflows` na `main`, sem editar),
      `.github/ai-workflows.yml` e `.claude/skills/evidencias/SKILL.md`.
      Arquivo que o `doctor` deu `ok` fica como esta.
   3. Rode `doctor fix <owner/repo> --only secrets,vars,labels,topic`,
      antes de abrir o PR. O `--only` deixa o item `ai-yml` de fora: sem
      ele, o `doctor` abriria o proprio PR com o `ai.yml`, porque o PR
      desta skill ainda nao existe. O relatorio que o `fix` imprime ja e o
      estado final desses quatro itens (ele rele o repositorio depois de
      corrigir): guarde-o, porque o texto do PR sai dele.
   4. Commit e push. Abra o PR seguindo a skill `to-pr`, com base na branch
      padrao. O texto do PR descreve o repositorio como ele esta neste
      momento, depois do `fix`:
      - o que o `fix` fez (labels criados ou corrigidos, secrets e
        variaveis gravados, topic) entra como feito, nunca como pendencia
        nem como passo a executar;
      - o que ficou `manual` no relatorio do `fix` entra em **Antes e
        depois do deploy**, em *Antes*, com o comando que o relatorio deu.
        Se o `PROJECT_ENV` foi decidido, e aqui que vai o `gh secret set
        PROJECT_ENV -R <owner/repo>` com o conteudo esperado; o valor e do
        humano, nao seu;
      - em **Como testar**, o roteiro e: mergear, criar um issue, colocar
        `needs-triage` e conferir a aba Actions.
   5. Rode `doctor check <owner/repo>` de novo, com o PR aberto. O esperado:
      `ai-yml` em `manual` apontando para o PR ("PR aberto com o modelo,
      falta o merge"), `config` e `evidencias` como estavam (so mudam no
      merge) e os quatro itens do `fix` em `ok` ou `manual`. Se `ai-yml`
      sair `falta` ou `diverge` sem a URL do PR, a branch nao e
      `ai-workflows/*` ou o `ai.yml` do PR difere do modelo: corrija antes
      de responder.

7. **Responda** com: a URL do PR, o relatorio do `doctor check` do passo
   6.5, o que ficou `manual` e por que, e o proximo passo (mergear o PR e
   abrir o primeiro issue de teste). Nao repita como pendencia o que o
   `fix` ja fez.

## Casos

- **Site estatico** (`firebase.json` com `hosting`, so HTML): `setup_commands`
  e `quality_checks` vazios, `evidence_tools` com `npx serve`, `npx
  playwright` e `curl`; a skill `evidencias` diz a porta do `serve` e que a
  evidencia e um print da pagina inteira. Diga no PR que a ausencia de
  checks e decisao.
- **Backend externo sem emulador**: recomende comecar sem QA e ligar depois
  com `PROJECT_ENV`, salvo se o humano ja tem chave de teste em maos.
- **Repositorio parcialmente configurado**: escopo e so o que o `doctor`
  apontou. Nao reescreva o `ai.yml` se ele esta `ok`; nao mexa na skill
  `evidencias` que ja tem as cinco secoes.
- **Outra toolchain** (Python, Go, Rust, PHP): mesma logica, com os
  comandos daquela toolchain; a CI existente e a melhor fonte.

## Fora de escopo

- Editar ou apagar labels por conta propria: os do fluxo sao do `doctor`;
  os demais sao do repositorio.
- Criar o bucket, a regra de ciclo de vida ou qualquer credencial.
- Rodar triagem, implementacao ou QA no repositorio alvo.
- Alterar o `doctor`; se ele reporta errado, abra um issue em
  `samuel-morrissey/ai-workflows`.
