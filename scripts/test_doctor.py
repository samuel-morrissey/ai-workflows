#!/usr/bin/env python3
"""Testes das partes puras do doctor.py (sem gh, sem rede):

    python3 scripts/test_doctor.py
"""

import contextlib
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402
from test_workflows import (  # noqa: E402,F401
    AgentEnvConfig, ChainNoticeRun, ChainNoticeShape, PrClosedRun, PrClosedShape, PrFixTrigger, ResponsibleRun,
    ResponsibleShape, Run as WorkflowRun, SafetyNetRun, SafetyNetShape, Shape as WorkflowShape,
    SkillsMention, SkillsPremise, WebAccess, WebDomainsRun, WebDomainsShape)
from test_sub_tasks import (  # noqa: E402,F401
    Finish as SubTasksFinish, Notify as SubTasksNotify, Stack as SubTasksStack,
    Worker as SubTasksWorker)
from test_responsible import (  # noqa: E402,F401
    Cli as ResponsibleCli, Rules as ResponsibleRules)
from test_web_domains import (  # noqa: E402,F401
    Cli as WebDomainsCli, Entry as WebDomainsEntry, Extract as WebDomainsExtract, Read as WebDomainsRead)
from test_undo import (  # noqa: E402,F401
    BreakDown as UndoBreakDown, Cli as UndoCli, Docs as UndoDocs, DuringRound as UndoDuringRound,
    Label as UndoLabel, Refinement as UndoRefinement, Refusals as UndoRefusals, Router as UndoRouter,
    Shape as UndoShape, Triage as UndoTriage)
from test_advance import (  # noqa: E402,F401
    AiYml as AdvanceAiYml, ChainedUndo as AdvanceChainedUndo, Check as AdvanceCheck, Docs as AdvanceDocs,
    DoctorConfig as AdvanceDoctorConfig, Router as AdvanceRouter, Run as AdvanceRun, Shape as AdvanceShape)
from test_metrics import (  # noqa: E402,F401
    Compare as MetricsCompare, Mapping as MetricsMapping, Readme as MetricsReadme, Run as MetricsRun, Session as MetricsSession,
    Shape as MetricsShape, Subagents as MetricsSubagents)

TEMPLATE = """name: AI
on:
  issues:
    types: [labeled]
jobs:
  ai:
    uses: samuel-morrissey/ai-workflows/.github/workflows/router.yml@main
    with:
      evidence_bucket: ${{ vars.EVIDENCE_BUCKET }}
      evidence_public_url: ${{ vars.EVIDENCE_PUBLIC_URL }}
      evidence_endpoint: ${{ vars.EVIDENCE_ENDPOINT }}
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
"""

LEGACY = """name: AI
jobs:
  ai:
    uses: samuel-morrissey/ai-workflows/.github/workflows/router.yml@main
    # - setup_commands: preparacao do ambiente
    with:
      setup_commands: |
        export N_PREFIX="$RUNNER_TEMP/node" && npx --yes n 22
        npm ci
      quality_checks: |
        npm run check
      evidence_tools: |
        node
        npx playwright
        curl
      evidence_bucket: s3://public
      evidence_public_url: https://srv.example/public
      # evidence_endpoint: comentado
    secrets:
      CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
"""


