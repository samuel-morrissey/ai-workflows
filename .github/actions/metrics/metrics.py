#!/usr/bin/env python3
"""Metricas de tempo de uma rodada, por grupo fixo de passos.

Le os passos do job deste runner pela API de jobs da run (como a
round-failure), soma as duracoes (`started_at`/`completed_at`) de cada passo
no grupo que o mapeamento da etapa declara e publica o resultado em dois
lugares: uma tabela no $GITHUB_STEP_SUMMARY e o $METRICS_DIR/metrics.json, que
a action sobe como artifact `metrics`.

Os grupos sao sempre os mesmos, na mesma ordem, para duas runs da mesma etapa
ficarem lado a lado. Cada um sai como duracao em segundos ou num estado:

- `pulado`: o grupo existe na etapa, mas nenhum passo dele rodou;
- `n/a`: o grupo nao existe na etapa (ex.: `ambiente` na triagem);
- `n/d`: a API de jobs nao respondeu, ou nao achei o job.

Nunca falha a run: qualquer erro de leitura vira aviso e `n/d`.

Ambiente: GH_REPO, ETAPA, NUMBER, METRICS_DIR, GITHUB_RUN_ID,
GITHUB_RUN_ATTEMPT, RUNNER_NAME e GITHUB_STEP_SUMMARY.
"""

import datetime
import json
import os
import pathlib
import subprocess
import sys

SCHEMA_VERSION = 1
GROUPS = ("preparo", "ambiente", "agente", "pos-agente")

# O nome deste passo nos workflows: a leitura para nele. Ele e o
# round-failure rodam depois da leitura e nao entram na soma.
METRICS_STEP = "Registrar metricas da rodada"
IGNORED = (METRICS_STEP, "Comentar falha da rodada")

# Passos que o proprio Actions poe no job, fora do YAML.
IMPLICIT = {"Set up job": "preparo"}

# Passo `uses:` sem `name:` aparece na API como "Run <uses>".
CHECKOUT = "Run actions/checkout@v7"
AGENT = "Run anthropics/claude-code-action@v1"
WIP = "Aplicar work-in-progress"
UNWIP = "Remover work-in-progress"
RESP = "Resolver responsavel"
ENV = "Preparar ambiente do agente"
EVIDENCE = "Publicar evidencias"

# Mapeamento passo -> grupo, por etapa. Todo passo do job da etapa entra aqui
# (ou em IGNORED): passo novo ou renomeado num workflow sem entrada aqui faz
# o teste falhar. `job` e o nome do job, usado quando nenhum job casa com o
# runner deste passo.
STAGES = {
    "issue-triage": {"job": "Triage Issue", "steps": {
        CHECKOUT: "preparo", "Resolver numero do issue": "preparo", WIP: "preparo", RESP: "preparo",
        AGENT: "agente",
        "Remover needs-triage se a triagem concluiu": "pos-agente", UNWIP: "pos-agente"}},
    "issue-refinement": {"job": "Refine Issue", "steps": {
        CHECKOUT: "preparo", "Resolver numero do issue": "preparo", WIP: "preparo", RESP: "preparo",
        AGENT: "agente",
        "Garantir awaiting-reply se a rodada parou em pergunta": "pos-agente", UNWIP: "pos-agente"}},
    "issue-break-down": {"job": "Break Down Issue", "steps": {
        CHECKOUT: "preparo", "Resolver numero do issue": "preparo", WIP: "preparo", RESP: "preparo",
        AGENT: "agente",
        "Garantir awaiting-reply se a rodada parou em pergunta": "pos-agente", UNWIP: "pos-agente"}},
    "issue-remote-implement": {"job": "Implement Issue", "steps": {
        CHECKOUT: "preparo", "Resolver alvo": "preparo", WIP: "preparo", RESP: "preparo",
        "Baixar o planner": "preparo",
        ENV: "ambiente",
        AGENT: "agente",
        EVIDENCE: "pos-agente", "Garantir awaiting-pr-review se ha PR aberto": "pos-agente",
        UNWIP: "pos-agente", "Entrar na cadeia": "pos-agente", "Planejar e empilhar": "pos-agente",
        "Resolver responsavel do pai": "pos-agente", "Decidir e agir": "pos-agente"}},
    "issue-sub-task": {"job": "Implement Sub-task", "steps": {
        CHECKOUT: "preparo", "Baixar o planner": "preparo", "Resolver alvo": "preparo", WIP: "preparo",
        RESP: "preparo",
        ENV: "ambiente",
        AGENT: "agente",
        EVIDENCE: "pos-agente", "Devolver o controle ao pai": "pos-agente"}},
    "pr-fix": {"job": "Fix PR", "steps": {
        "Resolver alvo": "preparo", WIP: "preparo", CHECKOUT: "preparo",
        ENV: "ambiente",
        AGENT: "agente",
        EVIDENCE: "pos-agente", UNWIP: "pos-agente"}},
    "pr-merged": {"job": "Close Issues From Merged PR", "steps": {
        "Fechar os issues do Closes": "pos-agente"}},
}


def stage_groups(stage):
    """Grupos que existem na etapa: os do mapeamento mais o `preparo` do Set up job."""
    return set(STAGES[stage]["steps"].values()) | set(IMPLICIT.values())


def parse_time(value):
    if not value:
        return None
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def seconds(start, end):
    a, b = parse_time(start), parse_time(end)
    if a is None or b is None:
        return None
    return max(0, round((b - a).total_seconds()))


