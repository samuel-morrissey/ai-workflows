#!/usr/bin/env python3
"""Testes do passo "Comentar falha da rodada" dos workflows reutilizaveis
(issue-triage, issue-refinement, issue-break-down, issue-remote-implement,
issue-sub-task e pr-fix), sem gh nem rede. O passo e a composite action round-failure:
cada workflow a chama como ultimo passo, e o `run` dela e extraido do YAML e
roda num bash com um `gh` falso.

Tambem testa o passo "Garantir awaiting-pr-review se ha PR aberto" do
issue-remote-implement.yml, com um `gh` falso que guarda o estado do issue.

    python3 scripts/test_workflows.py
"""

import json
import os
import pathlib
import re
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

    def execute(self, env=None, jobs=JOBS, api_fail=False, comment_fail=False):
        tmp = tempfile.mkdtemp(prefix="wf-")
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
        }
        e.update(env or {})
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

    def test_numero_vem_do_evento_ou_do_payload(self):
        _, log, _ = self.execute(env={"NUMBER": "", "EVENT_NUMBER": "51"})
        self.assertIn("issue comment 51", log)
        _, log, _ = self.execute(env={"NUMBER": "", "PAYLOAD_NUMBER": "52"})
        self.assertIn("issue comment 52", log)


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
