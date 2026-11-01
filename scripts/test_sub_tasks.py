#!/usr/bin/env python3
"""Testes do sub_tasks.py com um GitHub falso no lugar do `gh api` (sem gh
nem rede): o merge de uma camada no meio da cadeia de sub-tasks.

    python3 scripts/test_sub_tasks.py
"""

import contextlib
import io
import json
import os
import pathlib
import re
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sub_tasks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKER = ROOT / ".github" / "workflows" / "issue-sub-task.yml"
PLANNER = ROOT / ".github" / "workflows" / "issue-remote-implement.yml"
SKILL = ROOT / "skills" / "issue-remote-implement" / "SKILL.md"
PARENT = 100


class FakeGitHub:
    """Pai #100 com sub-tasks #101.. e os PRs delas, respondendo as rotas que
    o sub_tasks.py usa. PR e (sub, estado, base, stack); `merged` vira estado
    fechado com merged_at."""

    def __init__(self, subs, prs):
        self.calls = []
        self.comments = {}
        self.subs =[{"number": n, "title": f"[SUB-TASK] parte {n}", "state": "open",
                      "body": f"Parte de #{PARENT}", "labels": []} for n in subs]
        self.prs = {}
        for i, (sub, state, base, stack) in enumerate(prs):
            number = 200 + i
            self.prs[number] = {
                "number": number, "state": "closed" if state == "merged" else state,
                "merged_at": "2026-10-30T00:00:00Z" if state == "merged" else None,
                "head": {"ref": f"sub-task-{sub}"}, "base": {"ref": base},
                "stack": {"number": stack} if stack else None,
                "html_url": f"https://github.com/o/r/pull/{number}",
                "node_id": f"PR_{number}", "body": f"Closes #{sub}\nParte de #{PARENT}",
            }

    def pr(self, sub):
        return next(p for p in self.prs.values()
                    if p["head"]["ref"] == f"sub-task-{sub}" and p["state"] == "open")

    def api(self, path, method=None, body=None, ok404=False):
        self.calls.append((method or "GET", path, body))
        r = "repos/o/r"
        if path == r:
            return {"default_branch": "main"}
        if path == f"{r}/issues/{PARENT}/sub_issues?per_page=100":
            return self.subs
        if re.fullmatch(rf"{r}/issues/\d+/dependencies/blocked_by\?per_page=100", path):
            return []
        m = re.fullmatch(rf"{r}/pulls\?head=o:(\S+)&state=all&per_page=20", path)
        if m:
            return [p for p in self.prs.values() if p["head"]["ref"] == m.group(1)]
        m = re.fullmatch(rf"{r}/pulls/(\d+)", path)
        if m:
            pr = self.prs[int(m.group(1))]
            if method == "PATCH":
                if "base" in body:
                    if pr["stack"]:
                        raise sub_tasks.ApiError("PR empilhado nao troca de base")
                    pr["base"] = {"ref": body["base"]}
                if "body" in body:
                    pr["body"] = body["body"]
            return pr
        if path == f"{r}/stacks" and method == "POST":
            for n in body["pull_requests"]:
                self.prs[n]["stack"] = {"number": 9}
            return {"number": 9}
        m = re.fullmatch(rf"{r}/stacks/(\d+)/add", path)
        if m and method == "POST":
            for n in body["pull_requests"]:
                self.prs[n]["stack"] = {"number": int(m.group(1))}
            return {}
        m = re.fullmatch(rf"{r}/issues/(\d+)/comments(\?per_page=100)?", path)
        if m:
            comments = self.comments.setdefault(int(m.group(1)), [])
            if method == "POST":
                comment = {"id": 900 + len(comments), "body": body["body"],
                           "html_url": f"https://github.com/o/r/issues/{m.group(1)}#issuecomment-{900 + len(comments)}"}
                comments.append(comment)
                return comment
            return comments
        m = re.fullmatch(rf"{r}/issues/comments/(\d+)", path)
        if m and method == "PATCH":
            comment = next(c for cs in self.comments.values() for c in cs if c["id"] == int(m.group(1)))
            comment["body"] = body["body"]
            return comment
        m = re.fullmatch(rf"{r}/issues/(\d+)/parent", path)
        if m:
            return {"number": PARENT}
        m = re.fullmatch(rf"{r}/issues/(\d+)", path)
        if m:
            n = int(m.group(1))
            sub = next((s for s in self.subs if s["number"] == n), None)
            return sub or {"number": n, "node_id": f"I_{n}", "state": "open", "title": "[FEAT] pai", "body": ""}
        raise AssertionError(f"rota inesperada: {method} {path}")

    def graphql(self, query):
        self.calls.append(("GRAPHQL", query, None))
        return {"data": {}}

    def writes(self):
        return [(m, p, b) for m, p, b in self.calls if m in ("PATCH", "POST")]


