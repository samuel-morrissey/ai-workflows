#!/usr/bin/env python3
"""Compara as metricas das ultimas runs de um repositorio, por etapa.

Lista as ultimas N runs do repositorio, baixa o artifact `metrics` de cada uma
(o metrics.json da action .github/actions/metrics) e imprime, para cada
etapa, uma tabela com quantas runs entraram e a mediana e o p90 de cada grupo
de passos e de cada metrica numerica da sessao do agente.

    python3 scripts/metrics.py <owner/repo> [--runs N]

Regras:

- Uma celula so conta os valores medidos: `pulado`, `n/a` e `n/d` nao entram,
  e uma celula sem nenhum valor sai `n/d`.
- O p90 e pelo posto mais proximo (o valor na posicao ceil(0,9 * n) da lista
  ordenada): sempre um valor que alguma run teve. Com uma run so, mediana e
  p90 sao o proprio valor.
- Ficam de fora, com a contagem no fim da saida: runs sem artifact `metrics`
  (anteriores a feature, expirados, ou de workflows que nao sao etapas), com
  `schema_version` que este script nao conhece, ou com o metrics.json
  ilegivel.
- Cada run conta uma vez: num re-run, vale o artifact mais novo da run.
- Etapas na ordem fixa das 7 etapas (etapa desconhecida vem depois, em ordem
  alfabetica) e linhas sempre na mesma ordem: duas execucoes do script
  comparam linha a linha.

Fala com o GitHub so por `gh api` (autenticacao do proprio `gh`). Sem
nenhuma metrica, avisa e sai com 0; com o `gh` falhando, sai com 1.
"""

import argparse
import io
import json
import math
import re
import statistics
import subprocess
import sys
import zipfile

SCHEMA_VERSIONS = (1,)
DEFAULT_RUNS = 50
STAGES = ("issue-triage", "issue-refinement", "issue-break-down", "issue-remote-implement",
          "issue-sub-task", "pr-fix", "pr-merged")
GROUPS = ("preparo", "ambiente", "agente", "pos-agente")

# Linhas da sessao: (rotulo, caminho no objeto `agente`, formato).
SESSION = (
    ("sessão: duração", ("duracao_ms",), "ms"),
    ("sessão: tempo de API", ("duracao_api_ms",), "ms"),
    ("sessão: turnos", ("turnos",), "num"),
    ("sessão: tokens de entrada", ("tokens", "entrada"), "num"),
    ("sessão: tokens de saída", ("tokens", "saida"), "num"),
    ("sessão: leitura de cache", ("tokens", "cache_leitura"), "num"),
    ("sessão: criação de cache", ("tokens", "cache_criacao"), "num"),
    ("sessão: custo (informativo)", ("custo_usd",), "usd"),
)


class GhError(Exception):
    pass


def gh_api(route, binary=False):
    proc = subprocess.run(["gh", "api", route], capture_output=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout).decode(errors="replace").strip()
        raise GhError(f"gh api {route}: {err or f'saiu com {proc.returncode}'}")
    if binary:
        return proc.stdout
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        raise GhError(f"gh api {route}: resposta ilegivel ({exc})")


def latest_runs(repo, limit):
    """Os ids das ultimas `limit` runs, do mais novo ao mais velho, sem repetir."""
    per_page = min(limit, 100)
    ids, page = [], 1
    while len(ids) < limit:
        data = gh_api(f"repos/{repo}/actions/runs?per_page={per_page}&page={page}")
        runs = data.get("workflow_runs") or []
        for run in runs:
            if run["id"] not in ids and len(ids) < limit:
                ids.append(run["id"])
        if len(runs) < per_page:
            break
        page += 1
    return ids


def metrics_artifact(repo, run_id):
    """O artifact `metrics` mais novo e nao expirado da run, ou None."""
    data = gh_api(f"repos/{repo}/actions/runs/{run_id}/artifacts?name=metrics&per_page=100")
    alive = [a for a in data.get("artifacts") or [] if a.get("name") == "metrics" and not a.get("expired")]
    if not alive:
        return None
    return max(alive, key=lambda a: (a.get("created_at") or "", a["id"]))


