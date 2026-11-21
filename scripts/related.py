#!/usr/bin/env python3
"""Repositorios relacionados: a chave `related_repos` e o comando `ai-related`.

Um projeto pode viver em mais de um repositorio (um site e o app dele, por
exemplo). A chave `related_repos` de .github/ai-workflows.yml lista os
vizinhos que o agente das etapas pode consultar: um bloco `|`, uma entrada
por linha, `repo` ou `owner/repo`, sempre do mesmo dono do repositorio da
rodada. O acesso usa um token de GitHub App, criado pelo workflow so para
esses repositorios, com codigo em leitura e issues e PRs em escrita.

O agente trata o vizinho como outra equipe: le o que precisar e pede mudanca
por issue ou comentario, sem alterar nada la. O token deixaria editar e
fechar issue e PR; quem segura isso e o comando `ai-related`, a unica porta
que o agente recebe, que so aceita as acoes da lista abaixo. So biblioteca
padrao.

Tres modos, os dois primeiros usados pela action related-repos:

    related.py read --owner <dono> --current <owner/repo> [--config <arquivo>]
                    [--github-output <arquivo>]
        Le a chave e grava `repos` (owner/repo, separados por virgula) e
        `names` (so o nome, para a action do token). Linha invalida, de outro
        dono ou o proprio repositorio: ignorada com `::warning`. Valor que nao
        e texto: `::error` e saida 1.

    related.py install --repos <lista> --dir <pasta> [--origin <owner/repo#n>]
                       [--reason <texto>] [--github-output <arquivo>]
                       [--github-path <arquivo>]
        Com o token em $RELATED_TOKEN, grava o token e o estado em <pasta>,
        cria o comando `ai-related` em <pasta>/bin e grava `allow` (sufixo do
        --allowed-tools) e `sentence` (frase do system prompt). Sem token,
        avisa com o motivo e deixa os dois vazios: a rodada segue sem vizinhos.

    related.py run --state <arquivo> <argumentos do ai-related>
        O comando do agente:

        ai-related repos
        ai-related <repo> clone [--ref <ref>]
        ai-related <repo> issue list|view [flags do gh]
        ai-related <repo> issue create --title <t> (--body <b> | --body-file <f>)
        ai-related <repo> issue comment <numero> (--body <b> | --body-file <f>)
        ai-related <repo> pr list|view|diff [flags do gh]
        ai-related <repo> pr comment <numero> (--body <b> | --body-file <f>)
        ai-related <repo> api <rota> [--paginate] [--jq <expr>]

        `api` e so GET, com a rota relativa a repos/<owner>/<repo>/. Todo
        issue e comentario criado ganha a linha de origem (o issue ou PR da
        rodada), se o texto ainda nao a cita. Acao fora da lista: saida 2.
"""

import argparse
import base64
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import web_domains  # noqa: E402

CONFIG_FILE = ".github/ai-workflows.yml"
KEY = "related_repos"
COMMAND = "ai-related"
SKILL = "samuel-morrissey-skills:related-repos"
OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?")
NAME_RE = re.compile(r"[A-Za-z0-9._-]+")
REF_RE = re.compile(r"[A-Za-z0-9._/-]+")
UNSAFE = "\"'`$\\"
READ = {("issue", "list"), ("issue", "view"), ("pr", "list"), ("pr", "view"), ("pr", "diff")}
WRITE = {("issue", "create"), ("issue", "comment"), ("pr", "comment")}
ALLOWED = ("repos; <repo> clone; <repo> issue list|view|create|comment; "
           "<repo> pr list|view|diff|comment; <repo> api <rota GET>")


class Refused(Exception):
    """Pedido fora do que o comando aceita: saida 2, com o motivo."""


# ------------------------------------------------------------------ leitura

def parse_entry(line, owner):
    """`owner/repo` de uma linha da chave; ValueError com o motivo."""
    if re.search(r"\s", line):
        raise ValueError("espaco no meio")
    if any(ch in line for ch in UNSAFE):
        raise ValueError("aspas, crase, cifrao ou barra invertida")
    if "://" in line or line.endswith(".git"):
        raise ValueError("use repo ou owner/repo, sem URL")
    entry_owner, _, name = line.rpartition("/")
    entry_owner = entry_owner or owner
    if not OWNER_RE.fullmatch(entry_owner) or not NAME_RE.fullmatch(name) or name in (".", ".."):
        raise ValueError("nome de repositorio invalido")
    if entry_owner.lower() != owner.lower():
        raise ValueError(f"outro dono: o token do App so alcanca repositorios de {owner}")
    return f"{owner}/{name}"


