#!/usr/bin/env python3
"""Leitura e acoes deterministicas sobre as sub-tasks de um pai.

Usado por dois workflows reutilizaveis deste repositorio:

- issue-remote-implement.yml, o planner do pai: `plan`, `stack`, `finish`
  e `status`;
- issue-sub-task.yml, o worker de uma sub-task: `base`.

Fala com o GitHub so por `gh api` (token do workflow em GH_TOKEN, repositorio
em GH_REPO como `owner/repo`). Nao roda agente: tudo aqui e regra fixa.

Conceitos (a `issue-git-flow` e a `issue-labeling` em skills/ sao a
referencia):

- A branch de uma sub-task chama `sub-task-<numero>`; e por ela que o PR da
  sub-task e encontrado.
- A ordem das camadas e a ordem em que os PRs foram abertos. As sub-tasks
  ainda sem PR entram depois, em ordem topologica dos bloqueios (blocked_by),
  com desempate pela ordem das sub-issues no pai.
- "Proxima" e a primeira sub-task sem PR que esta aberta, nao e humana
  (brief com `**Executor:** humano`), nao esta com work-in-progress nem
  awaiting-reply, e cujos bloqueadores ja tem PR ou estao fechados.
- A base da proxima e a branch do PR aberto mais alto; sem PR aberto, a
  branch padrao.

Subcomandos:

  plan <pai>                      JSON com ordem, proxima, espera e stack
  stack <pai>                     empilha os PRs abertos ainda fora do stack
  finish <pai>                    poe `Closes #<pai>` no PR do topo e vincula
  status <pai> --chain <estado> [--note <texto>]
                                  cria ou atualiza o comentario de status do pai
  base <sub>                      JSON com pai, base da branch e bloqueios

Saida de `plan`:

  {
    "parent": 181, "default_branch": "main",
    "rows": [{"number", "title", "state", "human", "wip", "awaiting",
              "pr": {"number", "state", "merged", "head", "base", "stack",
                     "html_url"} | null,
              "layer": 1 | null, "blocked_open": [..]}],
    "next": 187 | null,
    "wait": {"kind": "none|handoff|running|human|blocked", "note": "..."},
    "complete": true | false,
    "base": "sub-task-186",
    "stack": 8 | null
  }
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("GH_REPO") or ""
OWNER = REPO.split("/", 1)[0]
MARKER = "<!-- ai:sub-tasks-status -->"
HUMAN_RE = re.compile(r"\*\*Executor:\*\*\s*humano", re.IGNORECASE)
PARENT_RE = re.compile(r"Parte de #(\d+)")


class ApiError(Exception):
    pass


def api(path, method=None, body=None, ok404=False):
    cmd = ["gh", "api", path]
    if method:
        cmd += ["--method", method]
    stdin = None
    if body is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(body)
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        if ok404 and "HTTP 404" in err:
            return None
        raise ApiError(f"gh api {method or 'GET'} {path}: {err}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def graphql(query):
    result = subprocess.run(
        ["gh", "api", "graphql", "-f", f"query={query}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ApiError(f"gh api graphql: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout)


def labels_of(issue):
    return [label["name"] for label in issue.get("labels", [])]


def pr_of(sub):
    """PR da sub-task pela branch sub-task-<n>: o aberto, senao o mergeado.

    PR fechado sem merge e sobra de rodada rejeitada: conta como "sem PR".
    """
    prs = api(f"repos/{REPO}/pulls?head={OWNER}:sub-task-{sub}&state=all&per_page=20") or []
    chosen = next((p for p in prs if p["state"] == "open"), None) \
        or next((p for p in prs if p.get("merged_at")), None)
    if not chosen:
        return None
    full = api(f"repos/{REPO}/pulls/{chosen['number']}")
    stack = full.get("stack") or {}
    return {
        "number": full["number"],
        "state": full["state"],
        "merged": bool(full.get("merged_at")),
        "head": full["head"]["ref"],
        "base": full["base"]["ref"],
        "stack": stack.get("number"),
        "html_url": full["html_url"],
        "node_id": full["node_id"],
        "body": full.get("body") or "",
    }


def load(parent):
    default = api(f"repos/{REPO}")["default_branch"]
    subs = api(f"repos/{REPO}/issues/{parent}/sub_issues?per_page=100") or []
    rows = []
    for sub in subs:
        number = sub["number"]
        labels = labels_of(sub)
        blocked = api(f"repos/{REPO}/issues/{number}/dependencies/blocked_by?per_page=100") or []
        rows.append({
            "number": number,
            "title": sub["title"],
            "state": sub["state"],
            "human": bool(HUMAN_RE.search(sub.get("body") or "")),
            "wip": "work-in-progress" in labels,
            "awaiting": "awaiting-reply" in labels,
            "pr": pr_of(number),
            "blocked_by": [b["number"] for b in blocked],
        })
    return parent, default, rows


def analyze(parent, default, rows):
    by = {row["number"]: row for row in rows}
    with_pr = sorted((r for r in rows if r["pr"]), key=lambda r: r["pr"]["number"])
    stacked = [r["number"] for r in with_pr]
    done = set(stacked) | {r["number"] for r in rows if r["state"] == "closed"}
    external = {}

    def satisfied(blocker):
        if blocker in by:
            return blocker in done
        if blocker not in external:
            issue = api(f"repos/{REPO}/issues/{blocker}", ok404=True)
            external[blocker] = issue is None or issue["state"] == "closed"
        return external[blocker]

    # Ordem topologica das que ainda nao tem PR, desempate pela ordem das
    # sub-issues. Ciclo (nao deveria existir) cai no desempate.
    rest = [r["number"] for r in rows if r["state"] == "open" and not r["pr"]]
    planned = []
    while rest:
        ready = [n for n in rest
                 if all(b in planned or satisfied(b) for b in by[n]["blocked_by"])]
        pick = ready[0] if ready else rest[0]
        planned.append(pick)
        rest.remove(pick)

    layer = 0
    out_rows = []
    for number in stacked + planned:
        row = by[number]
        if row["pr"]:
            layer += 1
        out_rows.append({
            "number": number,
            "title": row["title"],
            "state": row["state"],
            "human": row["human"],
            "wip": row["wip"],
            "awaiting": row["awaiting"],
            "pr": row["pr"],
            "layer": layer if row["pr"] else None,
            "blocked_open": [b for b in row["blocked_by"] if not satisfied(b)],
        })
    # Sub-tasks fechadas sem PR (wontfix, deferred) aparecem no fim, so para
    # leitura.
    for row in rows:
        if row["state"] == "closed" and not row["pr"]:
            out_rows.append({**{k: row[k] for k in ("number", "title", "state", "human", "wip", "awaiting", "pr")},
                             "layer": None, "blocked_open": []})

    # A proxima e a primeira da fila que pode rodar agora. Uma sub-task em
    # execucao ou parada em pergunta trava a fila inteira (modo serial); uma
    # humana ou bloqueada e pulada, e o motivo registrado e o da primeira
    # pulada, que e a raiz da espera.
    nxt = None
    wait = None
    for number in planned:
        row = by[number]
        blocked_open = [b for b in row["blocked_by"] if not satisfied(b)]
        if row["wip"]:
            wait = wait or {"kind": "running", "note": f"#{number} esta em execucao."}
            break
        if row["awaiting"]:
            wait = wait or {"kind": "handoff", "note": f"#{number} parou numa pergunta; responda la para a cadeia seguir."}
            break
        if row["human"]:
            wait = wait or {"kind": "human", "note": f"#{number} e humana: faca a parte dela e aplique `go` aqui para a cadeia seguir."}
            continue
        if blocked_open:
            quem = ", ".join(f"#{b}" for b in blocked_open)
            wait = wait or {"kind": "blocked", "note": f"#{number} esta bloqueada por {quem}, sem PR e ainda aberto."}
            continue
        nxt = number
        wait = {"kind": "none", "note": ""}
        break
    wait = wait or {"kind": "none", "note": ""}

    open_prs = [by[n]["pr"] for n in stacked if by[n]["pr"]["state"] == "open"]
    return {
        "parent": parent,
        "default_branch": default,
        "rows": out_rows,
        "next": nxt,
        "wait": wait,
        "complete": not planned,
        "base": open_prs[-1]["head"] if open_prs else default,
        "stack": next((p["stack"] for p in open_prs if p["stack"]), None),
        "_stacked": stacked,
        "_open_prs": open_prs,
    }


def public(plan):
    out = {k: v for k, v in plan.items() if not k.startswith("_")}
    out["rows"] = [{**row, "pr": row["pr"] and {k: v for k, v in row["pr"].items() if k not in ("body", "node_id")}}
                   for row in out["rows"]]
    return out


def cmd_plan(args):
    plan = analyze(*load(args.parent))
    print(json.dumps(public(plan), ensure_ascii=False))


def cmd_stack(args):
    plan = analyze(*load(args.parent))
    open_prs = plan["_open_prs"]
    # Cada PR aberto precisa ter como base a head do anterior (ou a branch
    # padrao, no primeiro aberto): e o que o GitHub exige para empilhar.
    prev = plan["default_branch"]
    for pr in open_prs:
        if pr["base"] != prev:
            raise ApiError(
                f"PR #{pr['number']} tem base `{pr['base']}`, mas a camada de baixo e `{prev}`: "
                "a cadeia de bases quebrou e o stack nao pode ser montado.")
        prev = pr["head"]
    unstacked = [pr["number"] for pr in open_prs if not pr["stack"]]
    if not unstacked:
        print(json.dumps({"stack": plan["stack"], "added": []}))
        return
    if plan["stack"]:
        api(f"repos/{REPO}/stacks/{plan['stack']}/add", "POST", {"pull_requests": unstacked})
        print(json.dumps({"stack": plan["stack"], "added": unstacked}))
        return
    if len(open_prs) < 2:
        # Stack exige dois PRs; com um so, ainda nao ha o que empilhar.
        print(json.dumps({"stack": None, "added": []}))
        return
    created = api(f"repos/{REPO}/stacks", "POST", {"pull_requests": [pr["number"] for pr in open_prs]})
    print(json.dumps({"stack": created["number"], "added": [pr["number"] for pr in open_prs]}))


def cmd_finish(args):
    plan = analyze(*load(args.parent))
    open_prs = plan["_open_prs"]
    if not open_prs:
        print(json.dumps({"top": None}))
        return
    top = open_prs[-1]
    line = f"Closes #{args.parent}"
    if not re.search(rf"^\s*{re.escape(line)}\s*$", top["body"], re.MULTILINE):
        api(f"repos/{REPO}/pulls/{top['number']}", "PATCH", {"body": f"{line}\n{top['body']}"})
    # Vinculo nativo (aparece em Development do pai). O `Closes` no corpo ja
    # fecha o pai quando o topo entra na branch padrao; o vinculo e so
    # visibilidade, por isso a falha aqui vira aviso.
    pai = api(f"repos/{REPO}/issues/{args.parent}")
    linked = True
    try:
        graphql(
            "mutation { addCloseIssueReferences(input: {issueId: \"%s\", pullRequestIds: [\"%s\"]}) { clientMutationId } }"
            % (pai["node_id"], top["node_id"]))
    except ApiError as err:
        linked = False
        print(f"::warning::vinculo nativo do PR #{top['number']} com #{args.parent} falhou: {err}", file=sys.stderr)
    print(json.dumps({"top": top["number"], "html_url": top["html_url"], "linked": linked}))


def render_status(plan, chain, note):
    lines = [MARKER, "## Sub-tasks", "", "| Camada | Sub-task | PR | Estado |", "|---|---|---|---|"]
    for row in plan["rows"]:
        pr = row["pr"]
        if pr and pr["merged"]:
            estado = "mergeado"
        elif pr:
            estado = "em revisao"
        elif row["state"] == "closed":
            estado = "fechada sem PR"
        elif row["wip"]:
            estado = "em execucao"
        elif row["awaiting"]:
            estado = "aguardando resposta"
        elif row["human"]:
            estado = "humana"
        elif row["blocked_open"]:
            estado = "bloqueada por " + ", ".join(f"#{b}" for b in row["blocked_open"])
        elif row["number"] == plan["next"]:
            estado = "proxima"
        else:
            estado = "na fila"
        camada = str(row["layer"]) if row["layer"] else "—"
        pr_cell = f"#{pr['number']}" if pr else "—"
        lines.append(f"| {camada} | #{row['number']} {row['title']} | {pr_cell} | {estado} |")
    lines.append("")
    stack = f"#{plan['stack']}" if plan["stack"] else "ainda nao montada (precisa de dois PRs abertos)"
    lines.append(f"**Stack:** {stack}")
    lines.append(f"**Cadeia:** {chain}")
    if note:
        lines.append(f"**Nota:** {note}")
    return "\n".join(lines)


def cmd_status(args):
    plan = analyze(*load(args.parent))
    body = render_status(plan, args.chain, args.note or "")
    comments = api(f"repos/{REPO}/issues/{args.parent}/comments?per_page=100") or []
    existing = next((c for c in comments if MARKER in (c.get("body") or "")), None)
    if existing:
        api(f"repos/{REPO}/issues/comments/{existing['id']}", "PATCH", {"body": body})
        print(json.dumps({"comment": existing["html_url"], "updated": True}))
    else:
        created = api(f"repos/{REPO}/issues/{args.parent}/comments", "POST", {"body": body})
        print(json.dumps({"comment": created["html_url"], "updated": False}))


def cmd_base(args):
    sub = api(f"repos/{REPO}/issues/{args.sub}")
    parent_issue = api(f"repos/{REPO}/issues/{args.sub}/parent", ok404=True)
    parent = parent_issue["number"] if parent_issue else None
    if not parent:
        match = PARENT_RE.search(sub.get("body") or "")
        parent = int(match.group(1)) if match else None
    own_pr = pr_of(args.sub)
    out = {
        "sub": args.sub,
        "parent": parent,
        "is_sub_task": sub["title"].startswith("[SUB-TASK]"),
        "state": sub["state"],
        "human": bool(HUMAN_RE.search(sub.get("body") or "")),
        "open_pr": own_pr["number"] if own_pr and own_pr["state"] == "open" else None,
        "merged_pr": own_pr["number"] if own_pr and own_pr["merged"] else None,
        "base": None,
        "blocked_open": [],
    }
    if parent:
        plan = analyze(*load(parent))
        out["base"] = plan["base"]
        row = next((r for r in plan["rows"] if r["number"] == args.sub), None)
        out["blocked_open"] = row["blocked_open"] if row else []
    else:
        out["base"] = api(f"repos/{REPO}")["default_branch"]
    print(json.dumps(out, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "stack", "finish"):
        p = subs.add_parser(name)
        p.add_argument("parent", type=int)
    p = subs.add_parser("status")
    p.add_argument("parent", type=int)
    p.add_argument("--chain", required=True)
    p.add_argument("--note", default="")
    p = subs.add_parser("base")
    p.add_argument("sub", type=int)
    args = parser.parse_args()
    if not REPO:
        sys.exit("GH_REPO (owner/repo) e obrigatorio.")
    try:
        {"plan": cmd_plan, "stack": cmd_stack, "finish": cmd_finish,
         "status": cmd_status, "base": cmd_base}[args.cmd](args)
    except ApiError as err:
        print(str(err), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
