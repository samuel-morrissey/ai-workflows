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

O objeto `agente` traz os totais da sessao do agente, lidos do
`execution_file` da claude-code-action (EXECUTION_FILE): duracao, tempo de
API, turnos, motivo do fim, tokens, chamadas por ferramenta da sessao
principal e custo, mais o `--max-turns` da etapa (MAX_TURNS). Todo campo
existe sempre, com valor ou com o estado (`n/d`, `pulado`, `n/a`).

Nunca falha a run: qualquer erro de leitura vira aviso e `n/d`.

Ambiente: GH_REPO, ETAPA, NUMBER, METRICS_DIR, EXECUTION_FILE, MAX_TURNS,
GITHUB_RUN_ID, GITHUB_RUN_ATTEMPT, RUNNER_NAME e GITHUB_STEP_SUMMARY.
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
    if data["agente"] is not None:
        lines += session_summary(data["agente"])
    for w in data["avisos"]:
        lines += ["", f"> [!WARNING]\n> {w}"]
    return "\n".join(lines) + "\n"


TOKENS = (("entrada", "input_tokens"), ("saida", "output_tokens"),
          ("cache_leitura", "cache_read_input_tokens"), ("cache_criacao", "cache_creation_input_tokens"))


def agent_blank(state, max_turns=None):
    """O objeto `agente` com todo campo presente e no estado dado."""
    return {
        "estado": state, "duracao_ms": state, "duracao_api_ms": state, "turnos": state,
        "max_turns": max_turns if max_turns is not None else state, "fim": state,
        "tokens": {k: state for k, _ in TOKENS}, "ferramentas": state, "custo_usd": state,
    }


def read_messages(path):
    """As mensagens do execution_file: lista JSON (o que a action grava) ou JSONL."""
    text = pathlib.Path(path).read_text()
    try:
        data = json.loads(text)
    except ValueError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not isinstance(data, list) or not data or not all(isinstance(m, dict) for m in data):
        raise ValueError("nao e uma lista de mensagens")
    return data


def number_or_nd(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/d"


def session(stage, groups, env):
    """Totais da sessao do agente, lidos do execution_file da claude-code-action.

    Segue o grupo `agente`: `n/a` na etapa sem agente, `pulado` quando o passo
    nao rodou. Fora isso le o arquivo: `medido` com o evento `result`,
    `parcial` sem ele (so a contagem de ferramentas), `n/d` se o arquivo falta
    ou e ilegivel. Devolve o objeto e o aviso, se houver.
    """
    raw = (env.get("MAX_TURNS") or "").strip()
    max_turns = int(raw) if raw.isdigit() else None
    state = next(g["estado"] for g in groups if g["nome"] == "agente")
    if state in ("n/a", "pulado"):
        return agent_blank(state, max_turns), None
    path = (env.get("EXECUTION_FILE") or "").strip()
    try:
        if not path:
            raise ValueError("a action nao devolveu o caminho")
        messages = read_messages(path)
    except Exception as exc:  # ausente, vazio, truncado, ilegivel
        return agent_blank("n/d", max_turns), (
            f"Nao consegui ler o execution_file da sessao ({exc}); os campos da sessao saem `n/d`.")
    data = agent_blank("n/d", max_turns)
    tools = {}
    for m in messages:
        if m.get("type") != "assistant" or m.get("parent_tool_use_id"):
            continue  # so a sessao principal: subagente tem parent_tool_use_id
        content = (m.get("message") or {}).get("content")
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name"):
                tools[item["name"]] = tools.get(item["name"], 0) + 1
    data["ferramentas"] = dict(sorted(tools.items()))
    result = next((m for m in reversed(messages) if m.get("type") == "result"), None)
    if result is None:
        data["estado"] = "parcial"
        return data, ("A sessao terminou sem o evento `result` (estouro ou falha da action); "
                      "so a contagem de ferramentas foi publicada.")
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    data.update(
        estado="medido",
        duracao_ms=number_or_nd(result.get("duration_ms")),
        duracao_api_ms=number_or_nd(result.get("duration_api_ms")),
        turnos=number_or_nd(result.get("num_turns")),
        fim=result.get("subtype") if isinstance(result.get("subtype"), str) else "n/d",
        tokens={k: number_or_nd(usage.get(src)) for k, src in TOKENS},
        custo_usd=number_or_nd(result.get("total_cost_usd")),
    )
    return data, None


def session_summary(agente):
    def ms(v):
        return fmt(v / 1000) if isinstance(v, (int, float)) else v

    fim = agente["fim"]
    custo = agente["custo_usd"]
    t = agente["tokens"]
    rows = [("duração", ms(agente["duracao_ms"])), ("tempo de API", ms(agente["duracao_api_ms"])),
            ("turnos", agente["turnos"]), ("`--max-turns`", agente["max_turns"]),
            ("fim", fim if fim in ("n/d", "n/a", "pulado") else f"`{fim}`"),
            ("tokens de entrada", t["entrada"]), ("tokens de saída", t["saida"]),
            ("leitura de cache", t["cache_leitura"]), ("criação de cache", t["cache_criacao"]),
            ("custo (informativo)", f"US$ {custo:.4f}" if isinstance(custo, (int, float)) else custo)]
    lines = ["", "#### Sessão do agente", "", "| Campo | Valor |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    tools = agente["ferramentas"]
    if isinstance(tools, dict):
        listed = " · ".join(f"`{k}` {v}" for k, v in tools.items()) or "nenhuma"
    else:
        listed = tools
    lines += ["", f"Ferramentas da sessão principal (sem subagentes): {listed}",
              "", "O custo é informativo: com token OAuth ele não reflete cobrança."]
    return lines


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
    measure_jobs(data, stage, run_id, attempt, env)
    data["agente"], warning = session(stage, data["grupos"], env)
    if warning:
        data["avisos"].append(warning)
    return data


def measure_jobs(data, stage, run_id, attempt, env):
    """Preenche `job`, `grupos` e `avisos` pela API de jobs da run."""
    route = f"repos/{env.get('GH_REPO', '')}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100"
    try:
        proc = subprocess.run(["gh", "api", route], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout).strip() or f"gh saiu com {proc.returncode}")
        jobs = json.loads(proc.stdout)["jobs"]
    except Exception as exc:  # API fora do ar, resposta ilegivel, gh ausente
        data["avisos"].append(f"Nao consegui ler os passos pela API de jobs ({exc}); os grupos saem `n/d`.")
        return
    job = pick_job(jobs, env.get("RUNNER_NAME", ""), STAGES[stage]["job"])
    if job is None:
        data["avisos"].append("Nenhum job da run casa com este runner nem com o nome da etapa; os grupos saem `n/d`.")
        return
    groups, total, conclusion, warnings = measure(stage, job)
    data["job"] = {"nome": job.get("name"), "conclusao": conclusion, "segundos": total}
    data["grupos"] = groups
    data["avisos"] += warnings


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
