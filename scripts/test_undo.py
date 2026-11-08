#!/usr/bin/env python3
"""Testes do label `undo`, sem gh nem rede:

- o destino `issue-undo` do router.yml, avaliado com o `router_if` do
  test_workflows.py;
- o scripts/undo.py com um GitHub falso no lugar do `gh api`: reversao do
  refinamento e da quebra, recusas e `undo` aplicado de novo;
- o issue-undo.yml, a action undo e o passo "Processar undo da rodada" das
  etapas;
- o label no doctor e na issue-labeling, e as docs.

    python3 scripts/test_undo.py
"""

import contextlib
import io
import os
import pathlib
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402
import undo  # noqa: E402
from test_workflows import evaluate, parse_step, router_if, router_jobs, steps_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SKILLS = ROOT / "skills"
ACTION = ROOT / ".github" / "actions" / "undo" / "action.yml"
UNDO_USES = "samuel-morrissey/ai-workflows/.github/actions/undo@main"
STAGES = ("issue-triage.yml", "issue-refinement.yml", "issue-break-down.yml")
PENDING_STEP = "Processar undo da rodada"
PARENT = 100
R = "repos/o/r"

TRIAGEM = "## Triagem\n\n**Tipo:** `[SPEC]`\n**Proximo passo** (@ana): aplique `go`."
RODADA = "## Refinamento — rodada 1\n\n### Perguntas\n**Q1 — x:** ?"
REFINAMENTO = "## Refinamento\n\nO recorte.\n\n**Proximo passo** (@ana): aplique o label `go`."
QUEBRA = "## Quebra\n\n| Ordem | Sub-task | Bloqueada por |\n|---|---|---|\n| 1 | #101 a | — |"
DEVOLUCAO = ("O PR #80 foi fechado sem merge. O issue voltou de `awaiting-pr-review` para "
             "`ready-for-agent`: aplique `go` para retomar a implementacao.")


def labeled(name, number=PARENT, labels=(), state="open", title="[SPEC] Pai"):
    """Evento `issues` `labeled` como o GitHub manda ao router."""
    return {"action": "labeled", "label": {"name": name},
            "issue": {"number": number, "state": state, "title": title,
                      "labels": [{"name": n} for n in (*labels, name)]}}


class Router(unittest.TestCase):
    """O destino novo, avaliado pelo `if` do router.yml."""

    def jobs(self):
        return {name: router_if(job) for name, job in router_jobs().items() if "    if: >" in job}

    def running(self, event_name, payload):
        return sorted(n for n, cond in self.jobs().items() if evaluate(cond, event_name, payload))

    def test_job_chama_o_workflow_novo(self):
        job = router_jobs()["issue-undo"]
        self.assertIn("uses: samuel-morrissey/ai-workflows/.github/workflows/issue-undo.yml@main", job)
        self.assertTrue((WORKFLOWS / "issue-undo.yml").exists())

    def test_undo_sem_wip_roda_so_o_destino_novo_e_o_check_caller(self):
        for labels in (("needs-break-down",), ("ready-for-agent",), ("needs-refinement", "awaiting-reply"),
                       ("awaiting-pr-review",), ("needs-triage",), ()):
            self.assertEqual(self.running("issues", labeled("undo", labels=labels)),
                             ["check-caller", "issue-undo"], labels)
        # [SUB-TASK] e fechado tambem: a recusa e resposta.
        self.assertEqual(self.running("issues", labeled("undo", title="[SUB-TASK] x")),
                         ["check-caller", "issue-undo"])
        self.assertEqual(self.running("issues", labeled("undo", labels=("needs-break-down",), state="closed")),
                         ["check-caller", "issue-undo"])

    def test_undo_com_wip_nao_roda(self):
        for labels in (("needs-refinement", "work-in-progress"), ("ready-for-agent", "work-in-progress")):
            self.assertEqual(self.running("issues", labeled("undo", labels=labels)), ["check-caller"], labels)

    def test_outros_eventos_nao_rodam_o_undo(self):
        cond = self.jobs()["issue-undo"]
        self.assertFalse(evaluate(cond, "issues", labeled("go", labels=("needs-break-down",))))
        self.assertFalse(evaluate(cond, "issues", labeled("needs-refinement")))
        comment = {"action": "created", "comment": {"user": {"type": "User"}, "body": "undo"},
                   "issue": {"labels": [{"name": "undo"}, {"name": "awaiting-reply"}]}}
        self.assertFalse(evaluate(cond, "issue_comment", comment))

    def test_go_continua_indo_para_a_etapa(self):
        # O evaluate novo entende contains/join/startsWith: os destinos de
        # antes continuam respondendo como antes.
        self.assertEqual(self.running("issues", labeled("go", labels=("needs-break-down",))),
                         ["check-caller", "issue-break-down"])
        self.assertEqual(self.running("issues", labeled("go", labels=("ready-for-agent",))),
                         ["check-caller", "issue-remote-implement"])
        self.assertEqual(self.running("issues", labeled("go", title="[SUB-TASK] x")),
                         ["check-caller", "issue-sub-task"])
        self.assertEqual(self.running("issues", labeled("go")), ["check-caller", "issue-triage"])


