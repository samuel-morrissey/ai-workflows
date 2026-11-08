#!/usr/bin/env python3
"""Reversao do label `undo`: desfaz a ultima mudanca de estado feita por uma
etapa (refinamento ou quebra), ou recusa dizendo o motivo e o caminho.

Usado pela composite action .github/actions/undo, chamada por dois lugares:

- issue-undo.yml, o destino `issue-undo` do router (humano aplicou `undo`
  num issue sem work-in-progress);
- o passo "Processar undo da rodada" de issue-triage.yml,
  issue-refinement.yml e issue-break-down.yml, com `--pending`: um `undo`
  aplicado durante a rodada (o evento dele foi pulado pela guarda de
  work-in-progress) e processado quando a rodada termina.

Fala com o GitHub so por `gh api` (token do workflow em GH_TOKEN,
repositorio em GH_REPO como `owner/repo`). Nao roda agente: tudo aqui e
regra fixa.

Qual foi a ultima etapa sai dos comentarios do issue, escritos por bot, em
ordem:

- `## Triagem`, `## Refinamento` e `## Quebra` (primeira linha exata) sao as
  mudancas de estado das etapas. Rodada de perguntas (`## Refinamento —
  rodada N`, handoff) nao mudou o estado e nao conta;
- a devolucao do pr-closed.yml (PR fechado sem merge) tambem e uma mudanca
  de estado, mas nao de etapa: com ela no topo, o `undo` e recusado;
- cada comentario de reversao deste script leva `<!-- ai:undo etapa=X -->`
  e cancela a etapa mais recente ainda valida. Por isso as mudancas do
  proprio `undo` nao contam: aplicar de novo desfaz a etapa anterior.

    undo.py run <issue> [--pending]

Saida: JSON com `action` (`revert`, `refuse` ou `none`), `stage`, `state` e
`reason`. Erro de API: mensagem no stderr e saida 2.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse

REPO = os.environ.get("GH_REPO") or ""
OWNER = REPO.split("/", 1)[0]

UNDO = "undo"
# Cor e descricao canonicas: tabela da issue-labeling e FLOW_LABELS do doctor.
LABELS = {
    "undo": ("E4E669", "Desfaz a ultima etapa: volta o issue ao estado anterior"),
    "needs-refinement": ("FBCA04", "Falta lapidar requisitos ou esclarecer a solicitacao"),
    "needs-break-down": ("FBCA04", "Escopo entendido, falta quebrar em sub-tasks"),
}
HEADINGS = {"## Triagem": "triagem", "## Refinamento": "refinamento", "## Quebra": "quebra"}
UNDO_RE = re.compile(r"<!-- ai:undo etapa=(triagem|refinamento|quebra) -->")
# Texto dos comentarios do pr-closed.yml que devolvem um pontual ou um pai.
RETURN_RE = re.compile(r"foi fechado sem merge\. O issue voltou de `awaiting-pr-review`")
PARENT_RE = re.compile(r"Parte de #(\d+)")
# Estado que a etapa deixa e estado de antes dela.
AFTER = {"refinamento": ("needs-break-down",), "quebra": ("ready-for-agent", "ready-for-human")}
BEFORE = {"refinamento": "needs-refinement", "quebra": "needs-break-down"}
NAMES = {"triagem": "triagem", "refinamento": "refinamento", "quebra": "quebra em sub-tasks"}
AGAIN = {"refinamento": "o refinamento", "quebra": "a quebra"}
STATE_RE = re.compile(r"^(needs-|ready-for-|awaiting-pr-review$)")
CLOSE_PR = ("feche o PR sem merge: o `pr-closed.yml` devolve o issue ao estado de antes do PR. "
            "Na stack de um pai, feche os PRs das sub-tasks.")


class ApiError(Exception):
    pass


def api(path, method=None, body=None, ok404=False, paginate=False):
    cmd = ["gh", "api", path]
    if method:
        cmd += ["--method", method]
    if paginate:
        cmd += ["--paginate", "--slurp"]
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
    out = json.loads(result.stdout) if result.stdout.strip() else None
    if paginate and isinstance(out, list):
        return [item for page in out for item in (page if isinstance(page, list) else [page])]
    return out


def labels_of(issue):
    return [label["name"] for label in issue.get("labels", [])]


def history(comments):
    """Mudancas de estado ainda validas, da mais antiga a mais recente:
    [{"kind": "triagem|refinamento|quebra|devolucao", "url": ...}]."""
    events = []
    for c in comments:
        if (c.get("user") or {}).get("type") != "Bot":
            continue
        body = (c.get("body") or "").strip()
        first = body.splitlines()[0].strip() if body else ""
        undone = UNDO_RE.search(body)
        if undone:
            # Cancela a etapa mais recente ainda valida; a devolucao nunca e
            # desfeita (o undo a recusa), entao nao esta no caminho.
            for i in range(len(events) - 1, -1, -1):
                if events[i]["kind"] != "devolucao":
                    del events[i]
                    break
        elif first in HEADINGS:
            events.append({"kind": HEADINGS[first], "url": c.get("html_url") or ""})
        elif RETURN_RE.search(body):
            events.append({"kind": "devolucao", "url": c.get("html_url") or ""})
    return events


def ensure_label(name):
    if api(f"repos/{REPO}/labels/{urllib.parse.quote(name)}", ok404=True) is None:
        color, desc = LABELS[name]
        try:
            api(f"repos/{REPO}/labels", "POST", {"name": name, "color": color, "description": desc})
        except ApiError as err:
            if "already_exists" not in str(err):
                raise


def remove_label(number, name):
    api(f"repos/{REPO}/issues/{number}/labels/{urllib.parse.quote(name)}", "DELETE", ok404=True)


def comment(number, body):
    api(f"repos/{REPO}/issues/{number}/comments", "POST", {"body": body})


def pr_in_progress(sub):
    """PR aberto ou mergeado da sub-task (branch sub-task-<n>), como o planner."""
    prs = api(f"repos/{REPO}/pulls?head={OWNER}:sub-task-{sub}&state=all&per_page=20") or []
    return next((p for p in prs if p["state"] == "open" or p.get("merged_at")), None)


def refuse(number, reason, path, stage=None, state=None):
    body = (f"## Undo recusado\n\n**Motivo:** {reason}\n**Caminho:** {path}\n\n"
            "Nenhum label de estado mudou; o `undo` saiu do issue.")
    comment(number, body)
    return {"action": "refuse", "issue": number, "stage": stage, "state": state, "reason": reason}


def decide(issue, events, subs=None):
    """(motivo, caminho) da recusa, ou None quando a reversao vale. Puro:
    `subs` sao as sub-issues do pai, cada uma com a chave `pr`."""
    labels = labels_of(issue)
    state = next((l for l in labels if STATE_RE.match(l)), None)
    if issue["state"] != "open":
        return ("o issue esta fechado.", "nada a desfazer num issue fechado; reabra-o se ele deve voltar ao fluxo.")
    if (issue.get("title") or "").startswith("[SUB-TASK]"):
        m = PARENT_RE.search(issue.get("body") or "")
        pai = f"no pai #{m.group(1)}" if m else "no pai"
        return ("`undo` nao vale numa `[SUB-TASK]`: ela nao tem label de estado.",
                f"para desfazer a quebra que a criou, aplique `undo` {pai}.")
    if state == "needs-triage" or state is None and not events:
        return ("o issue esta em `needs-triage`: nenhuma etapa rodou, nao ha o que desfazer.",
                "aplique `go` para rodar a triagem.")
    if state == "awaiting-pr-review":
        return ("a implementacao comecou: o issue esta em `awaiting-pr-review`, com PR aberto.", CLOSE_PR)
    if not events:
        return ("nao achei, nos comentarios do issue, uma etapa (triagem, refinamento ou quebra) para desfazer.",
                "ajuste o label de estado na mao.")
    last = events[-1]
    if last["kind"] == "devolucao":
        return ("a ultima mudanca de estado foi a devolucao de um PR fechado sem merge, "
                "nao uma etapa antes da implementacao: a implementacao ja comecou.", CLOSE_PR)
    if last["kind"] == "triagem":
        return ("desfazer a triagem ainda nao e suportado.",
                "ajuste o label de estado e o titulo na mao, se precisar.")
    if state not in AFTER[last["kind"]]:
        esperado = " ou ".join(f"`{s}`" for s in AFTER[last["kind"]])
        return (f"o label de estado atual ({f'`{state}`' if state else 'nenhum'}) nao e o que a "
                f"{NAMES[last['kind']]} deixou ({esperado}): ele mudou depois dela.",
                "ajuste o label de estado na mao.")
    if last["kind"] == "quebra":
        with_pr = [s for s in subs or [] if s.get("pr")]
        if with_pr:
            prs = ", ".join(f"#{s['number']} (PR #{s['pr']['number']})" for s in with_pr)
            return (f"a implementacao comecou: sub-task com PR aberto ou mergeado: {prs}.", CLOSE_PR)
        wip = [s["number"] for s in subs or [] if "work-in-progress" in labels_of(s)]
        if wip:
            return ("sub-task em execucao agora (`work-in-progress`): "
                    + ", ".join(f"#{n}" for n in wip) + ".",
                    "espere a rodada dela terminar e aplique `undo` de novo.")
    return None


def revert_break_down(number, subs):
    closed = []
    for sub in subs:
        n = sub["number"]
        blocked = api(f"repos/{REPO}/issues/{n}/dependencies/blocked_by?per_page=100") or []
        for blocker in blocked:
            api(f"repos/{REPO}/issues/{n}/dependencies/blocked_by/{blocker['id']}", "DELETE", ok404=True)
        api(f"repos/{REPO}/issues/{number}/sub_issue", "DELETE", {"sub_issue_id": sub["id"]})
        if sub["state"] == "open":
            api(f"repos/{REPO}/issues/{n}", "PATCH", {"state": "closed", "state_reason": "not_planned"})
            comment(n, f"Fechada como \"not planned\" pelo `undo` da quebra em #{number}: "
                       "esta sub-task saiu da lista de sub-issues do pai e perdeu os bloqueios. "
                       "Um `go` no pai roda a quebra de novo, com sub-tasks novas.")
        closed.append(n)
    return closed


def run(number, pending=False):
    issue = api(f"repos/{REPO}/issues/{number}")
    labels = labels_of(issue)
    if pending and UNDO not in labels:
        return {"action": "none", "issue": number, "reason": "sem `undo` no issue"}
    # Como o `go`: o `undo` e consumido ao comecar, para poder ser aplicado de novo.
    if UNDO in labels:
        remove_label(number, UNDO)
        labels.remove(UNDO)
        issue["labels"] = [{"name": l} for l in labels]
    comments = api(f"repos/{REPO}/issues/{number}/comments?per_page=100", paginate=True) or []
    events = history(comments)
    subs = None
    if events and events[-1]["kind"] == "quebra":
        subs = api(f"repos/{REPO}/issues/{number}/sub_issues?per_page=100", paginate=True) or []
        for sub in subs:
            sub["pr"] = pr_in_progress(sub["number"])
    state = next((l for l in labels if STATE_RE.match(l)), None)
    refusal = decide(issue, events, subs)
    if refusal:
        stage = events[-1]["kind"] if events else None
        return refuse(number, *refusal, stage=stage, state=state)

    last = events[-1]
    stage, before = last["kind"], BEFORE[last["kind"]]
    closed = revert_break_down(number, subs) if stage == "quebra" else []
    ensure_label(before)
    # Troca o estado numa operacao so; o awaiting-reply sai junto (o issue
    # volta a um estado anterior e fica esperando `go`).
    keep = [l for l in labels if l not in (state, "awaiting-reply")]
    api(f"repos/{REPO}/issues/{number}/labels", "PUT", {"labels": keep + [before]})

    lines = [f"## Undo\n\n**Desfeito:** {'a' if stage == 'quebra' else 'o'} {NAMES[stage]}"
             + (f" ([comentario `## {stage.capitalize()}`]({last['url']}))." if last["url"] else ".")]
    if stage == "quebra":
        if closed:
            lines.append("**Sub-tasks fechadas** como \"not planned\", tiradas da lista de sub-issues e sem "
                         "bloqueios: " + ", ".join(f"#{n}" for n in closed) + ".")
        else:
            lines.append("**Sub-tasks:** nenhuma ligada a este issue.")
    lines.append(f"**Estado:** o issue voltou de `{state}` para `{before}`. Aplique `go` para rodar "
                 f"{AGAIN[stage]} de novo.")
    lines.append("Os comentarios anteriores ficam como historico; o comentario desfeito nao vale mais. "
                 "Aplicar `undo` de novo desfaz a etapa anterior a esta.")
    comment(number, "\n".join(lines) + f"\n\n<!-- ai:undo etapa={stage} -->")
    return {"action": "revert", "issue": number, "stage": stage, "state": before, "from": state,
            "closed": closed}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="cmd", required=True)
    p = subs.add_parser("run")
    p.add_argument("issue", type=int)
    p.add_argument("--pending", action="store_true",
                   help="so age se o issue carrega `undo` (fim de rodada de etapa)")
    args = parser.parse_args()
    if not REPO:
        sys.exit("GH_REPO (owner/repo) e obrigatorio.")
    try:
        print(json.dumps(run(args.issue, args.pending), ensure_ascii=False))
    except ApiError as err:
        print(str(err), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