class Base(unittest.TestCase):
    def run_cmd(self, gh, name, **kw):
        patches = {"api": gh.api, "graphql": gh.graphql, "REPO": "o/r", "OWNER": "o"}
        saved = {k: getattr(sub_tasks, k) for k in patches}
        for k, v in patches.items():
            setattr(sub_tasks, k, v)
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                getattr(sub_tasks, f"cmd_{name}")(SimpleNamespace(**kw))
        finally:
            for k, v in saved.items():
                setattr(sub_tasks, k, v)
        return json.loads(out.getvalue())


class Stack(Base):
    def test_base_em_camada_mergeada_vai_para_a_branch_padrao(self):
        # Camadas 1 e 2 mergeadas; a 3 abriu sobre a branch da 2, calculada
        # antes do merge.
        gh = FakeGitHub([101, 102, 103], [
            (101, "merged", "main", None), (102, "merged", "sub-task-101", None),
            (103, "open", "sub-task-102", None)])
        out = self.run_cmd(gh, "stack", parent=PARENT)
        self.assertEqual(gh.pr(103)["base"]["ref"], "main")
        self.assertEqual(out["retargeted"], [202])
        self.assertEqual(out["stack"], None)

    def test_base_em_camada_mergeada_vai_para_a_camada_aberta_abaixo(self):
        # Camada 1 mergeada; a 2 (aberta) foi retargetada pelo GitHub; a 3
        # nasceu sobre a 1 antes de a 2 abrir, por exemplo.
        gh = FakeGitHub([101, 102, 103], [
            (101, "merged", "main", None), (102, "open", "main", None),
            (103, "open", "sub-task-101", None)])
        out = self.run_cmd(gh, "stack", parent=PARENT)
        self.assertEqual(gh.pr(103)["base"]["ref"], "sub-task-102")
        self.assertEqual(out["retargeted"], [202])
        self.assertEqual(out["stack"], 9)
        self.assertEqual(sorted(out["added"]), [201, 202])

    def test_cadeia_sana_nao_troca_base(self):
        gh = FakeGitHub([101, 102], [(101, "open", "main", None), (102, "open", "sub-task-101", None)])
        out = self.run_cmd(gh, "stack", parent=PARENT)
        self.assertEqual(out["retargeted"], [])
        self.assertFalse([w for w in gh.writes() if w[1].startswith("repos/o/r/pulls/")])

    def test_base_trocada_a_mao_continua_quebrando(self):
        gh = FakeGitHub([101, 102], [(101, "open", "main", None), (102, "open", "outra-branch", None)])
        with self.assertRaisesRegex(sub_tasks.ApiError, "a cadeia de bases quebrou"):
            self.run_cmd(gh, "stack", parent=PARENT)
        self.assertEqual(gh.pr(102)["base"]["ref"], "outra-branch")

    def test_base_em_sub_task_aberta_fora_de_ordem_continua_quebrando(self):
        # Base numa sub-task que nao foi mergeada: nao e o caso do merge.
        gh = FakeGitHub([101, 102, 103], [
            (101, "open", "main", None), (102, "open", "sub-task-101", None),
            (103, "open", "sub-task-101", None)])
        with self.assertRaisesRegex(sub_tasks.ApiError, "a cadeia de bases quebrou"):
            self.run_cmd(gh, "stack", parent=PARENT)

    def test_pr_empilhado_nao_troca_de_base(self):
        gh = FakeGitHub([101, 102], [(101, "merged", "main", None), (102, "open", "sub-task-101", 9)])
        with self.assertRaisesRegex(sub_tasks.ApiError, "a cadeia de bases quebrou"):
            self.run_cmd(gh, "stack", parent=PARENT)
        self.assertFalse([w for w in gh.writes() if w[0] == "PATCH"])