def comment(body, kind="Bot", i=0):
    return {"user": {"login": "claude[bot]" if kind == "Bot" else "ana", "type": kind},
            "body": body, "html_url": f"https://github.com/o/r/issues/{PARENT}#issuecomment-{i}"}


class FakeGitHub:
    """Issues, sub-issues, bloqueios, PRs e labels do repositorio, respondendo
    as rotas que o undo.py usa."""

    def __init__(self, labels, bodies, title="[SPEC] Pai", state="open", subs=(), prs=(), blocked=None,
                 repo_labels=("undo", "needs-refinement", "needs-break-down")):
        self.calls = []
        self.repo_labels = {n: None for n in repo_labels}
        self.issues = {PARENT: {"number": PARENT, "id": 9000 + PARENT, "title": title, "state": state,
                                "body": "corpo", "labels": list(labels), "comments": []}}
        for i, body in enumerate(bodies):
            self.issues[PARENT]["comments"].append(body if isinstance(body, dict) else comment(body, i=i))
        self.subs = []
        for n in subs:
            if isinstance(n, tuple):
                n, st, lbl = n
            else:
                st, lbl = "open", []
            self.issues[n] = {"number": n, "id": 9000 + n, "title": f"[SUB-TASK] parte {n}", "state": st,
                              "state_reason": None, "body": f"Parte de #{PARENT}", "labels": list(lbl),
                              "comments": []}
            self.subs.append(n)
        self.blocked = {n: list(b) for n, b in (blocked or {}).items()}
        self.prs = [{"number": 200 + i, "head": {"ref": f"sub-task-{sub}"},
                     "state": "closed" if st == "merged" else st,
                     "merged_at": "2026-11-01T00:00:00Z" if st == "merged" else None}
                    for i, (sub, st) in enumerate(prs)]

    def view(self, n):
        issue = self.issues[n]
        return {**issue, "labels": [{"name": l} for l in issue["labels"]]}

    def api(self, path, method=None, body=None, ok404=False, paginate=False):
        method = method or "GET"
        self.calls.append((method, path, body))
        m = re.fullmatch(rf"{R}/issues/(\d+)", path)
        if m:
            issue = self.issues[int(m.group(1))]
            if method == "PATCH":
                issue.update(body)
            return self.view(issue["number"])
        m = re.fullmatch(rf"{R}/issues/(\d+)/comments(\?per_page=100)?", path)
        if m:
            issue = self.issues[int(m.group(1))]
            if method == "POST":
                issue["comments"].append(comment(body["body"], i=len(issue["comments"])))
                return {}
            assert paginate
            return list(issue["comments"])
        m = re.fullmatch(rf"{R}/issues/(\d+)/labels/(.+)", path)
        if m and method == "DELETE":
            labels = self.issues[int(m.group(1))]["labels"]
            if m.group(2) not in labels:
                return None if ok404 else self.fail(path)
            labels.remove(m.group(2))
            return []
        m = re.fullmatch(rf"{R}/issues/(\d+)/labels", path)
        if m and method == "PUT":
            current = self.issues[int(m.group(1))]["labels"]
            for name in body["labels"]:
                assert name in current or name in self.repo_labels, f"label inexistente: {name}"
            self.issues[int(m.group(1))]["labels"] = list(body["labels"])
            return []
        m = re.fullmatch(rf"{R}/labels/(.+)", path)
        if m:
            return {"name": m.group(1)} if m.group(1) in self.repo_labels else None
        if path == f"{R}/labels" and method == "POST":
            self.repo_labels[body["name"]] = (body["color"], body["description"])
            return {}
        if path == f"{R}/issues/{PARENT}/sub_issues?per_page=100":
            assert paginate
            return [self.view(n) for n in self.subs]
        if path == f"{R}/issues/{PARENT}/sub_issue" and method == "DELETE":
            n = body["sub_issue_id"] - 9000
            self.subs.remove(n)
            return {}
        m = re.fullmatch(rf"{R}/issues/(\d+)/dependencies/blocked_by\?per_page=100", path)
        if m:
            return [{"number": b, "id": 9000 + b} for b in self.blocked.get(int(m.group(1)), [])]
        m = re.fullmatch(rf"{R}/issues/(\d+)/dependencies/blocked_by/(\d+)", path)
        if m and method == "DELETE":
            self.blocked[int(m.group(1))].remove(int(m.group(2)) - 9000)
            return {}
        m = re.fullmatch(rf"{R}/pulls\?head=o:sub-task-(\d+)&state=all&per_page=20", path)
        if m:
            return [p for p in self.prs if p["head"]["ref"] == f"sub-task-{m.group(1)}"]
        return self.fail(path)

    def fail(self, path):
        raise AssertionError(f"rota inesperada: {path}")

    def writes(self):
        return [c for c in self.calls if c[0] != "GET"]


