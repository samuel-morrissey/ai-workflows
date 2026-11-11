#!/usr/bin/env python3
"""Testes do encadeamento das etapas antes da implementacao, sem gh nem rede:

- os destinos do router.yml para o `repository_dispatch` do tipo
  `ai-advance`, avaliados com o `router_if` do test_workflows.py;
- o tipo novo no ai.yml modelo, e o doctor apontando a copia antiga;
- o scripts/advance.py: `check` (auto_advance e ai.yml do checkout, frase
  do system prompt) e `run` (despacha a etapa seguinte, ou nao, ou comenta
  pedindo `go` quando o dispatch falha), com um GitHub falso;
- o `undo` durante uma etapa encadeada (`undo.py --chained-from`);
- a forma dos workflows de etapa e da action advance, e as docs.

    python3 scripts/test_advance.py
"""

import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import advance  # noqa: E402
import doctor  # noqa: E402
import undo  # noqa: E402
from test_undo import (  # noqa: E402
    BRIEF, PARENT, QUEBRA, R, REFINAMENTO, RODADA, TRIAGEM_SUGERIDO, FakeGitHub, labeled)
from test_workflows import (  # noqa: E402
    composite_run, evaluate, outputs_of, parse_step, router_if, router_jobs, steps_of)

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SKILLS = ROOT / "skills"
ACTION = ROOT / ".github" / "actions" / "advance" / "action.yml"
ADVANCE_USES = "samuel-morrissey/ai-workflows/.github/actions/advance@main"
MODEL = (WORKFLOWS / "ai.yml").read_text()
OLD_AI_YML = MODEL.replace("types: [ai-implement, ai-sub-task, ai-advance]", "types: [ai-implement, ai-sub-task]")
CHECK_STEP = "Ler encadeamento"
RUN_STEP = "Chamar a etapa seguinte"
WIP_IF = "always() && steps.wip.outcome == 'success' && steps.wip.outputs.skip != 'true'"
TRIAGEM_SPEC = ("## Triagem\n\n**Tipo:** `[SPEC]` (sugerido: `[FEAT]`)\n**Estado:** `needs-refinement`\n"
                "**Por que:** amplo\n**Em seguida:** o `/issue-refinement` roda sozinho, sem `go`. "
                "Aplique o label `undo` para desfazer esta triagem.")


def dispatch(stage, number=PARENT, sender="Bot"):
    return {"action": "ai-advance", "client_payload": {"issue": number, "stage": stage, "from": "triagem"},
            "sender": {"type": sender}}


class Router(unittest.TestCase):
    """O tipo novo de repository_dispatch, avaliado pelo `if` do router.yml."""

    def jobs(self):
        return {name: router_if(job) for name, job in router_jobs().items() if "    if: >" in job}

    def running(self, event_name, payload):
        return sorted(n for n, cond in self.jobs().items() if evaluate(cond, event_name, payload))

    def test_refinamento_roda_so_o_destino_de_refinamento(self):
        self.assertEqual(self.running("repository_dispatch", dispatch("refinement")), ["issue-refinement"])

    def test_quebra_roda_so_o_destino_de_quebra(self):
        self.assertEqual(self.running("repository_dispatch", dispatch("break-down")), ["issue-break-down"])

    def test_etapa_desconhecida_ou_sem_etapa_nao_roda_nada(self):
        for stage in ("triage", "implement", "", None):
            self.assertEqual(self.running("repository_dispatch", dispatch(stage)), [], stage)

    def test_tipos_de_antes_continuam_nos_destinos_de_hoje(self):
        self.assertEqual(self.running("repository_dispatch", {"action": "ai-implement", "client_payload": {"issue": 5}}),
                         ["issue-remote-implement"])
        self.assertEqual(self.running("repository_dispatch", {"action": "ai-sub-task", "client_payload": {"issue": 6}}),
                         ["issue-sub-task"])
        # O payload de etapa num tipo antigo nao desvia o destino.
        self.assertEqual(self.running("repository_dispatch", {"action": "ai-implement",
                                                              "client_payload": {"issue": 5, "stage": "refinement"}}),
                         ["issue-remote-implement"])

    def test_go_manual_continua_valendo(self):
        self.assertEqual(self.running("issues", labeled("go", labels=("needs-refinement",))),
                         ["check-caller", "issue-refinement"])
        self.assertEqual(self.running("issues", labeled("go", labels=("needs-break-down",))),
                         ["check-caller", "issue-break-down"])

    def test_dispatch_nao_passa_pelo_check_caller(self):
        # Elo interno: nenhum humano agindo, como nos tipos da cadeia de sub-tasks.
        self.assertFalse(evaluate(self.jobs()["check-caller"], "repository_dispatch", dispatch("refinement")))