def read(text, owner, current):
    """Repositorios liberados (sem repetir) e as linhas ignoradas."""
    result = {"repos": [], "ignored": []}
    seen = set()
    for line in web_domains.entries(web_domains.extract(text, KEY)):
        try:
            full = parse_entry(line, owner)
            if full.lower() == current.lower():
                raise ValueError("e o proprio repositorio da rodada")
        except ValueError as exc:
            result["ignored"].append((line, str(exc)))
            continue
        if full.lower() not in seen:
            seen.add(full.lower())
            result["repos"].append(full)
    return result


def emit(path, key, value):
    with open(path, "a", encoding="utf-8") as fh:
        if "\n" in value:
            d = f"EOF_{secrets.token_hex(8)}"
            fh.write(f"{key}<<{d}\n{value}\n{d}\n")
        else:
            fh.write(f"{key}={value}\n")


def cmd_read(args):
    try:
        with open(args.config, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = None
    try:
        result = read(text, args.owner, args.current)
    except web_domains.ConfigError as exc:
        print(f"::error file={args.config}::{exc}")
        return 1
    for line, reason in result["ignored"]:
        print(f"::warning file={args.config}::{KEY}: linha ignorada ({reason}): {line}")
    repos = ",".join(result["repos"])
    names = ",".join(r.split("/", 1)[1] for r in result["repos"])
    if result["repos"]:
        print(f"::notice::{KEY}: {' '.join(result['repos'])}")
    if args.github_output:
        emit(args.github_output, "repos", repos)
        emit(args.github_output, "names", names)
    else:
        print(json.dumps({"repos": result["repos"], "names": names,
                          "ignored": [list(i) for i in result["ignored"]]}))
    return 0


# --------------------------------------------------------------- instalacao

def allow():
    """Sufixo do `--allowed-tools`: so o comando `ai-related`."""
    return f",Bash({COMMAND}:*)"


def sentence(repos):
    """Frase do system prompt, comecando por espaco.

    Sem aspas duplas, crase, cifrao nem barra invertida: vai entre aspas em
    claude_args (os nomes com eles ja foram ignorados na leitura).
    """
    return (f" Repositorios relacionados (chave {KEY} de {CONFIG_FILE}): {', '.join(repos)}."
            " Sao de outras equipes: consulte quando a tarefa precisar e peca mudanca por issue ou"
            f" comentario, sem alterar nada la. O unico acesso e o comando {COMMAND} ({COMMAND} repos"
            f" mostra o uso). Antes do primeiro uso, invoque a skill {SKILL} e siga as regras dela."
            " O token desse acesso vale 1 hora a partir do comeco da rodada: leia e peca cedo.")


def cmd_install(args):
    repos = [r for r in args.repos.split(",") if r]
    token = os.environ.get("RELATED_TOKEN", "")
    if not repos or not token:
        if repos:
            print(f"::warning::{KEY}: sem acesso aos repositorios relacionados nesta rodada"
                  f" ({args.reason or 'sem token do GitHub App'}); a rodada segue sem eles.")
        if args.github_output:
            emit(args.github_output, "allow", "")
            emit(args.github_output, "sentence", "")
        return 0
    base = os.path.abspath(args.dir)
    bin_dir = os.path.join(base, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    token_file = os.path.join(base, "token")
    with open(os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        fh.write(token)
    state_file = os.path.join(base, "state.json")
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump({"repos": repos, "origin": args.origin or "", "token_file": token_file,
                   "clone_dir": os.path.join(base, "repos")}, fh)
    shim = os.path.join(bin_dir, COMMAND)
    with open(shim, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n"
                 f"exec python3 -I {shlex.quote(os.path.abspath(__file__))} run"
                 f" --state {shlex.quote(state_file)} \"$@\"\n")
    os.chmod(shim, os.stat(shim).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if args.github_path:
        with open(args.github_path, "a", encoding="utf-8") as fh:
            fh.write(bin_dir + "\n")
    print(f"::notice::{KEY}: comando {COMMAND} liberado para {' '.join(repos)}")
    if args.github_output:
        emit(args.github_output, "allow", allow())
        emit(args.github_output, "sentence", sentence(repos))
    else:
        print(json.dumps({"allow": allow(), "sentence": sentence(repos), "command": shim}))
    return 0


# ------------------------------------------------------------------ comando

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused(message)


def resolve(state, wanted):
    for full in state["repos"]:
        if wanted.lower() in (full.lower(), full.split("/", 1)[1].lower()):
            return full
    raise Refused(f"{wanted} nao esta em {KEY}. Liberados: {', '.join(state['repos'])}.")


def token_of(state):
    with open(state["token_file"], encoding="utf-8") as fh:
        return fh.read().strip()


def gh_env(state):
    env = {k: v for k, v in os.environ.items()
           if k not in ("GH_REPO", "GH_HOST", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}
    env["GH_TOKEN"] = token_of(state)
    env["GH_PROMPT_DISABLED"] = "1"
    return env


def run_gh(state, cmd, stdin=None):
    proc = subprocess.run(["gh", *cmd], env=gh_env(state), input=stdin, text=True, stderr=subprocess.PIPE)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0 and re.search(r"HTTP 401|Bad credentials", proc.stderr or ""):
        print(f"{COMMAND}: o token dos repositorios relacionados expirou (vale 1 hora a partir do comeco"
              " da rodada). Registre no comentario da rodada o que faltou consultar ou pedir.", file=sys.stderr)
    return proc.returncode


def check_read_args(args):
    for arg in args:
        if arg in ("-w", "--web"):
            raise Refused("--web nao e aceito: a rodada nao tem navegador.")
        if arg == "--repo" or arg.startswith(("--repo=", "-R")):
            raise Refused("o repositorio e o primeiro argumento; -R/--repo nao e aceito.")
        if "://" in arg:
            raise Refused("passe o numero, nao a URL: o repositorio e o primeiro argumento.")


def with_origin(state, body):
    body = body.strip()
    if not body:
        raise Refused("corpo vazio.")
    origin = state.get("origin") or ""
    if origin and origin not in body:
        body += f"\n\n_Origem: {origin}_"
    return body + "\n"


def body_of(state, ns):
    if (ns.body is None) == (ns.body_file is None):
        raise Refused("passe o texto com --body ou com --body-file, um dos dois.")
    if ns.body_file is not None:
        try:
            with open(ns.body_file, encoding="utf-8") as fh:
                return with_origin(state, fh.read())
        except OSError as exc:
            raise Refused(f"nao foi possivel ler {ns.body_file}: {exc.strerror}")
    return with_origin(state, ns.body)


def write_parser(group, action):
    parser = Parser(prog=f"{COMMAND} <repo> {group} {action}", add_help=False, allow_abbrev=False)
    if action == "create":
        parser.add_argument("-t", "--title", required=True)
    else:
        parser.add_argument("number")
    parser.add_argument("-b", "--body")
    parser.add_argument("-F", "--body-file")
    return parser


def cmd_write(state, full, group, action, args):
    ns = write_parser(group, action).parse_args(args)
    body = body_of(state, ns)
    if action == "create":
        if not ns.title.strip():
            raise Refused("titulo vazio.")
        cmd = [group, action, "--title", ns.title]
    else:
        if not re.fullmatch(r"[0-9]+", ns.number):
            raise Refused("passe o numero do issue ou do PR, sem # e sem URL.")
        cmd = [group, action, ns.number]
    return run_gh(state, [*cmd, "--body-file", "-", "-R", full], stdin=body)


def cmd_api(state, full, args):
    parser = Parser(prog=f"{COMMAND} <repo> api", add_help=False, allow_abbrev=False)
    parser.add_argument("route")
    parser.add_argument("--paginate", action="store_true")
    parser.add_argument("-q", "--jq")
    ns = parser.parse_args(args)
    route = ns.route
    if (not route or route.startswith(("/", "-")) or "://" in route or re.search(r"\s", route)
            or ".." in route.split("?", 1)[0].split("/")):
        raise Refused(f"rota invalida: passe a parte depois de repos/{full}/, como pulls/12/comments.")
    cmd = ["api", "--method", "GET", f"repos/{full}/{route}"]
    if ns.paginate:
        cmd.append("--paginate")
    if ns.jq is not None:
        cmd += ["--jq", ns.jq]
    return run_gh(state, cmd)


def git_env(state):
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    basic = base64.b64encode(f"x-access-token:{token_of(state)}".encode()).decode()
    env = dict(os.environ)
    # Credencial so no ambiente do processo: nao vai para a linha de comando
    # nem fica gravada no .git/config do clone.
    env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.{server}/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}", "GIT_TERMINAL_PROMPT": "0"})
    return server, env


def cmd_clone(state, full, args):
    parser = Parser(prog=f"{COMMAND} <repo> clone", add_help=False, allow_abbrev=False)
    parser.add_argument("--ref")
    ns = parser.parse_args(args)
    if ns.ref is not None and (not REF_RE.fullmatch(ns.ref) or ns.ref.startswith("-") or ".." in ns.ref):
        raise Refused("ref invalida: passe uma branch, tag ou commit.")
    server, env = git_env(state)
    root = state["clone_dir"]
    dest = os.path.join(root, *full.split("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    def git(*cmd, cwd=root):
        return subprocess.run(["git", *cmd], cwd=cwd, env=env, stdout=subprocess.DEVNULL).returncode

    if not os.path.isdir(os.path.join(dest, ".git")):
        # Fora do workspace e de qualquer repositorio: o clone nao herda a
        # credencial que o checkout da rodada deixou no repositorio dela.
        rc = git("clone", "--quiet", "--depth", "1", f"{server}/{full}.git", dest)
        if rc != 0:
            print(f"{COMMAND}: nao foi possivel clonar {full}. O GitHub App esta instalado nele,"
                  " com leitura de codigo?", file=sys.stderr)
            return rc
    if ns.ref is not None:
        rc = (git("fetch", "--quiet", "--depth", "1", "origin", ns.ref, cwd=dest)
              or git("checkout", "--quiet", "--detach", "FETCH_HEAD", cwd=dest))
        if rc != 0:
            print(f"{COMMAND}: nao foi possivel trazer a ref {ns.ref} de {full}.", file=sys.stderr)
            return rc
    print(dest)
    print(f"Clone raso de {full}{' em ' + ns.ref if ns.ref else ''}, so para leitura: use Read, Grep e Glob"
          " nessa pasta. Nada dela vai para o repositorio da rodada nem volta para o vizinho.", file=sys.stderr)
    return 0


def usage(state):
    lines = [f"Repositorios relacionados liberados ({KEY}):"]
    lines += [f"  {full}" for full in state["repos"]]
    lines += ["", "Uso (<repo> e o nome, com ou sem o dono):",
              f"  {COMMAND} <repo> clone [--ref <ref>]            clone raso para ler o codigo",
              f"  {COMMAND} <repo> issue list|view [flags do gh]  ler issues",
              f"  {COMMAND} <repo> issue create --title <t> --body-file <f>",
              f"  {COMMAND} <repo> issue comment <n> --body-file <f>",
              f"  {COMMAND} <repo> pr list|view|diff [flags do gh] ler PRs",
              f"  {COMMAND} <repo> pr comment <n> --body-file <f>",
              f"  {COMMAND} <repo> api <rota> [--paginate] [--jq <e>]  GET em repos/<owner>/<repo>/<rota>",
              "", "--body <texto> vale no lugar de --body-file. Editar, fechar, aplicar label,",
              "revisar ou mergear no vizinho nao e aceito: peca num issue ou num comentario."]
    return "\n".join(lines)


def run(state, argv):
    if not argv or argv[0] in ("repos", "help", "-h", "--help"):
        print(usage(state))
        return 0
    full = resolve(state, argv[0])
    rest = argv[1:]
    if rest[:1] == ["clone"]:
        return cmd_clone(state, full, rest[1:])
    if rest[:1] == ["api"]:
        return cmd_api(state, full, rest[1:])
    pair = tuple(rest[:2])
    if pair in READ:
        check_read_args(rest[2:])
        return run_gh(state, [*pair, *rest[2:], "-R", full])
    if pair in WRITE:
        return cmd_write(state, full, pair[0], pair[1], rest[2:])
    raise Refused(f"'{' '.join(rest[:2]) or '(vazio)'}' nao e aceito em repositorio relacionado."
                  f" Aceitos: {ALLOWED}. O vizinho e de outra equipe: peca a mudanca num issue ou comentario.")


def cmd_run(state_file, argv):
    try:
        with open(state_file, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        print(f"{COMMAND}: repositorios relacionados indisponiveis nesta rodada.", file=sys.stderr)
        return 2
    try:
        return run(state, argv)
    except Refused as exc:
        print(f"{COMMAND}: recusado: {exc}", file=sys.stderr)
        return 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # O modo run repassa o resto dos argumentos como estao (flags do gh).
    if argv[:2] == ["run", "--state"] and len(argv) >= 3:
        return cmd_run(argv[2], argv[3:])
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    p_read = sub.add_parser("read")
    p_read.add_argument("--config", default=CONFIG_FILE)
    p_read.add_argument("--owner", required=True)
    p_read.add_argument("--current", required=True)
    p_read.add_argument("--github-output")
    p_install = sub.add_parser("install")
    p_install.add_argument("--repos", required=True)
    p_install.add_argument("--dir", required=True)
    p_install.add_argument("--origin", default="")
    p_install.add_argument("--reason", default="")
    p_install.add_argument("--github-output")
    p_install.add_argument("--github-path")
    args = parser.parse_args(argv)
    return cmd_read(args) if args.mode == "read" else cmd_install(args)


if __name__ == "__main__":
    sys.exit(main())
