#!/usr/bin/env python3
"""Testes do passo "Registrar metricas da rodada" (composite action metrics)
nas 7 etapas, sem gh nem rede: a posicao e a condicao do passo em cada
workflow, o mapeamento passo -> grupo contra os passos do YAML, e o `run` da
action extraido do YAML e rodado num bash com um `gh` falso que responde a
API de jobs.

    python3 scripts/test_metrics.py
"""

import importlib.util
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_workflows import composite_run, parse_step, steps_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_DIR = ROOT / ".github" / "actions" / "metrics"
ACTION = ACTION_DIR / "action.yml"
METRICS_PY = ACTION_DIR / "metrics.py"
USES = "samuel-morrissey/ai-workflows/.github/actions/metrics@main"
STEP = "Registrar metricas da rodada"
FAILURE_STEP = "Comentar falha da rodada"
STAGES = ["issue-triage", "issue-refinement", "issue-break-down", "issue-remote-implement",
          "issue-sub-task", "pr-fix", "pr-merged"]
ORDER = ["preparo", "ambiente", "agente", "pos-agente"]
AGENT_STAGES = {"issue-triage": "50", "issue-refinement": "80", "issue-break-down": "100",
                "issue-remote-implement": "250", "issue-sub-task": "250", "pr-fix": "250"}

spec = importlib.util.spec_from_file_location("metrics", METRICS_PY)
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

FAKE_GH = r'''#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "api repos"*)
    [ "${FAKE_GH_API_FAIL:-}" = "1" ] && { echo "HTTP 503: api indisponivel" >&2; exit 1; }
    cat "$FAKE_GH_JOBS"
    ;;
  *) echo "gh falso: comando inesperado: $*" >&2; exit 2 ;;
esac
'''


def api_names(f):
    """Nomes dos passos do workflow como a API de jobs os mostra."""
    names = []
    for name, _ in steps_of((WORKFLOWS / f).read_text()):
        names.append(name if " " in name or "@" not in name else "Run " + name)
    return names


def t(sec):
    m, s = divmod(sec, 60)
    return f"2026-11-01T10:{m:02d}:{s:02d}Z"


def step(n, name, start, end, conclusion="success"):
    return {"number": n, "name": name, "status": "completed", "conclusion": conclusion,
            "started_at": t(start), "completed_at": t(end)}


def job(steps, runner="GitHub Actions 7", name="ai / Implement Issue", started=0):
    return {"name": name, "runner_name": runner, "status": "in_progress",
            "started_at": t(started), "steps": steps}


CHECK_CALLER = {"name": "ai / Check caller", "runner_name": "GitHub Actions 1", "started_at": t(0),
                "steps": [{"number": 1, "name": "Verificar o ai.yml do chamador", "conclusion": "success",
                           "started_at": t(0), "completed_at": t(50)}]}

# issue-remote-implement pontual: 0-60s de preparo, 60-90 ambiente, 90-400 agente,
# 400-430 pos-agente, os passos do planner pulados.
PONTUAL = {"jobs": [CHECK_CALLER, job([
    step(1, "Set up job", 0, 2),
    step(2, "Run actions/checkout@v7", 2, 5),
    step(3, "Resolver alvo", 5, 10),
    step(4, "Aplicar work-in-progress", 10, 15),
    step(5, "Resolver responsavel", 15, 20),
    step(6, "Preparar ambiente do agente", 20, 50),
    step(7, "Run anthropics/claude-code-action@v1", 50, 400),
    step(8, "Publicar evidencias", 400, 410),
    step(9, "Garantir awaiting-pr-review se ha PR aberto", 410, 415),
    step(10, "Remover work-in-progress", 415, 420),
    step(11, "Baixar o planner", 420, 420, "skipped"),
    step(12, "Entrar na cadeia", 420, 420, "skipped"),
    step(13, "Planejar e empilhar", 420, 420, "skipped"),
    step(14, "Resolver responsavel do pai", 420, 420, "skipped"),
    step(15, "Decidir e agir", 420, 420, "skipped"),
    {"number": 16, "name": STEP, "status": "in_progress", "conclusion": None,
     "started_at": t(421), "completed_at": None},
    {"number": 17, "name": FAILURE_STEP, "status": "pending", "conclusion": None,
     "started_at": None, "completed_at": None},
])]}

# O mesmo workflow num pai: o lado pontual inteiro pulado, o planner roda.
PAI = {"jobs": [job([
    step(1, "Set up job", 0, 1),
    step(2, "Run actions/checkout@v7", 1, 3),
    step(3, "Resolver alvo", 3, 6),
    step(4, "Aplicar work-in-progress", 6, 6, "skipped"),
    step(5, "Resolver responsavel", 6, 6, "skipped"),
    step(6, "Preparar ambiente do agente", 6, 6, "skipped"),
    step(7, "Run anthropics/claude-code-action@v1", 6, 6, "skipped"),
    step(8, "Publicar evidencias", 6, 6, "skipped"),
    step(9, "Garantir awaiting-pr-review se ha PR aberto", 6, 6, "skipped"),
    step(10, "Remover work-in-progress", 6, 6, "skipped"),
    step(11, "Baixar o planner", 6, 8),
    step(12, "Entrar na cadeia", 8, 12),
    step(13, "Planejar e empilhar", 12, 20),
    step(14, "Resolver responsavel do pai", 20, 22),
    step(15, "Decidir e agir", 22, 30),
    {"number": 16, "name": STEP, "status": "in_progress", "conclusion": None,
     "started_at": t(31), "completed_at": None},
])]}

def tool_use(name, uid):
    return {"type": "tool_use", "id": uid, "name": name, "input": {}}