class AiYml(unittest.TestCase):
    def test_modelo_declara_o_tipo_novo(self):
        m = re.search(r"\n  repository_dispatch:\n    types: \[([^\]]*)\]\n", MODEL)
        self.assertEqual([t.strip() for t in m.group(1).split(",")], ["ai-implement", "ai-sub-task", "ai-advance"])
        self.assertEqual(advance.EVENT_TYPE, "ai-advance")

    def test_doctor_aponta_a_copia_antiga(self):
        self.assertNotEqual(doctor.normalize(OLD_AI_YML), doctor.normalize(MODEL))
        repo = SimpleNamespace(full="dono/app", ref="main", default_branch="main", template=MODEL,
                               ai_yml=OLD_AI_YML, inline={})
        with mock.patch.object(doctor, "model_prs", lambda r: []):
            f = doctor.check_ai_yml(repo)
        self.assertEqual(f.status, "diverge", f.detail)
        self.assertIn("--only ai-yml", f.fix)
        repo.ai_yml = MODEL
        self.assertEqual(doctor.check_ai_yml(repo).status, "ok")

    def test_check_json_aponta_ai_yml_divergente(self):
        def fake_repo(full, *_):
            return SimpleNamespace(full=full, ref="main", default_branch="main", is_org=False, template=MODEL,
                                   ai_yml=OLD_AI_YML, inline={})
        out = io.StringIO()
        with mock.patch.object(doctor, "Repo", fake_repo), mock.patch.object(doctor, "model_prs", lambda r: []), \
                contextlib.redirect_stdout(out):
            code = doctor.main(["check", "dono/app", "--only", "ai-yml", "--json"])
        [finding] = json.loads(out.getvalue())["findings"]
        self.assertEqual((finding["item"], finding["status"]), ("ai-yml", "diverge"))
        self.assertEqual(code, 1)


class DoctorConfig(unittest.TestCase):
    def check(self, text):
        repo = SimpleNamespace(config_text=text, config_error=None, inline={},
                               config=doctor.parse_simple_yaml(text))
        return doctor.check_config(repo)

    def test_auto_advance_false_e_chave_conhecida(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\nweb_domains: docs.x.com\n"
                       "auto_advance: false\n")
        self.assertEqual(f.status, "ok", f.detail)
        self.assertNotIn("desconhecida", f.detail)
        self.assertIn("auto_advance", doctor.CONFIG_KEYS)

    def test_comentario_de_modelo_cita_a_chave(self):
        text = doctor.render_config_yaml({"quality_checks": "make test\n", "auto_advance": "false"})
        header = [l for l in text.splitlines() if l.startswith("#")]
        self.assertTrue(any("auto_advance" in l for l in header), header)
        self.assertIn("auto_advance: false\n", text)
        self.assertEqual(doctor.parse_simple_yaml(text)["auto_advance"], "false")