class Finish(Base):
    def test_topo_recebe_closes_do_pai_depois_de_merge_no_meio(self):
        gh = FakeGitHub([101, 102, 103], [
            (101, "merged", "main", None), (102, "open", "main", None),
            (103, "open", "sub-task-101", None)])
        self.run_cmd(gh, "stack", parent=PARENT)
        out = self.run_cmd(gh, "finish", parent=PARENT)
        top = gh.pr(103)
        self.assertEqual(out["top"], 202)
        self.assertTrue(out["linked"])
        self.assertTrue(top["body"].startswith(f"Closes #{PARENT}\n"))
        self.assertEqual(top["base"]["ref"], "sub-task-102")
        self.assertEqual(gh.pr(102)["base"]["ref"], "main")
        self.assertIn('pullRequestIds: ["PR_202"]', gh.calls[-1][1])

    def test_toda_a_stack_mergeada_ultima_vai_para_a_branch_padrao(self):
        # Sem passar pelo `stack`: o proprio finish acerta a base do topo.
        gh = FakeGitHub([101, 102], [(101, "merged", "main", None), (102, "open", "sub-task-101", None)])
        out = self.run_cmd(gh, "finish", parent=PARENT)
        self.assertEqual(out["top"], 201)
        self.assertEqual(gh.pr(102)["base"]["ref"], "main")
        self.assertTrue(gh.pr(102)["body"].startswith(f"Closes #{PARENT}\n"))


class Worker(Base):
    def test_retarget_corrige_o_pr_da_sub_task_aberto_na_run(self):
        gh = FakeGitHub([101, 102], [(101, "merged", "main", None), (102, "open", "sub-task-101", None)])
        out = self.run_cmd(gh, "retarget", parent=PARENT)
        self.assertEqual(out["retargeted"], [201])
        self.assertEqual(gh.pr(102)["base"]["ref"], "main")
        self.assertFalse([w for w in gh.writes() if "stacks" in w[1]])

    def test_base_calculada_antes_do_merge_e_corrigida_quando_o_worker_volta(self):
        # O worker devolve o controle ao planner, que roda o `stack` antes de
        # despachar a proxima: a base morta nao chega a ser empilhada.
        gh = FakeGitHub([101, 102, 103], [
            (101, "merged", "main", None), (102, "merged", "sub-task-101", None),
            (103, "open", "sub-task-102", None)])
        self.run_cmd(gh, "stack", parent=PARENT)
        plan = self.run_cmd(gh, "plan", parent=PARENT)
        self.assertEqual(gh.pr(103)["base"]["ref"], "main")
        self.assertEqual(plan["base"], "sub-task-103")

    def test_skill_confere_merge_da_base_antes_do_pr(self):
        text = SKILL.read_text()
        mode = text.split("## Modo sub-task", 1)[1].split("\n## ", 1)[0]
        self.assertIn("gh pr list --head <base> --state merged", mode)
        self.assertIn("`origin/<base>` nao existe mais", mode)
        self.assertIn("antes de abrir o PR", mode)
        self.assertIn("use a branch padrao no lugar de `<base>`", mode)

    def test_worker_entrega_o_controle_ao_planner_que_empilha(self):
        # O `stack` (com a correcao de base) roda no planner a cada volta do
        # worker; o worker termina sempre devolvendo o controle ao pai.
        self.assertIn("event_type=ai-implement", WORKER.read_text())
        self.assertIn('sub_tasks.py" stack "$NUMBER"', PLANNER.read_text())


