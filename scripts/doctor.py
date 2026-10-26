#!/usr/bin/env python3
"""Verifica e corrige a configuracao de um repositorio consumidor do fluxo.

Um repositorio que usa os workflows deste repositorio precisa de alguns itens
(README.md, "O que um repositorio precisa"). Este script confere cada um e,
com `fix`, corrige o que e seguro corrigir sem decisao humana. Rodar de novo
nao muda nada: cada correcao so acontece quando o item nao esta `ok`.

Fala com o GitHub so pelo `gh` (sessao local ou GH_TOKEN num workflow). Nao
tem dependencia alem da biblioteca padrao.

Subcomandos:

  check <owner/repo> [--json] [--only item,...] [--ref main]
  fix   <owner/repo> [--json] [--only item,...] [--ref main]
  check --all <owner> [<owner>...]      todos os repositorios com o topic
  fix   --all <owner> [<owner>...]      `ai-workflows` de cada dono

Itens, na ordem em que aparecem no relatorio:

  ai-yml      .github/workflows/ai.yml na branch padrao igual ao modelo
              (fix: PR no repositorio com o arquivo novo; inputs inline do
              ai.yml antigo migram para .github/ai-workflows.yml no mesmo PR)
  config      .github/ai-workflows.yml presente e valido
  secrets     CLAUDE_CODE_OAUTH_TOKEN; EVIDENCE_* quando ha bucket;
              PROJECT_ENV so informativo (fix: grava a partir do config.env)
  vars        EVIDENCE_BUCKET, EVIDENCE_PUBLIC_URL, EVIDENCE_ENDPOINT
              (fix: grava a partir do config.env, na org ou no repositorio)
  labels      os 13 labels do fluxo com cor e descricao canonicas (fix: cria os
              que faltam e corrige os divergentes); colisoes so informativas
  evidencias  .claude/skills/evidencias/SKILL.md com as cinco secoes
  topic       topic `ai-workflows` no repositorio (fix: adiciona)
  bucket      a URL publica do bucket responde (so informativo)

Estados: ok, falta, diverge, manual, info. Saida: 0 quando tudo e ok ou
info; 1 quando ha algo a corrigir; 2 em erro de acesso ou de argumento.

Valores do dono (secrets e variaveis) vem de um arquivo .env fora de qualquer
repositorio, `~/.config/ai-workflows/config.env` (ou o caminho em
AI_WORKFLOWS_CONFIG), com as chaves CLAUDE_CODE_OAUTH_TOKEN,
EVIDENCE_ACCESS_KEY_ID, EVIDENCE_SECRET_ACCESS_KEY, EVIDENCE_BUCKET,
EVIDENCE_PUBLIC_URL e EVIDENCE_ENDPOINT. Sem o arquivo, ou sem a chave, o
item sai como `manual`, com o comando para fazer a mao.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request

TEMPLATE_REPO = "samuel-morrissey/ai-workflows"
AI_YML = ".github/workflows/ai.yml"
CONFIG_FILE = ".github/ai-workflows.yml"
SKILL_FILE = ".claude/skills/evidencias/SKILL.md"
TOPIC = "ai-workflows"
BRANCH_PREFIX = "ai-workflows/"
DOCTOR_BRANCH = BRANCH_PREFIX + "doctor"
CONFIG_KEYS = ("setup_commands", "quality_checks", "evidence_tools",
               "evidence_bucket", "evidence_public_url", "evidence_endpoint")
VAR_NAMES = ("EVIDENCE_BUCKET", "EVIDENCE_PUBLIC_URL", "EVIDENCE_ENDPOINT")
SECRET_TOKEN = "CLAUDE_CODE_OAUTH_TOKEN"
SECRET_BUCKET = ("EVIDENCE_ACCESS_KEY_ID", "EVIDENCE_SECRET_ACCESS_KEY")
SECRET_PROJECT = "PROJECT_ENV"
ITEMS = ("ai-yml", "config", "secrets", "vars", "labels", "evidencias", "topic", "bucket")
SKILL_SECTIONS = ("evidencia ideal", "como subir", "dados e acesso", "antes", "limites")
# Cor e descricao canonicas (skills/issue-labeling/SKILL.md).
FLOW_LABELS = {
    "go": ("3FB950", "Pode seguir: roda a etapa do estado atual"),
    "needs-triage": ("FBCA04", "Issue crua aguardando triagem"),
    "needs-discovery": ("FBCA04", "Falta descobrir os limites do que se quer construir"),
    "needs-refinement": ("FBCA04", "Falta lapidar requisitos ou esclarecer a solicitacao"),
    "needs-break-down": ("FBCA04", "Escopo entendido, falta quebrar em sub-tasks"),
    "ready-for-agent": ("0E8A16", "Pronto para o agente executar"),
    "ready-for-human": ("1D76DB", "Unidade executavel exclusivamente humana; o agente so orienta"),
    "awaiting-pr-review": ("5319E7", "Implementacao concluida pelo agente; PR aberto e pronto para analise"),
    "wontfix": ("FFFFFF", "Nao sera feito"),
    "deferred": ("CFD3D7", "Despriorizado: nao agora, pode voltar"),
    "work-in-progress": ("D93F0B", "Worker em execucao nesta issue"),
    "awaiting-reply": ("C5DEF5", "Rodada encerrada com pergunta impeditiva; aguarda resposta humana"),
    "priority": ("B60205", "Prioridade decidida pelo humano"),
}
TYPE_LABELS = {"bug", "feature", "feat", "infra", "docs", "refactor", "task", "enhancement"}
STATUS_ORDER = {"falta": 0, "diverge": 1, "manual": 2, "info": 3, "ok": 4}


class DoctorError(Exception):
    """Erro de acesso ou de argumento: saida 2."""


class ConfigError(Exception):
    """Arquivo de configuracao fora do subconjunto aceito."""


# --------------------------------------------------------------------- gh

def gh(*args, stdin=None, check=True):
    result = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise DoctorError(f"gh {' '.join(args[:3])}: {(result.stderr or result.stdout).strip()}")
    return result


def api(path, method=None, body=None, ok404=False, jq=None):
    cmd = ["api", path]
    if method:
        cmd += ["--method", method]
    if jq:
        cmd += ["--jq", jq]
    stdin = None
    if body is not None:
        cmd += ["--input", "-"]
        stdin = json.dumps(body)
    result = gh(*cmd, stdin=stdin, check=False)
    if result.returncode != 0:
        err = (result.stderr or result.stdout).strip()
        if ok404 and "HTTP 404" in err:
            return None
        raise DoctorError(f"gh api {method or 'GET'} {path}: {err}")
    out = result.stdout.strip()
    if not out:
        return None
    return out if jq else json.loads(out)


def fetch_file(repo, path, ref=None):
    """Conteudo de um arquivo pela API de contents, ou None quando nao existe."""
    url = f"repos/{repo}/contents/{path}" + (f"?ref={ref}" if ref else "")
    data = api(url, ok404=True)
    if data is None or data.get("type") != "file":
        return None
    return base64.b64decode(data["content"]).decode("utf-8")


def file_sha(repo, path, ref):
    data = api(f"repos/{repo}/contents/{path}?ref={ref}", ok404=True)
    return data["sha"] if data else None


# ------------------------------------------------------------ texto puro

def strip_accents(text):
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text):
    """Comparacao de arquivos: ignora espaco no fim das linhas e do arquivo."""
    return "\n".join(line.rstrip() for line in (text or "").strip().splitlines())


def parse_simple_yaml(text):
    """Le o subconjunto de YAML do arquivo de configuracao: um mapa de
    `chave: valor` no topo, com escalares de texto ou blocos literais (`|`).
    Qualquer outra coisa (lista, mapa aninhado, bloco `>`) e ConfigError.
    Retorna dict chave -> texto."""
    result = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise ConfigError(f"linha {i + 1}: indentacao inesperada fora de um bloco")
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:(?:\s+(.*?))?\s*$", line)
        if not m:
            raise ConfigError(f"linha {i + 1}: esperado `chave: valor`")
        key, value = m.group(1), m.group(2)
        if value is None or value == "":
            # Valor vazio ou mapa/lista aninhada nas linhas seguintes
            if i + 1 < len(lines) and lines[i + 1][:1] in " \t" and lines[i + 1].strip():
                raise ConfigError(f"linha {i + 1}: `{key}` precisa ser texto (escalar ou bloco |)")
            result[key] = ""
            i += 1
            continue
        if value.startswith("#"):
            result[key] = ""
            i += 1
            continue
        if value in ("|", "|-", "|+"):
            i += 1
            block = []
            indent = None
            while i < len(lines):
                raw = lines[i]
                if raw.strip() == "":
                    block.append("")
                    i += 1
                    continue
                cur = len(raw) - len(raw.lstrip(" "))
                if indent is None:
                    if cur == 0:
                        break
                    indent = cur
                if cur < indent:
                    break
                block.append(raw[indent:])
                i += 1
            while block and block[-1] == "":
                block.pop()
            result[key] = "\n".join(block) + ("\n" if block and value != "|-" else "")
            continue
        if value.startswith((">", "[", "{", "-", "&", "*", "!")):
            raise ConfigError(f"linha {i + 1}: `{key}` precisa ser texto (escalar ou bloco |)")
        if (value[0] == value[-1] and value[0] in "\"'" and len(value) >= 2):
            value = value[1:-1]
        else:
            value = re.sub(r"\s+#.*$", "", value)
        result[key] = value
        i += 1
    return result


def extract_with_block(ai_yml):
    """Inputs inline do bloco `with:` do job `ai` de um ai.yml. Linhas
    comentadas nao contam. Valores que sao expressoes (`${{ ... }}`) sao
    descartados: nao sao valor de projeto. Retorna dict chave -> texto."""
    lines = ai_yml.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if re.match(r"^\s{4}with:\s*$", l))
    except StopIteration:
        return {}
    block = []
    for raw in lines[start + 1:]:
        if raw.strip() == "" or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent <= 4:
            break
        block.append(raw[6:])
    try:
        values = parse_simple_yaml("\n".join(block))
    except ConfigError:
        return {}
    return {k: v for k, v in values.items() if k in CONFIG_KEYS and v.strip() and "${{" not in v}


def render_config_yaml(values):
    """Texto de .github/ai-workflows.yml a partir de um dict."""
    out = ["# Comandos deste repositorio para o fluxo de IA (samuel-morrissey/ai-workflows).",
           "# Chaves: setup_commands, quality_checks, evidence_tools, um comando por linha."]
    for key in CONFIG_KEYS:
        if key not in values:
            continue
        value = values[key].rstrip("\n")
        if "\n" in value or not re.fullmatch(r"[A-Za-z0-9_./:@+=-]+", value):
            out.append(f"{key}: |")
            out.extend(f"  {line}" if line else "" for line in value.split("\n"))
        else:
            out.append(f"{key}: {value}")
    return "\n".join(out) + "\n"


def parse_env(text):
    result = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            result[key] = value
    return result


def skill_missing_sections(text):
    body = strip_accents(text or "").lower()
    headings = {h.strip() for h in re.findall(r"^#+\s*(.+?)\s*$", body, re.MULTILINE)}
    return [s for s in SKILL_SECTIONS if not any(h == s or h.startswith(s + " ") for h in headings)]


# ------------------------------------------------------------- relatorio

class Finding:
    def __init__(self, item, status, detail, fix=None, fixer=None):
        self.item, self.status, self.detail, self.fix, self.fixer = item, status, detail, fix, fixer

    def as_dict(self):
        return {"item": self.item, "status": self.status, "detail": self.detail, "fix": self.fix}


def exit_code(findings):
    return 1 if any(f.status in ("falta", "diverge", "manual") for f in findings) else 0


def render_report(repo, findings, actions=None):
    width = max(len(f.item) for f in findings) if findings else 10
    lines = [f"== {repo}"]
    for f in findings:
        lines.append(f"  {f.item.ljust(width)}  {f.status.ljust(7)}  {f.detail}")
    fixes = [f for f in findings if f.fix and f.status != "ok"]
    if fixes:
        lines.append("  correcoes:")
        for f in fixes:
            lines.append(f"    [{f.item}] {f.fix}")
    if actions:
        lines.append("  acoes:")
        lines.extend(f"    {a}" for a in actions)
    return "\n".join(lines)


# ------------------------------------------------------------- contexto

class Repo:
    """Tudo que os itens compartilham sobre o repositorio alvo."""

    def __init__(self, full, ref, template_path=None, config_env_path=None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", full):
            raise DoctorError(f"repositorio invalido: {full} (esperado owner/repo)")
        self.full = full
        self.owner, self.name = full.split("/", 1)
        self.ref = ref
        info = api(f"repos/{full}", ok404=True)
        if info is None:
            raise DoctorError(f"{full}: repositorio nao encontrado ou sem acesso")
        if info.get("archived"):
            raise DoctorError(f"{full}: repositorio arquivado")
        self.default_branch = info.get("default_branch")
        if not self.default_branch:
            raise DoctorError(f"{full}: sem branch padrao")
        self.private = bool(info.get("private"))
        self.is_org = info["owner"]["type"] == "Organization"
        self.admin = bool(info.get("permissions", {}).get("admin"))
        self.in_actions = bool(os.environ.get("GITHUB_ACTIONS"))
        if template_path:
            with open(template_path, encoding="utf-8") as fh:
                self.template = fh.read()
        else:
            self.template = fetch_file(TEMPLATE_REPO, AI_YML, ref)
            if self.template is None:
                raise DoctorError(f"modelo {AI_YML} nao encontrado em {TEMPLATE_REPO}@{ref}")
        path = config_env_path or os.environ.get("AI_WORKFLOWS_CONFIG") or os.path.expanduser("~/.config/ai-workflows/config.env")
        self.config_env_path = path
        self.config_env = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                self.config_env = parse_env(fh.read())
        # Arquivos do repositorio, lidos uma vez
        self.ai_yml = fetch_file(full, AI_YML, self.default_branch)
        self.inline = extract_with_block(self.ai_yml) if self.ai_yml else {}
        self.config_text = fetch_file(full, CONFIG_FILE, self.default_branch)
        self.config_error = None
        self.config = {}
        if self.config_text is not None:
            try:
                self.config = parse_simple_yaml(self.config_text)
            except ConfigError as exc:
                self.config_error = str(exc)
        self._vars = None
        self._secrets = None

    # Valor efetivo de uma chave: arquivo, senao inline do ai.yml
    def effective(self, key):
        if key in self.config and self.config[key].strip():
            return self.config[key]
        return self.inline.get(key, "")

    def wants_evidence(self):
        return bool(self.effective("evidence_tools").strip())

    # Variaveis e secrets visiveis ao repositorio: (nivel, valor) por nome
    def variables(self):
        if self._vars is None:
            found, errors = {}, []
            r = gh("variable", "list", "-R", self.full, "--json", "name,value", check=False)
            if r.returncode == 0:
                for v in json.loads(r.stdout or "[]"):
                    found[v["name"]] = ("repo", v["value"])
            else:
                errors.append(f"repo: {(r.stderr or r.stdout).strip()}")
            if self.is_org:
                r = gh("variable", "list", "--org", self.owner, "--json", "name,value,visibility,selectedReposURL", check=False)
                if r.returncode == 0:
                    for v in json.loads(r.stdout or "[]"):
                        if v["name"] not in found and self._org_item_reaches(v, "variables"):
                            found[v["name"]] = ("org", v["value"])
                else:
                    errors.append(f"org: {(r.stderr or r.stdout).strip()}")
            self._vars = (found, errors)
        return self._vars

    def secrets(self):
        if self._secrets is None:
            found, errors = {}, []
            r = gh("secret", "list", "-R", self.full, "--json", "name", check=False)
            if r.returncode == 0:
                for s in json.loads(r.stdout or "[]"):
                    found[s["name"]] = "repo"
            else:
                errors.append(f"repo: {(r.stderr or r.stdout).strip()}")
            if self.is_org:
                r = gh("secret", "list", "--org", self.owner, "--json", "name,visibility,selectedReposURL", check=False)
                if r.returncode == 0:
                    for s in json.loads(r.stdout or "[]"):
                        if s["name"] not in found and self._org_item_reaches(s, "secrets"):
                            found[s["name"]] = "org"
                else:
                    errors.append(f"org: {(r.stderr or r.stdout).strip()}")
            self._secrets = (found, errors)
        return self._secrets

    def _org_item_reaches(self, item, kind):
        vis = item.get("visibility", "all")
        if vis == "all":
            return True
        if vis == "private":
            return self.private
        names = api(f"orgs/{self.owner}/actions/{kind}/{item['name']}/repositories", ok404=True) or {}
        return any(r["name"] == self.name for r in names.get("repositories", []))


# ----------------------------------------------------------------- itens

def check_ai_yml(repo):
    desired = repo.template
    if repo.ai_yml is not None and normalize(repo.ai_yml) == normalize(desired):
        return Finding("ai-yml", "ok", f"igual ao modelo ({TEMPLATE_REPO}@{repo.ref})")
    if repo.ai_yml is None:
        status, detail = "falta", f"{AI_YML} nao existe na branch {repo.default_branch}"
    else:
        status, detail = "diverge", "diferente do modelo"
        if repo.inline:
            detail += f"; inputs inline em with: ({', '.join(sorted(repo.inline))}) migram para {CONFIG_FILE}"
    # Um PR aberto de uma branch ai-workflows/* (do doctor ou da skill
    # setup-repo) que ja traz o modelo resolve o item: so falta o merge, que
    # e humano. Abrir outro PR seria duplicar.
    for pr in model_prs(repo):
        on_branch = fetch_file(repo.full, AI_YML, pr["headRefName"])
        if on_branch is not None and normalize(on_branch) == normalize(desired):
            return Finding("ai-yml", "manual", f"{detail}; PR aberto com o modelo, falta o merge: {pr['url']}")
        if pr["headRefName"] == DOCTOR_BRANCH:
            detail += f"; PR do doctor desatualizado: {pr['url']}"
    return Finding("ai-yml", status, detail,
                   fix=f"python3 scripts/doctor.py fix {repo.full} --only ai-yml", fixer=fix_ai_yml)


def model_prs(repo):
    """PRs abertos para a branch padrao vindos de branches ai-workflows/*."""
    out = gh("pr", "list", "-R", repo.full, "--base", repo.default_branch, "--state", "open",
             "--limit", "100", "--json", "number,url,headRefName", check=False)
    if out.returncode != 0:
        return []
    prs = json.loads(out.stdout or "[]")
    return [pr for pr in prs if pr["headRefName"].startswith(BRANCH_PREFIX)]


def doctor_pr(repo):
    out = gh("pr", "list", "-R", repo.full, "--head", DOCTOR_BRANCH, "--state", "open",
             "--json", "number,url", check=False)
    if out.returncode != 0:
        return None
    prs = json.loads(out.stdout or "[]")
    return prs[0] if prs else None


def fix_ai_yml(repo):
    """Abre (ou atualiza) o PR do doctor com o ai.yml do modelo e, quando o
    ai.yml atual tem inputs inline, o arquivo de configuracao com eles."""
    files = {AI_YML: repo.template}
    migrated = {}
    if repo.inline and repo.config_text is None:
        migrated = dict(repo.inline)
        files[CONFIG_FILE] = render_config_yaml(migrated)
    pr = doctor_pr(repo)
    if pr is None:
        head_sha = api(f"repos/{repo.full}/git/ref/heads/{repo.default_branch}")["object"]["sha"]
        existing = api(f"repos/{repo.full}/git/ref/heads/{DOCTOR_BRANCH}", ok404=True)
        if existing is None:
            api(f"repos/{repo.full}/git/refs", "POST", {"ref": f"refs/heads/{DOCTOR_BRANCH}", "sha": head_sha})
        else:
            api(f"repos/{repo.full}/git/refs/heads/{DOCTOR_BRANCH}", "PATCH", {"sha": head_sha, "force": True})
    changed = []
    for path, content in files.items():
        current = fetch_file(repo.full, path, DOCTOR_BRANCH)
        if current is not None and normalize(current) == normalize(content):
            continue
        body = {"message": f"chore(ai): atualiza {path} pelo doctor do ai-workflows",
                "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                "branch": DOCTOR_BRANCH}
        sha = file_sha(repo.full, path, DOCTOR_BRANCH)
        if sha:
            body["sha"] = sha
        api(f"repos/{repo.full}/contents/{path}", "PUT", body)
        changed.append(path)
    if pr is None:
        title = f"chore(ai): atualiza {AI_YML} para o modelo do ai-workflows"
        lines = [f"Atualiza `{AI_YML}` para a copia identica do modelo em {TEMPLATE_REPO}@{repo.ref}."]
        if migrated:
            lines.append(f"Os inputs que estavam inline no `with:` ({', '.join(sorted(migrated))}) "
                         f"passam para `{CONFIG_FILE}`, sem mudanca de valor.")
        lines.append("")
        lines.append("Aberto por `scripts/doctor.py` do ai-workflows. Rodar o doctor de novo "
                     "atualiza este PR em vez de abrir outro.")
        out = gh("pr", "create", "-R", repo.full, "--base", repo.default_branch, "--head", DOCTOR_BRANCH,
                 "--title", title, "--body", "\n".join(lines))
        return f"PR aberto: {out.stdout.strip()}" + (f" (arquivos: {', '.join(changed)})" if changed else "")
    if changed:
        return f"PR {pr['url']} atualizado: {', '.join(changed)}"
    return f"PR {pr['url']} ja tem o conteudo do modelo"


def check_config(repo):
    if repo.config_text is None:
        if repo.inline:
            return Finding("config", "falta", f"{CONFIG_FILE} nao existe; os inputs estao inline no ai.yml e migram com o item ai-yml",
                           fix=f"python3 scripts/doctor.py fix {repo.full} --only ai-yml")
        return Finding("config", "manual", f"{CONFIG_FILE} nao existe e o ai.yml nao tem inputs: use a skill setup-repo para inferir os comandos",
                       fix=f"/samuel-morrissey-skills:setup-repo {repo.full}")
    if repo.config_error:
        return Finding("config", "diverge", f"{CONFIG_FILE} invalido: {repo.config_error}")
    unknown = sorted(k for k in repo.config if k not in CONFIG_KEYS)
    notes = []
    if unknown:
        notes.append(f"chaves desconhecidas ignoradas pelo workflow: {', '.join(unknown)}")
    if not repo.config.get("quality_checks", "").strip():
        notes.append("sem quality_checks: o PR sai declarando que nao houve verificacao")
    if not repo.config.get("evidence_tools", "").strip():
        notes.append("sem evidence_tools: o QA independente nao roda")
    status = "diverge" if unknown else ("info" if notes else "ok")
    return Finding("config", status, "; ".join(notes) or f"{CONFIG_FILE} valido")


def check_secrets(repo):
    found, errors = repo.secrets()
    if errors and not found:
        return Finding("secrets", "manual", "sem permissao para listar secrets: " + " | ".join(errors))
    missing, notes, fixers = [], [], []
    required = [SECRET_TOKEN]
    if effective_bucket(repo)[0]:
        required += list(SECRET_BUCKET)
    for name in required:
        if name in found:
            notes.append(f"{name} ({found[name]})")
        else:
            missing.append(name)
    if SECRET_PROJECT in found:
        notes.append(f"{SECRET_PROJECT} ({found[SECRET_PROJECT]})")
    if not missing:
        return Finding("secrets", "ok", ", ".join(notes))
    available = [n for n in missing if n in repo.config_env]
    unavailable = [n for n in missing if n not in repo.config_env]
    detail = "faltam: " + ", ".join(missing)
    fix = None
    fixer = None
    if available:
        fixer = lambda r, names=available: fix_secrets(r, names)
        fix = f"python3 scripts/doctor.py fix {repo.full} --only secrets"
    if unavailable:
        detail += f"; sem valor em {repo.config_env_path} para: {', '.join(unavailable)}"
        fix = fix or " && ".join(f"gh secret set {n} -R {repo.full}" for n in unavailable)
    return Finding("secrets", "falta" if available else "manual", detail, fix=fix, fixer=fixer)


def fix_secrets(repo, names):
    done = []
    for name in names:
        gh("secret", "set", name, "-R", repo.full, stdin=repo.config_env[name])
        done.append(name)
    repo._secrets = None
    return f"secrets gravados em {repo.full}: {', '.join(done)}"


def effective_bucket(repo):
    """(bucket, url, endpoint, origem) em vigor: arquivo/inline do repositorio, senao variaveis."""
    file_values = tuple(repo.effective(k) for k in ("evidence_bucket", "evidence_public_url", "evidence_endpoint"))
    if file_values[0].strip():
        return (*[v.strip() for v in file_values], "arquivo")
    found, _ = repo.variables()
    vals = tuple(found.get(n, (None, ""))[1] for n in VAR_NAMES)
    return (*vals, "vars")


def check_vars(repo):
    found, errors = repo.variables()
    if errors and not found and not repo.config_env:
        return Finding("vars", "manual", "sem permissao para listar variaveis: " + " | ".join(errors))
    expected = {n: repo.config_env[n] for n in VAR_NAMES if repo.config_env.get(n)}
    present = {n: found[n] for n in VAR_NAMES if n in found}
    bucket = effective_bucket(repo)
    if bucket[3] == "arquivo":
        where = CONFIG_FILE if repo.config.get("evidence_bucket") else "with: do ai.yml"
        return Finding("vars", "info", f"bucket definido em {where} ({bucket[0]}); para padronizar, mova para as variaveis EVIDENCE_*")
    if not expected:
        if present:
            return Finding("vars", "ok", ", ".join(f"{n} ({present[n][0]})" for n in present))
        return Finding("vars", "info", "sem bucket: evidencias vao como artifact da run (defina EVIDENCE_* no config.env para ligar)")
    wrong = {n: v for n, v in expected.items() if n in present and present[n][1] != v}
    missing = [n for n in expected if n not in present]
    if not wrong and not missing:
        return Finding("vars", "ok", ", ".join(f"{n} ({present[n][0]})" for n in expected))
    parts = []
    if missing:
        parts.append("faltam: " + ", ".join(missing))
    if wrong:
        parts.append("diferentes do config.env: " + ", ".join(wrong))
    level = "org" if repo.is_org else "repo"
    return Finding("vars", "falta" if missing and not wrong else "diverge", "; ".join(parts) + f" (nivel: {level})",
                   fix=f"python3 scripts/doctor.py fix {repo.full} --only vars",
                   fixer=lambda r, names=missing + list(wrong): fix_vars(r, names))


def fix_vars(repo, names):
    done = []
    for name in names:
        value = repo.config_env[name]
        if repo.is_org:
            gh("variable", "set", name, "--org", repo.owner, "--visibility", "all", "--body", value)
        else:
            gh("variable", "set", name, "-R", repo.full, "--body", value)
        done.append(name)
    repo._vars = None
    return f"variaveis gravadas ({'org ' + repo.owner if repo.is_org else repo.full}): {', '.join(done)}"


def label_plan(labels):
    """Separa os labels do fluxo em: ausentes e existentes com cor ou
    descricao fora do canonico. `labels` e {nome: {"color", "description"}}."""
    missing = [n for n in FLOW_LABELS if n not in labels]
    different = [n for n, (color, desc) in FLOW_LABELS.items()
                 if n in labels and ((labels[n].get("color") or "").upper() != color
                                     or (labels[n].get("description") or "") != desc)]
    return missing, different


def label_collisions(labels):
    return sorted(n for n in labels if n.startswith("priority-") or n.lower() in TYPE_LABELS)


def check_labels(repo):
    out = gh("label", "list", "-R", repo.full, "--limit", "300", "--json", "name,color,description")
    labels = {l["name"]: l for l in json.loads(out.stdout or "[]")}
    missing, different = label_plan(labels)
    collisions = label_collisions(labels)
    collision_note = ("labels do repositorio que colidem com o vocabulario do fluxo (decida o mapeamento): "
                      + ", ".join(collisions)) if collisions else ""
    if missing or different:
        parts = []
        if missing:
            parts.append("faltam: " + ", ".join(missing))
        if different:
            parts.append("cor ou descricao fora do canonico: " + ", ".join(different))
        if collision_note:
            parts.append(collision_note)
        return Finding("labels", "falta" if missing else "diverge", "; ".join(parts),
                       fix=f"python3 scripts/doctor.py fix {repo.full} --only labels", fixer=fix_labels)
    if collision_note:
        return Finding("labels", "info", collision_note)
    return Finding("labels", "ok", f"os {len(FLOW_LABELS)} labels do fluxo existem com cor e descricao canonicas")


def fix_labels(repo):
    """Cria os labels do fluxo que faltam e corrige cor e descricao dos que
    divergem. Nunca apaga nem renomeia label."""
    out = gh("label", "list", "-R", repo.full, "--limit", "300", "--json", "name,color,description")
    labels = {l["name"]: l for l in json.loads(out.stdout or "[]")}
    missing, different = label_plan(labels)
    for name in missing:
        color, desc = FLOW_LABELS[name]
        gh("label", "create", name, "-R", repo.full, "--color", color, "--description", desc)
    for name in different:
        color, desc = FLOW_LABELS[name]
        gh("label", "edit", name, "-R", repo.full, "--color", color, "--description", desc)
    done = []
    if missing:
        done.append("criados: " + ", ".join(missing))
    if different:
        done.append("corrigidos: " + ", ".join(different))
    return "labels " + "; ".join(done) if done else "labels ja canonicos"


def check_evidencias(repo):
    text = fetch_file(repo.full, SKILL_FILE, repo.default_branch)
    if text is None:
        if repo.wants_evidence():
            return Finding("evidencias", "manual", f"{SKILL_FILE} nao existe e evidence_tools esta ligado: o QA segue o padrao por tipo de projeto",
                           fix=f"/samuel-morrissey-skills:setup-repo {repo.full}")
        return Finding("evidencias", "info", f"{SKILL_FILE} nao existe; sem evidence_tools, o QA nao roda")
    missing = skill_missing_sections(text)
    if missing:
        return Finding("evidencias", "diverge", "secoes ausentes no SKILL.md: " + ", ".join(missing),
                       fix=f"/samuel-morrissey-skills:setup-repo {repo.full}")
    return Finding("evidencias", "ok", f"{SKILL_FILE} com as cinco secoes")


def check_topic(repo):
    names = (api(f"repos/{repo.full}/topics") or {}).get("names", [])
    if TOPIC in names:
        return Finding("topic", "ok", f"topic `{TOPIC}` presente")
    return Finding("topic", "falta", f"topic `{TOPIC}` ausente: o repositorio fica fora do inventario (--all)",
                   fix=f"gh repo edit {repo.full} --add-topic {TOPIC}", fixer=fix_topic)


def fix_topic(repo):
    gh("repo", "edit", repo.full, "--add-topic", TOPIC)
    return f"topic `{TOPIC}` adicionado em {repo.full}"


def check_bucket(repo):
    bucket, url, endpoint, origin = effective_bucket(repo)
    if not bucket:
        return Finding("bucket", "info", "sem bucket configurado")
    if not url:
        return Finding("bucket", "diverge", f"{bucket} sem URL publica: o workflow cai para artifact")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except (urllib.error.URLError, OSError) as exc:
        return Finding("bucket", "info", f"{url} nao respondeu: {exc}")
    return Finding("bucket", "info", f"{url} respondeu HTTP {code} ({origin}{', endpoint ' + endpoint if endpoint else ''})")


CHECKS = {
    "ai-yml": check_ai_yml,
    "config": check_config,
    "secrets": check_secrets,
    "vars": check_vars,
    "labels": check_labels,
    "evidencias": check_evidencias,
    "topic": check_topic,
    "bucket": check_bucket,
}


# ------------------------------------------------------------------ main

def run_checks(repo, only):
    findings = []
    for item in ITEMS:
        if only and item not in only:
            continue
        try:
            findings.append(CHECKS[item](repo))
        except DoctorError as exc:
            findings.append(Finding(item, "manual", f"erro de acesso: {exc}"))
    return findings


def run_repo(full, args):
    repo = Repo(full, args.ref, args.template, args.config_env)
    findings = run_checks(repo, args.only)
    actions = []
    if args.command == "fix":
        for f in findings:
            if f.status in ("falta", "diverge") and f.fixer:
                try:
                    actions.append(f.fixer(repo))
                except DoctorError as exc:
                    actions.append(f"[{f.item}] falhou: {exc}")
        if actions:
            # Releitura depois das correcoes: o relatorio final e o estado real
            repo = Repo(full, args.ref, args.template, args.config_env)
            findings = run_checks(repo, args.only)
        else:
            actions.append("nada a corrigir")
    return repo, findings, actions


def list_repos(owners):
    repos = []
    for owner in owners:
        out = gh("repo", "list", owner, "--topic", TOPIC, "--limit", "200", "--no-archived",
                 "--json", "nameWithOwner")
        repos += [r["nameWithOwner"] for r in json.loads(out.stdout or "[]")]
    return repos


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("check", "fix"))
    parser.add_argument("repo", nargs="?", help="owner/repo")
    parser.add_argument("--all", nargs="+", metavar="OWNER", help="todos os repositorios com o topic ai-workflows destes donos")
    parser.add_argument("--only", help="itens separados por virgula")
    parser.add_argument("--ref", default="main", help=f"ref de {TEMPLATE_REPO} com o modelo do ai.yml")
    parser.add_argument("--template", help="arquivo local com o modelo do ai.yml (em vez de baixar)")
    parser.add_argument("--config-env", help="arquivo .env com secrets e variaveis do dono")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.repo) == bool(args.all):
        parser.error("informe owner/repo ou --all <owner>...")
    if args.only:
        args.only = [i.strip() for i in args.only.split(",") if i.strip()]
        bad = [i for i in args.only if i not in ITEMS]
        if bad:
            parser.error(f"item desconhecido: {', '.join(bad)} (validos: {', '.join(ITEMS)})")
    try:
        targets = [args.repo] if args.repo else list_repos(args.all)
        if not targets:
            print(f"nenhum repositorio com o topic `{TOPIC}` em: {', '.join(args.all)}", file=sys.stderr)
            return 0
        worst = 0
        results = []
        for full in targets:
            repo, findings, actions = run_repo(full, args)
            worst = max(worst, exit_code(findings))
            if args.json:
                results.append({"repo": full, "default_branch": repo.default_branch, "owner_type": "org" if repo.is_org else "user",
                                "findings": [f.as_dict() for f in findings], "actions": actions, "exit": exit_code(findings)})
            else:
                print(render_report(full, findings, actions if args.command == "fix" else None))
        if args.json:
            print(json.dumps(results if args.all else results[0], ensure_ascii=False, indent=2))
        return worst
    except DoctorError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