def assistant(*tools, parent=None):
    return {"type": "assistant", "parent_tool_use_id": parent,
            "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}, *tools]}}


# Sessao como o execution_file da claude-code-action a grava: uma lista de
# mensagens, com o evento `result` no fim. A chamada a `Agent` abre um
# subagente (t4), cujas mensagens trazem parent_tool_use_id = "t4".
SESSION_MESSAGES = [
    {"type": "system", "subtype": "init", "session_id": "s1", "tools": ["Bash", "Read"]},
    assistant(tool_use("Bash", "t1")),
    {"type": "user", "parent_tool_use_id": None,
     "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
    assistant(tool_use("Read", "t2"), tool_use("Bash", "t3")),
    assistant(tool_use("Agent", "t4")),
    assistant(tool_use("Bash", "s1"), tool_use("Grep", "s2"), parent="t4"),
    assistant(tool_use("Write", "s3"), parent="t4"),
    assistant(tool_use("Edit", "t5")),
]
RESULT = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 42,
          "duration_ms": 330000, "duration_api_ms": 250500, "total_cost_usd": 1.2345,
          "usage": {"input_tokens": 1200, "output_tokens": 34000,
                    "cache_read_input_tokens": 2500000, "cache_creation_input_tokens": 98000}}
SESSION = SESSION_MESSAGES + [RESULT]
MAX_TURNS_SESSION = SESSION_MESSAGES + [{
    "type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 251,
    "duration_ms": 900000, "duration_api_ms": 700000,
    "usage": {"input_tokens": 10, "output_tokens": 20,
              "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}}]
MAIN_TOOLS = {"Agent": 1, "Bash": 2, "Edit": 1, "Read": 1}

MERGED = {"jobs": [job([
    step(1, "Set up job", 0, 1),
    step(2, "Fechar os issues do Closes", 1, 4),
    {"number": 3, "name": STEP, "status": "in_progress", "conclusion": None,
     "started_at": t(4), "completed_at": None},
], name="ai / Close Issues From Merged PR")]}


class Shape(unittest.TestCase):
    """O passo nas 7 etapas: uma vez, penultimo, sempre, sem derrubar."""

    def test_penultimo_passo_de_cada_workflow(self):
        for name in STAGES:
            names = [n for n, _ in steps_of((WORKFLOWS / f"{name}.yml").read_text())]
            self.assertEqual(names.count(STEP), 1, name)
            if FAILURE_STEP in names:
                # O round-failure continua o ultimo.
                self.assertEqual(names[-1], FAILURE_STEP, name)
                self.assertEqual(names[-2], STEP, name)
            else:
                # pr-merged nao tem round-failure: o de metricas e o ultimo.
                self.assertEqual(name, "pr-merged")
                self.assertEqual(names[-1], STEP, name)

    def test_always_sem_derrubar_o_job(self):
        for name in STAGES:
            block = dict(steps_of((WORKFLOWS / f"{name}.yml").read_text()))[STEP]
            s = parse_step(block)
            self.assertEqual(s["if"], "always()", name)
            self.assertEqual(s["continue_on_error"], "true", name)
            self.assertEqual(s["uses"], USES, name)
            self.assertEqual(s["with"]["etapa"], name, name)
            number = ("${{ github.event.pull_request.number }}" if name == "pr-merged"
                      else "${{ steps.target.outputs.number }}")
            self.assertEqual(s["with"]["number"], number, name)

    def test_permissao_actions_read(self):
        for name in STAGES:
            self.assertIn("\n  actions: read\n", (WORKFLOWS / f"{name}.yml").read_text(), name)

    def test_action_do_agente_com_id_e_metricas_com_execution_file_e_max_turns(self):
        for name in AGENT_STAGES:
            steps = dict(steps_of((WORKFLOWS / f"{name}.yml").read_text()))
            agent = steps["anthropics/claude-code-action@v1"]
            step_id = re.search(r"^        id: (\S+)$", agent, re.M)
            self.assertIsNotNone(step_id, f"{name}: o passo da action sem `id:`")
            turns = re.search(r"^            --max-turns (\d+)$", agent, re.M).group(1)
            self.assertEqual(turns, AGENT_STAGES[name], name)
            w = parse_step(steps[STEP])["with"]
            self.assertEqual(w.get("execution_file"),
                             "${{ steps.%s.outputs.execution_file }}" % step_id.group(1), name)
            self.assertEqual(w.get("max_turns"), turns, name)
        # As 6 etapas com agente e os tetos de turnos do brief.
        self.assertEqual(sorted(AGENT_STAGES), sorted(s for s in STAGES if s != "pr-merged"))
        w = parse_step(dict(steps_of((WORKFLOWS / "pr-merged.yml").read_text()))[STEP])["with"]
        self.assertNotIn("execution_file", w)
        self.assertNotIn("max_turns", w)

    def test_action_repassa_execution_file_e_max_turns_ao_script(self):
        text = ACTION.read_text()
        for line in ("  execution_file:\n", "  max_turns:\n",
                     "EXECUTION_FILE: ${{ inputs.execution_file }}",
                     "MAX_TURNS: ${{ inputs.max_turns }}"):
            self.assertIn(line, text)

    def test_artifact_metrics_sem_falhar_no_re_run(self):
        text = ACTION.read_text()
        self.assertIn("uses: actions/upload-artifact@v4", text)
        self.assertIn("name: metrics\n", text)
        self.assertIn("overwrite: true", text)
        self.assertIn("METRICS_PY: ${{ github.action_path }}/metrics.py", text)


class Mapping(unittest.TestCase):
    """Todo passo de cada workflow tem grupo, e o mapeamento nao cita passo que nao existe."""

    def test_todo_passo_tem_grupo(self):
        self.assertEqual(sorted(metrics.STAGES), sorted(STAGES))
        for name in STAGES:
            mapped = metrics.STAGES[name]["steps"]
            for step_name in api_names(f"{name}.yml"):
                if step_name in metrics.IGNORED:
                    continue
                self.assertIn(step_name, mapped, f"{name}: passo `{step_name}` sem grupo em metrics.py")
                self.assertIn(mapped[step_name], ORDER, name)

    def test_mapeamento_sem_passo_fantasma(self):
        for name in STAGES:
            real = set(api_names(f"{name}.yml"))
            for step_name in metrics.STAGES[name]["steps"]:
                self.assertIn(step_name, real, f"{name}: `{step_name}` nao existe no workflow")

    def test_grupos_por_etapa(self):
        sem_ambiente = {"issue-triage", "issue-refinement", "issue-break-down"}
        for name in STAGES:
            groups = metrics.stage_groups(name)
            if name == "pr-merged":
                self.assertEqual(groups, {"preparo", "pos-agente"})
            elif name in sem_ambiente:
                self.assertEqual(groups, {"preparo", "agente", "pos-agente"}, name)
            else:
                self.assertEqual(groups, set(ORDER), name)

    def test_nome_do_job_bate_com_o_workflow(self):
        for name in STAGES:
            self.assertIn(f"    name: {metrics.STAGES[name]['job']}\n",
                          (WORKFLOWS / f"{name}.yml").read_text(), name)


class Harness:
    """Roda o `run` da action num bash com gh falso e le o metrics.json e o summary."""

    def execute(self, jobs=PONTUAL, api_fail=False, raw=None, session=SESSION, session_raw=None,
                max_turns="250", **env):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="metrics-"))
        gh = tmp / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        (tmp / "jobs.json").write_text(raw if raw is not None else json.dumps(jobs))
        execution = ""
        if session_raw is not None or session is not None:
            execution = str(tmp / "claude-execution-output.json")
            pathlib.Path(execution).write_text(
                session_raw if session_raw is not None else json.dumps(session, indent=2))
        env.setdefault("EXECUTION_FILE", execution)
        env.setdefault("MAX_TURNS", max_turns)
        (tmp / "step.sh").write_text(composite_run(ACTION))
        e = {"PATH": f"{tmp}:{os.environ['PATH']}", "FAKE_GH_LOG": str(tmp / "log"),
             "FAKE_GH_JOBS": str(tmp / "jobs.json"), "FAKE_GH_API_FAIL": "1" if api_fail else "",
             "GH_TOKEN": "x", "GH_REPO": "o/r", "ETAPA": "issue-remote-implement", "NUMBER": "46",
             "METRICS_PY": str(METRICS_PY), "METRICS_DIR": str(tmp / "metrics"),
             "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1", "RUNNER_NAME": "GitHub Actions 7",
             "GITHUB_STEP_SUMMARY": str(tmp / "summary.md")}
        e.update(env)
        proc = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(tmp / "step.sh")],
                              env=e, capture_output=True, text=True)
        out = tmp / "metrics" / "metrics.json"
        data = json.loads(out.read_text()) if out.exists() else None
        summary = (tmp / "summary.md").read_text() if (tmp / "summary.md").exists() else ""
        log = (tmp / "log").read_text() if (tmp / "log").exists() else ""
        return proc, data, summary, log

    def groups(self, data):
        return [(g["nome"], g["estado"], g["segundos"]) for g in data["grupos"]]


