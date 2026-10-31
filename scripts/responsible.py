#!/usr/bin/env python3
"""Resolve o responsavel humano de um issue do fluxo.

Fonte unica da regra, usada pela action round-failure (o comentario
"## Rodada com falha" marca quem ela devolve) e pela action responsible, que
entrega o resultado ao agente das etapas de issue para o handoff e o
comentario final da etapa. Fala com o GitHub so por `gh api` (token em
GH_TOKEN, repositorio em GH_REPO como `owner/repo`). Nao roda agente.

A primeira regra que acha um humano vence:

1. os assignees do issue (todos os humanos entre eles);
2. o autor do issue, se for humano;
3. se o autor e bot ou agente:
   - numa `[SUB-TASK]`, o responsavel do pai (sub-issue nativa, senao a
     linha `Parte de #<pai>`), pelas mesmas regras;
   - em outro issue, a primeira linha `Responsável: @usuario` do corpo;
   - por ultimo, `default_responsible` de .github/ai-workflows.yml (vence
     o `--default`, que vem do input do workflow);
4. nenhuma achou: "sem responsavel" (`rule: none`, lista vazia). Nao e erro.

Bot ou agente nunca e resultado: conta como bot a conta com `type == "Bot"`
ou com login terminado em `[bot]`. Login do campo ou da chave que nao existe
tambem nao vale.

    responsible.py <numero> [--config .github/ai-workflows.yml] [--default <login>]

Saida: {"issue": <numero onde a regra achou>, "logins": [...], "rule":
"assignees|author|field|default|none"}. Falha de API sai com 2.
"""

import argparse
import json
import os
import re
import subprocess
import sys

REPO = os.environ.get("GH_REPO") or ""
CONFIG_FILE = ".github/ai-workflows.yml"
FIELD_RE = re.compile(r"^\s*\**Respons[áa]vel:?\**:?\s*@([A-Za-z0-9][A-Za-z0-9-]*(?:\[bot\])?)[ \t]*$", re.MULTILINE)
PARENT_RE = re.compile(r"Parte de #(\d+)")
KEY_RE = re.compile(r"^default_responsible:[ \t]*(.*)$", re.MULTILINE)


class ApiError(Exception):
    pass


def api(path, ok404=False):
    result = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        if ok404 and "HTTP 404" in err:
            return None
        raise ApiError(f"gh api {path}: {err}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def is_bot(user):
    return not user or user.get("type") == "Bot" or user.get("login", "").endswith("[bot]")


def human_login(login):
    """O login, se ele e de uma conta humana que existe; senao None."""
    login = (login or "").strip().lstrip("@")
    if not login or login.endswith("[bot]"):
        return None
    user = api(f"users/{login}", ok404=True)
    return None if is_bot(user) else user["login"]


def config_default(path):
    """`default_responsible` do arquivo: escalar de texto, ou None.

    Leitura so desta chave, sem parser YAML (a biblioteca padrao nao tem):
    escalar simples, com ou sem aspas e comentario. Bloco, lista ou mapa nao
    sao login; a agent-env ja falha o job com valor que nao e texto.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return None
    match = KEY_RE.search(text)
    if not match:
        return None
    value = re.sub(r"\s+#.*$", "", match.group(1)).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    if not value or value[0] in "[{|>-&*!":
        return None
    return value


def parent_of(number, issue):
    parent = api(f"repos/{REPO}/issues/{number}/parent", ok404=True)
    if parent:
        return parent["number"]
    match = PARENT_RE.search(issue.get("body") or "")
    return int(match.group(1)) if match else None


def resolve(number, config=CONFIG_FILE, default="", seen=None):
    seen = seen if seen is not None else set()
    seen.add(number)
    issue = api(f"repos/{REPO}/issues/{number}")
    assignees = [a["login"] for a in issue.get("assignees") or [] if not is_bot(a)]
    if assignees:
        return {"issue": number, "logins": assignees, "rule": "assignees"}
    if not is_bot(issue.get("user")):
        return {"issue": number, "logins": [issue["user"]["login"]], "rule": "author"}
    if (issue.get("title") or "").startswith("[SUB-TASK]"):
        parent = parent_of(number, issue)
        if parent and parent not in seen:
            return resolve(parent, config, default, seen)
    else:
        match = FIELD_RE.search(issue.get("body") or "")
        login = human_login(match.group(1)) if match else None
        if login:
            return {"issue": number, "logins": [login], "rule": "field"}
    login = human_login(config_default(config) or default)
    if login:
        return {"issue": number, "logins": [login], "rule": "default"}
    return {"issue": number, "logins": [], "rule": "none"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("number", type=int)
    parser.add_argument("--config", default=CONFIG_FILE)
    parser.add_argument("--default", default="", help="input default_responsible do workflow")
    args = parser.parse_args()
    if not REPO:
        sys.exit("GH_REPO (owner/repo) e obrigatorio.")
    try:
        print(json.dumps(resolve(args.number, args.config, args.default)))
    except ApiError as err:
        print(str(err), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
