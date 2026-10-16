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

- **Antes:** <screenshot, output or the failing test run>
- **Depois:** <screenshot, output or the passing test run>

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

- **Evidências** — proof the change works, as a before/after pair. Screenshots when the change is visual and the environment can take them; otherwise execution output: the exact test that failed and now passes, the command and its result, the response of the endpoint. The evidence comes from a run you made, pasted as it came out. Done when a reviewer could tell from this section alone that the change was exercised, not just written. Declaration: `Sem evidência executável: <why — e.g. a change the test suite cannot reach, with the manual check in Como testar>`.
- **Alterações** — exhaustive over the diff: every file in `--stat` maps to some bullet, or you consciously decided it is noise (lockfiles, generated output, formatting). Bullets describe behaviour, not mechanics — "adiciona rate limiting no login" beats "altera `AuthController.php`". This section is never empty: a PR has a diff.
- **Configurando o ambiente** — derive it from the diff, not from memory: a new key in `.env.example`, a new migration file, a changed seeder, a new service in `docker-compose`, a new dependency. Done when an analyst starting from a fresh `main` checkout could reach the feature using only this section. Declaration: `Nada a configurar: a mudança roda no ambiente que o time já tem.`
- **Como testar** — the reader is an **analista de qualidade**: they know the product, not the codebase. Name screens, buttons and menus the way the product names them; give real input values instead of "dados válidos"; cover the error and edge paths the diff introduces, not only the happy one. Write it whenever the diff changes anything a person can reach — a UI, an endpoint, a CLI, a job, an error path. Declaration, for a change reachable only by the test suite (refactors, build config, dependency bumps): `Sem teste manual: a mudança só é alcançável pela suíte; a prova está em Evidências.`
- **Risco do merge** — always two lines, never a declaration. *Reversão* says whether the merge is a two-way door (revert the PR and production is back where it was) or a one-way door (a migration that drops data, a message published to a queue, an external side effect, a contract consumers already depend on). *Impacto* names who or what feels the change: layout shift, consumers of an API, mobile, a background job, a billing path. Done when both lines are filled from the diff and a reviewer knows what breaks if the PR is wrong.
- **Antes e depois do deploy** — migrations to run, env vars and secrets to register in the production environment, feature flags to flip, backfills, cache or queue restarts, deploy order against a dependent service. Each item sits under *Antes* or *Depois* of the merge landing in production. Declaration: `Nada a fazer: o merge é o deploy inteiro.`
