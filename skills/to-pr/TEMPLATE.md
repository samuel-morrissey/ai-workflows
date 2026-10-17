# PR draft template

The format every draft follows — a new PR or replacement text for an existing one. Read by [to-pr](SKILL.md) at draft-writing time.

The template is **fixed**: every heading below appears in every draft, in this order, whatever the diff. A section with nothing to say still appears, with the one-line declaration given for it under **Section tests**, so the reader learns the section was weighed rather than forgotten.

```markdown
<title: one line, imperative, no trailing period>

Closes #<issue>   <!-- only when the PR resolves a GitHub issue; one line per issue; drop the line otherwise -->

## Resumo

One or two sentences: what changes and why. The reviewer should know whether
this PR concerns them after reading this alone.
End with `Relacionado: #<issue>` or the ticket key for references the PR
does not close.

## Evidências

- **Antes:** <what a user saw or got before the change — a real screenshot, video, diagram, measurement or output>
- **Depois:** <the same view after the change, captured the same way>

## Alterações

- Grouped by area or concern, not one bullet per commit
- Each bullet says what changed and, where it isn't obvious, why
- Reference files with backticks

## QA

### Configurando o ambiente

Everything that must be true before the feature can be exercised at all:
env vars (name, and what value to put in them), migrations, seeds,
feature flags, external services, the command to start the app.
Commands in copyable blocks, in the order they must be run.

### Como testar

1. Numbered steps, each one an action the analyst takes
2. Each step ends on what appears on screen — the observable outcome

### Qualidade de código

- `<command>` — <result: passed, or the failure as it came out>
- One line per automated check that ran: lint, typecheck, tests, build

## Merge e deploy

### Risco do merge

**Reversão:** <mão dupla | mão única> — <one line: how to roll back, or what makes it irreversible>
**Impacto:** <baixo | médio | alto> — <one line: who or what feels the change>

### Antes e depois do deploy

- **Antes:** <what must be done in production before the merge lands>
- **Depois:** <what must be done in production after the merge lands>
```

## Section tests

Each section has a test for its content and a declaration for when it has none. The declaration is the whole section: one line, no heading dropped.

- **Evidências** — a before/after comparison at the level of the user and/or visual, whenever possible: what someone using the product, the API, the tool or the document actually sees or gets, before and after the change. Pick the evidence from the nature of the repository and of what this PR changes. Examples, **not an exhaustive list**: real screenshots; real videos or GIFs of the feature in use; architecture diagrams before and after; performance data or benchmarks; real CLI output or endpoint response as the user sees it; the rendered document or text excerpt before and after; real usage examples; logs or metrics from a running system. Use whatever shows the change best, including kinds not listed here. The *before* shows the real previous state, captured the same way as the *after* — a description of what was missing is not a *before*. Lint, typecheck and test-suite results are **not** evidence: they prove the code is sound, not what changed for the user, and they belong in **Qualidade de código**. The evidence comes from something you captured or ran, pasted as it came out; when the environment cannot capture the best kind (no screen for a screenshot, no browser for a video), use the best kind it can, and say which one you would add. Done when a reviewer could see what changed for the user from this section alone, without reading the diff. Declaration, for a change with nothing user-facing or visual to compare and no fitting non-visual evidence (benchmark, diagram): `Sem evidência de uso: <why — e.g. internal refactor with no observable change; the checks are in Qualidade de código>`.
- **Alterações** — exhaustive over the diff: every file in `--stat` maps to some bullet, or you consciously decided it is noise (lockfiles, generated output, formatting). Bullets describe behaviour, not mechanics — "adiciona rate limiting no login" beats "altera `AuthController.php`". This section is never empty: a PR has a diff.
- **Configurando o ambiente** — derive it from the diff, not from memory: a new key in `.env.example`, a new migration file, a changed seeder, a new service in `docker-compose`, a new dependency. Done when an analyst starting from a fresh `main` checkout could reach the feature using only this section. Declaration: `Nada a configurar: a mudança roda no ambiente que o time já tem.`
- **Como testar** — the reader is an **analista de qualidade**: they know the product, not the codebase. Name screens, buttons and menus the way the product names them; give real input values instead of "dados válidos"; cover the error and edge paths the diff introduces, not only the happy one. Write it whenever the diff changes anything a person can reach — a UI, an endpoint, a CLI, a job, an error path. Declaration, for a change reachable only by the test suite (refactors, build config, dependency bumps): `Sem teste manual: a mudança só é alcançável pela suíte; a prova está em Qualidade de código.`
- **Qualidade de código** — every automated check run against the head: lint, typecheck, tests, build, and any other verification the repository has. One line per check: the exact command and its result as it came out (passed, or the failure). List only what actually ran — never claim a check you did not run. Done when a reviewer knows which checks ran and how each ended. Declaration: `Sem verificação automatizada: <why — e.g. the repository has no lint, typecheck or test suite, or the environment could not run them>`.
- **Risco do merge** — always two lines, never a declaration. *Reversão* says whether the merge is a two-way door (revert the PR and production is back where it was) or a one-way door (a migration that drops data, a message published to a queue, an external side effect, a contract consumers already depend on). *Impacto* names who or what feels the change: layout shift, consumers of an API, mobile, a background job, a billing path. Done when both lines are filled from the diff and a reviewer knows what breaks if the PR is wrong.
- **Antes e depois do deploy** — migrations to run, env vars and secrets to register in the production environment, feature flags to flip, backfills, cache or queue restarts, deploy order against a dependent service. Each item sits under *Antes* or *Depois* of the merge landing in production. Declaration: `Nada a fazer: o merge é o deploy inteiro.`
