#!/usr/bin/env python3
"""Testes do responsible.py com um GitHub falso no lugar do `gh api` (sem gh
nem rede): a ordem de resolucao do responsavel de um issue.

    python3 scripts/test_responsible.py
"""

import contextlib
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import responsible  # noqa: E402

BOT = {"login": "github-actions[bot]", "type": "Bot"}
APP = {"login": "claude", "type": "Bot"}


def human(login):
    return {"login": login, "type": "User"}


class FakeGitHub:
    """Issues, pais e usuarios, respondendo as rotas que o responsible.py usa."""

    def __init__(self, issues, parents=None, users=None, fail=None):
        self.issues = issues
        self.parents = parents or {}
        self.users = users or {}
        self.fail = fail
        self.calls = []

    def api(self, path, ok404=False):
        self.calls.append(path)
        if self.fail and self.fail in path:
            raise responsible.ApiError(f"gh api {path}: HTTP 503")
        r = "repos/o/r"
        m = re.fullmatch(rf"{r}/issues/(\d+)/parent", path)
        if m:
            parent = self.parents.get(int(m.group(1)))
            if parent is None:
                if ok404:
                    return None
                raise responsible.ApiError("HTTP 404")
            return {"number": parent}
        m = re.fullmatch(rf"{r}/issues/(\d+)", path)
        if m:
            return self.issues[int(m.group(1))]
        m = re.fullmatch(r"users/(.+)", path)
        if m:
            user = self.users.get(m.group(1))
            if user is None and ok404:
                return None
            return user
        raise AssertionError(f"rota inesperada: {path}")


def issue(author, title="[FEAT] algo", body="", assignees=()):
    return {"title": title, "body": body, "user": author, "assignees": list(assignees)}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="resp-"))
        self.config = self.tmp / "ai-workflows.yml"
        self._repo = responsible.REPO
        responsible.REPO = "o/r"

    def tearDown(self):
        responsible.REPO = self._repo

    def resolve(self, gh, number, config_text=None, default=""):
        if config_text is not None:
            self.config.write_text(config_text)
        self._api = responsible.api
        responsible.api = gh.api
        try:
            return responsible.resolve(number, str(self.config), default)
        finally:
            responsible.api = self._api