class Run(Harness, unittest.TestCase):
    """Os grupos de passos, pelo mapeamento de cada etapa."""

    def test_soma_pelo_mapeamento_na_ordem_fixa(self):
        proc, data, summary, log = self.execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("api repos/o/r/actions/runs/123/attempts/1/jobs", log)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["etapa"], "issue-remote-implement")
        self.assertEqual(data["numero"], 46)
        self.assertEqual(data["run"], {"id": 123, "attempt": 1})
        self.assertEqual(self.groups(data), [
            ("preparo", "medido", 20), ("ambiente", "medido", 30),
            ("agente", "medido", 350), ("pos-agente", "medido", 20)])
        # Total do job ate o passo de metricas; o check-caller nunca entra.
        self.assertEqual(data["job"], {"nome": "ai / Implement Issue", "conclusao": "success", "segundos": 421})
        self.assertEqual(data["agente"]["estado"], "medido")
        self.assertEqual(data["avisos"], [])
        self.assertIn("| preparo | 20s |", summary)
        self.assertIn("| agente | 5m 50s |", summary)
        self.assertIn("| **total do job** | 7m 01s |", summary)
        rows = [line.split("|")[1].strip() for line in summary.splitlines() if line.startswith("| ")][1:5]
        self.assertEqual(rows, ORDER)

    def test_pai_pula_o_agente(self):
        proc, data, summary, _ = self.execute(jobs=PAI)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # O download do planner e preparo, mesmo rodando depois do lado pontual.
        self.assertEqual(self.groups(data), [
            ("preparo", "medido", 8), ("ambiente", "pulado", None),
            ("agente", "pulado", None), ("pos-agente", "medido", 22)])
        self.assertIn("| agente | pulado |", summary)

    def test_skip_da_guarda_pula_tudo_depois_do_wip(self):
        jobs = {"jobs": [job([
            step(1, "Set up job", 0, 1), step(2, "Run actions/checkout@v7", 1, 2),
            step(3, "Resolver numero do issue", 2, 3), step(4, "Aplicar work-in-progress", 3, 5),
            step(5, "Resolver responsavel", 5, 5, "skipped"),
            step(6, "Run anthropics/claude-code-action@v1", 5, 5, "skipped"),
            step(7, "Remover needs-triage se a triagem concluiu", 5, 5, "skipped"),
            step(8, "Remover work-in-progress", 5, 5, "skipped"),
            {"number": 9, "name": STEP, "started_at": t(6), "conclusion": None}],
            name="ai / Triage Issue")]}
        proc, data, _, _ = self.execute(jobs=jobs, ETAPA="issue-triage")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.groups(data), [
            ("preparo", "medido", 5), ("ambiente", "n/a", None),
            ("agente", "pulado", None), ("pos-agente", "pulado", None)])

    def test_pr_merged_sem_ambiente_nem_agente(self):
        proc, data, summary, _ = self.execute(jobs=MERGED, ETAPA="pr-merged", NUMBER="70")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.groups(data), [
            ("preparo", "medido", 1), ("ambiente", "n/a", None),
            ("agente", "n/a", None), ("pos-agente", "medido", 3)])
        self.assertIn("| ambiente | n/a |", summary)
        self.assertIn("| agente | n/a |", summary)
        self.assertIn("(#70)", summary)

    def test_api_falhando_sai_com_zero_e_n_d(self):
        proc, data, summary, _ = self.execute(api_fail=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([g["estado"] for g in data["grupos"]], ["n/d"] * 4)
        self.assertEqual(data["job"]["conclusao"], "n/d")
        self.assertIsNone(data["job"]["segundos"])
        self.assertIn("> [!WARNING]", summary)
        self.assertIn("Nao consegui ler os passos pela API de jobs", summary)
        self.assertIn("| preparo | n/d |", summary)
        self.assertIn("::warning::", proc.stdout)

    def test_api_falhando_mantem_n_a_dos_grupos_que_nao_existem(self):
        proc, data, _, _ = self.execute(api_fail=True, ETAPA="pr-merged")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([g["estado"] for g in data["grupos"]], ["n/d", "n/a", "n/a", "n/d"])

    def test_resposta_ilegivel_tambem_e_n_d(self):
        for raw in ("<html>bad gateway</html>", '{"message": "x"}'):
            proc, data, summary, _ = self.execute(raw=raw)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual([g["estado"] for g in data["grupos"]], ["n/d"] * 4, raw)
            self.assertIn("> [!WARNING]", summary)

    def test_agente_que_falhou_ainda_mede(self):
        jobs = json.loads(json.dumps(PONTUAL))
        steps = jobs["jobs"][1]["steps"]
        steps[6]["conclusion"] = "failure"
        for s in steps[7:10]:
            s["conclusion"] = "skipped"
        proc, data, _, _ = self.execute(jobs=jobs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["job"]["conclusao"], "failure")
        self.assertEqual(self.groups(data)[2], ("agente", "medido", 350))
        self.assertEqual(self.groups(data)[3], ("pos-agente", "pulado", None))

    def test_metricas_e_round_failure_nao_entram_na_soma(self):
        jobs = json.loads(json.dumps(PONTUAL))
        steps = jobs["jobs"][1]["steps"]
        steps[15].update(status="completed", conclusion="success", completed_at=t(900))
        steps[16].update(status="completed", conclusion="success", started_at=t(900), completed_at=t(999))
        _, data, _, _ = self.execute(jobs=jobs)
        self.assertEqual(self.groups(data)[3], ("pos-agente", "medido", 20))
        self.assertEqual(data["job"]["segundos"], 421)

    def test_re_run_registra_o_attempt(self):
        proc, data, _, log = self.execute(GITHUB_RUN_ATTEMPT="2")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("attempts/2/jobs", log)
        self.assertEqual(data["run"]["attempt"], 2)

    def test_sem_job_do_runner_usa_o_job_da_etapa_e_nunca_o_check_caller(self):
        proc, data, _, _ = self.execute(RUNNER_NAME="outro runner")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["job"]["nome"], "ai / Implement Issue")
        self.assertEqual(self.groups(data)[0], ("preparo", "medido", 20))
        only_caller = {"jobs": [CHECK_CALLER]}
        proc, data, summary, _ = self.execute(jobs=only_caller, RUNNER_NAME="outro runner")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([g["estado"] for g in data["grupos"]], ["n/d"] * 4)
        self.assertIn("Nenhum job da run casa", summary)

    def test_passo_sem_grupo_avisa(self):
        jobs = json.loads(json.dumps(PONTUAL))
        jobs["jobs"][1]["steps"][9]["name"] = "Passo renomeado"
        proc, data, summary, _ = self.execute(jobs=jobs)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("`Passo renomeado`", summary)
        self.assertEqual(self.groups(data)[3], ("pos-agente", "medido", 20))

    def test_sem_numero_fica_null(self):
        _, data, summary, _ = self.execute(NUMBER="")
        self.assertIsNone(data["numero"])
        self.assertIn("### Metricas da rodada: issue-remote-implement\n", summary)

    def test_script_quebrado_nao_falha_o_passo(self):
        proc, data, summary, _ = self.execute(ETAPA="etapa-inexistente")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(data)
        self.assertIn("Nao consegui medir a rodada", summary)