class Check(unittest.TestCase):
    """`advance.py check`: o encadeamento vale com o ai.yml novo e sem `auto_advance: false`."""

    def check(self, config=None, ai_yml=MODEL, stage="triagem"):
        return advance.check(stage, config, ai_yml)

    def assertSafe(self, sentence):
        for ch in '"`$\\\n':
            self.assertNotIn(ch, sentence)

    def test_sem_chave_encadeia(self):
        for config in (None, "", "quality_checks: make test\n"):
            out = self.check(config)
            self.assertTrue(out["enabled"], config)
            self.assertTrue(out["sentence"].startswith(" Encadeamento: ligado"), out)
            self.assertIn("nao peca go e nao marque ninguem", out["sentence"])
            self.assertIn("undo", out["sentence"])
            self.assertSafe(out["sentence"])

    def test_auto_advance_false_desliga(self):
        for config in ("auto_advance: false\n", "auto_advance: False # sem cadeia\n", "auto_advance: 'false'\n",
                       "quality_checks: |\n  make\nauto_advance:   false\n"):
            out = self.check(config)
            self.assertFalse(out["enabled"], config)
            self.assertIn("auto_advance", out["reason"])
            self.assertTrue(out["sentence"].startswith(" Encadeamento: desligado"), out)
            self.assertIn("pede go e marca o responsavel", out["sentence"])
            self.assertSafe(out["sentence"])

    def test_outro_valor_encadeia(self):
        for config in ("auto_advance: true\n", "auto_advance: no\n", "auto_advance: falso\n", "auto_advance:\n",
                       "# auto_advance: false\n", "setup_commands: |\n  auto_advance: false\n"):
            self.assertTrue(self.check(config)["enabled"], config)

    def test_ai_yml_antigo_desliga(self):
        for ai_yml in (OLD_AI_YML, None, ""):
            out = self.check(ai_yml=ai_yml)
            self.assertFalse(out["enabled"], ai_yml)
            self.assertIn("ai-advance", out["reason"])
            self.assertTrue(out["sentence"].startswith(" Encadeamento: desligado"))
            self.assertSafe(out["sentence"])

    def test_frase_nomeia_os_estados_da_etapa(self):
        self.assertIn("needs-refinement ou needs-break-down", self.check(stage="triagem")["sentence"])
        refinamento = self.check(stage="refinamento")["sentence"]
        self.assertIn("needs-break-down", refinamento)
        self.assertNotIn("needs-refinement", refinamento)

    def test_cli_grava_no_github_output(self):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="adv-"))
        (tmp / ".github" / "workflows").mkdir(parents=True)
        (tmp / ".github" / "workflows" / "ai.yml").write_text(MODEL)
        (tmp / ".github" / "ai-workflows.yml").write_text("auto_advance: false\n")
        proc = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "advance.py"), "check", "--stage",
                               "triagem", "--github-output", str(tmp / "out")],
                              cwd=tmp, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = outputs_of((tmp / "out").read_text())
        self.assertEqual(out["enabled"], "false")
        self.assertTrue(out["sentence"].startswith(" Encadeamento: desligado"))


class FakeRepo:
    """Issue e dispatches do repositorio, respondendo as rotas do advance.py."""

    def __init__(self, labels, state="open", fail=()):
        self.issue = {"number": PARENT, "state": state, "labels": [{"name": n} for n in labels]}
        self.dispatches, self.comments, self.fail = [], [], set(fail)

    def api(self, path, method=None, body=None):
        if (method or "GET", path) in self.fail or path in self.fail:
            raise advance.ApiError(f"gh api {method or 'GET'} {path}: HTTP 422")
        if path == f"{R}/issues/{PARENT}" and not method:
            return self.issue
        if path == f"{R}/dispatches" and method == "POST":
            self.dispatches.append(body)
            return None
        if path == f"{R}/issues/{PARENT}/comments" and method == "POST":
            self.comments.append(body["body"])
            return {}
        raise AssertionError(f"rota inesperada: {method} {path}")