def pick_job(jobs, runner, job_name):
    """O job deste runner; sem ele, o da etapa pelo nome. Nunca o check-caller."""
    mine = [j for j in jobs if runner and j.get("runner_name") == runner]
    if mine:
        return mine[0]
    for j in jobs:
        name = j.get("name") or ""
        if name == job_name or name.endswith(" / " + job_name):
            return j
    return None


def group_of(stage, name, after_agent):
    steps = STAGES[stage]["steps"]
    if name in steps:
        return steps[name], True
    if name in IMPLICIT:
        return IMPLICIT[name], True
    # Sem entrada: o teste acusa; na run, o passo cai pela posicao.
    return ("pos-agente" if after_agent else "preparo"), name.startswith("Post ")


def measure(stage, job):
    """Grupos e totais do job, ate o passo de metricas (exclusive)."""
    present = stage_groups(stage)
    totals, ran, warnings = {g: 0 for g in GROUPS}, set(), []
    failed = cancelled = False
    after_agent = False
    end = None
    for step in sorted(job.get("steps") or [], key=lambda s: s.get("number", 0)):
        name = step.get("name") or ""
        if name == METRICS_STEP:
            end = step.get("started_at")
            break
        if name in IGNORED:
            continue
        group, known = group_of(stage, name, after_agent)
        if not known:
            warnings.append(f"Passo sem grupo no mapeamento de {stage}: `{name}` (somado em `{group}`).")
        if group == "agente":
            after_agent = True
        conclusion = step.get("conclusion")
        if conclusion == "failure":
            failed = True
        elif conclusion == "cancelled":
            cancelled = True
        if conclusion in (None, "skipped"):
            continue
        dur = seconds(step.get("started_at"), step.get("completed_at"))
        if dur is None:
            continue
        totals[group] += dur
        ran.add(group)
    groups = []
    for g in GROUPS:
        if g not in present:
            groups.append({"nome": g, "estado": "n/a", "segundos": None})
        elif g in ran:
            groups.append({"nome": g, "estado": "medido", "segundos": totals[g]})
        else:
            groups.append({"nome": g, "estado": "pulado", "segundos": None})
    if end is None:
        end = datetime.datetime.now(datetime.timezone.utc).isoformat()
    total = seconds(job.get("started_at"), end)
    conclusion = "failure" if failed else "cancelled" if cancelled else "success"
    return groups, total, conclusion, warnings


def unavailable(stage):
    present = stage_groups(stage)
    return [{"nome": g, "estado": "n/d" if g in present else "n/a", "segundos": None} for g in GROUPS]


def fmt(seconds_):
    m, s = divmod(int(seconds_), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def summary(data):
    num = f" (#{data['numero']})" if data["numero"] else ""
    lines = [f"### Metricas da rodada: {data['etapa']}{num}", "", "| Grupo | Duracao |", "|---|---|"]
    for g in data["grupos"]:
        cell = fmt(g["segundos"]) if g["estado"] == "medido" else g["estado"]
        lines.append(f"| {g['nome']} | {cell} |")
    total = data["job"]["segundos"]
    lines.append(f"| **total do job** | {fmt(total) if total is not None else 'n/d'} |")
    lines += ["", f"Conclusao do job ate aqui: `{data['job']['conclusao']}` · "
              f"run {data['run']['id']}, attempt {data['run']['attempt']}"]
    for w in data["avisos"]:
        lines += ["", f"> [!WARNING]\n> {w}"]
    return "\n".join(lines) + "\n"


def collect(env):
    stage = env.get("ETAPA", "")
    if stage not in STAGES:
        raise SystemExit(f"etapa desconhecida: {stage!r} (conhecidas: {', '.join(STAGES)})")
    run_id, attempt = env.get("GITHUB_RUN_ID", ""), env.get("GITHUB_RUN_ATTEMPT", "1")
    number = env.get("NUMBER", "")
    data = {
        "schema_version": SCHEMA_VERSION,
        "etapa": stage,
        "numero": int(number) if number.isdigit() else None,
        "run": {"id": int(run_id) if run_id.isdigit() else run_id,
                "attempt": int(attempt) if attempt.isdigit() else attempt},
        "job": {"nome": None, "conclusao": "n/d", "segundos": None},
        "grupos": unavailable(stage),
        "agente": None,
        "avisos": [],
    }
    route = f"repos/{env.get('GH_REPO', '')}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
    try:
        proc = subprocess.run(["gh", "api", route], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip() or f"gh saiu com {proc.returncode}")
        jobs = json.loads(proc.stdout)["jobs"]
    except Exception as exc:  # API fora do ar, resposta ilegivel, gh ausente
        data["avisos"].append(f"Nao consegui ler os passos pela API de jobs ({exc}); os grupos saem `n/d`.")
        return data
    job = pick_job(jobs, env.get("RUNNER_NAME", ""), STAGES[stage]["job"])
    if job is None:
        data["avisos"].append("Nenhum job da run casa com este runner nem com o nome da etapa; os grupos saem `n/d`.")
        return data
    groups, total, conclusion, warnings = measure(stage, job)
    data["job"] = {"nome": job.get("name"), "conclusao": conclusion, "segundos": total}
    data["grupos"] = groups
    data["avisos"] += warnings
    return data


def main():
    env = os.environ
    data = collect(env)
    out = pathlib.Path(env.get("METRICS_DIR") or ".")
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    text = summary(data)
    if env.get("GITHUB_STEP_SUMMARY"):
        with open(env["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(text)
    for w in data["avisos"]:
        print(f"::warning::{w}")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