class Rules(Base):
    def test_assignee_humano_vence_autor_bot(self):
        gh = FakeGitHub({1: issue(BOT, body="Responsável: @fulano", assignees=[human("ana"), human("bia")])})
        self.assertEqual(self.resolve(gh, 1), {"issue": 1, "logins": ["ana", "bia"], "rule": "assignees"})

    def test_assignee_bot_nao_conta(self):
        gh = FakeGitHub({1: issue(human("carla"), assignees=[APP])})
        self.assertEqual(self.resolve(gh, 1)["logins"], ["carla"])

    def test_autor_humano_sem_assignee(self):
        gh = FakeGitHub({2: issue(human("carla"))})
        self.assertEqual(self.resolve(gh, 2), {"issue": 2, "logins": ["carla"], "rule": "author"})

    def test_campo_em_issue_de_autor_humano_nao_vale(self):
        gh = FakeGitHub({2: issue(human("carla"), body="Responsável: @fulano")}, users={"fulano": human("fulano")})
        self.assertEqual(self.resolve(gh, 2)["logins"], ["carla"])

    def test_sub_task_de_bot_herda_do_pai(self):
        gh = FakeGitHub({3: issue(BOT, title="[SUB-TASK] fatia", body="Parte de #9\nResponsável: @fulano"),
                         9: issue(human("dani"), title="[FEAT] pai")},
                        parents={3: 9}, users={"fulano": human("fulano")})
        self.assertEqual(self.resolve(gh, 3), {"issue": 9, "logins": ["dani"], "rule": "author"})

    def test_sub_task_sem_parent_nativo_usa_parte_de(self):
        gh = FakeGitHub({3: issue(BOT, title="[SUB-TASK] fatia", body="Parte de #9"),
                         9: issue(BOT, title="[FEAT] pai", assignees=[human("eva")])})
        self.assertEqual(self.resolve(gh, 3), {"issue": 9, "logins": ["eva"], "rule": "assignees"})

    def test_sub_task_com_pai_de_bot_segue_campo_e_chave_do_pai(self):
        gh = FakeGitHub({3: issue(BOT, title="[SUB-TASK] fatia"),
                         9: issue(BOT, title="[FEAT] pai", body="Contexto\n\nResponsável: @fulano\n")},
                        parents={3: 9}, users={"fulano": human("fulano")})
        self.assertEqual(self.resolve(gh, 3), {"issue": 9, "logins": ["fulano"], "rule": "field"})
        gh = FakeGitHub({3: issue(BOT, title="[SUB-TASK] fatia"), 9: issue(BOT, title="[FEAT] pai")},
                        parents={3: 9}, users={"gil": human("gil")})
        self.assertEqual(self.resolve(gh, 3, "default_responsible: gil\n"),
                         {"issue": 9, "logins": ["gil"], "rule": "default"})

    def test_campo_em_issue_de_bot(self):
        gh = FakeGitHub({4: issue(BOT, body="## Contexto\nResponsável: @fulano\n")}, users={"fulano": human("fulano")})
        self.assertEqual(self.resolve(gh, 4), {"issue": 4, "logins": ["fulano"], "rule": "field"})

    def test_campo_aceita_sem_acento_e_vale_a_primeira_linha(self):
        gh = FakeGitHub({4: issue(BOT, body="Responsavel: @fulano\nResponsável: @beltrano")},
                        users={"fulano": human("fulano"), "beltrano": human("beltrano")})
        self.assertEqual(self.resolve(gh, 4)["logins"], ["fulano"])

    def test_campo_apontando_para_bot_e_ignorado(self):
        gh = FakeGitHub({4: issue(BOT, body="Responsável: @renovate[bot]")}, users={"gil": human("gil")})
        self.assertEqual(self.resolve(gh, 4, "default_responsible: gil\n"),
                         {"issue": 4, "logins": ["gil"], "rule": "default"})
        gh = FakeGitHub({4: issue(BOT, body="Responsável: @claude")}, users={"claude": APP})
        self.assertEqual(self.resolve(gh, 4), {"issue": 4, "logins": [], "rule": "none"})

    def test_campo_no_meio_de_uma_linha_nao_vale(self):
        gh = FakeGitHub({4: issue(BOT, body="Veja o Responsável: @fulano no outro issue")},
                        users={"fulano": human("fulano")})
        self.assertEqual(self.resolve(gh, 4)["rule"], "none")

    def test_chave_default_responsible(self):
        gh = FakeGitHub({5: issue(BOT)}, users={"gil": human("gil")})
        cfg = "# comentario\nquality_checks: |\n  make test\ndefault_responsible: \"@gil\" # dono\n"
        self.assertEqual(self.resolve(gh, 5, cfg), {"issue": 5, "logins": ["gil"], "rule": "default"})

    def test_sem_chave_sem_responsavel_sem_erro(self):
        gh = FakeGitHub({5: issue(BOT)})
        self.assertEqual(self.resolve(gh, 5, "quality_checks: make test\n"), {"issue": 5, "logins": [], "rule": "none"})

    def test_sem_arquivo_a_ultima_regra_nao_acha_ninguem(self):
        gh = FakeGitHub({5: issue(BOT)})
        self.assertFalse(self.config.exists())
        self.assertEqual(self.resolve(gh, 5)["rule"], "none")

    def test_chave_que_nao_e_texto_nao_vira_responsavel(self):
        gh = FakeGitHub({5: issue(BOT)}, users={"gil": human("gil")})
        self.assertEqual(self.resolve(gh, 5, "default_responsible:\n  - gil\n")["rule"], "none")
        self.assertEqual(self.resolve(gh, 5, "default_responsible: [gil]\n")["rule"], "none")

    def test_chave_do_arquivo_vence_o_input(self):
        gh = FakeGitHub({5: issue(BOT)}, users={"gil": human("gil"), "hugo": human("hugo")})
        self.assertEqual(self.resolve(gh, 5, "default_responsible: gil\n", default="hugo")["logins"], ["gil"])
        self.assertEqual(self.resolve(gh, 5, "quality_checks: x\n", default="hugo")["logins"], ["hugo"])

    def test_chave_apontando_para_bot_ou_inexistente(self):
        gh = FakeGitHub({5: issue(BOT)}, users={"claude": APP})
        self.assertEqual(self.resolve(gh, 5, "default_responsible: claude\n")["rule"], "none")
        self.assertEqual(self.resolve(gh, 5, "default_responsible: ninguem\n")["rule"], "none")

    def test_ciclo_de_pais_termina(self):
        gh = FakeGitHub({3: issue(BOT, title="[SUB-TASK] a"), 4: issue(BOT, title="[SUB-TASK] b")},
                        parents={3: 4, 4: 3})
        self.assertEqual(self.resolve(gh, 3)["rule"], "none")

    def test_api_falhando_vira_erro(self):
        gh = FakeGitHub({1: issue(BOT)}, fail="issues/1")
        with self.assertRaises(responsible.ApiError):
            self.resolve(gh, 1)


class Cli(Base):
    def run_main(self, argv, gh):
        self._api = responsible.api
        responsible.api = gh.api
        out, err = io.StringIO(), io.StringIO()
        old = sys.argv
        sys.argv = ["responsible.py"] + argv
        code = 0
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                responsible.main()
        except SystemExit as exc:
            code = exc.code
        finally:
            sys.argv = old
            responsible.api = self._api
        return code, out.getvalue(), err.getvalue()

    def test_imprime_json(self):
        self.config.write_text("default_responsible: gil\n")
        gh = FakeGitHub({5: issue(BOT)}, users={"gil": human("gil")})
        code, out, _ = self.run_main(["5", "--config", str(self.config)], gh)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"issue": 5, "logins": ["gil"], "rule": "default"})

    def test_erro_de_api_sai_com_2(self):
        gh = FakeGitHub({5: issue(BOT)}, fail="issues/5")
        code, out, err = self.run_main(["5", "--config", str(self.config)], gh)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("HTTP 503", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