class Run(unittest.TestCase):
    """`advance.py run`: despacha, nao despacha, ou comenta pedindo `go`."""

    def execute(self, gh, stage="triagem", before="needs-triage", enabled=True, logins="ana", undo_result=""):
        with mock.patch.object(advance, "api", gh.api), mock.patch.object(advance, "REPO", "o/r"):
            return advance.run(PARENT, stage, before, enabled, logins, undo_result)

    def test_triagem_em_needs_refinement_chama_o_refinamento(self):
        gh = FakeRepo(["needs-refinement"])
        out = self.execute(gh)
        self.assertEqual(out["action"], "dispatch", out)
        self.assertEqual(gh.dispatches, [{"event_type": "ai-advance",
                                          "client_payload": {"issue": PARENT, "stage": "refinement",
                                                             "from": "triagem"}}])
        self.assertEqual(gh.comments, [])
        # O payload enviado roda so o destino de refinamento.
        event = {"action": gh.dispatches[0]["event_type"], "client_payload": gh.dispatches[0]["client_payload"]}
        self.assertEqual(Router().running("repository_dispatch", event), ["issue-refinement"])

    def test_triagem_e_refinamento_em_needs_break_down_chamam_a_quebra(self):
        for stage, before in (("triagem", "needs-triage"), ("refinamento", "needs-refinement")):
            gh = FakeRepo(["needs-break-down", "priority"])
            out = self.execute(gh, stage=stage, before=before)
            self.assertEqual(out["action"], "dispatch", stage)
            [sent] = gh.dispatches
            self.assertEqual(sent["client_payload"], {"issue": PARENT, "stage": "break-down", "from": stage})
            event = {"action": sent["event_type"], "client_payload": sent["client_payload"]}
            self.assertEqual(Router().running("repository_dispatch", event), ["issue-break-down"])

    def test_auto_advance_false_nao_despacha(self):
        for stage, labels in (("triagem", ["needs-refinement"]), ("triagem", ["needs-break-down"]),
                              ("refinamento", ["needs-break-down"])):
            gh = FakeRepo(labels)
            out = self.execute(gh, stage=stage, before="needs-triage" if stage == "triagem" else "needs-refinement",
                               enabled=False)
            self.assertEqual(out["action"], "none", out)
            self.assertEqual((gh.dispatches, gh.comments), ([], []))

    def test_pergunta_discovery_e_ready_nao_despacham(self):
        for labels in (["needs-triage", "awaiting-reply"], ["needs-discovery"], ["ready-for-agent"],
                       ["ready-for-human"], ["needs-refinement", "awaiting-reply"]):
            gh = FakeRepo(labels)
            out = self.execute(gh)
            self.assertEqual(out["action"], "none", labels)
            self.assertEqual((gh.dispatches, gh.comments), ([], []), labels)
        # Refinamento que parou numa rodada de perguntas.
        gh = FakeRepo(["needs-refinement", "awaiting-reply"])
        self.assertEqual(self.execute(gh, stage="refinamento", before="needs-refinement")["action"], "none")
        self.assertEqual(gh.dispatches, [])

    def test_fechado_wontfix_ou_deferred_nao_despacha(self):
        for labels, state in ((["needs-refinement"], "closed"), (["wontfix"], "closed"),
                              (["deferred", "needs-refinement"], "open")):
            gh = FakeRepo(labels, state=state)
            self.assertEqual(self.execute(gh)["action"], "none", labels)
            self.assertEqual((gh.dispatches, gh.comments), ([], []))

    def test_estado_que_nao_mudou_na_rodada_nao_despacha(self):
        gh = FakeRepo(["needs-break-down"])
        out = self.execute(gh, stage="refinamento", before="needs-break-down")
        self.assertEqual(out["action"], "none")
        self.assertEqual(gh.dispatches, [])

    def test_undo_da_rodada_nao_despacha(self):
        # Revertido: o estado ja voltou; nada e chamado nem comentado.
        gh = FakeRepo(["needs-triage"])
        out = self.execute(gh, undo_result='{"action": "revert", "stage": "triagem"}')
        self.assertEqual(out["action"], "none")
        self.assertEqual((gh.dispatches, gh.comments), ([], []))
        # Recusado ou ainda no issue: nao chama, e o comentario novo pede `go`.
        for labels, result in ((["needs-refinement"], '{"action": "refuse"}'),
                               (["needs-refinement", "undo"], "")):
            gh = FakeRepo(labels)
            out = self.execute(gh, undo_result=result)
            self.assertEqual(out["action"], "failed", labels)
            self.assertEqual(gh.dispatches, [])
            [body] = gh.comments
            self.assertIn("aplique o label `go`", body)

    def test_dispatch_que_falha_comenta_pedindo_go_e_marca(self):
        gh = FakeRepo(["needs-refinement"], fail=[f"{R}/dispatches"])
        out = self.execute(gh, logins="ana bia")
        self.assertEqual(out["action"], "failed", out)
        [body] = gh.comments
        self.assertTrue(body.startswith("## Etapa seguinte nao chamada"), body)
        self.assertIn("**Proximo passo** (@ana @bia): aplique o label `go`", body)
        self.assertIn("`/issue-refinement`", body)
        self.assertIn("HTTP 422", body)

    def test_dispatch_que_falha_sem_responsavel_nao_marca(self):
        gh = FakeRepo(["needs-break-down"], fail=[f"{R}/dispatches"])
        out = self.execute(gh, stage="refinamento", before="needs-refinement", logins="")
        self.assertEqual(out["action"], "failed")
        [body] = gh.comments
        self.assertNotIn("@", body)
        self.assertIn("**Proximo passo:** aplique o label `go`", body)
        self.assertIn("**Responsavel:** nao ha responsavel identificavel; ninguem foi marcado.", body)
        self.assertIn("`/issue-break-down`", body)

    def test_login_estranho_nao_vira_mencao(self):
        gh = FakeRepo(["needs-refinement"], fail=[f"{R}/dispatches"])
        self.execute(gh, logins="x[bot] ana $(id)")
        [body] = gh.comments
        self.assertIn("(@ana)", body)
        self.assertNotIn("bot", body)
        self.assertNotIn("$(", body)

    def test_comentario_que_falha_nao_derruba(self):
        gh = FakeRepo(["needs-refinement"], fail=[f"{R}/dispatches", f"{R}/issues/{PARENT}/comments"])
        out = self.execute(gh)
        self.assertEqual(out["action"], "failed")
        self.assertIn("comentario", out["reason"])

    def test_cli(self):
        gh = FakeRepo(["needs-refinement"])
        out = io.StringIO()
        argv = ["advance.py", "run", str(PARENT), "--stage", "triagem", "--before", "needs-triage",
                "--enabled", "true", "--logins", "ana"]
        with mock.patch.object(advance, "api", gh.api), mock.patch.object(advance, "REPO", "o/r"), \
                mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
            advance.main()
        self.assertEqual(json.loads(out.getvalue())["action"], "dispatch")