SESSION_KEYS = ["estado", "duracao_ms", "duracao_api_ms", "turnos", "max_turns", "fim", "tokens",
                "ferramentas", "custo_usd", "subagentes"]
TOKEN_KEYS = ["entrada", "saida", "cache_leitura", "cache_criacao"]


class Session(Harness, unittest.TestCase):
    """O objeto `agente` do metrics.json e a secao "Sessão do agente" do summary,
    lidos do execution_file da claude-code-action."""

    def assert_shape(self, agente):
        self.assertEqual(list(agente), SESSION_KEYS)
        self.assertEqual(list(agente["tokens"]), TOKEN_KEYS)

    def test_sessao_success_completa(self):
        proc, data, summary, _ = self.execute()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["schema_version"], 1)
        agente = data["agente"]
        self.assert_shape(agente)
        self.assertEqual(agente, {
            "estado": "medido", "duracao_ms": 330000, "duracao_api_ms": 250500, "turnos": 42,
            "max_turns": 250, "fim": "success",
            "tokens": {"entrada": 1200, "saida": 34000, "cache_leitura": 2500000, "cache_criacao": 98000},
            "ferramentas": MAIN_TOOLS, "custo_usd": 1.2345,
            # O Agent t4 nao tem description nem tool_result, e as mensagens nao tem tempo.
            "subagentes": [{"descricao": "n/d", "tipo": "n/d", "turnos": 2, "duracao_ms": "n/d",
                            "concluido": False}]})
        self.assertEqual(data["avisos"], [])
        section = summary.split("Sessão do agente", 1)[1]
        for cell in ("| duração | 5m 30s |", "| tempo de API | 4m 10s |", "| turnos | 42 |",
                     "| `--max-turns` | 250 |", "| fim | `success` |", "| tokens de entrada | 1200 |",
                     "| tokens de saída | 34000 |", "| leitura de cache | 2500000 |",
                     "| criação de cache | 98000 |", "| custo (informativo) | US$ 1.2345 |"):
            self.assertIn(cell, section, cell)
        self.assertIn("`Agent` 1 · `Bash` 2 · `Edit` 1 · `Read` 1", section)
        self.assertIn("OAuth", section)

    def test_sessao_error_max_turns_publica_o_que_ha(self):
        proc, data, summary, _ = self.execute(session=MAX_TURNS_SESSION)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agente = data["agente"]
        self.assert_shape(agente)
        self.assertEqual(agente["fim"], "error_max_turns")
        self.assertEqual(agente["turnos"], 251)
        self.assertEqual(agente["max_turns"], 250)
        # O result de erro nao traz custo: o campo fica presente, como n/d.
        self.assertEqual(agente["custo_usd"], "n/d")
        self.assertEqual(agente["ferramentas"], MAIN_TOOLS)
        self.assertIn("| fim | `error_max_turns` |", summary)
        self.assertIn("| custo (informativo) | n/d |", summary)

    def test_sessao_sem_result_conta_ferramentas_e_o_resto_e_n_d(self):
        proc, data, summary, _ = self.execute(session=SESSION_MESSAGES)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agente = data["agente"]
        self.assert_shape(agente)
        self.assertEqual(agente["estado"], "parcial")
        self.assertEqual(agente["ferramentas"], MAIN_TOOLS)
        self.assertEqual(agente["max_turns"], 250)
        for key in ("duracao_ms", "duracao_api_ms", "turnos", "fim", "custo_usd"):
            self.assertEqual(agente[key], "n/d", key)
        self.assertEqual(agente["tokens"], dict.fromkeys(TOKEN_KEYS, "n/d"))
        self.assertIn("sem o evento `result`", summary)

    def test_sem_execution_file_sai_n_d_com_aviso(self):
        cases = [dict(session=None), dict(EXECUTION_FILE="/nao/existe/output.json")]
        cases += [dict(session_raw=raw) for raw in ('[{"type": "system"}, {"type": "res', "", "nao e json",
                                                    '{"type": "result"}')]
        for case in cases:
            proc, data, summary, _ = self.execute(**case)
            self.assertEqual(proc.returncode, 0, (case, proc.stderr))
            agente = data["agente"]
            self.assert_shape(agente)
            self.assertEqual(agente["estado"], "n/d", case)
            for key in ("duracao_ms", "duracao_api_ms", "turnos", "fim", "ferramentas", "custo_usd"):
                self.assertEqual(agente[key], "n/d", (case, key))
            self.assertEqual(agente["tokens"], dict.fromkeys(TOKEN_KEYS, "n/d"), case)
            # O teto vem da config da etapa, nao da sessao.
            self.assertEqual(agente["max_turns"], 250, case)
            self.assertIn("> [!WARNING]", summary, case)
            self.assertIn("execution_file", summary, case)
            self.assertIn("| duração | n/d |", summary, case)
            # O resto das metricas sai normalmente.
            self.assertEqual(self.groups(data)[2], ("agente", "medido", 350), case)

    def test_subagente_fora_da_contagem(self):
        _, data, _, _ = self.execute()
        tools = data["agente"]["ferramentas"]
        self.assertNotIn("Grep", tools)
        self.assertNotIn("Write", tools)
        self.assertEqual(tools["Bash"], 2)

    def test_sessao_em_jsonl_tambem_e_lida(self):
        raw = "\n".join(json.dumps(m) for m in SESSION) + "\n"
        _, data, _, _ = self.execute(session_raw=raw)
        self.assertEqual(data["agente"]["estado"], "medido")
        self.assertEqual(data["agente"]["ferramentas"], MAIN_TOOLS)

    def test_agente_pulado_e_etapa_sem_agente(self):
        _, data, summary, _ = self.execute(jobs=PAI, session=None)
        self.assert_shape(data["agente"])
        self.assertEqual(data["agente"]["estado"], "pulado")
        self.assertEqual(data["agente"]["fim"], "pulado")
        self.assertEqual(data["avisos"], [])
        self.assertIn("Sessão do agente", summary)
        _, data, summary, _ = self.execute(jobs=MERGED, ETAPA="pr-merged", session=None, max_turns="")
        self.assert_shape(data["agente"])
        self.assertEqual(data["agente"]["estado"], "n/a")
        self.assertEqual(data["agente"]["max_turns"], "n/a")
        self.assertEqual(data["agente"]["tokens"], dict.fromkeys(TOKEN_KEYS, "n/a"))
        self.assertEqual(data["avisos"], [])

    def test_api_de_jobs_fora_ainda_le_a_sessao(self):
        _, data, _, _ = self.execute(api_fail=True)
        self.assertEqual(data["agente"]["estado"], "medido")
        self.assertEqual(data["agente"]["turnos"], 42)