class Base(unittest.TestCase):
    def execute(self, gh, pending=False, number=PARENT):
        with mock.patch.object(undo, "api", gh.api), mock.patch.object(undo, "REPO", "o/r"), \
                mock.patch.object(undo, "OWNER", "o"):
            return undo.run(number, pending)

    def last_comment(self, gh, n=PARENT):
        return gh.issues[n]["comments"][-1]["body"]

    def assertRefused(self, gh, out, labels, motivo):
        """Recusa: comentario com motivo e caminho, labels de estado iguais, `undo` fora."""
        self.assertEqual(out["action"], "refuse", out)
        self.assertEqual(gh.issues[PARENT]["labels"], list(labels))
        body = self.last_comment(gh)
        self.assertTrue(body.startswith("## Undo recusado"), body)
        self.assertIn("**Motivo:**", body)
        self.assertIn("**Caminho:**", body)
        self.assertIn(motivo, body)
        self.assertNotIn("@", body)
        self.assertNotIn("ai:undo etapa=", body)
        self.assertFalse([c for c in gh.writes() if c[0] in ("PUT", "PATCH") or "sub_issue" in c[1]
                          or "dependencies" in c[1]])
        return body


class Refinement(Base):
    def test_desfaz_o_refinamento(self):
        gh = FakeGitHub(["needs-break-down", "undo"], [TRIAGEM, RODADA, "humano: Q1 ok", REFINAMENTO])
        gh.issues[PARENT]["comments"][2] = comment("Q1 ok", kind="User")
        out = self.execute(gh)
        self.assertEqual(out["action"], "revert", out)
        self.assertEqual(out["stage"], "refinamento")
        self.assertEqual(gh.issues[PARENT]["labels"], ["needs-refinement"])
        body = self.last_comment(gh)
        self.assertTrue(body.startswith("## Undo"), body)
        self.assertIn("refinamento", body)
        self.assertIn("`needs-break-down` para `needs-refinement`", body)
        self.assertIn("`go`", body)
        self.assertIn("#issuecomment-3", body, "aponta o ## Refinamento desfeito")
        self.assertNotIn("@", body)
        # Comentarios anteriores ficam: so um novo entrou.
        self.assertEqual(len(gh.issues[PARENT]["comments"]), 5)

    def test_troca_o_estado_numa_operacao_e_cria_o_label_se_faltar(self):
        gh = FakeGitHub(["needs-break-down", "undo", "priority"], [TRIAGEM, REFINAMENTO], repo_labels=("undo",))
        self.execute(gh)
        puts = [c for c in gh.calls if c[0] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-refinement", "priority"])
        self.assertEqual(gh.repo_labels["needs-refinement"], undo.LABELS["needs-refinement"])

    def test_rodada_de_perguntas_depois_nao_conta_e_awaiting_reply_sai(self):
        # Refinamento desfeito antes, nova rodada parou em pergunta: o undo
        # agora desfaz a triagem (nao suportado). Ja a quebra que parou em
        # pergunta e desfeita pelo refinamento anterior.
        gh = FakeGitHub(["needs-break-down", "awaiting-reply", "undo"],
                        [TRIAGEM, REFINAMENTO, "## Status\n\n**Preciso de voce** (@ana): Q?"])
        out = self.execute(gh)
        self.assertEqual(out["stage"], "refinamento")
        self.assertEqual(gh.issues[PARENT]["labels"], ["needs-refinement"])

    def test_humano_escrevendo_o_cabecalho_nao_conta(self):
        gh = FakeGitHub(["needs-break-down", "undo"], [TRIAGEM, REFINAMENTO])
        gh.issues[PARENT]["comments"].append(comment(QUEBRA, kind="User"))
        out = self.execute(gh)
        self.assertEqual(out["stage"], "refinamento")


def broken_down(**kw):
    """Pai que passou por triagem, refinamento e quebra, com #101..#103."""
    kw.setdefault("subs", (101, 102, 103))
    kw.setdefault("blocked", {102: [101], 103: [101, 102, 50]})
    return FakeGitHub(kw.pop("labels", ["ready-for-agent", "undo"]), [TRIAGEM, REFINAMENTO, QUEBRA], **kw)


class BreakDown(Base):
    def test_desfaz_a_quebra(self):
        gh = broken_down()
        out = self.execute(gh)
        self.assertEqual(out["action"], "revert", out)
        self.assertEqual(out["stage"], "quebra")
        self.assertEqual(gh.issues[PARENT]["labels"], ["needs-break-down"])
        self.assertEqual(gh.subs, [], "sub_issues do pai vazio")
        for n in (101, 102, 103):
            self.assertEqual(gh.issues[n]["state"], "closed", n)
            self.assertEqual(gh.issues[n]["state_reason"], "not_planned", n)
            self.assertEqual(gh.blocked.get(n, []), [], n)
            self.assertIn(f"#{PARENT}", self.last_comment(gh, n))
        body = self.last_comment(gh)
        self.assertIn("quebra", body)
        self.assertIn("#101, #102, #103", body)
        self.assertIn("`ready-for-agent` para `needs-break-down`", body)
        self.assertNotIn("@", body)

    def test_bloqueio_para_issue_de_fora_sai_junto(self):
        gh = broken_down()
        self.execute(gh)
        self.assertEqual(gh.blocked[103], [])
        self.assertIn(("DELETE", f"{R}/issues/103/dependencies/blocked_by/9050", None), gh.calls)

    def test_sub_task_ja_fechada_sai_e_fica_fechada(self):
        gh = broken_down(subs=(101, (102, "closed", [])), blocked={102: [101]})
        gh.issues[102]["state_reason"] = "completed"
        self.execute(gh)
        self.assertEqual(gh.subs, [])
        self.assertEqual(gh.issues[102]["state_reason"], "completed", "a ja fechada nao e reaberta nem mexida")
        self.assertEqual(gh.blocked[102], [])
        self.assertEqual(gh.issues[101]["state_reason"], "not_planned")

    def test_sub_task_em_awaiting_reply_sem_pr_fecha_como_as_outras(self):
        gh = broken_down(subs=(101, (102, "open", ["awaiting-reply"])), blocked={})
        out = self.execute(gh)
        self.assertEqual(out["action"], "revert")
        self.assertEqual(gh.issues[102]["state"], "closed")

    def test_ready_for_human_tambem_volta(self):
        gh = broken_down(labels=["ready-for-human", "undo"])
        self.execute(gh)
        self.assertEqual(gh.issues[PARENT]["labels"], ["needs-break-down"])

    def test_pr_fechado_sem_merge_nao_conta_como_implementacao(self):
        gh = broken_down(prs=[(101, "closed")])
        out = self.execute(gh)
        self.assertEqual(out["action"], "revert")

    def test_undo_de_novo_desfaz_o_refinamento(self):
        gh = broken_down()
        self.execute(gh)
        gh.issues[PARENT]["labels"].append("undo")
        out = self.execute(gh)
        self.assertEqual(out["action"], "revert", out)
        self.assertEqual(out["stage"], "refinamento", "o primeiro undo nao conta como etapa")
        self.assertEqual(gh.issues[PARENT]["labels"], ["needs-refinement"])
        # Terceiro: so sobrou a triagem, ainda nao suportada.
        gh.issues[PARENT]["labels"].append("undo")
        out = self.execute(gh)
        self.assertEqual(out["action"], "refuse")
        self.assertIn("ainda nao e suportado", self.last_comment(gh))

    def test_go_depois_do_undo_passa_na_conferencia_da_quebra(self):
        # O passo 1 da issue-break-down exige needs-break-down e nenhuma
        # sub-issue; uma quebra nova volta a ser a ultima etapa.
        gh = broken_down()
        self.execute(gh)
        self.assertIn("needs-break-down", gh.issues[PARENT]["labels"])
        self.assertEqual(gh.subs, [])
        gh.issues[PARENT]["labels"] = ["ready-for-agent", "undo"]
        gh.issues[PARENT]["comments"].append(comment(QUEBRA, i=99))
        out = self.execute(gh)
        self.assertEqual(out["stage"], "quebra", "a quebra refeita e a nova ultima etapa")


class Refusals(Base):
    def test_pontual_em_awaiting_pr_review(self):
        gh = FakeGitHub(["awaiting-pr-review", "undo"], [TRIAGEM], title="[FEAT] Pontual")
        out = self.execute(gh)
        body = self.assertRefused(gh, out, ["awaiting-pr-review"], "implementacao comecou")
        self.assertIn("feche o PR", body)

    def test_pai_com_pr_de_sub_task_aberto_ou_mergeado(self):
        for st in ("open", "merged"):
            gh = broken_down(prs=[(102, st)])
            out = self.execute(gh)
            body = self.assertRefused(gh, out, ["ready-for-agent"], "implementacao comecou")
            self.assertIn("#102 (PR #200)", body)
            self.assertEqual(gh.subs, [101, 102, 103])
            self.assertTrue(all(gh.issues[n]["state"] == "open" for n in gh.subs))

    def test_sub_task(self):
        gh = FakeGitHub(["undo"], [], title="[SUB-TASK] Camada")
        gh.issues[PARENT]["body"] = "Parte de #88 (secoes 4 e 5)."
        out = self.execute(gh)
        body = self.assertRefused(gh, out, [], "`[SUB-TASK]`")
        self.assertIn("no pai #88", body)

    def test_needs_triage(self):
        gh = FakeGitHub(["needs-triage", "undo"], [])
        out = self.execute(gh)
        self.assertRefused(gh, out, ["needs-triage"], "nao ha o que desfazer")

    def test_issue_fechado(self):
        gh = FakeGitHub(["needs-break-down", "undo"], [TRIAGEM, REFINAMENTO], state="closed")
        out = self.execute(gh)
        self.assertRefused(gh, out, ["needs-break-down"], "fechado")

    def test_devolucao_do_pr_closed_e_a_ultima_mudanca(self):
        gh = FakeGitHub(["ready-for-agent", "undo"], [TRIAGEM, DEVOLUCAO], title="[FEAT] Pontual")
        out = self.execute(gh)
        body = self.assertRefused(gh, out, ["ready-for-agent"], "PR fechado sem merge")
        self.assertIn("feche o PR", body)

    def test_ultima_etapa_e_a_triagem(self):
        for labels in (["needs-refinement", "undo"], ["ready-for-agent", "undo"]):
            gh = FakeGitHub(labels, [TRIAGEM])
            out = self.execute(gh)
            self.assertRefused(gh, out, labels[:1], "desfazer a triagem ainda nao e suportado")

    def test_sub_task_rodando_agora(self):
        gh = broken_down(subs=(101, (102, "open", ["work-in-progress"])), blocked={})
        out = self.execute(gh)
        self.assertRefused(gh, out, ["ready-for-agent"], "#102")

    def test_estado_mexido_depois_da_etapa(self):
        gh = FakeGitHub(["ready-for-agent", "undo"], [TRIAGEM, REFINAMENTO])
        out = self.execute(gh)
        self.assertRefused(gh, out, ["ready-for-agent"], "mudou depois dela")


class DuringRound(Base):
    """`--pending`: o passo do fim da rodada de etapa."""

    def test_sem_undo_nao_faz_nada(self):
        gh = FakeGitHub(["needs-break-down", "work-in-progress"], [TRIAGEM, REFINAMENTO])
        out = self.execute(gh, pending=True)
        self.assertEqual(out["action"], "none")
        self.assertEqual(gh.writes(), [])

    def test_refinamento_que_acabou_de_terminar_e_desfeito(self):
        # O `undo` chegou com work-in-progress; a rodada postou o ## Refinamento
        # e trocou o label; o passo de fim de rodada desfaz essa mudanca.
        gh = FakeGitHub(["needs-break-down", "work-in-progress", "undo"], [TRIAGEM, RODADA, REFINAMENTO])
        out = self.execute(gh, pending=True)
        self.assertEqual(out["action"], "revert")
        # O work-in-progress e de quem chama: o passo seguinte o tira.
        self.assertEqual(sorted(gh.issues[PARENT]["labels"]), ["needs-refinement", "work-in-progress"])


class Cli(unittest.TestCase):
    def test_erro_de_api_sai_com_2(self):
        def boom(*a, **k):
            raise undo.ApiError("gh api GET repos/o/r/issues/100: HTTP 503")
        err = io.StringIO()
        with mock.patch.object(undo, "api", boom), mock.patch.object(undo, "REPO", "o/r"), \
                mock.patch.object(sys, "argv", ["undo.py", "run", "100"]), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                undo.main()
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("HTTP 503", err.getvalue())


class Shape(unittest.TestCase):
    """issue-undo.yml, a action e o passo de fim de rodada das etapas."""

    def test_workflow_so_gh_com_wip_e_a_action(self):
        text = (WORKFLOWS / "issue-undo.yml").read_text()
        self.assertIn("on:\n  workflow_call:\n", text)
        self.assertIn("\n  issues: write\n", text)
        self.assertNotIn("anthropics/claude-code-action", text)
        steps = steps_of(text)
        names = [n for n, _ in steps]
        self.assertEqual(names, ["Resolver numero do issue", "Aplicar work-in-progress",
                                 "Desfazer a ultima etapa", "Remover work-in-progress"])
        step = parse_step(dict(steps)["Desfazer a ultima etapa"])
        self.assertEqual(step["uses"], UNDO_USES)
        self.assertEqual(step["with"]["number"], "${{ steps.target.outputs.number }}")
        wip = dict(steps)["Aplicar work-in-progress"]
        self.assertIn("gh issue edit \"$NUMBER\" --add-label work-in-progress", wip)
        color, desc = doctor.FLOW_LABELS["undo"]
        self.assertIn(f'gh label create undo --color {color} \\\n            --description "{desc}"', wip)
        self.assertEqual(parse_step(dict(steps)["Remover work-in-progress"])["if"],
                         "always() && steps.wip.outcome == 'success' && steps.wip.outputs.skip != 'true'")

    def test_action_roda_o_script_da_mesma_ref(self):
        text = ACTION.read_text()
        self.assertIn("UNDO_PY: ${{ github.action_path }}/../../../scripts/undo.py", text)
        self.assertIn("GH_REPO: ${{ github.repository }}", text)
        self.assertIn("--pending", text)
        self.assertTrue((ROOT / "scripts" / "undo.py").exists())

    def test_etapas_processam_o_undo_antes_de_tirar_o_wip(self):
        for f in STAGES:
            steps = steps_of((WORKFLOWS / f).read_text())
            names = [n for n, _ in steps]
            self.assertEqual(names.count(PENDING_STEP), 1, f)
            i = names.index(PENDING_STEP)
            self.assertLess(names.index("anthropics/claude-code-action@v1"), i, f)
            self.assertEqual(names[i + 1], "Remover work-in-progress", f)
            step = parse_step(dict(steps)[PENDING_STEP])
            self.assertEqual(step["uses"], UNDO_USES, f)
            self.assertEqual(step["with"]["pending"], '"true"', f)
            self.assertEqual(step["continue_on_error"], "true", f)
            self.assertEqual(step["if"],
                             "always() && steps.wip.outcome == 'success' && steps.wip.outputs.skip != 'true'", f)

    def test_ai_yml_nao_muda(self):
        text = (WORKFLOWS / "ai.yml").read_text()
        self.assertIn("  issues:\n    types: [labeled]\n", text)


class Label(unittest.TestCase):
    def row(self):
        labeling = (SKILLS / "issue-labeling" / "SKILL.md").read_text()
        return [l for l in labeling.splitlines() if l.startswith("| `undo` |")][0]

    def test_doctor_cobra_e_cria_o_undo_com_a_cor_da_issue_labeling(self):
        cells = [c.strip(" `") for c in self.row().strip("|").split("|")]
        self.assertEqual(tuple(cells[-2:]), doctor.FLOW_LABELS["undo"])
        self.assertEqual(undo.LABELS["undo"], doctor.FLOW_LABELS["undo"])
        for name in ("needs-refinement", "needs-break-down"):
            self.assertEqual(undo.LABELS[name], doctor.FLOW_LABELS[name], name)
        # Repositorio sem o `undo`: o check aponta a falta.
        labels = {n: {"color": c, "description": d} for n, (c, d) in doctor.FLOW_LABELS.items() if n != "undo"}
        self.assertEqual(doctor.label_plan(labels), (["undo"], []))

    def test_fix_labels_cria_o_undo(self):
        existing = [{"name": n, "color": c, "description": d}
                    for n, (c, d) in doctor.FLOW_LABELS.items() if n != "undo"]
        calls = []

        def fake_gh(*args, **kw):
            calls.append(args)
            out = __import__("json").dumps(existing) if args[:2] == ("label", "list") else ""
            return type("R", (), {"stdout": out, "returncode": 0})()

        with mock.patch.object(doctor, "gh", fake_gh):
            result = doctor.fix_labels(type("Repo", (), {"full": "o/r"})())
        color, desc = doctor.FLOW_LABELS["undo"]
        self.assertIn(("label", "create", "undo", "-R", "o/r", "--color", color, "--description", desc), calls)
        self.assertEqual(result, "labels criados: undo")


class Docs(unittest.TestCase):
    def flat(self, text):
        return " ".join(text.split())

    def test_issue_labeling(self):
        text = (SKILLS / "issue-labeling" / "SKILL.md").read_text()
        section = self.flat(text.split("\n## Label de volta\n", 1)[1].split("\n## ", 1)[0])
        for s in ("ultima mudanca de label de estado feita por uma etapa", "not planned",
                  "ainda nao suportado", "`blocked_by`", "aplicar `undo` de novo desfaz a etapa anterior",
                  "`awaiting-pr-review`", "`[SUB-TASK]`", "`needs-triage`", "fechado",
                  "Nenhuma run e cancelada", "tire o `work-in-progress` do pai"):
            self.assertIn(s, section, s)
        rule = self.flat(text.split("2. **O fluxo so anda para frente:**", 1)[1].split("\n3. ", 1)[0])
        self.assertIn("o label `undo` volta uma etapa", rule)
        self.assertIn("`issue-undo.yml`", rule)
        reading = self.flat(text.split("Lendo os labels juntos:", 1)[1].split("\n## ", 1)[0])
        self.assertIn("`undo`", reading)

    def test_etapas_rodando_de_novo(self):
        refinement = self.flat((SKILLS / "issue-refinement" / "SKILL.md").read_text())
        self.assertIn("Rodando de novo depois de um `undo`.", refinement)
        self.assertIn("substituido", refinement)
        self.assertIn("comentario humano posterior ao `undo`", refinement)
        breakdown = self.flat((SKILLS / "issue-break-down" / "SKILL.md").read_text())
        self.assertIn("Rodando de novo depois de um `undo`.", breakdown)
        self.assertIn("Crie sub-tasks novas", breakdown)
        self.assertIn("nao contam como \"ja quebrado\"", breakdown)

    def test_readme_e_router(self):
        readme = (ROOT / "README.md").read_text()
        etapas = readme.split("## Etapas", 1)[1].split("\n### ", 1)[0]
        self.assertIn("`undo`", etapas)
        self.assertIn("`issue-undo.yml`", etapas)
        self.assertIn("### O label `undo`", readme)
        table = readme.split("| Labels no issue | Quer dizer |", 1)[1].split("\n\n", 1)[0]
        self.assertIn("`undo`", table)
        router = (WORKFLOWS / "router.yml").read_text()
        self.assertIn("O label `undo`", router.split("\non:\n", 1)[0])
        job = router_jobs()["issue-undo"]
        self.assertIn("# Undo:", router.split("  issue-undo:", 1)[0].rsplit("\n\n", 1)[1])
        self.assertIn("ai-undo-", job)


if __name__ == "__main__":
    unittest.main(verbosity=1)