class ChainedUndo(unittest.TestCase):
    """`undo` aplicado durante uma etapa encadeada: desfaz as duas."""

    def execute(self, gh, chained_from):
        with mock.patch.object(undo, "api", gh.api), mock.patch.object(undo, "REPO", "o/r"), \
                mock.patch.object(undo, "OWNER", "o"):
            return undo.run(PARENT, True, chained_from)

    def no_dispatch(self, gh, out, stage="refinamento", before="needs-refinement"):
        repo = FakeRepo(gh.issues[PARENT]["labels"])
        with mock.patch.object(advance, "api", repo.api), mock.patch.object(advance, "REPO", "o/r"):
            result = advance.run(PARENT, stage, before, True, "ana", json.dumps(out))
        self.assertEqual(result["action"], "none", result)
        self.assertEqual((repo.dispatches, repo.comments), ([], []))

    def test_refinamento_encadeado_pela_triagem_volta_a_needs_triage(self):
        # Triagem [SPEC] encadeou o refinamento; o `undo` chegou durante ele, e
        # o refinamento terminou em needs-break-down.
        gh = FakeGitHub(["needs-break-down", "work-in-progress", "undo"], [TRIAGEM_SPEC, REFINAMENTO],
                        title="[SPEC] foo", repo_labels=("undo", "needs-refinement", "needs-break-down",
                                                         "needs-triage"))
        out = self.execute(gh, "triagem")
        self.assertEqual(out["action"], "revert", out)
        self.assertEqual(out["stage"], "refinamento")
        self.assertEqual(out["also"]["stage"], "triagem")
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-triage", "work-in-progress"])
        self.assertEqual(gh.issues[PARENT]["title"], "[FEAT] foo")
        self.assertEqual(gh.issues[PARENT]["body"], "corpo")
        undos = [c["body"] for c in gh.issues[PARENT]["comments"][2:]]
        self.assertEqual(len(undos), 2)
        self.assertIn("<!-- ai:undo etapa=refinamento -->", undos[0])
        self.assertIn("encadeado pela triagem", undos[0])
        self.assertIn("<!-- ai:undo etapa=triagem -->", undos[1])
        for body in undos:
            self.assertNotIn("@", body)
        self.no_dispatch(gh, out)

    def test_pontual_grande_volta_titulo_e_corpo_de_antes(self):
        triagem = ("## Triagem\n\n**Tipo:** `[FEAT]` (sugerido: `[BUG]`)\n**Estado:** `needs-break-down`\n"
                   "**Por que:** grande")
        gh = FakeGitHub(["ready-for-agent", "work-in-progress", "undo"], [triagem, QUEBRA], title="[FEAT] grande")
        gh.issues[PARENT]["body"] = BRIEF
        out = self.execute(gh, "triagem")
        self.assertEqual((out["stage"], out["also"]["stage"]), ("quebra", "triagem"))
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-triage", "work-in-progress"])
        self.assertEqual(gh.issues[PARENT]["title"], "[BUG] grande")
        self.assertEqual(gh.issues[PARENT]["body"], BRIEF, "o corpo de antes da triagem e o mesmo")

    def test_refinamento_que_parou_em_pergunta_so_desfaz_a_triagem(self):
        gh = FakeGitHub(["needs-refinement", "awaiting-reply", "work-in-progress", "undo"], [TRIAGEM_SPEC, RODADA],
                        title="[SPEC] foo", repo_labels=("undo", "needs-triage"))
        out = self.execute(gh, "triagem")
        self.assertEqual(out["stage"], "triagem")
        self.assertNotIn("also", out)
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-triage", "work-in-progress"])
        self.assertEqual(gh.issues[PARENT]["title"], "[FEAT] foo")

    def test_quebra_encadeada_pelo_refinamento_volta_a_needs_refinement(self):
        gh = FakeGitHub(["ready-for-agent", "work-in-progress", "undo"], [TRIAGEM_SPEC, REFINAMENTO, QUEBRA],
                        subs=(101,))
        out = self.execute(gh, "refinamento")
        self.assertEqual((out["stage"], out["also"]["stage"]), ("quebra", "refinamento"))
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-refinement", "work-in-progress"])
        self.assertEqual(gh.issues[101]["state"], "closed")

    def test_sem_cadeia_desfaz_uma_etapa_so(self):
        gh = FakeGitHub(["needs-break-down", "work-in-progress", "undo"], [TRIAGEM_SPEC, REFINAMENTO],
                        title="[SPEC] foo")
        out = self.execute(gh, None)
        self.assertEqual(out["stage"], "refinamento")
        self.assertNotIn("also", out)
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-refinement", "work-in-progress"])
        self.assertEqual(gh.issues[PARENT]["title"], "[SPEC] foo")

    def test_sem_undo_nada_muda(self):
        gh = FakeGitHub(["needs-break-down", "work-in-progress"], [TRIAGEM_SPEC, REFINAMENTO])
        out = self.execute(gh, "triagem")
        self.assertEqual(out["action"], "none")
        self.assertEqual(gh.writes(), [])

    def test_cli_aceita_chained_from(self):
        gh = FakeGitHub(["needs-refinement", "work-in-progress", "undo"], [TRIAGEM_SUGERIDO], title="[SPEC] foo",
                        repo_labels=("undo", "needs-triage"))
        out = io.StringIO()
        argv = ["undo.py", "run", str(PARENT), "--pending", "--chained-from", "triagem"]
        with mock.patch.object(undo, "api", gh.api), mock.patch.object(undo, "REPO", "o/r"), \
                mock.patch.object(undo, "OWNER", "o"), mock.patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(out):
            undo.main()
        self.assertEqual(json.loads(out.getvalue())["stage"], "triagem")