class SimpleYaml(unittest.TestCase):
    def test_escalar_e_bloco(self):
        cfg = doctor.parse_simple_yaml(
            "# comentario\nsetup_commands: |\n  npm ci\n  echo \"a: b\" # nao e comentario\n\nquality_checks: npm test\nevidence_tools: \"\"\n")
        self.assertEqual(cfg["setup_commands"], "npm ci\necho \"a: b\" # nao e comentario\n")
        self.assertEqual(cfg["quality_checks"], "npm test")
        self.assertEqual(cfg["evidence_tools"], "")

    def test_lista_e_mapa_sao_erro(self):
        with self.assertRaises(doctor.ConfigError):
            doctor.parse_simple_yaml("quality_checks:\n  - npm test\n")
        with self.assertRaises(doctor.ConfigError):
            doctor.parse_simple_yaml("quality_checks: [npm test]\n")
        with self.assertRaises(doctor.ConfigError):
            doctor.parse_simple_yaml("quality_checks: >\n  npm test\n")
        with self.assertRaises(doctor.ConfigError):
            doctor.parse_simple_yaml("  indentado: x\n")

    def test_chave_vazia_e_comentario_inline(self):
        cfg = doctor.parse_simple_yaml("evidence_tools:\nevidence_bucket: s3://b # bucket\n")
        self.assertEqual(cfg, {"evidence_tools": "", "evidence_bucket": "s3://b"})

    def test_bloco_com_linha_em_branco_no_meio(self):
        cfg = doctor.parse_simple_yaml("a: |\n  um\n\n  dois\nb: x\n")
        self.assertEqual(cfg["a"], "um\n\ndois\n")
        self.assertEqual(cfg["b"], "x")


class WithBlock(unittest.TestCase):
    def test_modelo_novo_nao_tem_inline(self):
        self.assertEqual(doctor.extract_with_block(TEMPLATE), {})

    def test_legado_extrai_valores(self):
        inline = doctor.extract_with_block(LEGACY)
        self.assertEqual(set(inline), {"setup_commands", "quality_checks", "evidence_tools", "evidence_bucket", "evidence_public_url"})
        self.assertEqual(inline["quality_checks"], "npm run check\n")
        self.assertTrue(inline["setup_commands"].startswith("export N_PREFIX"))
        self.assertEqual(inline["evidence_bucket"], "s3://public")

    def test_sem_with(self):
        self.assertEqual(doctor.extract_with_block("jobs:\n  ai:\n    uses: x\n"), {})


class RenderConfig(unittest.TestCase):
    def test_bloco_para_multilinha_e_escalar_para_simples(self):
        text = doctor.render_config_yaml({"quality_checks": "npm test\nnpm run build\n", "evidence_bucket": "s3://public",
                                          "evidence_public_url": "https://x.y/p q"})
        self.assertIn("quality_checks: |\n  npm test\n  npm run build\n", text)
        self.assertIn("evidence_bucket: s3://public\n", text)
        self.assertIn("evidence_public_url: |\n  https://x.y/p q\n", text)
        # o que o doctor escreve, o doctor le de volta igual
        back = doctor.parse_simple_yaml(text)
        self.assertEqual(back["quality_checks"], "npm test\nnpm run build\n")
        self.assertEqual(back["evidence_bucket"], "s3://public")

    def test_ida_e_volta_do_legado(self):
        inline = doctor.extract_with_block(LEGACY)
        back = doctor.parse_simple_yaml(doctor.render_config_yaml(inline))
        self.assertEqual(back, inline)


class EnvFile(unittest.TestCase):
    def test_formatos(self):
        env = doctor.parse_env("# c\nA=1\nexport B=\"x=y\"\nC='z'\nSEM_IGUAL\n1X=2\n D = 3 \n")
        self.assertEqual(env, {"A": "1", "B": "x=y", "C": "z", "D": "3"})


class Compare(unittest.TestCase):
    def test_normaliza_espaco_no_fim(self):
        self.assertEqual(doctor.normalize("a: 1  \nb: 2\n\n"), doctor.normalize("a: 1\nb: 2"))
        self.assertNotEqual(doctor.normalize("a: 1"), doctor.normalize("a: 2"))


class SkillSections(unittest.TestCase):
    def test_secoes_com_e_sem_acento(self):
        text = "# Evidências deste projeto\n## Evidência ideal\n## Como subir\n## Dados e acesso\n## Antes\n## Limites\n"
        self.assertEqual(doctor.skill_missing_sections(text), [])
        self.assertEqual(doctor.skill_missing_sections("## Como subir\n## Antes\n"), ["evidencia ideal", "dados e acesso", "limites"])