def read_metrics(blob):
    """O metrics.json de dentro do zip do artifact."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = next(n for n in z.namelist() if n.rsplit("/", 1)[-1] == "metrics.json")
        data = json.loads(z.read(name))
    if not isinstance(data, dict):
        raise ValueError("nao e um objeto")
    return data


def collect(repo, limit):
    """Os metrics.json validos das ultimas runs e as contagens do que ficou de fora."""
    found, skipped = [], {"sem": 0, "schema": 0, "ilegivel": 0}
    seen = set()
    for run_id in latest_runs(repo, limit):
        artifact = metrics_artifact(repo, run_id)
        if artifact is None or artifact["id"] in seen:
            skipped["sem"] += artifact is None
            continue
        seen.add(artifact["id"])
        blob = gh_api(f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
        try:
            data = read_metrics(blob)
        except Exception:  # zip ou json ilegivel, sem metrics.json
            skipped["ilegivel"] += 1
            continue
        if data.get("schema_version") not in SCHEMA_VERSIONS:
            skipped["schema"] += 1
            continue
        if not isinstance(data.get("etapa"), str):
            skipped["ilegivel"] += 1
            continue
        found.append(data)
    return found, skipped


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def group_value(data, name):
    for g in data.get("grupos") or []:
        if isinstance(g, dict) and g.get("nome") == name and g.get("estado") == "medido":
            return number(g.get("segundos"))
    return None


def session_value(data, path):
    value = data.get("agente")
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return number(value)


def p90(values):
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def half_up(x):
    return int(math.floor(x + 0.5))


def duration(seconds):
    m, s = divmod(half_up(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt(value, kind):
    if value is None:
        return "n/d"
    if kind == "s":
        return duration(value)
    if kind == "ms":
        return duration(value / 1000)
    if kind == "usd":
        return f"US$ {value:.4f}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def stage_order(name):
    return (STAGES.index(name), "") if name in STAGES else (len(STAGES), name)


def table(runs):
    rows = [(g, lambda d, g=g: group_value(d, g), "s") for g in GROUPS]
    rows += [(label, lambda d, p=path: session_value(d, p), kind) for label, path, kind in SESSION]
    lines = ["| Linha | Valores | Mediana | p90 |", "|---|---|---|---|"]
    for label, get, kind in rows:
        values = [v for v in (get(d) for d in runs) if v is not None]
        med = statistics.median(values) if values else None
        top = p90(values) if values else None
        lines.append(f"| {label} | {len(values)} | {fmt(med, kind)} | {fmt(top, kind)} |")
    return lines


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def report(repo, limit, found, skipped):
    lines = [f"Métricas das últimas {limit} runs de {repo}: "
             f"{plural(len(found), 'run com métricas', 'runs com métricas')}."]
    if not found:
        lines = [f"Nenhuma run com métricas nas últimas {limit} runs de {repo}."]
    by_stage = {}
    for data in found:
        by_stage.setdefault(data["etapa"], []).append(data)
    for stage in sorted(by_stage, key=stage_order):
        runs = by_stage[stage]
        lines += ["", f"### {stage}: {plural(len(runs), 'run', 'runs')}", ""] + table(runs)
    out = []
    if skipped["sem"]:
        out.append(f"- {plural(skipped['sem'], 'run', 'runs')} sem artifact `metrics` "
                   "(anterior à feature, expirado ou de workflow que não é etapa).")
    if skipped["schema"]:
        out.append(f"- {plural(skipped['schema'], 'run', 'runs')} com `schema_version` desconhecido "
                   f"(este script lê: {', '.join(map(str, SCHEMA_VERSIONS))}).")
    if skipped["ilegivel"]:
        out.append(f"- {plural(skipped['ilegivel'], 'run', 'runs')} com `metrics.json` ilegível.")
    if out:
        lines += ["", "Fora da conta:"] + out
    return "\n".join(lines) + "\n"


def positive(text):
    if not text.isdigit() or int(text) < 1:
        raise argparse.ArgumentTypeError("precisa ser um inteiro maior que zero")
    return int(text)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Mediana e p90 das métricas das últimas runs de um repositório, por etapa.")
    parser.add_argument("repo", help="o repositório, como owner/repo")
    parser.add_argument("-n", "--runs", type=positive, default=DEFAULT_RUNS,
                        help=f"quantas runs recentes considerar (padrão: {DEFAULT_RUNS})")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        parser.error(f"repositório inválido: {args.repo!r} (use owner/repo)")
    try:
        found, skipped = collect(args.repo, args.runs)
    except GhError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(report(args.repo, args.runs, found, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