def at(sec):
    return f"2026-11-01T11:{sec // 60:02d}:{sec % 60:02d}.000Z"


def agent_call(uid, description, subagent_type=None):
    inp = {"description": description, "prompt": "faca algo"}
    if subagent_type:
        inp["subagent_type"] = subagent_type
    return {"type": "tool_use", "id": uid, "name": "Agent", "input": inp}


def msg(kind, content, parent=None, ts=None, msg_id=None):
    m = {"type": kind, "parent_tool_use_id": parent, "message": {"role": kind, "content": content}}
    if msg_id:
        m["message"]["id"] = msg_id
    if ts is not None:
        m["timestamp"] = at(ts)
    return m


def result_of(uid, parent=None, ts=None):
    return msg("user", [{"type": "tool_result", "tool_use_id": uid, "content": "pronto"}], parent=parent, ts=ts)


def text(parent=None, ts=None, msg_id=None):
    return msg("assistant", [{"type": "text", "text": "ok"}], parent=parent, ts=ts, msg_id=msg_id)


# Duas chamadas Agent em sequencia, as duas concluidas: a1 (QA, 3 turnos,
# de 10s a 130s) e a2 (sem tipo, 2 turnos, de 140s a 200s).
TWO_AGENTS = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    msg("assistant", [agent_call("a1", "QA rodada 1", "general-purpose")], ts=10),
    text(parent="a1", ts=20), text(parent="a1", ts=60), text(parent="a1", ts=120),
    result_of("a1", ts=130),
    msg("assistant", [agent_call("a2", "QA rodada 2")], ts=140),
    text(parent="a2", ts=150), text(parent="a2", ts=190),
    result_of("a2", ts=200),
    text(ts=210),
    RESULT,
]


def strip_ts(messages):
    out = json.loads(json.dumps(messages))
    for m in out:
        m.pop("timestamp", None)
    return out


class Subagents(Harness, unittest.TestCase):
    """A quebra por subagente: `agente.subagentes` e a tabela "Subagentes"."""

    def table(self, summary):
        section = summary.split("#### Subagentes", 1)[1].split("\n\n", 2)[1]
        return [line for line in section.splitlines() if line.startswith("| ")][1:]

    def test_duas_chamadas_concluidas_na_ordem(self):
        proc, data, summary, _ = self.execute(session=TWO_AGENTS)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["agente"]["subagentes"], [
            {"descricao": "QA rodada 1", "tipo": "general-purpose", "turnos": 3, "duracao_ms": 120000,
             "concluido": True},
            {"descricao": "QA rodada 2", "tipo": "n/d", "turnos": 2, "duracao_ms": 60000, "concluido": True},
        ])
        rows = self.table(summary)
        self.assertEqual(len(rows), 2, summary)
        self.assertIn("QA rodada 1", rows[0])
        self.assertIn("2m 00s", rows[0])
        self.assertIn("| 3 |", rows[0])
        self.assertIn("QA rodada 2", rows[1])
        self.assertIn("1m 00s", rows[1])

    def test_sem_tempo_duracao_n_d_e_turnos_corretos(self):
        _, data, summary, _ = self.execute(session=strip_ts(TWO_AGENTS))
        subs = data["agente"]["subagentes"]
        self.assertEqual([s["turnos"] for s in subs], [3, 2])
        self.assertEqual([s["duracao_ms"] for s in subs], ["n/d", "n/d"])
        self.assertEqual([s["concluido"] for s in subs], [True, True])
        self.assertTrue(all("n/d" in r for r in self.table(summary)))

    def test_chamada_sem_tool_result_nao_concluida(self):
        cut = TWO_AGENTS[:6] + [msg("assistant", [agent_call("a2", "QA rodada 2")], ts=140),
                                text(parent="a2", ts=150)]
        proc, data, summary, _ = self.execute(session=cut)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        subs = data["agente"]["subagentes"]
        self.assertEqual(subs[0]["concluido"], True)
        self.assertEqual(subs[1], {"descricao": "QA rodada 2", "tipo": "n/d", "turnos": 1,
                                   "duracao_ms": "n/d", "concluido": False})
        rows = self.table(summary)
        self.assertIn("não", rows[1])
        self.assertIn("sim", rows[0])

    def test_paralelos_contam_so_o_proprio_parent(self):
        parallel = [
            msg("assistant", [agent_call("p1", "explorar A"), agent_call("p2", "explorar B", "Explore")], ts=0),
            text(parent="p1", ts=5), text(parent="p2", ts=6), text(parent="p2", ts=7),
            text(parent="p1", ts=8), text(parent="p2", ts=9), text(parent="p1", ts=10),
            text(parent="p2", ts=11),
            result_of("p2", ts=30), result_of("p1", ts=50),
            RESULT,
        ]
        _, data, summary, _ = self.execute(session=parallel)
        subs = data["agente"]["subagentes"]
        self.assertEqual([(s["descricao"], s["turnos"], s["duracao_ms"]) for s in subs],
                         [("explorar A", 3, 50000), ("explorar B", 4, 30000)])
        self.assertEqual(len(self.table(summary)), 2)

    def test_turno_e_a_mensagem_do_assistente_nao_o_bloco(self):
        # O SDK pode partir uma mensagem do assistente em varios eventos com o mesmo id.
        split = [
            msg("assistant", [agent_call("a1", "qa")], ts=0),
            text(parent="a1", ts=1, msg_id="m1"), text(parent="a1", ts=2, msg_id="m1"),
            text(parent="a1", ts=3, msg_id="m2"),
            result_of("a1", ts=4), RESULT,
        ]
        _, data, _, _ = self.execute(session=split)
        self.assertEqual(data["agente"]["subagentes"][0]["turnos"], 2)

    def test_subagente_aninhado_conta_o_proprio_id(self):
        nested = [
            msg("assistant", [agent_call("a1", "fora")], ts=0),
            text(parent="a1", ts=1),
            msg("assistant", [agent_call("b1", "dentro")], parent="a1", ts=2),
            text(parent="b1", ts=3), text(parent="b1", ts=4),
            result_of("b1", parent="a1", ts=5),
            text(parent="a1", ts=6),
            result_of("a1", ts=10), RESULT,
        ]
        _, data, _, _ = self.execute(session=nested)
        subs = data["agente"]["subagentes"]
        self.assertEqual([(s["descricao"], s["turnos"], s["duracao_ms"]) for s in subs],
                         [("fora", 3, 10000), ("dentro", 2, 3000)])

    def test_sessao_sem_agent_tabela_com_nenhum(self):
        proc, data, summary, _ = self.execute(session=[text(ts=0), RESULT])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(data["agente"]["subagentes"], [])
        rows = self.table(summary)
        self.assertEqual(len(rows), 1)
        self.assertIn("nenhum", rows[0])

    def test_sem_execution_file_lista_n_d(self):
        _, data, summary, _ = self.execute(session=None)
        self.assertEqual(data["agente"]["subagentes"], "n/d")
        self.assertIn("n/d", self.table(summary)[0])

    def test_sessao_sem_result_ainda_lista(self):
        _, data, _, _ = self.execute(session=TWO_AGENTS[:-1])
        self.assertEqual(data["agente"]["estado"], "parcial")
        self.assertEqual(len(data["agente"]["subagentes"]), 2)

    def test_agente_pulado_e_etapa_sem_agente(self):
        _, data, summary, _ = self.execute(jobs=PAI, session=None)
        self.assertEqual(data["agente"]["subagentes"], "pulado")
        self.assertIn("#### Subagentes", summary)
        _, data, _, _ = self.execute(jobs=MERGED, ETAPA="pr-merged", session=None, max_turns="")
        self.assertEqual(data["agente"]["subagentes"], "n/a")

    def test_descricao_com_barra_nao_quebra_a_tabela(self):
        session = [msg("assistant", [agent_call("a1", "QA | rodada")], ts=0), result_of("a1", ts=1), RESULT]
        _, _, summary, _ = self.execute(session=session)
        self.assertIn("QA \\| rodada", self.table(summary)[0])


