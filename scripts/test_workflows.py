#!/usr/bin/env python3
"""Testes do passo "Comentar falha da rodada" dos workflows reutilizaveis
(issue-triage, issue-refinement, issue-break-down, issue-remote-implement e
issue-sub-task), sem gh nem rede. O passo e a composite action round-failure:
cada workflow a chama como ultimo passo, e o `run` dela e extraido do YAML e
roda num bash com um `gh` falso.

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
         "issue-remote-implement.yml", "issue-sub-task.yml"]
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