class Shape(unittest.TestCase):
    """Os workflows de etapa, a action advance e a action undo."""

    def steps(self, f):
        return steps_of((WORKFLOWS / f).read_text())

    def test_etapas_resolvem_o_issue_pelo_payload(self):
        for f in ("issue-refinement.yml", "issue-break-down.yml"):
            target = dict(self.steps(f))["Resolver numero do issue"]
            self.assertIn("PAYLOAD_NUMBER: ${{ github.event.client_payload.issue }}", target, f)
            self.assertIn("PAYLOAD_FROM: ${{ github.event.client_payload.from }}", target, f)
            self.assertIn('echo "from=', target, f)

    def test_guarda_da_etapa_despachada(self):
        for f, label in (("issue-refinement.yml", "needs-refinement"), ("issue-break-down.yml", "needs-break-down")):
            wip = dict(self.steps(f))["Aplicar work-in-progress"]
            self.assertIn("FROM: ${{ steps.target.outputs.from }}", wip, f)
            self.assertIn(f"EXPECTED: {label}", wip, f)

    def test_undo_da_rodada_recebe_a_etapa_que_encadeou(self):
        for f in ("issue-refinement.yml", "issue-break-down.yml"):
            step = parse_step(dict(self.steps(f))["Processar undo da rodada"])
            self.assertEqual(step["with"]["chained_from"], "${{ steps.target.outputs.from }}", f)
        action = (ROOT / ".github" / "actions" / "undo" / "action.yml").read_text()
        self.assertIn("  chained_from:\n", action)
        self.assertIn("--chained-from", composite_run(ROOT / ".github" / "actions" / "undo" / "action.yml"))

    def test_triagem_e_refinamento_leem_o_encadeamento_antes_do_agente(self):
        for f, stage in (("issue-triage.yml", "triagem"), ("issue-refinement.yml", "refinamento")):
            steps = self.steps(f)
            names = [n for n, _ in steps]
            i = names.index(CHECK_STEP)
            self.assertGreater(i, names.index("Aplicar work-in-progress"), f)
            self.assertLess(i, names.index("anthropics/claude-code-action@v1"), f)
            step = parse_step(dict(steps)[CHECK_STEP])
            self.assertEqual(step["uses"], ADVANCE_USES, f)
            self.assertEqual(step["with"]["mode"], "check", f)
            self.assertEqual(step["with"]["stage"], stage, f)
            self.assertEqual(step["continue_on_error"], "true", f)
            self.assertRegex(dict(steps)[CHECK_STEP], r"(?m)^        id: chain$", f)
            agent = dict(steps)["anthropics/claude-code-action@v1"]
            self.assertIn("${{ steps.web.outputs.sentence }}${{ steps.chain.outputs.sentence }}\"", agent, f)

    def test_triagem_e_refinamento_chamam_a_seguinte_depois_do_wip(self):
        for f, stage in (("issue-triage.yml", "triagem"), ("issue-refinement.yml", "refinamento")):
            steps = self.steps(f)
            names = [n for n, _ in steps]
            i = names.index(RUN_STEP)
            self.assertEqual(names[i - 1], "Remover work-in-progress", f)
            self.assertLess(names.index("Processar undo da rodada"), i, f)
            step = parse_step(dict(steps)[RUN_STEP])
            self.assertEqual(step["uses"], ADVANCE_USES, f)
            # So quando a rodada inteira deu certo: falha fora do agente nao encadeia.
            self.assertEqual(step["if"], "success() && steps.wip.outputs.skip != 'true'", f)
            self.assertEqual(step["continue_on_error"], "true", f)
            w = step["with"]
            self.assertEqual(w["mode"], "run", f)
            self.assertEqual(w["stage"], stage, f)
            self.assertEqual(w["enabled"], "${{ steps.chain.outputs.enabled }}", f)
            self.assertEqual(w["before"], "${{ steps.chain.outputs.before }}", f)
            self.assertEqual(w["logins"], "${{ steps.responsavel.outputs.logins }}", f)
            self.assertEqual(w["undo_result"], "${{ steps.undo.outputs.result }}", f)
            self.assertRegex(dict(steps)["Processar undo da rodada"], r"(?m)^        id: undo$", f)

    def test_quebra_nao_encadeia(self):
        names = [n for n, _ in self.steps("issue-break-down.yml")]
        self.assertNotIn(RUN_STEP, names)
        self.assertNotIn(CHECK_STEP, names)

    def test_action_roda_o_script_da_mesma_ref(self):
        text = ACTION.read_text()
        self.assertIn("ADVANCE_PY: ${{ github.action_path }}/../../../scripts/advance.py", text)
        self.assertIn("GH_REPO: ${{ github.repository }}", text)
        for name in ("mode", "stage", "number", "enabled", "before", "logins", "undo_result"):
            self.assertIn(f"\n  {name}:\n", text, name)
        for name in ("enabled", "sentence", "before", "result"):
            self.assertRegex(text, rf"\n  {name}:\n    description:", name)


