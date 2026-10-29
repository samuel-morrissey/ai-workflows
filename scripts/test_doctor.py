#!/usr/bin/env python3
"""Testes das partes puras do doctor.py (sem gh, sem rede):

    python3 scripts/test_doctor.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402
from test_workflows import Run as WorkflowRun, Shape as WorkflowShape  # noqa: E402,F401

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


if __name__ == "__main__":
    unittest.main(verbosity=1)
