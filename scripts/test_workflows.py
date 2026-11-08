#!/usr/bin/env python3
"""Testes do passo "Comentar falha da rodada" dos workflows reutilizaveis
(issue-triage, issue-refinement, issue-break-down, issue-remote-implement,
issue-sub-task e pr-fix), sem gh nem rede. O passo e a composite action round-failure:
cada workflow a chama como ultimo passo, e o `run` dela e extraido do YAML e
roda num bash com um `gh` falso.

Tambem testa o passo "Garantir awaiting-pr-review se ha PR aberto" do
issue-remote-implement.yml, com um `gh` falso que guarda o estado do issue,
e o passo "Resolver responsavel" (action responsible) das etapas de issue: a
posicao antes do agente, a frase que chega ao system prompt e os modelos de
comentario das skills que levam a mencao. Do pr-fix.yml, testa a frase "Quem
disparou a rodada:" que o passo "Resolver alvo" monta para o handoff no PR; da
remote-to-pr, o pedido de review e o fallback com `@`. Do pr-closed.yml, o
destino do router.yml para PR fechado sem merge e o passo que devolve o
estado dos issues, com um `gh` falso que guarda os issues e os PRs.

    python3 scripts/test_workflows.py
"""

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION = ROOT / ".github" / "actions" / "round-failure" / "action.yml"
USES = "samuel-morrissey/ai-workflows/.github/actions/round-failure@main"
FILES = ["issue-triage.yml", "issue-refinement.yml", "issue-break-down.yml",
         "issue-remote-implement.yml", "issue-sub-task.yml", "pr-fix.yml"]
STEP_NAME = "Comentar falha da rodada"
PR_FIX = "pr-fix.yml"

# Resolucao falsa no lugar de scripts/responsible.py: imprime $FAKE_RESP, ou
# falha com FAKE_RESP_FAIL=1, e registra os argumentos em $FAKE_RESP_LOG.
FAKE_RESPONSIBLE = r'''import os, sys
with open(os.environ["FAKE_RESP_LOG"], "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\n")
if os.environ.get("FAKE_RESP_FAIL") == "1":
    print("gh api repos/o/r/issues/46: HTTP 503", file=sys.stderr)
    sys.exit(2)
print(os.environ["FAKE_RESP"])
'''

FAKE_GH = r'''#!/usr/bin/env bash
# gh falso: registra cada chamada em $FAKE_GH_LOG e responde conforme o ambiente.
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "api repos"*)
    [ "${FAKE_GH_API_FAIL:-}" = "1" ] && { echo "api indisponivel" >&2; exit 1; }
    cat "$FAKE_GH_JOBS"
    ;;
  "issue comment")
    [ "${FAKE_GH_COMMENT_FAIL:-}" = "1" ] && { echo "comentario recusado" >&2; exit 1; }
    shift 2
    number="$1"; shift
    while [ $# -gt 0 ]; do
      if [ "$1" = "--body" ]; then printf '%s' "$2" > "$FAKE_GH_BODY"; shift; fi
      shift
    done
    echo "https://github.com/o/r/issues/$number#issuecomment-1"
    ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 2 ;;
esac
'''

JOBS = {"jobs": [
    {"name": "ai / Check caller", "runner_name": "GitHub Actions 1", "status": "completed",
     "steps": [{"name": "Comparar", "conclusion": "success"}]},
    {"name": "ai / Implement Issue", "runner_name": "GitHub Actions 7", "status": "in_progress",
     "steps": [{"name": "Resolver alvo", "conclusion": "success"},
               {"name": "Preparar ambiente do consumidor", "conclusion": "failure"},
               {"name": "Remover work-in-progress", "conclusion": "success"},
               {"name": STEP_NAME, "conclusion": None}]},
]}


def steps_of(text):
    """Lista de (nome, bloco de texto do passo) do unico job do workflow."""
    m = re.search(r"^    steps:\n", text, re.M)
    body = text[m.end():]
    parts = re.split(r"^(?=      - )", body, flags=re.M)
    out = []
    for part in parts:
        name = re.search(r"^      - name: (.+)$", part, re.M)
        if name:
            out.append((name.group(1).strip(), part))
        elif part.startswith("      - uses:"):
            out.append((re.search(r"uses: (\S+)", part).group(1), part))
    return out


def parse_step(block):
    """Extrai if, continue-on-error, uses e o `with:` de um passo do workflow."""
    cond = re.search(r"^        if: (.+)$", block, re.M)
    coe = re.search(r"^        continue-on-error: (\S+)$", block, re.M)
    uses = re.search(r"^        uses: (\S+)$", block, re.M)
    with_ = dict(re.findall(r"^          ([a-z_]+): (.*)$", block.split("        with:\n", 1)[-1], re.M))
    return {"if": cond and cond.group(1).strip(), "continue_on_error": coe and coe.group(1),
            "uses": uses and uses.group(1), "with": with_}


def load_steps():
    return {f: parse_step(dict(steps_of((WORKFLOWS / f).read_text()))[STEP_NAME]) for f in FILES}


def action_run():
    """Texto do `run` do unico passo da action round-failure."""
    run = ACTION.read_text().split("      run: |\n", 1)[1]
    lines = []
    for line in run.splitlines():
        if line.strip() == "":
            lines.append("")
        elif line.startswith("        "):
            lines.append(line[8:])
        else:
            break
    return "\n".join(lines).rstrip("\n") + "\n"


def action_input_default(name):
    m = re.search(r"^  %s:\n(?:    .*\n)*?    default: \"(.*)\"$" % name, ACTION.read_text(), re.M)
    return m.group(1)


class Shape(unittest.TestCase):
    def test_ultimo_passo_de_cada_workflow(self):
        for f in FILES:
            names = [n for n, _ in steps_of((WORKFLOWS / f).read_text())]
            self.assertEqual(names[-1], STEP_NAME, f)
            self.assertEqual(names.count(STEP_NAME), 1, f)

    def test_failure_sem_derrubar_o_job(self):
        for f, step in load_steps().items():
            self.assertEqual(step["if"], "failure()", f)
            self.assertEqual(step["continue_on_error"], "true", f)
            self.assertEqual(step["uses"], USES, f)
            self.assertEqual(step["with"]["number"], "${{ steps.target.outputs.number }}", f)
            self.assertTrue(step["with"]["etapa"], f)

    def test_action_usa_a_resolucao_do_proprio_repositorio(self):
        text = ACTION.read_text()
        self.assertIn("RESPONSIBLE_PY: ${{ github.action_path }}/../../../scripts/responsible.py", text)
        self.assertIn("TRIGGER_LOGIN: ${{ github.event.comment.user.login || github.event.review.user.login }}", text)
        self.assertIn("IS_PR: ${{ github.event.pull_request != null || github.event.issue.pull_request != null }}", text)
        self.assertEqual(action_input_default("mencionar"), "auto")
        self.assertTrue((ROOT / "scripts" / "responsible.py").exists())

    def test_so_o_pr_fix_roda_em_evento_de_pr(self):
        # O modo `auto` marca quem disparou em evento de PR: so vale enquanto
        # o pr-fix e a unica etapa com round-failure que roda nesses eventos.
        router = (WORKFLOWS / "router.yml").read_text()
        jobs = re.split(r"^  (?=[a-z-]+:\n)", router.split("\njobs:\n", 1)[1], flags=re.M)
        checked = set()
        for job in jobs:
            name = job.split(":", 1)[0]
            uses = re.search(r"/\.github/workflows/([\w-]+\.yml)@main", job)
            if not uses or uses.group(1) not in FILES:
                continue
            checked.add(uses.group(1))
            cond = re.search(r"    if: >\n((?:      .*\n)+)", job).group(1)
            on_pr = "pull_request_review" in cond or bool(re.search(r"(?<!!)github\.event\.issue\.pull_request &&", cond))
            self.assertEqual(on_pr, uses.group(1) == PR_FIX, name)
        self.assertEqual(checked, set(FILES))

    def test_action_le_numero_de_issue_e_de_pr(self):
        text = ACTION.read_text()
        self.assertIn("GH_TOKEN: ${{ github.token }}", text)
        self.assertIn("EVENT_NUMBER: ${{ github.event.issue.number || github.event.pull_request.number }}", text)
        self.assertIn("PAYLOAD_NUMBER: ${{ github.event.client_payload.issue }}", text)

    def test_permissao_actions_read(self):
        for f in FILES:
            self.assertIn("\n  actions: read\n", (WORKFLOWS / f).read_text(), f)