class Readme(unittest.TestCase):
    def test_readme_descreve_summary_grupos_e_artifact(self):
        readme = (ROOT / "README.md").read_text()
        section = readme.split("## Métricas", 1)[1].split("\n## ", 1)[0]
        for word in ("$GITHUB_STEP_SUMMARY", "`preparo`", "`ambiente`", "`agente`", "`pos-agente`",
                     "`pulado`", "`n/a`", "`n/d`", "`metrics`", "metrics.json", "schema_version"):
            self.assertIn(word, section, word)
        for word in ("Sessão do agente", "execution_file", "duracao_ms", "duracao_api_ms", "turnos",
                     "max_turns", "fim", "tokens", "ferramentas", "parent_tool_use_id", "custo_usd",
                     "informativo", "`parcial`"):
            self.assertIn(word, section, word)
        for word in ("Subagentes", "subagentes", "descricao", "tipo", "duracao_ms", "concluido",
                     "nenhum", "tool_result", "timestamp"):
            self.assertIn(word, section, word)
        testar = readme.split("## Testar", 1)[1].split("\n## ", 1)[0]
        self.assertIn("scripts/test_metrics.py", testar)

    def test_readme_mostra_como_rodar_o_script_de_comparacao(self):
        readme = (ROOT / "README.md").read_text()
        section = readme.split("## Métricas", 1)[1].split("\n## ", 1)[0]
        self.assertIn("python3 scripts/metrics.py", section)
        for word in ("--runs", "mediana", "p90", "`schema_version`", "sem artifact"):
            self.assertIn(word, section, word)
        testar = readme.split("## Testar", 1)[1].split("\n## ", 1)[0]
        self.assertIn("scripts/metrics.py", testar)


# --- scripts/metrics.py: a comparacao entre runs --------------------------

COMPARE_PY = ROOT / "scripts" / "metrics.py"
REPO = "o/r"

# Um `gh` falso que serve as rotas de um JSON: cada rota e um arquivo (o zip
# do artifact) ou um corpo JSON; rota ausente vira HTTP 404.
FAKE_GH_ROUTES = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_GH_FAIL"):
    sys.stderr.write(os.environ["FAKE_GH_FAIL"] + "\n")
    sys.exit(1)
if args[:1] != ["api"] or len(args) != 2:
    sys.stderr.write("gh falso: comando inesperado: %r\n" % (args,))
    sys.exit(2)
import re, urllib.parse
data = json.load(open(os.environ["FAKE_GH_ROUTES"]))
route = data["routes"].get(args[1])
m = re.fullmatch(r"repos/(.+)/actions/runs\?(.*)", args[1])
if route is None and m and m.group(1) == data["repo"]:
    q = dict(urllib.parse.parse_qsl(m.group(2)))
    n, p = int(q["per_page"]), int(q["page"])
    runs = [{"id": r, "run_attempt": 1} for r in data["runs"]]
    route = {"json": {"total_count": len(runs), "workflow_runs": runs[(p - 1) * n:p * n]}}
if route is None:
    sys.stderr.write("gh: Not Found (HTTP 404)\n")
    sys.exit(1)
if "file" in route:
    sys.stdout.buffer.write(open(route["file"], "rb").read())
else:
    sys.stdout.write(json.dumps(route["json"]))