class Notify(Base):
    """O aviso no pai: comentario novo, com mencao, na parada e na stack completa."""

    def notify(self, gh, kind, note="", logins=""):
        return self.run_cmd(gh, "notify", parent=PARENT, kind=kind, note=note, logins=logins)

    def posted(self, gh):
        return [b["body"] for m, p, b in gh.writes() if m == "POST" and p == f"repos/o/r/issues/{PARENT}/comments"]

    def test_parada_marca_o_responsavel_com_motivo_e_como_retomar(self):
        gh = FakeGitHub([101], [])
        note = "#101 e humana: faca a parte dela e aplique `go` aqui para a cadeia seguir."
        out = self.notify(gh, "parada", note, "ana bia")
        [body] = self.posted(gh)
        self.assertTrue(body.startswith("## Cadeia parada"), body)
        self.assertIn("@ana @bia", body)
        self.assertIn(note, body)
        self.assertIn("aplique `go` neste issue para retomar", body)
        self.assertNotIn(sub_tasks.MARKER, body)
        self.assertIn("issuecomment", out["comment"])

    def test_stack_completa_pede_revisao_de_baixo_para_cima(self):
        gh = FakeGitHub([101], [])
        self.notify(gh, "completa", logins="ana")
        [body] = self.posted(gh)
        self.assertTrue(body.startswith("## Stack completa"), body)
        self.assertIn("@ana", body)
        self.assertIn("de baixo para cima", body)
        self.assertNotIn(sub_tasks.MARKER, body)

    def test_sem_responsavel_diz_e_nao_marca(self):
        gh = FakeGitHub([101], [])
        for kind in ("parada", "completa"):
            self.notify(gh, kind, "motivo qualquer", "")
        bodies = self.posted(gh)
        self.assertEqual(len(bodies), 2)
        for body in bodies:
            self.assertIn("nao ha responsavel identificavel; ninguem foi marcado.", body)
            self.assertNotIn("@", body)

    def test_login_que_nao_e_de_usuario_nunca_vira_mencao(self):
        gh = FakeGitHub([101], [])
        self.notify(gh, "parada", "m", "x[bot] a\"b ana")
        [body] = self.posted(gh)
        self.assertIn("**Responsavel:** @ana\n", body)
        self.assertNotIn("bot", body)

    def test_repeticao_gera_comentario_novo_e_nao_edita(self):
        gh = FakeGitHub([101], [])
        self.notify(gh, "parada", "mesmo motivo", "ana")
        self.notify(gh, "parada", "mesmo motivo", "ana")
        self.assertEqual(len(self.posted(gh)), 2)
        self.assertFalse([w for w in gh.writes() if w[0] == "PATCH"])

    def test_status_continua_editado_e_sem_mencao(self):
        gh = FakeGitHub([101, 102], [(101, "open", "main", None)])
        self.run_cmd(gh, "status", parent=PARENT, chain="rodando", note="#102 despachada para o agente.")
        self.notify(gh, "parada", "#102 e humana: faca a parte dela.", "ana")
        self.run_cmd(gh, "status", parent=PARENT, chain="parada", note="#102 e humana: faca a parte dela.")
        status = [c for c in gh.comments[PARENT] if sub_tasks.MARKER in c["body"]]
        self.assertEqual(len(status), 1, "um so comentario de status, editado")
        self.assertIn("**Cadeia:** parada", status[0]["body"])
        self.assertNotIn("@", status[0]["body"])
        self.assertEqual(len(gh.comments[PARENT]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