class Run(unittest.TestCase):
    """Roda o `run` do passo num bash com gh falso."""

    @classmethod
    def setUpClass(cls):
        cls.script = action_run()
        cls.retomar = action_input_default("retomar")

    def execute(self, env=None, jobs=JOBS, api_fail=False, comment_fail=False,
                resp='{"issue": 46, "logins": [], "rule": "none"}', resp_fail=False):
        tmp = tempfile.mkdtemp(prefix="wf-")
        pathlib.Path(tmp, "responsible.py").write_text(FAKE_RESPONSIBLE)
        gh = pathlib.Path(tmp, "gh")
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        pathlib.Path(tmp, "jobs.json").write_text(json.dumps(jobs))
        script = pathlib.Path(tmp, "step.sh")
        script.write_text(self.script)
        e = {
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "FAKE_GH_LOG": f"{tmp}/log", "FAKE_GH_JOBS": f"{tmp}/jobs.json", "FAKE_GH_BODY": f"{tmp}/body",
            "FAKE_GH_API_FAIL": "1" if api_fail else "", "FAKE_GH_COMMENT_FAIL": "1" if comment_fail else "",
            "GH_TOKEN": "x", "GH_REPO": "o/r", "ETAPA": "implementacao", "NUMBER": "46",
            "EVENT_NUMBER": "", "PAYLOAD_NUMBER": "", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "RUNNER_NAME": "GitHub Actions 7",
            "RETOMAR": self.retomar,
            "RESPONSIBLE_PY": f"{tmp}/responsible.py", "FAKE_RESP": resp, "FAKE_RESP_LOG": f"{tmp}/resp.log",
            "FAKE_RESP_FAIL": "1" if resp_fail else "", "DEFAULT_RESPONSIBLE": "", "MENCIONAR": "auto",
            "TRIGGER_LOGIN": "", "TRIGGER_TYPE": "", "IS_PR": "false",
        }
        e.update(env or {})
        self.resp_log = pathlib.Path(tmp, "resp.log")
        proc = subprocess.run(["bash", "-eo", "pipefail", str(script)], env=e, capture_output=True, text=True)
        log = pathlib.Path(tmp, "log").read_text() if pathlib.Path(tmp, "log").exists() else ""
        body = pathlib.Path(tmp, "body").read_text() if pathlib.Path(tmp, "body").exists() else None
        return proc, log, body

    def test_comenta_passo_e_link(self):
        proc, log, body = self.execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("api repos/o/r/actions/runs/123/attempts/1/jobs", log)
        self.assertIn("issue comment 46 --body", log)
        self.assertIn("## Rodada com falha", body)
        self.assertIn("**implementacao**", body)
        self.assertIn("**Preparar ambiente do consumidor**", body)
        self.assertIn("https://github.com/o/r/actions/runs/123", body)
        self.assertIn("corrija a causa e aplique `go` de novo. Esta falha nao mudou o label de estado.", body)
        self.assertIn("::notice::Falha da rodada registrada no issue #46", proc.stdout)

    def test_filtra_o_job_deste_runner(self):
        jobs = {"jobs": [
            {"runner_name": "GitHub Actions 2", "steps": [{"name": "Outro job", "conclusion": "failure"}]},
            {"runner_name": "GitHub Actions 7", "steps": [{"name": "Meu passo", "conclusion": "failure"}]},
        ]}
        _, _, body = self.execute(jobs=jobs)
        self.assertIn("**Meu passo**", body)
        self.assertNotIn("Outro job", body)

    def test_sem_job_do_runner_usa_qualquer_falha(self):
        jobs = {"jobs": [{"runner_name": "outro", "steps": [{"name": "Baixar o planner", "conclusion": "failure"}]}]}
        _, _, body = self.execute(jobs=jobs)
        self.assertIn("**Baixar o planner**", body)

    def test_api_indisponivel_comenta_so_com_o_link(self):
        proc, _, body = self.execute(api_fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::Nao consegui ler pela API", proc.stdout)
        self.assertIn("https://github.com/o/r/actions/runs/123", body)
        self.assertIn("nao consegui identificar", body)
        self.assertNotIn("no passo **", body)

    def test_comentario_recusado_nao_derruba_o_passo(self):
        proc, log, body = self.execute(comment_fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("issue comment 46", log)
        self.assertIsNone(body)
        self.assertIn("::warning::Nao consegui comentar", proc.stdout)

    def test_sem_issue_nao_comenta(self):
        proc, log, body = self.execute(env={"NUMBER": ""})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(log, "")
        self.assertIsNone(body)
        self.assertIn("nao ha onde comentar", proc.stdout)

    def test_retomar_troca_o_fim_da_frase(self):
        _, _, body = self.execute(env={"RETOMAR": "comente `@claude` de novo."})
        self.assertIn("corrija a causa e comente `@claude` de novo.", body)
        self.assertNotIn("`go`", body)

    def test_marca_o_responsavel_do_issue(self):
        proc, _, body = self.execute(
            resp='{"issue": 46, "logins": ["ana", "bia"], "rule": "assignees"}',
            env={"DEFAULT_RESPONSIBLE": "gil"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("46 --default gil", self.resp_log.read_text())
        self.assertIn("**Responsavel:** @ana @bia", body)
        self.assertIn("## Rodada com falha", body)

    def test_sem_responsavel_diz_e_nao_marca(self):
        proc, _, body = self.execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nao ha responsavel identificavel", body)
        self.assertNotIn("@", body)

    def test_resolucao_falhando_ainda_comenta_sem_mencao(self):
        proc, log, body = self.execute(resp_fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("issue comment 46 --body", log)
        self.assertIn("## Rodada com falha", body)
        self.assertIn("**Preparar ambiente do consumidor**", body)
        self.assertNotIn("@", body)
        self.assertNotIn("Responsavel", body)
        self.assertIn("::warning::Nao consegui resolver o responsavel", proc.stdout)

    def test_resolucao_com_saida_invalida_ainda_comenta(self):
        proc, _, body = self.execute(resp="nao e json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("## Rodada com falha", body)
        self.assertNotIn("@", body)

    def test_pr_fix_marca_quem_disparou(self):
        proc, _, body = self.execute(
            resp='{"issue": 46, "logins": ["ana"], "rule": "author"}',
            env={"IS_PR": "true", "TRIGGER_LOGIN": "revisora", "TRIGGER_TYPE": "User",
                 "ETAPA": "correcao de PR"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("**Quem disparou a rodada:** @revisora", body)
        self.assertNotIn("@ana", body)
        self.assertFalse(self.resp_log.exists(), "o responsavel do issue nao e consultado")

    def test_mencionar_explicito_vence_o_auto(self):
        _, _, body = self.execute(env={"MENCIONAR": "quem-disparou", "TRIGGER_LOGIN": "revisora"})
        self.assertIn("@revisora", body)
        _, _, body = self.execute(resp='{"issue": 46, "logins": ["ana"], "rule": "author"}',
                                  env={"MENCIONAR": "responsavel", "IS_PR": "true", "TRIGGER_LOGIN": "revisora"})
        self.assertIn("**Responsavel:** @ana", body)
        self.assertNotIn("revisora", body)

    def test_pr_fix_sem_humano_no_evento_nao_marca(self):
        proc, _, body = self.execute(env={"IS_PR": "true", "TRIGGER_LOGIN": "x[bot]",
                                          "TRIGGER_TYPE": "Bot"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("@", body)
        self.assertIn("nao identifiquei quem disparou", body)

    def test_numero_vem_do_evento_ou_do_payload(self):
        _, log, _ = self.execute(env={"NUMBER": "", "EVENT_NUMBER": "51"})
        self.assertIn("issue comment 51", log)
        _, log, _ = self.execute(env={"NUMBER": "", "PAYLOAD_NUMBER": "52"})
        self.assertIn("issue comment 52", log)


AGENT_ENV = ROOT / ".github" / "actions" / "agent-env" / "action.yml"


def agent_env_config_run():
    """Texto do `run` do passo "Ler configuracao do repositorio" da agent-env."""
    block = AGENT_ENV.read_text().split("    - name: Ler configuracao do repositorio\n", 1)[1]
    lines = []
    for line in block.split("      run: |\n", 1)[1].splitlines():
        if line.strip() == "":
            lines.append("")
        elif line.startswith("        "):
            lines.append(line[8:])
        else:
            break
    return "\n".join(lines).rstrip("\n") + "\n"


class AgentEnvConfig(unittest.TestCase):
    """O passo que le .github/ai-workflows.yml, com o yq do runner."""

    def setUp(self):
        if not shutil.which("yq"):
            self.skipTest("yq ausente")

    def execute(self, text):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="cfg-"))
        (tmp / ".github").mkdir()
        (tmp / ".github" / "ai-workflows.yml").write_text(text)
        (tmp / "step.sh").write_text(agent_env_config_run())
        env = {"PATH": os.environ["PATH"], "CONFIG_FILE": ".github/ai-workflows.yml",
               "GITHUB_OUTPUT": str(tmp / "out")}
        proc = subprocess.run(["bash", "-e", str(tmp / "step.sh")], cwd=tmp, env=env,
                              capture_output=True, text=True)
        out = (tmp / "out").read_text() if (tmp / "out").exists() else ""
        return proc, out

    def test_default_responsible_sem_aviso_de_chave_desconhecida(self):
        proc, out = self.execute("quality_checks: make test\ndefault_responsible: fulano\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("Chave desconhecida", proc.stdout)
        self.assertRegex(out, r"default_responsible<<EOF_\w+\nfulano\n")

    def test_chave_desconhecida_ainda_avisa(self):
        proc, _ = self.execute("responsavel: fulano\n")
        self.assertIn("Chave desconhecida ignorada: responsavel", proc.stdout)

    def test_web_domains_sem_aviso_de_chave_desconhecida(self):
        proc, _ = self.execute("quality_checks: make test\nweb_domains: |\n  https://docs.asaas.com/reference\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("Chave desconhecida", proc.stdout)

    def test_default_responsible_que_nao_e_texto_falha(self):
        proc, _ = self.execute("default_responsible:\n  - fulano\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("default_responsible precisa ser texto", proc.stdout)


SAFETY_STEP = "Garantir awaiting-pr-review se ha PR aberto"
SAFETY_IF = ("always() && steps.target.outputs.kind == 'pontual' && steps.wip.outcome == 'success'"
             " && steps.wip.outputs.skip != 'true'")
REVIEW_COLOR = "5319E7"
REVIEW_DESC = "Implementacao concluida pelo agente; PR aberto e pronto para analise"

# gh falso com estado: o issue, os labels do repositorio e os PRs ficam em
# $FAKE_STATE (JSON), e as escritas do passo mudam esse estado.
FAKE_GH_STATE = r'''#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
def opt(name):
    return args[args.index(name) + 1] if name in args else None
def save():
    json.dump(state, open(path, "w"))
cmd = " ".join(args[:2])
if state.get("fail") and cmd in state["fail"]:
    print("api indisponivel", file=sys.stderr); sys.exit(1)
issue = state["issue"]
if cmd == "issue view":
    print(json.dumps({"state": issue["state"], "labels": [{"name": n} for n in issue["labels"]]}))
elif cmd == "pr list":
    assert opt("--state") == "open", args
    print(json.dumps([p for p in state["prs"] if p["state"] == "OPEN"]))
elif cmd == "label create":
    if args[2] in state["repo_labels"]:
        print("label ja existe", file=sys.stderr); sys.exit(1)
    state["repo_labels"][args[2]] = {"color": opt("--color"), "description": opt("--description")}
    save()
elif cmd == "issue edit":
    add, remove = opt("--add-label"), opt("--remove-label")
    if add:
        issue["labels"].append(add)
    if remove:
        issue["labels"].remove(remove)
    issue["edits"] = issue.get("edits", 0) + 1
    save()
else:
    print("gh falso: comando inesperado: %s" % " ".join(args), file=sys.stderr); sys.exit(2)
'''


def step_run(block):
    """Texto do `run: |` de um passo do workflow (indentacao de 10)."""
    lines = []
    for line in block.split("        run: |\n", 1)[1].splitlines():
        if line.strip() == "":
            lines.append("")
        elif line.startswith("          "):
            lines.append(line[10:])
        else:
            break
    return "\n".join(lines).rstrip("\n") + "\n"


def pr(number, body, state="OPEN", closes=()):
    return {"number": number, "body": body, "state": state,
            "closingIssuesReferences": [{"number": n} for n in closes]}


class SafetyNetShape(unittest.TestCase):
    """Posicao e condicao do passo no issue-remote-implement.yml."""

    @classmethod
    def setUpClass(cls):
        cls.steps = steps_of((WORKFLOWS / "issue-remote-implement.yml").read_text())
        cls.names = [n for n, _ in cls.steps]

    def test_roda_depois_do_agente_e_antes_de_remover_wip(self):
        self.assertIn(SAFETY_STEP, self.names)
        i = self.names.index(SAFETY_STEP)
        self.assertLess(self.names.index("anthropics/claude-code-action@v1"), i)
        self.assertEqual(self.names[i + 1], "Remover work-in-progress")

    def test_sempre_no_pontual_e_sem_bloquear_o_wip(self):
        step = parse_step(dict(self.steps)[SAFETY_STEP])
        self.assertEqual(step["if"], SAFETY_IF)
        self.assertEqual(step["continue_on_error"], "true")


class SafetyNetRun(unittest.TestCase):
    """Roda o passo num bash com gh falso e confere os labels do issue depois."""

    @classmethod
    def setUpClass(cls):
        block = dict(steps_of((WORKFLOWS / "issue-remote-implement.yml").read_text()))[SAFETY_STEP]
        cls.script = step_run(block)

    def execute(self, prs, labels=("ready-for-agent", "work-in-progress"), state="OPEN",
                repo_labels=None, fail=(), number="4"):
        tmp = tempfile.mkdtemp(prefix="wf-")
        gh = pathlib.Path(tmp, "gh")
        gh.write_text(FAKE_GH_STATE)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        st = pathlib.Path(tmp, "state.json")
        st.write_text(json.dumps({
            "issue": {"state": state, "labels": list(labels)}, "prs": prs, "fail": list(fail),
            "repo_labels": repo_labels if repo_labels is not None else
            {"awaiting-pr-review": {"color": REVIEW_COLOR, "description": REVIEW_DESC}}}))
        script = pathlib.Path(tmp, "step.sh")
        script.write_text(self.script)
        env = {"PATH": f"{tmp}:{os.environ['PATH']}", "FAKE_STATE": str(st),
               "FAKE_GH_LOG": f"{tmp}/log", "GH_TOKEN": "x", "NUMBER": number}
        proc = subprocess.run(["bash", "-eo", "pipefail", str(script)], env=env,
                              capture_output=True, text=True)
        return proc, json.loads(st.read_text())

    def assertUnchanged(self, proc, after, labels=("ready-for-agent", "work-in-progress")):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issue"]["labels"], list(labels))
        self.assertNotIn("edits", after["issue"])
        self.assertIn("::notice::", proc.stdout)

    def test_pr_aberto_com_closes_troca_o_label(self):
        proc, after = self.execute([pr(57, "Closes #4\n\n## Resumo")])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("awaiting-pr-review", after["issue"]["labels"])
        self.assertNotIn("ready-for-agent", after["issue"]["labels"])
        self.assertEqual(after["issue"]["edits"], 1, "troca numa unica operacao")
        self.assertRegex(proc.stdout, r"::notice::.*rede de seguranca.*#57")

    def test_pr_vinculado_pela_api_tambem_conta(self):
        proc, after = self.execute([pr(58, "## Resumo sem linha de vinculo", closes=[4])])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("ready-for-agent", after["issue"]["labels"])
        self.assertIn("#58", proc.stdout)

    def test_handoff_sem_pr_mantem_ready_for_agent(self):
        labels = ("ready-for-agent", "work-in-progress", "awaiting-reply")
        proc, after = self.execute([], labels=labels)
        self.assertUnchanged(proc, after, labels)
        self.assertIn("Nenhum PR aberto fecha #4", proc.stdout)

    def test_handoff_com_pr_aberto_troca_e_mantem_awaiting_reply(self):
        labels = ("ready-for-agent", "work-in-progress", "awaiting-reply")
        _, after = self.execute([pr(59, "Closes #4")], labels=labels)
        self.assertEqual(sorted(after["issue"]["labels"]),
                         ["awaiting-pr-review", "awaiting-reply", "work-in-progress"])

    def test_numero_que_comeca_igual_nao_casa(self):
        prs = [pr(60, "Closes #40", closes=[40]), pr(61, "Closes #41\nParte de #14", closes=[41]),
               pr(62, "Closes #14", closes=[14])]
        proc, after = self.execute(prs)
        self.assertUnchanged(proc, after)

    def test_pr_que_so_cita_nao_casa(self):
        proc, after = self.execute([pr(63, "Parte de #4\nver #4")])
        self.assertUnchanged(proc, after)

    def test_pr_fechado_ou_mergeado_nao_casa(self):
        prs = [pr(64, "Closes #4", state="CLOSED", closes=[4]), pr(65, "Closes #4", state="MERGED", closes=[4])]
        proc, after = self.execute(prs)
        self.assertUnchanged(proc, after)

    def test_skill_ja_trocou_nada_muda(self):
        labels = ("awaiting-pr-review", "work-in-progress")
        proc, after = self.execute([pr(66, "Closes #4")], labels=labels)
        self.assertUnchanged(proc, after, labels)

    def test_issue_fechado_nada_muda(self):
        proc, after = self.execute([pr(67, "Closes #4")], state="CLOSED")
        self.assertUnchanged(proc, after)
        self.assertIn("fechado", proc.stdout)

    def test_cria_o_label_canonico_se_faltar(self):
        _, after = self.execute([pr(68, "Closes #4")], repo_labels={})
        self.assertEqual(after["repo_labels"]["awaiting-pr-review"],
                         {"color": REVIEW_COLOR, "description": REVIEW_DESC})
        self.assertIn("awaiting-pr-review", after["issue"]["labels"])

    def test_falha_de_api_falha_o_passo_sem_mexer(self):
        # O passo tem continue-on-error: a falha nao impede o Remover work-in-progress.
        proc, after = self.execute([pr(69, "Closes #4")], fail=["pr list"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(after["issue"]["labels"], ["ready-for-agent", "work-in-progress"])


RESP_ACTION = ROOT / ".github" / "actions" / "responsible" / "action.yml"
RESP_USES = "samuel-morrissey/ai-workflows/.github/actions/responsible@main"
RESP_STEP = "Resolver responsavel"
RESP_OUT = "${{ steps.responsavel.outputs.sentence }}"
AGENT = "anthropics/claude-code-action@v1"
# Etapas que rodam o agente num issue. O pr-fix fica fora: o aviso dele e de
# outra fatia.
AGENT_FILES = ["issue-triage.yml", "issue-refinement.yml", "issue-break-down.yml",
               "issue-remote-implement.yml", "issue-sub-task.yml"]
# As que nao usam a agent-env: o responsavel vai num --append-system-prompt
# proprio. As outras o levam no prompt_prefix da agent-env, que monta o unico
# --append-system-prompt da rodada.
OWN_SYSPROMPT = ["issue-triage.yml", "issue-refinement.yml", "issue-break-down.yml"]

# gh falso para a resolucao real: `gh api <rota>` responde o JSON de
# $FAKE_API/<rota com / trocado por _>.json, ou HTTP 404.
FAKE_GH_API = r'''#!/usr/bin/env bash
[ "$1" = "api" ] || { echo "gh falso: comando inesperado: $*" >&2; exit 2; }
f="$FAKE_API/$(printf '%s' "$2" | tr '/' '_').json"
[ -f "$f" ] || { echo "gh: Not Found (HTTP 404)" >&2; exit 1; }
cat "$f"
'''


def composite_run(path):
    """Texto do `run` do unico passo de uma composite action."""
    run = path.read_text().split("      run: |\n", 1)[1]
    lines = []
    for line in run.splitlines():
        if line.strip() == "":
            lines.append("")
        elif line.startswith("        "):
            lines.append(line[8:])
        else:
            break
    return "\n".join(lines).rstrip("\n") + "\n"


def outputs_of(text):
    """Mapa do $GITHUB_OUTPUT: `k=v` e `k<<DELIM ... DELIM`; a ultima vence."""
    out, lines, i = {}, text.splitlines(), 0
    while i < len(lines):
        line = lines[i]
        m = re.fullmatch(r"([a-z_]+)<<(\S+)", line)
        if m:
            end = lines.index(m.group(2), i + 1)
            out[m.group(1)] = "\n".join(lines[i + 1:end])
            i = end + 1
            continue
        k, _, v = line.partition("=")
        out[k] = v
        i += 1
    return out


class ResponsibleShape(unittest.TestCase):
    """Toda rodada de agente em issue recebe o responsavel pronto."""

    def steps(self, f):
        return steps_of((WORKFLOWS / f).read_text())

    def test_resolve_antes_do_agente_sem_derrubar_a_rodada(self):
        for f in AGENT_FILES:
            names = [n for n, _ in self.steps(f)]
            self.assertEqual(names.count(RESP_STEP), 1, f)
            self.assertLess(names.index(RESP_STEP), names.index(AGENT), f)
            self.assertGreater(names.index(RESP_STEP), names.index("Aplicar work-in-progress"), f)
            if "Preparar ambiente do agente" in names:
                self.assertLess(names.index(RESP_STEP), names.index("Preparar ambiente do agente"), f)
            step = parse_step(dict(self.steps(f))[RESP_STEP])
            self.assertEqual(step["uses"], RESP_USES, f)
            self.assertEqual(step["continue_on_error"], "true", f)
            self.assertEqual(step["with"]["number"], "${{ steps.target.outputs.number }}", f)
            # Roda sempre que o agente roda.
            agent_if = parse_step(dict(self.steps(f))[AGENT])["if"]
            self.assertEqual(step["if"], agent_if, f)

    def test_responsavel_chega_ao_system_prompt(self):
        for f in AGENT_FILES:
            steps = dict(self.steps(f))
            agent = steps[AGENT]
            if f in OWN_SYSPROMPT:
                # A frase do responsavel abre o system prompt; a das fontes da
                # web (WebDomainsShape) vem depois dela.
                self.assertIn(f'--append-system-prompt "{RESP_OUT}', agent, f)
            else:
                self.assertIn("${{ steps.ambiente.outputs.sysprompt }}", agent, f)
                prefix = parse_step(steps["Preparar ambiente do agente"])["with"]["prompt_prefix"]
                self.assertIn(RESP_OUT, prefix, f)
            # Um --append-system-prompt so por rodada.
            self.assertLessEqual(agent.count("--append-system-prompt"), 1, f)

    def test_sub_task_mantem_o_modo_sub_task_no_comeco(self):
        prefix = parse_step(dict(self.steps("issue-sub-task.yml"))["Preparar ambiente do agente"])["with"]["prompt_prefix"]
        self.assertTrue(prefix.startswith('"Modo sub-task: #'), prefix)
        self.assertTrue(prefix.endswith(f' {RESP_OUT}"'), prefix)

    def test_pr_fix_fica_de_fora(self):
        self.assertNotIn(RESP_STEP, [n for n, _ in self.steps(PR_FIX)])

    def test_action_le_a_chave_do_checkout(self):
        text = RESP_ACTION.read_text()
        self.assertIn("RESPONSIBLE_PY: ${{ github.action_path }}/../../../scripts/responsible.py", text)
        self.assertIn("GH_REPO: ${{ github.repository }}", text)
        # Sem --config: o responsible.py le .github/ai-workflows.yml do
        # diretorio de trabalho, que e o checkout do consumidor.
        self.assertNotIn("--config", composite_run(RESP_ACTION))


class ResponsibleRun(unittest.TestCase):
    """Roda o passo da action responsible num bash, com a resolucao falsa ou real."""

    def execute(self, resp=None, resp_fail=False, real=None, config=None, default=""):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="resp-wf-"))
        (tmp / "step.sh").write_text(composite_run(RESP_ACTION))
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(tmp / "out"), "NUMBER": "46",
               "DEFAULT_RESPONSIBLE": default, "GH_REPO": "o/r", "GH_TOKEN": "x",
               "FAKE_RESP_LOG": str(tmp / "resp.log")}
        if real is None:
            (tmp / "responsible.py").write_text(FAKE_RESPONSIBLE)
            env.update({"RESPONSIBLE_PY": str(tmp / "responsible.py"),
                        "FAKE_RESP": resp or '{"issue": 46, "logins": [], "rule": "none"}',
                        "FAKE_RESP_FAIL": "1" if resp_fail else ""})
        else:
            api = tmp / "api"
            api.mkdir()
            for route, data in real.items():
                (api / (route.replace("/", "_") + ".json")).write_text(json.dumps(data))
            gh = tmp / "bin" / "gh"
            gh.parent.mkdir()
            gh.write_text(FAKE_GH_API)
            gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
            env.update({"RESPONSIBLE_PY": str(ROOT / "scripts" / "responsible.py"),
                        "FAKE_API": str(api), "PATH": f"{gh.parent}:{os.environ['PATH']}"})
        work = tmp / "checkout"
        (work / ".github").mkdir(parents=True)
        if config is not None:
            (work / ".github" / "ai-workflows.yml").write_text(config)
        self.resp_log = tmp / "resp.log"
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp / "step.sh")],
                              cwd=work, env=env, capture_output=True, text=True)
        out = outputs_of((tmp / "out").read_text()) if (tmp / "out").exists() else {}
        return proc, out

    def assertSafe(self, sentence):
        # Vai entre aspas duplas em claude_args.
        for ch in '"`$\\\n':
            self.assertNotIn(ch, sentence)

    def test_logins_viram_mencao(self):
        proc, out = self.execute('{"issue": 46, "logins": ["ana", "bia"], "rule": "assignees"}', default="gil")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("46 --default gil", self.resp_log.read_text())
        self.assertTrue(out["sentence"].startswith("Responsavel: @ana @bia"), out)
        self.assertEqual(out["logins"], "ana bia")
        self.assertSafe(out["sentence"])

    def test_sem_responsavel_diz_e_nao_marca(self):
        proc, out = self.execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: sem responsavel"), out)
        self.assertNotIn("@", out["sentence"])
        self.assertEqual(out["logins"], "")
        self.assertSafe(out["sentence"])

    def test_resolucao_falhando_segue_sem_responsavel(self):
        proc, out = self.execute(resp_fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::Nao consegui resolver o responsavel do #46", proc.stdout)
        self.assertTrue(out["sentence"].startswith("Responsavel: sem responsavel"), out)
        self.assertNotIn("@", out["sentence"])

    def test_saida_invalida_segue_sem_responsavel(self):
        proc, out = self.execute("nao e json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("@", out["sentence"])

    def test_login_estranho_nunca_vira_mencao(self):
        # Defesa em profundidade: bot ou texto que quebraria as aspas.
        proc, out = self.execute('{"issue": 46, "logins": ["x[bot]", "a\\" b", "ana"], "rule": "assignees"}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: @ana "), out)
        self.assertNotIn("bot", out["sentence"])
        self.assertSafe(out["sentence"])

    def test_triagem_de_autor_humano_sem_assignee_marca_o_autor(self):
        proc, out = self.execute(real={
            "repos/o/r/issues/46": {"title": "Algo", "body": "", "assignees": [],
                                    "user": {"login": "autora", "type": "User"}}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: @autora "), out)

    def test_sub_task_de_bot_marca_o_responsavel_do_pai(self):
        proc, out = self.execute(real={
            "repos/o/r/issues/46": {"title": "[SUB-TASK] fatia", "body": "Parte de #40.", "assignees": [],
                                    "user": {"login": "github-actions[bot]", "type": "Bot"}},
            "repos/o/r/issues/46/parent": {"number": 40},
            "repos/o/r/issues/40": {"title": "[SPEC] pai", "body": "", "assignees": [],
                                    "user": {"login": "dona", "type": "User"}}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: @dona "), out)
        self.assertNotIn("github-actions", out["sentence"])

    def test_default_responsible_vem_do_checkout(self):
        proc, out = self.execute(config="default_responsible: gil\n", real={
            "repos/o/r/issues/46": {"title": "[FEAT] x", "body": "", "assignees": [],
                                    "user": {"login": "claude", "type": "Bot"}},
            "users/gil": {"login": "gil", "type": "User"}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: @gil "), out)

    def test_issue_de_bot_sem_nada_fica_sem_responsavel(self):
        proc, out = self.execute(real={
            "repos/o/r/issues/46": {"title": "[FEAT] x", "body": "", "assignees": [],
                                    "user": {"login": "claude", "type": "Bot"}}})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["sentence"].startswith("Responsavel: sem responsavel"), out)
        self.assertNotIn("@", out["sentence"])


SKILLS = ROOT / "skills"
NO_ONE = "**Responsavel:** nao ha responsavel identificavel; ninguem foi marcado."


class SkillsMention(unittest.TestCase):
    """Os modelos de comentario das skills levam a mencao onde ela vai."""

    def skill(self, name):
        return (SKILLS / name / "SKILL.md").read_text()

    def test_async_first_documenta_mencao_e_sem_responsavel(self):
        text = self.skill("issue-async-first")
        self.assertIn("## Mencao ao responsavel", text)
        self.assertIn('**"Responsavel:"**', text)
        self.assertIn("**Preciso de voce** (@responsavel):", text)
        self.assertIn(NO_ONE, text)
        self.assertIn("Nunca edite um comentario existente", text)

    def test_comentarios_finais_marcam_no_proximo_passo(self):
        triage = self.skill("issue-triage")
        # passo 5, passo 6.3 e passo 6.7
        self.assertEqual(triage.count("**Proximo passo** (@responsavel):"), 3)
        # Nenhum modelo de comentario ficou com o Proximo passo sem mencao.
        self.assertNotRegex(triage, r"(?m)^ *\*\*Proximo passo:\*\*")
        refinement = self.skill("issue-refinement")
        self.assertIn("**Ao responder** (@responsavel):", refinement)
        self.assertIn("**Proximo passo** (@responsavel): aplique o label `go`", refinement)
        self.assertIn("**Proximo passo** (@responsavel): aplique o label `go` neste issue",
                      self.skill("issue-break-down"))
        for name in ("issue-triage", "issue-refinement", "issue-break-down"):
            self.assertIn("nao ha responsavel identificavel", self.skill(name), name)

    def test_implement_marca_o_handoff_e_nunca_o_bot(self):
        text = self.skill("issue-remote-implement")
        self.assertIn('**"Responsavel:"**', text)
        self.assertIn("nunca marque o\nbot autor da sub-task", text)

    def test_implement_relata_o_review_no_comentario_final(self):
        text = self.skill("issue-remote-implement")
        self.assertIn("**Review:**", text)
        self.assertIn("nao ha responsavel identificavel; nenhum review pedido", text)

    def test_remote_to_pr_pede_review_e_cai_para_mencao(self):
        text = self.skill("remote-to-pr")
        self.assertIn("## Pedido de review", text)
        # Um login por chamada: falha parcial so atinge quem falhou.
        self.assertIn("gh api -X POST repos/{owner}/{repo}/pulls/<numero>/requested_reviewers "
                      "-f 'reviewers[]=<login>'", text)
        self.assertIn("gh pr view <url> --json reviewRequests", text)
        # Fallback: um comentario no PR, com @ so a quem falhou.
        self.assertIn("gh api -X POST repos/{owner}/{repo}/issues/<numero>/comments", text)
        self.assertIn("so para quem falhou", text)
        self.assertIn("ja esta em `reviewRequests`", text)
        self.assertIn("nenhum review e pedido", text)
        self.assertIn("O corpo do PR nao leva `@`", text)
        self.assertIn("A rodada segue", text)
        # PR existente nao pede review de novo.
        existing = text.split("## PR existente", 1)[1]
        self.assertIn("Nao peca review", existing)

    def test_remote_to_pr_so_usa_comandos_da_allowlist(self):
        # O pedido de review e o fallback rodam dentro do implement e da
        # sub-task: so com o que a allowlist delas libera.
        section = self.skill("remote-to-pr").split("## Pedido de review", 1)[1].split("\n## ", 1)[0]
        cmds = re.findall(r"(?m)^ *(gh [a-z]+(?: [a-z]+)?)", section)
        self.assertTrue(cmds)
        for f in ("issue-remote-implement.yml", "issue-sub-task.yml"):
            allow = (WORKFLOWS / f).read_text()
            for cmd in cmds:
                self.assertIn(f"Bash({cmd}:*)", allow, (f, cmd))

    def test_pr_fix_marca_quem_disparou_no_handoff(self):
        text = self.skill("pr-fix")
        self.assertIn('**"Quem disparou a rodada:"**', text)
        self.assertIn("**Preciso de voce** (@quem-disparou):", text)
        self.assertIn("nao o responsavel do issue", text)
        self.assertIn("**Quem disparou a rodada:** nao identifiquei quem disparou; ninguem foi marcado.", text)

    def test_issue_labeling_review_por_camada(self):
        section = self.skill("issue-labeling").split("## Pai e sub-tasks", 1)[1].split("\n## ", 1)[0]
        self.assertIn("pede review do responsavel do pai", section)
        self.assertIn("cada camada", section)

    def test_readme_cobre_o_pr(self):
        readme = (ROOT / "README.md").read_text()
        notif = readme.split("### Notificação", 1)[1].split("\n## ", 1)[0]
        self.assertIn("pedido de review", notif)
        self.assertIn("Handoff da correção de PR", notif)
        self.assertNotIn("ainda não marcam", notif)


PREMISSA_LINK = "../issue-triage/AGENT-BRIEF.md#premissa-externa"


class SkillsPremise(unittest.TestCase):
    """Premissa externa: uma secao no AGENT-BRIEF.md, citada por quem escreve."""

    def brief(self):
        return (SKILLS / "issue-triage" / "AGENT-BRIEF.md").read_text()

    def section(self):
        return self.brief().split("\n## Premissa externa\n", 1)[1].split("\n## ", 1)[0]

    def test_secao_nomeia_os_quatro_textos_e_as_regras(self):
        section = " ".join(self.section().replace("**", "").split())
        for texto in ("brief completo", "leitura de codigo", "refinamento", "corpo de PR"):
            self.assertIn(texto, section, texto)
        self.assertIn("Premissa nao verificada: <premissa>; fonte: <payload/log/teste>; "
                      "se estiver errada, descarta <x>", section)
        self.assertIn("URL consultado", section)
        self.assertIn("Fonte secundaria", section)
        self.assertIn("continua nao verificada", section)

    def test_brief_completo_aponta_para_a_secao_sem_repetir(self):
        brief = self.brief()
        full = brief.split("\n## Brief completo", 1)[1].split("\n## Leitura de codigo", 1)[0]
        self.assertIn("[Premissa externa](#premissa-externa)", full)
        # O texto da regra mora so na secao nova.
        self.assertNotIn("URL consultado", full)
        self.assertNotIn("documentacao oficial", full)
        self.assertEqual(brief.count("Fonte secundaria"), 1)

    def test_refinement_cita_a_secao(self):
        text = (SKILLS / "issue-refinement" / "SKILL.md").read_text()
        final = text.split("\n## Refinamento\n", 1)[1]
        self.assertIn(PREMISSA_LINK, final)

    def test_remote_to_pr_aplica_nos_dois_modos(self):
        text = (SKILLS / "remote-to-pr" / "SKILL.md").read_text()
        new, existing = text.split("\n## PR existente\n", 1)
        self.assertIn(PREMISSA_LINK, new.split("\n## Pedido de review\n", 1)[0])
        self.assertIn(PREMISSA_LINK, existing)


# Web das etapas de issue: lista fixa de dominios, nos dois lados do espelho.
WEB_DOMAINS = {"docs.github.com", "code.claude.com", "platform.claude.com"}
WEB_STAGES = {"issue-triage.yml": "issue-triage", "issue-refinement.yml": "issue-refinement",
              "issue-break-down.yml": "issue-break-down"}
NO_WEB_STAGES = {"issue-remote-implement.yml": "issue-remote-implement",
                 "issue-sub-task.yml": "issue-remote-implement", "pr-fix.yml": "pr-fix"}
MAX_TURNS = {"issue-triage.yml": "50", "issue-refinement.yml": "80", "issue-break-down.yml": "100"}
WEB_LINK = "AGENT-BRIEF.md#uso-da-web"


def workflow_tools(name):
    """Ferramentas do `--allowed-tools` do workflow, sem o sufixo do agent-env."""
    text = (WORKFLOWS / name).read_text()
    raw = re.findall(r'--allowed-tools "([^"]*)"', text)
    assert len(raw) == 1, name
    return [t for t in re.sub(r"\$\{\{[^}]*\}\}", "", raw[0]).split(",") if t]


def skill_tools(name):
    """Ferramentas do frontmatter `allowed-tools` da skill."""
    front = (SKILLS / name / "SKILL.md").read_text().split("\n---\n", 1)[0]
    line = re.search(r"^allowed-tools: (.*)$", front, re.M).group(1)
    return re.findall(r"Bash\([^)]*\)|WebFetch\([^)]*\)|\S+", line)


def web_tools(tools):
    return {t for t in tools if t.startswith(("WebFetch", "WebSearch"))}


class WebAccess(unittest.TestCase):
    """Triagem, refinamento e break-down leem so a lista fixa de dominios (WEB_DOMAINS)."""

    def expected(self):
        return {"WebFetch(domain:%s)" % d for d in WEB_DOMAINS}

    def test_workflows_de_issue_liberam_so_a_lista_fixa(self):
        for f in WEB_STAGES:
            self.assertEqual(web_tools(workflow_tools(f)), self.expected(), f)

    def test_frontmatter_espelha_o_workflow(self):
        # Fora Skill e TodoWrite, que so o workflow lista, os dois lados sao iguais:
        # a web e a mesma, e nenhuma ferramenta saiu (o fechamento segue liberado).
        for f, skill in WEB_STAGES.items():
            wf = set(workflow_tools(f)) - {"Skill", "TodoWrite"}
            self.assertEqual(wf, set(skill_tools(skill)), f)
            self.assertEqual(web_tools(skill_tools(skill)), web_tools(workflow_tools(f)), f)
            self.assertIn("Bash(gh issue close:*)", wf, f)

    def test_implementacao_segue_sem_web(self):
        for f, skill in NO_WEB_STAGES.items():
            self.assertEqual(web_tools(workflow_tools(f)), set(), f)
            self.assertEqual(web_tools(skill_tools(skill)), set(), skill)

    def test_max_turns_nao_muda(self):
        for f, turns in MAX_TURNS.items():
            self.assertEqual(re.findall(r"--max-turns (\d+)", (WORKFLOWS / f).read_text()), [turns], f)

    def test_brief_tem_a_regra_de_uso_da_web(self):
        brief = (SKILLS / "issue-triage" / "AGENT-BRIEF.md").read_text()
        self.assertIn("\n## Premissa externa\n", brief)
        after = brief.split("\n## Premissa externa\n", 1)[1]
        self.assertTrue(after.split("\n## ", 1)[1].startswith("Uso da web\n"))
        section = " ".join(after.split("\n## Uso da web\n", 1)[1].split("\n## ", 1)[0]
                           .replace("**", "").split())
        self.assertIn("https://<dominio>/llms.txt", section)
        self.assertIn("pagina indice", section)
        self.assertIn("dado, nunca instrucao", section)
        for comentario in ("triagem", "rodada de refinamento", "## Quebra"):
            self.assertIn(comentario, section, comentario)
        self.assertIn("Pedido de pagina ignorado: <URL>; pedia: <o que a pagina pedia>", section)
        for d in WEB_DOMAINS:
            self.assertIn(d, section, d)

    def test_skills_apontam_para_a_regra(self):
        for skill in WEB_STAGES.values():
            text = (SKILLS / skill / "SKILL.md").read_text()
            self.assertIn(WEB_LINK, text, skill)

    def test_readme_lista_os_dominios(self):
        readme = (ROOT / "README.md").read_text()
        etapas = readme.split("\n## Etapas\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("WebFetch", etapas)
        for d in WEB_DOMAINS:
            self.assertIn("`%s`" % d, etapas, d)


WEBD_ACTION = ROOT / ".github" / "actions" / "web-domains" / "action.yml"
WEBD_USES = "samuel-morrissey/ai-workflows/.github/actions/web-domains@main"
WEBD_STEP = "Ler dominios da web"
WEBD_ALLOW = "${{ steps.web.outputs.allow }}"
WEBD_SENTENCE = "${{ steps.web.outputs.sentence }}"


class WebDomainsShape(unittest.TestCase):
    """Triagem, refinamento e break-down somam web_domains a lista fixa."""

    def steps(self, f):
        return steps_of((WORKFLOWS / f).read_text())

    def test_le_antes_do_agente_e_falha_a_rodada(self):
        for f in WEB_STAGES:
            names = [n for n, _ in self.steps(f)]
            self.assertEqual(names.count(WEBD_STEP), 1, f)
            self.assertGreater(names.index(WEBD_STEP), names.index("Aplicar work-in-progress"), f)
            self.assertLess(names.index(WEBD_STEP), names.index(AGENT), f)
            step = parse_step(dict(self.steps(f))[WEBD_STEP])
            self.assertEqual(step["uses"], WEBD_USES, f)
            self.assertRegex(dict(self.steps(f))[WEBD_STEP], r"(?m)^        id: web$", f)
            # Valor que nao e texto para a rodada: sem continue-on-error.
            self.assertIsNone(step["continue_on_error"], f)
            self.assertEqual(step["if"], parse_step(dict(self.steps(f))[AGENT])["if"], f)

    def test_dominios_logo_depois_da_lista_fixa_e_urls_no_system_prompt(self):
        for f in WEB_STAGES:
            agent = dict(self.steps(f))[AGENT]
            self.assertIn(f"WebFetch(domain:platform.claude.com){WEBD_ALLOW},Skill", agent, f)
            self.assertIn(f'--append-system-prompt "{RESP_OUT}{WEBD_SENTENCE}"', agent, f)

    def test_implementacao_nao_le(self):
        for f in NO_WEB_STAGES:
            text = (WORKFLOWS / f).read_text()
            self.assertNotIn(WEBD_USES, text, f)
            self.assertNotIn("steps.web.outputs", text, f)

    def test_brief_e_readme_documentam_a_chave(self):
        brief = (SKILLS / "issue-triage" / "AGENT-BRIEF.md").read_text()
        section = " ".join(brief.split("\n## Uso da web\n", 1)[1].split("\n## ", 1)[0].replace("**", "").split())
        self.assertIn("web_domains", section)
        self.assertIn("URL de entrada", section)
        self.assertIn("Fontes da web do consumidor", section)
        self.assertIn('"nao verificada" quer dizer "nao ha fonte oficial", nao "nao achei a URL"', section)
        readme = (ROOT / "README.md").read_text()
        table = readme.split("\n## O que um repositório precisa\n", 1)[1].split("\n### ", 1)[0]
        self.assertIn("`web_domains`", table)
        config = readme.split("\n### O arquivo `.github/ai-workflows.yml`\n", 1)[1].split("\n### ", 1)[0]
        item = config.split("- `web_domains`:", 1)[1]
        for texto in ("URL de entrada", "`https://`", "curinga", "lista fixa", "falha a rodada",
                      "Só essas três etapas a usam", "`doctor`"):
            self.assertIn(texto, item, texto)

    def test_lista_fixa_do_leitor_e_a_dos_workflows(self):
        import web_domains
        self.assertEqual(set(web_domains.FIXED), WEB_DOMAINS)


class WebDomainsRun(unittest.TestCase):
    """Roda o passo da action web-domains com o leitor real num checkout falso."""

    def execute(self, config=None):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="webd-wf-"))
        (tmp / "step.sh").write_text(composite_run(WEBD_ACTION))
        work = tmp / "checkout"
        (work / ".github").mkdir(parents=True)
        if config is not None:
            (work / ".github" / "ai-workflows.yml").write_text(config)
        env = {"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(tmp / "out"),
               "CONFIG_FILE": ".github/ai-workflows.yml",
               "WEB_DOMAINS_PY": str(ROOT / "scripts" / "web_domains.py")}
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-e", str(tmp / "step.sh")],
                              cwd=work, env=env, capture_output=True, text=True)
        out = outputs_of((tmp / "out").read_text()) if (tmp / "out").exists() else {}
        return proc, out

    def tools(self, out):
        """--allowed-tools da triagem como o runner o monta, com o sufixo."""
        raw = re.search(r'--allowed-tools "([^"]*)"', (WORKFLOWS / "issue-triage.yml").read_text()).group(1)
        return raw.replace(WEBD_ALLOW, out["allow"]).split(",")

    def test_url_de_entrada_libera_o_host_e_chega_ao_prompt(self):
        proc, out = self.execute("web_domains: |\n  https://docs.asaas.com/reference\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("::warning", proc.stdout)
        self.assertEqual(web_tools(self.tools(out)),
                         {"WebFetch(domain:%s)" % d for d in WEB_DOMAINS | {"docs.asaas.com"}})
        self.assertIn("https://docs.asaas.com/reference", out["sentence"])
        for ch in '"`$\\\n':
            self.assertNotIn(ch, out["sentence"])

    def test_sem_arquivo_ou_sem_chave_so_a_lista_fixa_sem_aviso(self):
        for config in (None, "quality_checks: make test\n"):
            proc, out = self.execute(config)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("::warning", proc.stdout)
            self.assertEqual(out["allow"], "")
            self.assertEqual(out["sentence"], "")
            self.assertEqual(web_tools(self.tools(out)), {"WebFetch(domain:%s)" % d for d in WEB_DOMAINS})

    def test_linha_invalida_avisa_e_as_validas_valem(self):
        proc, out = self.execute('web_domains: |\n  http://x.com\n  *.x.com\n  x .com\n  "x.com"\n  docs.y.com\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        warnings = [l for l in proc.stdout.splitlines() if l.startswith("::warning")]
        self.assertEqual(len(warnings), 4, proc.stdout)
        self.assertEqual(out["allow"], ",WebFetch(domain:docs.y.com)")

    def test_todas_invalidas_so_a_lista_fixa(self):
        proc, out = self.execute("web_domains: |\n  http://x.com\n  *.x.com\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.count("::warning"), 2)
        self.assertEqual(out["allow"], "")
        self.assertEqual(out["sentence"], "")

    def test_lista_yaml_falha_o_passo(self):
        proc, out = self.execute("web_domains:\n  - docs.asaas.com\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("::error file=.github/ai-workflows.yml::web_domains precisa ser texto", proc.stdout)
        self.assertNotIn("allow", out)


def workflow_run(block):
    """Texto do `run: |` de um passo de workflow (indentacao de 10)."""
    run = block.split("        run: |\n", 1)[1]
    lines = []
    for line in run.splitlines():
        if line.strip() == "":
            lines.append("")
        elif line.startswith("          "):
            lines.append(line[10:])
        else:
            break
    return "\n".join(lines).rstrip("\n") + "\n"


# gh falso do "Resolver alvo" do pr-fix: `gh pr view` responde $FAKE_PR.
FAKE_GH_PR = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "pr view") printf '%s' "$FAKE_PR" ;;
  "pr comment") ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 2 ;;
esac
'''
QUEM_OUT = "${{ steps.target.outputs.quem }}"


class PrFixTrigger(unittest.TestCase):
    """O pr-fix.yml passa ao agente quem disparou a rodada, para o handoff."""

    def steps(self):
        return dict(steps_of((WORKFLOWS / PR_FIX).read_text()))

    def test_login_vem_do_autor_do_comentario_ou_da_review(self):
        target = self.steps()["Resolver alvo"]
        self.assertIn("TRIGGER_LOGIN: ${{ github.event.comment.user.login || github.event.review.user.login }}", target)
        self.assertIn("TRIGGER_TYPE: ${{ github.event.comment.user.type || github.event.review.user.type }}", target)

    def test_frase_chega_ao_system_prompt(self):
        steps = self.steps()
        prefix = parse_step(steps["Preparar ambiente do agente"])["with"]["prompt_prefix"]
        self.assertTrue(prefix.startswith('"Correcao de PR: #'), prefix)
        self.assertTrue(prefix.endswith(f' {QUEM_OUT}"'), prefix)
        self.assertIn("${{ steps.ambiente.outputs.sysprompt }}", steps[AGENT])
        self.assertLessEqual(steps[AGENT].count("--append-system-prompt"), 1)

    def execute(self, login, kind="User", event="issue_comment"):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="prfix-"))
        (tmp / "step.sh").write_text(workflow_run(self.steps()["Resolver alvo"]))
        gh = tmp / "gh"
        gh.write_text(FAKE_GH_PR)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        env = {"PATH": f"{tmp}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(tmp / "out"),
               "FAKE_GH_LOG": str(tmp / "log"), "GH_TOKEN": "x", "GH_REPO": "o/r",
               "EVENT_NAME": event, "PR_NUMBER": "71", "REVIEW_ID": "9", "COMMENT_ID": "8",
               "TRIGGER_LOGIN": login, "TRIGGER_TYPE": kind,
               "FAKE_PR": json.dumps({"state": "OPEN", "isCrossRepository": False,
                                      "headRefName": "sub-task-67", "baseRefName": "sub-task-66",
                                      "closingIssuesReferences": [{"number": 67}]})}
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp / "step.sh")],
                              env=env, capture_output=True, text=True)
        out = outputs_of((tmp / "out").read_text()) if (tmp / "out").exists() else {}
        return proc, out

    def assertSafe(self, sentence):
        for ch in '"`$\\\n':
            self.assertNotIn(ch, sentence)

    def test_comentario_marca_quem_comentou(self):
        proc, out = self.execute("revisora")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["quem"].startswith("Quem disparou a rodada: @revisora "), out)
        self.assertIn("nao o responsavel do issue", out["quem"])
        self.assertEqual(out["trigger"], "comentario 8")
        self.assertSafe(out["quem"])

    def test_review_marca_quem_revisou(self):
        proc, out = self.execute("revisor", event="pull_request_review")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["quem"].startswith("Quem disparou a rodada: @revisor "), out)
        self.assertEqual(out["trigger"], "review 9")

    def test_bot_ou_vazio_nao_marca(self):
        for login, kind in (("claude[bot]", "Bot"), ("algum", "Bot"), ("", "")):
            proc, out = self.execute(login, kind)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(out["quem"].startswith("Quem disparou a rodada: nao identificado"), (login, out))
            self.assertNotIn("@", out["quem"])
            self.assertSafe(out["quem"])

    def test_login_estranho_nunca_vira_mencao(self):
        proc, out = self.execute('a" --x $(id)')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(out["quem"].startswith("Quem disparou a rodada: nao identificado"), out)
        self.assertSafe(out["quem"])


DECIDE = "Decidir e agir"
NOTICE_RESP = "Resolver responsavel do pai"
PAI_IF = "steps.target.outputs.kind == 'pai' && steps.chain.outputs.skip != 'true'"

# Planner falso no lugar de $RUNNER_TEMP/sub_tasks.py: registra cada chamada
# (argv em JSON) em $FAKE_PLANNER_LOG e falha o subcomando em $FAKE_PLANNER_FAIL.
FAKE_PLANNER = r'''import json, os, sys
with open(os.environ["FAKE_PLANNER_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] in os.environ.get("FAKE_PLANNER_FAIL", "").split():
    print("gh api repos/o/r/issues/56/comments: HTTP 503", file=sys.stderr)
    sys.exit(2)
print("{}")
'''

# gh falso do "Decidir e agir": labels do pai em $FAKE_LABELS, aceita as
# escritas de label e o dispatch, e registra tudo em $FAKE_GH_LOG.
FAKE_GH_DECIDE = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "issue view") printf '%s\n' $FAKE_LABELS ;;
  "issue edit"|"label create") ;;
  "api --method") ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 2 ;;
esac
'''


class ChainNoticeShape(unittest.TestCase):
    """O planner resolve o responsavel do pai e o passa ao "Decidir e agir"."""

    def steps(self):
        return steps_of((WORKFLOWS / "issue-remote-implement.yml").read_text())

    def test_resolve_o_responsavel_do_pai_antes_de_decidir_sem_derrubar(self):
        names = [n for n, _ in self.steps()]
        self.assertLess(names.index("Entrar na cadeia"), names.index(NOTICE_RESP))
        self.assertLess(names.index(NOTICE_RESP), names.index(DECIDE))
        step = parse_step(dict(self.steps())[NOTICE_RESP])
        self.assertEqual(step["uses"], RESP_USES)
        self.assertEqual(step["continue_on_error"], "true")
        self.assertEqual(step["with"]["number"], "${{ steps.target.outputs.number }}")
        self.assertEqual(step["if"], PAI_IF)

    def test_decidir_recebe_os_logins(self):
        block = dict(self.steps())[DECIDE]
        self.assertIn("RESP_LOGINS: ${{ steps.responsavel_pai.outputs.logins }}", block)
        self.assertIn("id: responsavel_pai", dict(self.steps())[NOTICE_RESP])

    def test_docs_cobrem_o_aviso_da_cadeia(self):
        labeling = (SKILLS / "issue-labeling" / "SKILL.md").read_text()
        section = labeling.split("## Pai e sub-tasks", 1)[1].split("\n## ", 1)[0]
        section = " ".join(section.split())
        self.assertIn("comentario novo no pai", section)
        self.assertIn("marca o responsavel do pai", section)
        self.assertIn("stack completa", section)
        readme = (ROOT / "README.md").read_text()
        notif = readme.split("### Notificação", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Cadeia parada", notif)
        self.assertIn("Stack completa", notif)


class ChainNoticeRun(unittest.TestCase):
    """Roda o "Decidir e agir" num bash, com gh e planner falsos, e confere
    quais caminhos postam o aviso novo no pai (subcomando `notify`)."""

    def execute(self, fail="", labels="ready-for-agent work-in-progress", **env):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="decide-"))
        block = dict(steps_of((WORKFLOWS / "issue-remote-implement.yml").read_text()))[DECIDE]
        (tmp / "step.sh").write_text(workflow_run(block))
        (tmp / "sub_tasks.py").write_text(FAKE_PLANNER)
        gh = tmp / "gh"
        gh.write_text(FAKE_GH_DECIDE)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        base = {"PATH": f"{tmp}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp), "GH_TOKEN": "x",
                "GH_REPO": "o/r", "NUMBER": "56", "CHAIN": "true", "FROM": "", "OUTCOME": "",
                "FROM_SOURCE": "", "FROM_RUN": "", "NEXT": "", "COMPLETE": "false",
                "WAIT_KIND": "none", "WAIT_NOTE": "", "STACK_ERROR": "", "RESP_LOGINS": "ana",
                "FAKE_PLANNER_LOG": str(tmp / "planner.log"), "FAKE_PLANNER_FAIL": fail,
                "FAKE_GH_LOG": str(tmp / "gh.log"), "FAKE_LABELS": labels}
        base.update(env)
        # O shell padrao do GitHub Actions: bash -e com pipefail.
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp / "step.sh")],
                              env=base, capture_output=True, text=True)
        log = tmp / "planner.log"
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        ghlog = (tmp / "gh.log").read_text() if (tmp / "gh.log").exists() else ""
        return proc, calls, ghlog

    def notices(self, calls):
        return [c for c in calls if c[0] == "notify"]

    def opt(self, call, name):
        return call[call.index(name) + 1]

    def assertNotice(self, proc, calls, kind, note=None):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [notice] = self.notices(calls)
        self.assertEqual(notice[1], "56")
        self.assertEqual(self.opt(notice, "--kind"), kind)
        self.assertEqual(self.opt(notice, "--logins"), "ana")
        if note is not None:
            self.assertEqual(self.opt(notice, "--note"), note)
        # O status continua sendo editado na mesma rodada, sem `@`, e antes do aviso.
        status = [c for c in calls if c[0] == "status"]
        self.assertEqual(len(status), 1)
        self.assertNotIn("@", self.opt(status[0], "--note"))
        self.assertLess(calls.index(status[0]), calls.index(notice))
        return notice

    def test_sub_task_humana_para_e_avisa(self):
        note = "#57 e humana: faca a parte dela e aplique `go` aqui para a cadeia seguir."
        proc, calls, gh = self.execute(WAIT_KIND="human", WAIT_NOTE=note)
        self.assertNotice(proc, calls, "parada", note)
        self.assertEqual(self.opt([c for c in calls if c[0] == "status"][0], "--note"), note)
        self.assertIn("--remove-label work-in-progress", gh)

    def test_bloqueio_externo_para_e_avisa(self):
        note = "#58 esta bloqueada por #9, sem PR e ainda aberto."
        proc, calls, _ = self.execute(WAIT_KIND="blocked", WAIT_NOTE=note)
        self.assertNotice(proc, calls, "parada", note)

    def test_rodada_sem_pr_e_sem_pergunta_para_e_avisa(self):
        for outcome in ("none", "skipped"):
            proc, calls, _ = self.execute(FROM_SOURCE="chain", OUTCOME=outcome, FROM="57", FROM_RUN="123")
            notice = self.assertNotice(proc, calls, "parada")
            self.assertIn("#57 terminou sem PR e sem pergunta", self.opt(notice, "--note"))
            self.assertIn("actions/runs/123", self.opt(notice, "--note"))

    def test_falha_ao_empilhar_para_e_avisa(self):
        proc, calls, _ = self.execute(STACK_ERROR="PR #70 tem base `x`.")
        notice = self.assertNotice(proc, calls, "parada")
        self.assertIn("Nao consegui empilhar os PRs: PR #70 tem base `x`.", self.opt(notice, "--note"))

    def test_stack_completa_aplica_o_label_e_avisa(self):
        proc, calls, gh = self.execute(COMPLETE="true")
        self.assertNotice(proc, calls, "completa")
        self.assertIn("--add-label awaiting-pr-review --remove-label ready-for-agent", gh)
        self.assertEqual([c[0] for c in calls], ["finish", "status", "notify"])

    def test_cadeia_que_segue_nao_avisa(self):
        for env in ({"NEXT": "59"}, {"WAIT_KIND": "handoff", "WAIT_NOTE": "#57 parou numa pergunta."},
                    {"WAIT_KIND": "running", "WAIT_NOTE": "#57 esta em execucao."}):
            proc, calls, _ = self.execute(**env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self.notices(calls), [], env)
            self.assertEqual([c[0] for c in calls], ["status"], env)

    def test_pai_fora_da_cadeia_so_atualiza_o_status(self):
        for env in ({}, {"STACK_ERROR": "PR #70 tem base `x`."}, {"WAIT_KIND": "human", "WAIT_NOTE": "humana"}):
            proc, calls, _ = self.execute(CHAIN="false", **env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(self.notices(calls), [], env)
            self.assertEqual([c[0] for c in calls], ["status"], env)

    def test_sem_responsavel_ainda_avisa(self):
        proc, calls, _ = self.execute(WAIT_KIND="human", WAIT_NOTE="humana", RESP_LOGINS="")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [notice] = self.notices(calls)
        self.assertEqual(self.opt(notice, "--logins"), "")

    def test_aviso_falhando_nao_falha_a_rodada(self):
        proc, calls, gh = self.execute(fail="notify", COMPLETE="true")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::warning::", proc.stdout)
        self.assertEqual([c[0] for c in calls], ["finish", "status", "notify"])
        self.assertIn("--add-label awaiting-pr-review", gh)
        proc, calls, gh = self.execute(fail="notify", WAIT_KIND="human", WAIT_NOTE="humana")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--remove-label work-in-progress", gh)



PR_CLOSED = "pr-closed.yml"
PR_CLOSED_STEP = "Devolver o estado dos issues do Closes"
READY_COLOR = "0E8A16"
READY_DESC = "Pronto para o agente executar"


def router_jobs():
    """{nome do job: bloco de texto} do router.yml."""
    body = (WORKFLOWS / "router.yml").read_text().split("\njobs:\n", 1)[1]
    jobs = re.split(r"^  (?=[a-z-]+:\n)", body, flags=re.M)
    return {job.split(":", 1)[0]: job for job in jobs if job.strip()}


def router_if(job):
    return " ".join(re.search(r"    if: >\n((?:      .*\n)+)", job).group(1).split())


def evaluate(cond, event_name, payload):
    """Avalia um `if` simples do router (so ==, !=, &&, ||, !) contra o evento."""
    ctx = {"event_name": event_name, "event": payload}

    def lookup(m):
        value = ctx
        for key in m.group(1).split("."):
            value = value.get(key) if isinstance(value, dict) else None
        return repr(value)

    expr = re.sub(r"\bgithub\.([\w.]+)", lookup, cond)
    expr = expr.replace("&&", " and ").replace("||", " or ")
    expr = re.sub(r"!(?!=)", " not ", expr).replace("true", "True").replace("false", "False")
    return eval(expr, {})


def closed_event(merged, base="main", action="closed"):
    return {"action": action, "repository": {"default_branch": "main"},
            "pull_request": {"merged": merged, "base": {"ref": base}, "labels": []}}


class PrClosedShape(unittest.TestCase):
    """O destino `pr-closed` do router.yml e o workflow que ele chama."""

    def test_job_chama_o_workflow_novo(self):
        job = router_jobs()["pr-closed"]
        self.assertIn(f"uses: samuel-morrissey/ai-workflows/.github/workflows/{PR_CLOSED}@main", job)
        self.assertTrue((WORKFLOWS / PR_CLOSED).exists())

    def test_fechado_sem_merge_em_qualquer_base_chama(self):
        cond = router_if(router_jobs()["pr-closed"])
        for base in ("main", "sub-task-66"):
            self.assertTrue(evaluate(cond, "pull_request", closed_event(False, base)), base)

    def test_mergeado_nao_chama(self):
        cond = router_if(router_jobs()["pr-closed"])
        for base in ("main", "sub-task-66"):
            self.assertFalse(evaluate(cond, "pull_request", closed_event(True, base)), base)

    def test_outros_eventos_nao_chamam(self):
        cond = router_if(router_jobs()["pr-closed"])
        self.assertFalse(evaluate(cond, "pull_request", closed_event(False, action="opened")))
        self.assertFalse(evaluate(cond, "issues", {"action": "closed"}))

    def test_pr_merged_continua_so_no_merge(self):
        cond = router_if(router_jobs()["pr-merged"])
        self.assertTrue(evaluate(cond, "pull_request", closed_event(True, "sub-task-66")))
        self.assertFalse(evaluate(cond, "pull_request", closed_event(False, "sub-task-66")))

    def test_so_gh_sem_agente(self):
        text = (WORKFLOWS / PR_CLOSED).read_text()
        self.assertIn("on:\n  workflow_call:\n", text)
        self.assertIn("\n  issues: write\n", text)
        self.assertNotIn(AGENT, text)
        self.assertEqual([n for n, _ in steps_of(text)], [PR_CLOSED_STEP])

    def test_docs_cobrem_a_excecao(self):
        labeling = (SKILLS / "issue-labeling" / "SKILL.md").read_text()
        rule = " ".join(labeling.split("2. **O fluxo so anda para frente:**", 1)[1].split("\n3. ", 1)[0].split())
        self.assertIn("fechado sem merge", rule)
        self.assertIn("`pr-closed.yml`", rule)
        row = [l for l in labeling.splitlines() if l.startswith("| `awaiting-pr-review` |")][0]
        self.assertIn("fechado sem merge", row)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("`pr-closed.yml`", readme.split("## Etapas", 1)[1].split("\n### ", 1)[0])
        self.assertIn("`pr-closed.yml`", readme.split("## Como funciona", 1)[1])


# gh falso com estado para o pr-closed: issues e PRs abertos em $FAKE_STATE,
# e as escritas do passo mudam esse estado.
FAKE_GH_CLOSED = r"""#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(" ".join(args) + "\n")
def opt(name):
    return args[args.index(name) + 1] if name in args else None
def save():
    json.dump(state, open(path, "w"))
cmd = " ".join(args[:2])
if cmd in state.get("fail", []):
    print("api indisponivel", file=sys.stderr); sys.exit(1)
issue = state["issues"].get(args[2]) if cmd.startswith("issue ") else None
if cmd == "issue view":
    if issue is None:
        print("Could not resolve to an issue", file=sys.stderr); sys.exit(1)
    print(json.dumps({"state": issue["state"], "title": issue["title"],
                      "labels": [{"name": n} for n in issue["labels"]]}))
elif cmd == "pr list":
    assert opt("--state") == "open", args
    print(json.dumps(state["prs"]))
elif cmd == "label create":
    if args[2] in state["repo_labels"]:
        print("label ja existe", file=sys.stderr); sys.exit(1)
    state["repo_labels"][args[2]] = {"color": opt("--color"), "description": opt("--description")}
    save()
elif cmd == "issue edit":
    add, remove = opt("--add-label"), opt("--remove-label")
    if add:
        if add not in state["repo_labels"]:
            print("label nao existe: %s" % add, file=sys.stderr); sys.exit(1)
        issue["labels"].append(add)
    if remove:
        issue["labels"].remove(remove)
    issue["edits"] = issue.get("edits", 0) + 1
    save()
elif cmd == "issue comment":
    issue.setdefault("comments", []).append(opt("--body"))
    save()
else:
    print("gh falso: comando inesperado: %s" % " ".join(args), file=sys.stderr); sys.exit(2)
"""


def issue(title="[INFRA] Pontual", labels=("awaiting-pr-review",), state="OPEN"):
    return {"title": title, "labels": list(labels), "state": state}


class PrClosedRun(unittest.TestCase):
    """Roda o passo do pr-closed.yml num bash com gh falso e confere os issues."""

    @classmethod
    def setUpClass(cls):
        block = dict(steps_of((WORKFLOWS / PR_CLOSED).read_text()))[PR_CLOSED_STEP]
        cls.script = workflow_run(block)

    def execute(self, body, issues, prs=(), repo_labels=None, fail=(), number="80"):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="prclosed-"))
        gh = tmp / "gh"
        gh.write_text(FAKE_GH_CLOSED)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        st = tmp / "state.json"
        st.write_text(json.dumps({
            "issues": issues, "prs": list(prs), "fail": list(fail),
            "repo_labels": repo_labels if repo_labels is not None else
            {"ready-for-agent": {"color": READY_COLOR, "description": READY_DESC},
             "awaiting-pr-review": {"color": REVIEW_COLOR, "description": REVIEW_DESC}}}))
        (tmp / "step.sh").write_text(self.script)
        env = {"PATH": f"{tmp}:{os.environ['PATH']}", "FAKE_STATE": str(st),
               "FAKE_GH_LOG": str(tmp / "log"), "GH_TOKEN": "x", "GH_REPO": "o/r",
               "PR_NUMBER": number, "BODY": body}
        # O shell padrao do GitHub Actions: bash -e com pipefail.
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp / "step.sh")],
                              env=env, capture_output=True, text=True)
        return proc, json.loads(st.read_text())

    def assertUntouched(self, after, n, labels):
        self.assertEqual(after["issues"][n]["labels"], list(labels), n)
        self.assertNotIn("edits", after["issues"][n], n)
        self.assertNotIn("comments", after["issues"][n], n)

    def test_pontual_volta_para_ready_for_agent_e_comenta(self):
        proc, after = self.execute("Closes #4\n\n## Resumo", {"4": issue()})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["4"]["labels"], ["ready-for-agent"])
        self.assertEqual(after["issues"]["4"]["edits"], 1, "troca numa unica operacao")
        [comment] = after["issues"]["4"]["comments"]
        self.assertIn("#80", comment)
        self.assertIn("`go`", comment)
        self.assertNotIn("@", comment)

    def test_fixes_e_resolves_tambem_contam(self):
        proc, after = self.execute("fixes #4\nResolves #5", {"4": issue(), "5": issue()})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["4"]["labels"], ["ready-for-agent"])
        self.assertEqual(after["issues"]["5"]["labels"], ["ready-for-agent"])

    def test_sub_task_perde_o_label_e_o_pai_volta(self):
        issues = {"57": issue("[SUB-TASK] Camada", ("awaiting-pr-review",)),
                  "56": issue("[FEAT] Pai", ("awaiting-pr-review",))}
        proc, after = self.execute("Closes #57\nParte de #56", issues)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["57"]["labels"], [])
        self.assertIn("#56", after["issues"]["57"]["comments"][0])
        self.assertEqual(after["issues"]["56"]["labels"], ["ready-for-agent"])
        self.assertIn("retomar a cadeia", after["issues"]["56"]["comments"][0])

    def test_pai_em_cadeia_nao_muda(self):
        issues = {"57": issue("[SUB-TASK] Camada"),
                  "56": issue("[FEAT] Pai", ("ready-for-agent", "work-in-progress"))}
        proc, after = self.execute("Closes #57\nParte de #56", issues)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["57"]["labels"], [])
        self.assertUntouched(after, "56", ("ready-for-agent", "work-in-progress"))
        issues["56"] = issue("[FEAT] Pai", ("ready-for-agent",))
        _, after = self.execute("Closes #57\nParte de #56", issues)
        self.assertUntouched(after, "56", ("ready-for-agent",))

    def test_camada_do_meio_com_o_topo_aberto_devolve_o_pai(self):
        # O topo aberto declara `Closes #56`; o guarda de outro PR nao vale para o pai.
        issues = {"57": issue("[SUB-TASK] Meio"), "56": issue("[FEAT] Pai")}
        prs = [pr(81, "Closes #58\nCloses #56\nParte de #56", closes=[58, 56])]
        proc, after = self.execute("Closes #57\nParte de #56", issues, prs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["56"]["labels"], ["ready-for-agent"])
        self.assertEqual(after["issues"]["57"]["labels"], [])

    def test_topo_da_stack_sem_dupla_troca(self):
        issues = {"58": issue("[SUB-TASK] Topo"), "56": issue("[FEAT] Pai")}
        proc, after = self.execute("Closes #58\nCloses #56\nParte de #56", issues)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["56"]["labels"], ["ready-for-agent"])
        self.assertEqual(after["issues"]["56"]["edits"], 1)
        self.assertEqual(len(after["issues"]["56"]["comments"]), 1)
        self.assertEqual(after["issues"]["58"]["labels"], [])

    def test_issues_fora_do_alcance_nao_mudam(self):
        issues = {"4": issue(state="CLOSED"),
                  "5": issue(labels=("ready-for-agent",)),
                  "6": issue(labels=("awaiting-pr-review", "work-in-progress")),
                  "7": issue(), "8": issue("[SUB-TASK] Outra")}
        prs = [pr(82, "Closes #7"), pr(83, "## Resumo", closes=[8])]
        body = "Closes #4\nCloses #5\nCloses #6\nCloses #7\nCloses #8\nCloses #9"
        proc, after = self.execute(body, issues, prs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertUntouched(after, "4", ("awaiting-pr-review",))
        self.assertUntouched(after, "5", ("ready-for-agent",))
        self.assertUntouched(after, "6", ("awaiting-pr-review", "work-in-progress"))
        self.assertUntouched(after, "7", ("awaiting-pr-review",))
        self.assertUntouched(after, "8", ("awaiting-pr-review",))
        self.assertIn("#9 nao encontrado", proc.stdout)

    def test_o_proprio_pr_e_numero_parecido_nao_contam_como_outro(self):
        prs = [pr(80, "Closes #4", closes=[4]), pr(84, "Closes #40\nver #4", closes=[40])]
        proc, after = self.execute("Closes #4", {"4": issue()}, prs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["issues"]["4"]["labels"], ["ready-for-agent"])

    def test_pr_sem_closes_termina_sem_mexer(self):
        proc, after = self.execute("Parte de #56\n\n## Resumo", {"56": issue("[FEAT] Pai")})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("::notice::PR #80 nao declara Closes", proc.stdout)
        self.assertUntouched(after, "56", ("awaiting-pr-review",))

    def test_cria_o_ready_for_agent_canonico_se_faltar(self):
        labels = {"awaiting-pr-review": {"color": REVIEW_COLOR, "description": REVIEW_DESC}}
        proc, after = self.execute("Closes #4", {"4": issue()}, repo_labels=labels)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(after["repo_labels"]["ready-for-agent"],
                         {"color": READY_COLOR, "description": READY_DESC})
        self.assertEqual(after["issues"]["4"]["labels"], ["ready-for-agent"])

    def test_cor_e_descricao_batem_com_a_issue_labeling(self):
        labeling = (SKILLS / "issue-labeling" / "SKILL.md").read_text()
        row = [l for l in labeling.splitlines() if l.startswith("| `ready-for-agent` |")][0]
        self.assertEqual([c.strip(" `") for c in row.strip("|").split("|")][-2:], [READY_COLOR, READY_DESC])

    def test_falha_de_api_falha_o_passo_sem_mexer(self):
        proc, after = self.execute("Closes #4", {"4": issue()}, fail=["pr list"])
        self.assertNotEqual(proc.returncode, 0)
        self.assertUntouched(after, "4", ("awaiting-pr-review",))


class SubTaskBaseCheckout(unittest.TestCase):
    """O setup da sub-task roda sobre a base da stack, nao sobre a branch padrao."""

    STEP = "Checkout da base da sub-task"

    def test_checkout_da_base_antes_do_ambiente(self):
        steps = steps_of((WORKFLOWS / "issue-sub-task.yml").read_text())
        names = [n for n, _ in steps]
        self.assertEqual(names.count(self.STEP), 1)
        self.assertGreater(names.index(self.STEP), names.index("Aplicar work-in-progress"))
        self.assertLess(names.index(self.STEP), names.index(RESP_STEP))
        self.assertLess(names.index(self.STEP), names.index("Preparar ambiente do agente"))
        step = parse_step(dict(steps)[self.STEP])
        self.assertEqual(step["uses"], "actions/checkout@v7")
        self.assertEqual(step["with"]["ref"], "${{ steps.target.outputs.base }}")
        # Historico completo: o agente cria a branch a partir de origin/<base>.
        self.assertIn("          fetch-depth: 0\n", dict(steps)[self.STEP])
        self.assertEqual(step["if"], parse_step(dict(steps)[AGENT])["if"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