def flat(text):
    return " ".join(text.split())


class Docs(unittest.TestCase):
    def skill(self, name):
        return (SKILLS / name / "SKILL.md").read_text()

    def test_triagem_cita_undo_sem_go_nem_mencao_quando_encadeia(self):
        text = self.skill("issue-triage")
        self.assertIn('"Encadeamento:"', text)
        lines = [l for l in text.splitlines() if l.strip().startswith("**Em seguida:**")]
        self.assertGreaterEqual(len(lines), 2, "passos 5 e 6.3")
        for line in lines:
            self.assertNotIn("@", line)
            self.assertIn("`undo`", line)
            self.assertIn("sem `go`", line)
        self.assertIn("`/issue-refinement`", " ".join(lines))
        self.assertIn("`/issue-break-down`", " ".join(lines))

    def test_refinamento_cita_undo_sem_go_nem_mencao_quando_encadeia(self):
        text = self.skill("issue-refinement")
        self.assertIn('"Encadeamento:"', text)
        final = text.split("\n## Refinamento\n", 1)[1]
        [line] = [l for l in final.splitlines() if l.strip().startswith("**Em seguida:**")]
        self.assertNotIn("@", line)
        self.assertIn("`/issue-break-down`", line)
        self.assertIn("`undo`", line)

    def test_quebra_pede_go_da_implementacao(self):
        text = flat(self.skill("issue-break-down"))
        self.assertIn("**Proximo passo** (@responsavel): aplique o label `go` neste issue", text)
        self.assertIn("Antes do `go` da implementacao", text)
        self.assertIn("rodar encadeada", text)

    def test_async_first_mencao_nao_vale_para_etapa_que_encadeia(self):
        section = flat(self.skill("issue-async-first").split("## Mencao ao responsavel", 1)[1].split("\n## ", 1)[0])
        self.assertIn("etapa que encadeia", section)
        self.assertIn("nao marca ninguem", section)

    def test_labeling(self):
        text = self.skill("issue-labeling")
        partida = flat(text.split("\n## Label de partida\n", 1)[1].split("\n## ", 1)[0])
        for s in ("`auto_advance: false`", "`ai-advance`", "a implementacao", "seguem sozinhas"):
            self.assertIn(s, partida, s)
        for label in ("needs-refinement", "needs-break-down"):
            row = [l for l in text.splitlines() if l.startswith(f"| `{label}` |")][0]
            self.assertIn("sozinh", row, label)
            self.assertIn("`go`", row, label)
        reading = flat(text.split("Lendo os labels juntos:", 1)[1].split("\n## ", 1)[0])
        self.assertIn("encade", reading)

    def test_agent_brief_editavel_antes_do_go_da_implementacao(self):
        brief = flat((SKILLS / "issue-triage" / "AGENT-BRIEF.md").read_text())
        section = brief.split("**O brief e editavel.**", 1)[1][:1200]
        self.assertIn("`go` da implementacao", section)
        self.assertIn("`undo`", section)

    def test_readme(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("`ai-advance`", readme)
        config = readme.split("\n### O arquivo `.github/ai-workflows.yml`\n", 1)[1].split("\n### ", 1)[0]
        item = flat(config.split("- `auto_advance`:", 1)[1].split("\n- ", 1)[0])
        for s in ("`auto_advance: false`", "`go`", "encade", "qualquer outro valor"):
            self.assertIn(s, item, s)
        notif = flat(readme.split("### Notificação", 1)[1].split("\n## ", 1)[0])
        self.assertIn("encadeia", notif)
        self.assertIn("Etapa seguinte não chamada", notif)

    def test_router_e_ai_yml(self):
        router = (WORKFLOWS / "router.yml").read_text().split("\non:\n", 1)[0]
        self.assertIn("`ai-advance`", router)
        self.assertIn("auto_advance", router)
        head = MODEL.split("\npermissions:", 1)[0]
        self.assertIn("`ai-advance`", head)


if __name__ == "__main__":
    unittest.main(verbosity=1)
