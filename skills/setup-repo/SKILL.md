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
| `doctor fix` | secrets, variaveis, label `go`, topic, e o PR do `ai.yml` quando esta skill nao o incluiu |

Nao escreva arquivo que o `doctor` reporta `ok`. Nao decida sozinho o que e
pergunta (passo 5). Nao rode o fluxo no repositorio alvo para validar.

## Argumento

`owner/repo`. Sem argumento, use o repositorio do checkout atual
(`gh repo view --json nameWithOwner`). Sem nenhum dos dois, pare e peca.

## Passos

1. **Rode o doctor e leia o relatorio.** No checkout deste plugin o script e
   `scripts/doctor.py`; fora dele, baixe para uma pasta temporaria:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/samuel-morrissey/ai-workflows/main/scripts/doctor.py -o "$TMPDIR/doctor.py"
   python3 -I "$TMPDIR/doctor.py" check <owner/repo> --json
   ```

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
   3. Commit e push. Abra o PR seguindo a skill `to-pr`, com base na branch
      padrao. Em **Como testar**, o roteiro e: mergear, criar um issue,
      colocar `needs-triage`, e conferir a aba Actions.
   4. Rode `doctor fix <owner/repo>` para secrets, variaveis, label `go` e
      topic. Se o `PROJECT_ENV` foi decidido, diga ao humano o `gh secret
      set PROJECT_ENV -R <owner/repo>` com o conteudo esperado; o valor e
      dele, nao seu.
   5. Rode `doctor check <owner/repo>` de novo. Enquanto o PR nao e
      mergeado, `ai-yml`, `config` e `evidencias` seguem como estavam: diga
      isso e mostre o que ficou `manual`.

7. **Responda** com: a URL do PR, o relatorio final do `doctor`, o que
   ficou `manual` e por que, e o proximo passo (mergear o PR e abrir o
   primeiro issue de teste).

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

- Editar ou apagar labels existentes.
- Criar o bucket, a regra de ciclo de vida ou qualquer credencial.
- Rodar triagem, implementacao ou QA no repositorio alvo.
- Alterar o `doctor`; se ele reporta errado, abra um issue em
  `samuel-morrissey/ai-workflows`.
