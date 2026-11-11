#!/usr/bin/env python3
"""Encadeamento das etapas antes da implementacao: a etapa que termina chama
a seguinte, sem esperar `go`.

Seguem sozinhas: triagem -> `needs-refinement` (roda o refinamento),
triagem -> `needs-break-down` e refinamento -> `needs-break-down` (rodam a
quebra). Todo `ready-for-*`, `needs-discovery` e rodada que termina com
`awaiting-reply` continuam parados, como antes.

Trocar o label nao basta: label aplicado pelo token do workflow nao gera
evento. A etapa chama a seguinte com um `repository_dispatch` do tipo
`ai-advance` (payload: `issue`, `stage` = `refinement` ou `break-down`, e
`from` = a etapa que chamou), criado com o GITHUB_TOKEN; o router.yml leva o
evento ao destino da etapa.

Usado pela composite action .github/actions/advance, em dois momentos da
triagem (issue-triage.yml) e do refinamento (issue-refinement.yml):

    advance.py check --stage triagem|refinamento [--number N] [--github-output F]

antes do agente: le `auto_advance` de .github/ai-workflows.yml e o
.github/workflows/ai.yml do checkout (o do consumidor). `auto_advance:
false`, ou um ai.yml sem o tipo `ai-advance`, desligam o encadeamento. Sai
`enabled`, `reason`, `before` (o label de estado do issue agora) e a frase
"Encadeamento: ..." do system prompt, que diz a skill se o comentario final
pede `go` e marca o responsavel (desligado) ou diz que a etapa seguinte
roda sozinha e que o `undo` desfaz esta (ligado).

    advance.py run <issue> --stage triagem|refinamento --before <label>
                   --enabled true|false [--logins "a b"] [--undo-result JSON]

depois da rodada, ja sem work-in-progress: despacha a etapa seguinte quando
o encadeamento esta ligado, o issue esta aberto, sem `wontfix`/`deferred`
nem `awaiting-reply`, e a rodada o levou a um estado que encadeia. Um
`undo` processado na rodada para a cadeia. Quando o comentario da etapa ja
disse que a seguinte ia rodar e ela nao foi chamada (dispatch que falhou,
`undo` recusado ou pendente), comenta de novo no issue pedindo `go` e
marcando o responsavel (`--logins`).

Fala com o GitHub so por `gh api` (GH_TOKEN, GH_REPO = owner/repo). Saida:
JSON com `action` (`dispatch`, `none` ou `failed`) e `reason`.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("GH_REPO") or ""
CONFIG_FILE = ".github/ai-workflows.yml"
AI_YML = ".github/workflows/ai.yml"
EVENT_TYPE = "ai-advance"
KEY_RE = re.compile(r"^auto_advance[ \t]*:[ \t]*(.*?)[ \t]*$", re.M)
DISPATCH_RE = re.compile(r"^  repository_dispatch:[ \t]*\n(?:[ \t]*#.*\n)*[ \t]+types:[ \t]*\[([^\]]*)\]", re.M)
STATE_RE = re.compile(r"^(needs-|ready-for-|awaiting-pr-review$)")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
# Estado que a etapa deixa -> etapa seguinte (destino do router).
NEXT = {"triagem": {"needs-refinement": "refinement", "needs-break-down": "break-down"},
        "refinamento": {"needs-break-down": "break-down"}}
SKILL = {"refinement": "/issue-refinement", "break-down": "/issue-break-down"}
NAMES = {"triagem": "a triagem", "refinamento": "o refinamento"}


class ApiError(Exception):
    pass


def api(path, method=None, body=None):
    cmd = ["gh", "api", path]
    if method:
        cmd += ["--method", method]
    stdin = None
    if body is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(body)
    result = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if result.returncode != 0:
        raise ApiError(f"gh api {method or 'GET'} {path}: {(result.stderr or result.stdout).strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def auto_advance_off(config):
    """True so com `auto_advance: false` no topo do arquivo."""
    m = KEY_RE.search(config or "")
    if not m:
        return False
    value = re.sub(r"(^|\s+)#.*$", "", m.group(1)).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value.lower() == "false"


def declares_type(ai_yml):
    m = DISPATCH_RE.search(ai_yml or "")
    return bool(m) and EVENT_TYPE in [t.strip() for t in m.group(1).split(",")]


def check(stage, config, ai_yml):
    """Liga ou desliga o encadeamento da etapa. Puro: recebe os textos."""
    states = " ou ".join(NEXT[stage])
    if auto_advance_off(config):
        enabled, reason = False, f"auto_advance: false em {CONFIG_FILE}"
    elif not declares_type(ai_yml):
        enabled, reason = False, (f"o {AI_YML} deste repositorio ainda nao declara o tipo {EVENT_TYPE} em "
                                  "repository_dispatch; o PR de atualizacao do check-caller resolve")
    else:
        enabled, reason = True, ""
    if enabled:
        sentence = (f" Encadeamento: ligado (resolvido pelo workflow). Se esta rodada terminar em {states}, o "
                    "workflow chama a etapa seguinte sozinho, sem go: no comentario final, nao peca go e nao "
                    "marque ninguem; diga qual etapa roda em seguida e que aplicar o label undo desfaz esta "
                    "etapa. Os outros desfechos seguem como sempre.")
    else:
        sentence = (f" Encadeamento: desligado ({reason}). Nenhuma etapa e chamada sozinha: o comentario final "
                    "que deixa o issue num estado seguinte pede go e marca o responsavel, como sempre.")
    return {"enabled": enabled, "reason": reason, "sentence": sentence}


def state_of(issue):
    return next((l["name"] for l in issue.get("labels", []) if STATE_RE.match(l["name"])), None)


def mention(logins):
    valid = [l for l in (logins or "").split() if LOGIN_RE.match(l)]
    return " ".join(f"@{l}" for l in valid)


def ask_go(number, stage, state, nxt, why, logins):
    who = mention(logins)
    step = f"aplique o label `go` neste issue para rodar o `{SKILL[nxt]}`."
    lines = [f"## Etapa seguinte nao chamada\n\n{NAMES[stage].capitalize()} terminou em `{state}`, mas o "
             f"`{SKILL[nxt]}` nao foi chamado sozinho: {why}", ""]
    if who:
        lines.append(f"**Proximo passo** ({who}): {step}")
    else:
        lines.append(f"**Proximo passo:** {step}")
        lines.append("**Responsavel:** nao ha responsavel identificavel; ninguem foi marcado.")
    api(f"repos/{REPO}/issues/{number}/comments", "POST", {"body": "\n".join(lines)})


def run(number, stage, before, enabled, logins="", undo_result=""):
    def none(reason):
        return {"action": "none", "issue": number, "reason": reason}

    if not enabled:
        return none("encadeamento desligado")
    issue = api(f"repos/{REPO}/issues/{number}")
    labels = [l["name"] for l in issue.get("labels", [])]
    state = state_of(issue)
    if issue.get("state") != "open":
        return none("issue fechado")
    if {"wontfix", "deferred"} & set(labels):
        return none("issue fora do fluxo (wontfix/deferred)")
    if "awaiting-reply" in labels:
        return none("a rodada parou numa pergunta")
    nxt = NEXT[stage].get(state)
    if not nxt:
        return none(f"estado {state or 'nenhum'} nao encadeia")
    if state == before:
        return none(f"estado {state} nao mudou nesta rodada")
    try:
        undone = json.loads(undo_result) if undo_result else {}
    except ValueError:
        undone = {}
    if undone.get("action") == "revert":
        return none("o undo da rodada desfez a etapa")
    if undone.get("action") == "refuse":
        why = "o `undo` aplicado durante a rodada foi recusado, e a cadeia parou nele."
    elif "undo" in labels:
        why = "um `undo` aplicado durante a rodada ainda esta no issue, sem processar."
    else:
        why = None
        payload = {"issue": number, "stage": nxt, "from": stage}
        try:
            api(f"repos/{REPO}/dispatches", "POST", {"event_type": EVENT_TYPE, "client_payload": payload})
            return {"action": "dispatch", "issue": number, "stage": nxt, "from": stage}
        except ApiError as err:
            why = f"o `repository_dispatch` falhou ({str(err)[:300]})."
    try:
        ask_go(number, stage, state, nxt, why, logins)
        reason = why
    except ApiError as err:
        reason = f"{why} E o comentario pedindo go falhou: {str(err)[:300]}"
    return {"action": "failed", "issue": number, "stage": nxt, "reason": reason}


def read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def write_outputs(path, values):
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={value}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="cmd", required=True)
    c = subs.add_parser("check")
    c.add_argument("--stage", choices=sorted(NEXT), required=True)
    c.add_argument("--number", type=int)
    c.add_argument("--github-output")
    r = subs.add_parser("run")
    r.add_argument("issue", type=int)
    r.add_argument("--stage", choices=sorted(NEXT), required=True)
    r.add_argument("--before", default="")
    r.add_argument("--enabled", default="false")
    r.add_argument("--logins", default="")
    r.add_argument("--undo-result", default="")
    args = parser.parse_args()

    if args.cmd == "check":
        out = check(args.stage, read(CONFIG_FILE), read(AI_YML))
        out["before"] = ""
        if args.number and REPO:
            try:
                out["before"] = state_of(api(f"repos/{REPO}/issues/{args.number}")) or ""
            except ApiError as err:
                print(f"::warning::Nao consegui ler o estado do #{args.number}: {str(err)[:300]}")
        if args.github_output:
            write_outputs(args.github_output, {"enabled": "true" if out["enabled"] else "false",
                                               "before": out["before"], "sentence": out["sentence"]})
        print(json.dumps(out, ensure_ascii=False))
        return
    if not REPO:
        sys.exit("GH_REPO (owner/repo) e obrigatorio.")
    try:
        out = run(args.issue, args.stage, args.before, args.enabled == "true", args.logins, args.undo_result)
    except ApiError as err:
        print(str(err), file=sys.stderr)
        sys.exit(2)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