'''

SESSION_FIELDS = ("duracao_ms", "duracao_api_ms", "turnos", "custo_usd")


def metrics_json(etapa, run_id, groups=(10, 0, 100, 5), agente=None, schema=1, attempt=1):
    """Um metrics.json como a action grava. `groups` traz os 4 grupos na
    ordem fixa: numero vira `medido`, string vira o estado."""
    grupos = [{"nome": n, "estado": "medido", "segundos": v} if isinstance(v, (int, float))
              else {"nome": n, "estado": v, "segundos": None} for n, v in zip(ORDER, groups)]
    if agente is None:
        agente = session_of(60000, 40000, 12, 1000, 200, 5000, 300, 0.5)
    return {"schema_version": schema, "etapa": etapa, "numero": 1,
            "run": {"id": run_id, "attempt": attempt},
            "job": {"nome": "x", "conclusao": "success", "segundos": 200},
            "grupos": grupos, "agente": agente, "avisos": []}


def session_of(dur, api, turns, entrada, saida, leitura, criacao, custo, state="medido"):
    return {"estado": state, "duracao_ms": dur, "duracao_api_ms": api, "turnos": turns,
            "max_turns": 250, "fim": "success",
            "tokens": {"entrada": entrada, "saida": saida, "cache_leitura": leitura,
                       "cache_criacao": criacao},
            "ferramentas": {}, "custo_usd": custo, "subagentes": []}


class CompareHarness:
    """Monta runs e artifacts num GitHub falso e roda scripts/metrics.py."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        bindir = self.dir / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(FAKE_GH_ROUTES)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.bindir = bindir
        self.runs = []      # ids, do mais novo ao mais velho
        self.routes = {}
        self.next_artifact = 1

    def tearDown(self):
        self.tmp.cleanup()

    def add_run(self, run_id, *payloads, expired=False):
        """Uma run com um artifact `metrics` por payload (dict ou texto cru); sem
        payload, a run nao tem artifact."""
        import zipfile
        self.runs.append(run_id)
        artifacts = []
        for i, payload in enumerate(payloads):
            aid = self.next_artifact
            self.next_artifact += 1
            path = self.dir / f"a{aid}.zip"
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("metrics.json", payload if isinstance(payload, str) else json.dumps(payload))
            self.routes[f"repos/{REPO}/actions/artifacts/{aid}/zip"] = {"file": str(path)}
            artifacts.append({"id": aid, "name": "metrics", "expired": expired,
                              "created_at": f"2026-11-01T10:00:0{i}Z",
                              "workflow_run": {"id": run_id}})
        self.routes[f"repos/{REPO}/actions/runs/{run_id}/artifacts?name=metrics&per_page=100"] = {
            "json": {"total_count": len(artifacts), "artifacts": artifacts}}

    def compare(self, *args, fail=None, repo=REPO):
        routes = self.dir / "routes.json"
        routes.write_text(json.dumps({"repo": REPO, "runs": self.runs, "routes": self.routes}))
        log = self.dir / "gh.log"
        log.write_text("")
        env = {**os.environ, "PATH": f"{self.bindir}{os.pathsep}{os.environ['PATH']}",
               "FAKE_GH_ROUTES": str(routes), "FAKE_GH_LOG": str(log)}
        env.pop("FAKE_GH_FAIL", None)
        if fail:
            env["FAKE_GH_FAIL"] = fail
        proc = subprocess.run([sys.executable, "-I", str(COMPARE_PY), repo, *args],
                              capture_output=True, text=True, env=env, timeout=60)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return proc, calls

    @staticmethod
    def section(out, etapa):
        """As linhas da tabela de uma etapa: {linha: (valores, mediana, p90)}."""
        block = out.split(f"### {etapa}", 1)[1].split("\n### ", 1)[0]
        rows = {}
        for line in block.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 4 and cells[0] not in ("Linha", "---"):
                rows[cells[0]] = tuple(cells[1:])
        return block, rows


ROW_NAMES = ["preparo", "ambiente", "agente", "pos-agente", "sessão: duração", "sessão: tempo de API",
             "sessão: turnos", "sessão: tokens de entrada", "sessão: tokens de saída",
             "sessão: leitura de cache", "sessão: criação de cache", "sessão: custo (informativo)"]


class Compare(CompareHarness, unittest.TestCase):
    def test_uma_linha_por_grupo_e_metrica_da_sessao_com_mediana_e_p90(self):
        # 10 runs do issue-sub-task: o preparo vai de 10s a 100s; mediana 55s
        # (media dos dois do meio), p90 pelo posto mais proximo: o 9o, 90s.
        for i in range(1, 11):
            self.add_run(100 + i, metrics_json(
                "issue-sub-task", 100 + i, groups=(10 * i, 60 * i, 120, 1),
                agente=session_of(1000 * i, 500 * i, i, 100 * i, 10 * i, 1000 * i, 7, 0.01 * i)))
        proc, _ = self.compare()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block, rows = self.section(proc.stdout, "issue-sub-task")
        self.assertIn("10 runs", block.splitlines()[0])
        self.assertEqual(list(rows), ROW_NAMES)
        self.assertEqual(rows["preparo"], ("10", "55s", "1m 30s"))
        self.assertEqual(rows["ambiente"], ("10", "5m 30s", "9m 00s"))
        self.assertEqual(rows["agente"], ("10", "2m 00s", "2m 00s"))
        self.assertEqual(rows["pos-agente"], ("10", "1s", "1s"))
        self.assertEqual(rows["sessão: duração"], ("10", "6s", "9s"))  # 5.5s arredonda para cima
        self.assertEqual(rows["sessão: tempo de API"], ("10", "3s", "5s"))  # 2.75s e 4.5s
        self.assertEqual(rows["sessão: turnos"], ("10", "5.5", "9"))
        self.assertEqual(rows["sessão: tokens de entrada"], ("10", "550", "900"))
        self.assertEqual(rows["sessão: tokens de saída"], ("10", "55", "90"))
        self.assertEqual(rows["sessão: leitura de cache"], ("10", "5500", "9000"))
        self.assertEqual(rows["sessão: criação de cache"], ("10", "7", "7"))
        self.assertEqual(rows["sessão: custo (informativo)"], ("10", "US$ 0.0550", "US$ 0.0900"))

    def test_etapa_com_uma_run_tem_mediana_e_p90_iguais_ao_valor(self):
        self.add_run(1, metrics_json("issue-triage", 1, groups=(42, "n/a", 300, 3),
                                     agente=session_of(250000, 1, 7, 1, 1, 1, 1, 1.25)))
        proc, _ = self.compare()
        _, rows = self.section(proc.stdout, "issue-triage")
        self.assertEqual(rows["preparo"], ("1", "42s", "42s"))
        self.assertEqual(rows["agente"], ("1", "5m 00s", "5m 00s"))
        self.assertEqual(rows["sessão: duração"], ("1", "4m 10s", "4m 10s"))
        self.assertEqual(rows["sessão: turnos"], ("1", "7", "7"))
        self.assertEqual(rows["sessão: custo (informativo)"], ("1", "US$ 1.2500", "US$ 1.2500"))

    def test_saida_estavel_etapas_na_ordem_fixa(self):
        # Runs chegam misturadas; a saida segue a ordem das 7 etapas.
        self.add_run(5, metrics_json("pr-merged", 5, groups=("n/a", "n/a", "n/a", 2),
                                     agente=session_of(*["n/a"] * 8, state="n/a")))
        self.add_run(4, metrics_json("issue-triage", 4))
        self.add_run(3, metrics_json("issue-sub-task", 3))
        self.add_run(2, metrics_json("issue-refinement", 2))
        first, _ = self.compare()
        second, _ = self.compare()
        self.assertEqual(first.stdout, second.stdout)
        heads = re.findall(r"^### ([\w-]+)", first.stdout, re.M)
        self.assertEqual(heads, ["issue-triage", "issue-refinement", "issue-sub-task", "pr-merged"])
        self.assertEqual(list(self.section(first.stdout, "pr-merged")[1]), ROW_NAMES)

    def test_ordem_das_etapas_e_a_da_action(self):
        self.assertEqual(list(metrics.STAGES), STAGES)
        source = COMPARE_PY.read_text()
        positions = [source.index(f'"{s}"') for s in STAGES]
        self.assertEqual(positions, sorted(positions))

    def test_celula_so_com_estados_sai_nd(self):
        self.add_run(2, metrics_json("issue-remote-implement", 2, groups=(5, "pulado", "pulado", 3),
                                     agente=session_of(*["pulado"] * 8, state="pulado")))
        self.add_run(1, metrics_json("issue-remote-implement", 1, groups=(7, "n/d", "pulado", "n/d"),
                                     agente=session_of(*["n/d"] * 8, state="n/d")))
        proc, _ = self.compare()
        _, rows = self.section(proc.stdout, "issue-remote-implement")
        self.assertEqual(rows["preparo"], ("2", "6s", "7s"))
        self.assertEqual(rows["pos-agente"], ("1", "3s", "3s"))  # o n/d nao entra
        for name in ROW_NAMES[1:3] + ROW_NAMES[4:]:
            self.assertEqual(rows[name], ("0", "n/d", "n/d"), name)

    def test_runs_sem_artifact_e_schema_desconhecido_ficam_de_fora_com_aviso(self):
        self.add_run(6, metrics_json("issue-triage", 6, groups=(10, "n/a", 1, 1)))
        self.add_run(5)                                                  # sem artifact
        self.add_run(4)                                                  # sem artifact
        self.add_run(3, metrics_json("issue-triage", 3, groups=(999, "n/a", 1, 1)),
                     expired=True)                                       # expirado
        self.add_run(2, metrics_json("issue-triage", 2, groups=(500, "n/a", 1, 1), schema=2))
        self.add_run(1, metrics_json("issue-triage", 1, groups=(30, "n/a", 1, 1)))
        proc, _ = self.compare()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block, rows = self.section(proc.stdout, "issue-triage")
        self.assertIn("2 runs", block.splitlines()[0])
        self.assertEqual(rows["preparo"], ("2", "20s", "30s"))
        self.assertIn("3 runs sem artifact `metrics`", proc.stdout)
        self.assertIn("1 run com `schema_version` desconhecido", proc.stdout)

    def test_metrics_json_ilegivel_fica_de_fora_sem_quebrar(self):
        self.add_run(2, "{nao e json")
        self.add_run(1, metrics_json("issue-triage", 1))
        proc, _ = self.compare()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 run com `metrics.json` ilegível", proc.stdout)
        self.assertIn("### issue-triage", proc.stdout)

    def test_re_run_conta_cada_run_uma_vez(self):
        # Dois artifacts na mesma run (attempts 1 e 2) e a run repetida na
        # lista (paginacao que andou): conta uma vez, o artifact mais novo.
        self.add_run(7, metrics_json("pr-fix", 7, groups=(100, 1, 1, 1), attempt=1),
                     metrics_json("pr-fix", 7, groups=(20, 1, 1, 1), attempt=2))
        self.runs.append(7)
        proc, calls = self.compare()
        block, rows = self.section(proc.stdout, "pr-fix")
        self.assertIn("1 run", block.splitlines()[0])
        self.assertEqual(rows["preparo"], ("1", "20s", "20s"))
        zips = [c for c in calls if c[1].endswith("/zip")]
        self.assertEqual(len(zips), 1)

    def test_flag_de_n_limita_as_runs(self):
        for i in range(5, 0, -1):
            self.add_run(i, metrics_json("issue-triage", i, groups=(10 * i, "n/a", 1, 1)))
        proc, calls = self.compare("--runs", "2")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block, rows = self.section(proc.stdout, "issue-triage")
        self.assertIn("2 runs", block.splitlines()[0])
        self.assertEqual(rows["preparo"], ("2", "45s", "50s"))  # as runs 5 e 4, as mais novas
        listed = {c[1] for c in calls if "/runs/" in c[1] and c[1].endswith("artifacts?name=metrics&per_page=100")}
        self.assertEqual(listed, {f"repos/{REPO}/actions/runs/{i}/artifacts?name=metrics&per_page=100"
                                  for i in (5, 4)})
        self.assertIn("últimas 2 runs", proc.stdout)

    def test_flag_de_n_pagina_alem_de_100(self):
        for i in range(150, 0, -1):
            self.add_run(i)
        proc, calls = self.compare("--runs", "120")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        listed = [c for c in calls if c[1].endswith("artifacts?name=metrics&per_page=100")]
        self.assertEqual(len(listed), 120)
        self.assertIn("120 runs sem artifact `metrics`", proc.stdout)

    def test_padrao_de_runs(self):
        for i in range(80, 0, -1):
            self.add_run(i)
        proc, calls = self.compare()
        listed = [c for c in calls if c[1].endswith("artifacts?name=metrics&per_page=100")]
        self.assertEqual(len(listed), 50)

    def test_flag_de_n_invalida(self):
        proc, _ = self.compare("--runs", "0")
        self.assertNotEqual(proc.returncode, 0)

    def test_sem_metricas_avisa_e_sai_com_zero(self):
        self.add_run(2)
        self.add_run(1)
        proc, _ = self.compare()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Nenhuma run com métricas", proc.stdout)
        self.assertNotIn("###", proc.stdout)

    def test_repositorio_sem_runs_avisa_e_sai_com_zero(self):
        proc, _ = self.compare()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Nenhuma run com métricas", proc.stdout)

    def test_gh_falhando_sai_com_erro(self):
        proc, _ = self.compare(fail="gh: To get started with GitHub CLI, please run:  gh auth login")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("erro:", proc.stderr)
        self.assertIn("gh auth login", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_repo_inexistente_sai_com_erro(self):
        proc, _ = self.compare(repo="o/inexistente")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("erro:", proc.stderr)
        self.assertIn("HTTP 404", proc.stderr)

    def test_repo_mal_formado(self):
        proc = subprocess.run([sys.executable, "-I", str(COMPARE_PY), "sem-barra"],
                              capture_output=True, text=True, timeout=60)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("owner/repo", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