class ConfigCheck(unittest.TestCase):
    """O item `config` (`doctor check --only config`) com o arquivo ja lido."""

    def check(self, text):
        repo = SimpleNamespace(config_text=text, config_error=None, inline={},
                               config=doctor.parse_simple_yaml(text))
        return doctor.check_config(repo)

    def test_default_responsible_e_chave_conhecida(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\ndefault_responsible: fulano\n"
                       "web_domains: docs.asaas.com\n")
        self.assertEqual(f.status, "ok", f.detail)

    def test_web_domains_e_chave_conhecida(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\n"
                       "web_domains: |\n  docs.asaas.com\n  https://docs.asaas.com/reference\n")
        self.assertEqual(f.status, "ok", f.detail)
        self.assertNotIn("web_domains", f.detail)

    def test_sem_web_domains_sai_info_apontando_a_setup_repo(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\n")
        self.assertEqual(f.status, "info", f.detail)
        self.assertIn("sem web_domains", f.detail)
        self.assertIn("setup-repo", f.detail)
        self.assertEqual(doctor.exit_code([f]), 0)

    def test_sem_web_domains_soma_a_nota_as_outras(self):
        f = self.check("quality_checks: make test\n")
        self.assertEqual(f.status, "info")
        self.assertIn("sem evidence_tools", f.detail)
        self.assertIn("sem web_domains", f.detail)

    def test_check_json_sem_web_domains_sai_info_e_codigo_0(self):
        text = "quality_checks: make test\nevidence_tools: make\n"

        def fake_repo(full, *_):
            return SimpleNamespace(full=full, default_branch="main", is_org=False, config_text=text,
                                   config_error=None, inline={}, config=doctor.parse_simple_yaml(text))

        out = io.StringIO()
        with mock.patch.object(doctor, "Repo", fake_repo), contextlib.redirect_stdout(out):
            code = doctor.main(["check", "dono/app", "--only", "config", "--json"])
        report = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["exit"], 0)
        [finding] = report["findings"]
        self.assertEqual((finding["item"], finding["status"]), ("config", "info"))
        self.assertIn("web_domains", finding["detail"])
        self.assertIn("setup-repo", finding["detail"])

    def test_linha_invalida_continua_diverge_sem_a_nota_de_ausencia(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\nweb_domains: http://x.com\n")
        self.assertEqual(f.status, "diverge")
        self.assertNotIn("sem web_domains", f.detail)

    def test_web_domains_acusa_a_linha_invalida(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\n"
                       "web_domains: |\n  docs.asaas.com\n  http://x.com\n  *.x.com\n")
        self.assertEqual(f.status, "diverge")
        self.assertIn("web_domains", f.detail)
        self.assertIn("http://x.com (esquema", f.detail)
        self.assertIn("*.x.com (curinga", f.detail)
        self.assertNotIn("docs.asaas.com (", f.detail)

    def test_web_domains_como_lista_e_invalido(self):
        with self.assertRaises(doctor.ConfigError):
            doctor.parse_simple_yaml("web_domains:\n  - docs.asaas.com\n")

    def test_chave_desconhecida_continua_diverge(self):
        f = self.check("quality_checks: make test\nevidence_tools: make\nresponsavel: fulano\n")
        self.assertEqual(f.status, "diverge")
        self.assertIn("responsavel", f.detail)


class Report(unittest.TestCase):
    def test_saida_e_render(self):
        ok = [doctor.Finding("topic", "ok", "x"), doctor.Finding("bucket", "info", "y")]
        self.assertEqual(doctor.exit_code(ok), 0)
        bad = ok + [doctor.Finding("labels", "falta", "sem go", fix="gh label create go")]
        self.assertEqual(doctor.exit_code(bad), 1)
        self.assertEqual(doctor.exit_code([doctor.Finding("config", "manual", "z")]), 1)
        text = doctor.render_report("o/r", bad, actions=["label criado"])
        self.assertIn("== o/r", text)
        self.assertIn("[labels] gh label create go", text)
        self.assertIn("acoes:", text)


class Labels(unittest.TestCase):
    def test_tudo_canonico(self):
        labels = {n: {"color": c.lower(), "description": d} for n, (c, d) in doctor.FLOW_LABELS.items()}
        self.assertEqual(doctor.label_plan(labels), ([], []))

    def test_faltando_e_divergente(self):
        labels = {n: {"color": c, "description": d} for n, (c, d) in doctor.FLOW_LABELS.items()}
        del labels["needs-triage"]
        labels["go"]["color"] = "000000"
        labels["priority"]["description"] = ""
        missing, different = doctor.label_plan(labels)
        self.assertEqual(missing, ["needs-triage"])
        self.assertEqual(different, ["go", "priority"])

    def test_fora_do_fluxo_nao_entra(self):
        labels = {"bug": {"color": "D73A4A", "description": ""}, "priority-high": {"color": "B60205", "description": ""},
                  "docs": {"color": "0075CA", "description": ""}, "chore": {"color": "EDEDED", "description": ""}}
        missing, different = doctor.label_plan(labels)
        self.assertEqual(len(missing), len(doctor.FLOW_LABELS))
        self.assertEqual(different, [])
        self.assertEqual(doctor.label_collisions(labels), ["bug", "docs", "priority-high"])


def flat(text):
    return " ".join(text.replace("**", "").split())


def section(text, start, end="\n## "):
    return text.split(start, 1)[1].split(end, 1)[0]


class SetupRepoWebDomains(unittest.TestCase):
    """A skill setup-repo propoe web_domains, tambem em repositorio ja configurado."""

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "skills", "setup-repo", "SKILL.md"), encoding="utf-8") as fh:
            cls.skill = fh.read()
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            cls.readme = fh.read()

    def step(self, n):
        return flat(section(self.skill, f"\n{n}. ", f"\n{n + 1}. "))

    def test_saida_0_com_o_info_de_web_domains_nao_encerra(self):
        s = self.step(1)
        self.assertIn("Saida 0", s)
        self.assertIn("`info` de `web_domains`", s)
        self.assertIn("nao encerra", s)
        self.assertIn("Os outros `info` seguem fora do escopo", s)

    def test_leitura_levanta_fornecedores_e_confere_a_url(self):
        s = self.step(2)
        for texto in ("fornecedores", "`package.json`", "`requirements*.txt`", "`pyproject.toml`", "`go.mod`",
                      "ADRs", "`CONTEXT.md`", "lista fixa", "`llms.txt` primeiro", "`curl`",
                      "outro host", "destino final", "pagina indice"):
            self.assertIn(texto, s, texto)

    def test_pergunta_unica_traz_a_lista_com_motivo(self):
        s = self.step(5)
        self.assertIn("`web_domains`", s)
        self.assertIn("recomendacao e o motivo", s)
        self.assertIn("ADR 0008", s)

    def test_aplicar_acrescenta_sem_reescrever(self):
        s = self.step(6)
        self.assertIn("`web_domains`", s)
        self.assertIn("sem reescrever nem reordenar as outras chaves", s)
        self.assertIn("so as entradas que faltam", s)
        self.assertIn("excecao", s)

    def test_casos_cobrem_chave_existente_e_sem_fornecedor(self):
        s = flat(section(self.skill, "\n## Casos\n"))
        for texto in ("Ja tem `web_domains`", "nunca remove", "Sem fornecedor externo", "nao ha PR",
                      "foi decidida", "repeticao, nao erro", "Repositorio parcialmente configurado"):
            self.assertIn(texto, s, texto)

    def test_readme_descreve_a_proposta_e_o_info(self):
        config = self.readme.split("\n### O arquivo `.github/ai-workflows.yml`\n", 1)[1].split("\n### ", 1)[0]
        item = flat(config.split("- `web_domains`:", 1)[1])
        for texto in ("`setup-repo`", "`info`", "`llms.txt`", "`curl`", "outro host"):
            self.assertIn(texto, item, texto)
        row = next(line for line in self.readme.splitlines() if line.startswith("| `config` |"))
        self.assertIn("`info`", row)
        self.assertIn("`setup-repo`", row)
        self.assertIn("web_domains", row)


if __name__ == "__main__":
    unittest.main(verbosity=1)
