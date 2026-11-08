#!/usr/bin/env python3
"""Testes do leitor de `web_domains` (scripts/web_domains.py), sem rede.

    python3 scripts/test_web_domains.py
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import web_domains  # noqa: E402

SCRIPT = pathlib.Path(__file__).resolve().parent / "web_domains.py"


class Extract(unittest.TestCase):
    """O valor bruto da chave no arquivo, sem parser YAML."""

    def test_bloco_literal(self):
        text = "quality_checks: |\n  make test\nweb_domains: |\n  docs.asaas.com\n\n  https://docs.asaas.com/reference\nevidence_tools: make\n"
        self.assertEqual(web_domains.extract(text), "docs.asaas.com\n\nhttps://docs.asaas.com/reference\n")

    def test_bloco_com_indicador_e_comentario(self):
        self.assertEqual(web_domains.extract("web_domains: |- # fornecedores\n  docs.x.com\n"), "docs.x.com")

    def test_bloco_ate_o_fim_do_arquivo(self):
        self.assertEqual(web_domains.extract("web_domains: |\n    docs.x.com\n    docs.y.com"), "docs.x.com\ndocs.y.com\n")

    def test_escalar_simples_e_entre_aspas(self):
        self.assertEqual(web_domains.extract("web_domains: docs.x.com # um so\n"), "docs.x.com")
        self.assertEqual(web_domains.extract("web_domains: 'https://docs.x.com/ref'\n"), "https://docs.x.com/ref")

    def test_sem_a_chave(self):
        self.assertIsNone(web_domains.extract("quality_checks: make test\n# web_domains: |\n"))
        # Chave aninhada nao e a do topo.
        self.assertIsNone(web_domains.extract("outra: |\n  web_domains: docs.x.com\n"))

    def test_lista_mapa_e_vazio_falham(self):
        for text in ("web_domains:\n  - docs.x.com\n", "web_domains:\n- docs.x.com\n",
                     "web_domains: [docs.x.com]\n", "web_domains: {a: b}\n",
                     "web_domains:\n  a: docs.x.com\n", "web_domains:\nquality_checks: x\n",
                     "web_domains: 42\n", "web_domains: true\n"):
            with self.assertRaises(web_domains.ConfigError, msg=text):
                web_domains.extract(text)


class Entry(unittest.TestCase):
    """Cada linha: dominio, URL de entrada https://, ou invalida com motivo."""

    def test_dominio(self):
        self.assertEqual(web_domains.parse_entry("Docs.Asaas.com"), ("docs.asaas.com", None))

    def test_url_de_entrada(self):
        self.assertEqual(web_domains.parse_entry("https://docs.asaas.com/reference"),
                         ("docs.asaas.com", "https://docs.asaas.com/reference"))
        self.assertEqual(web_domains.parse_entry("https://docs.x.com:8443/a?b=1"),
                         ("docs.x.com", "https://docs.x.com:8443/a?b=1"))

    def test_invalidas(self):
        cases = {
            "http://x.com": "esquema",
            "ftp://x.com/a": "esquema",
            "*.x.com": "curinga",
            "https://*.x.com/": "curinga",
            "x .com": "espaco",
            '"x.com"': "aspas",
            "'x.com'": "aspas",
            "`x.com`": "aspas",
            "x.com/$HOME": "aspas",
            "https:///caminho": "host vazio",
            "https://": "host vazio",
            "x.com/caminho": "https://",
            "localhost": "dominio",
            "x_y.com": "dominio",
        }
        for line, reason in cases.items():
            with self.assertRaises(ValueError, msg=line) as ctx:
                web_domains.parse_entry(line)
            self.assertIn(reason, str(ctx.exception), line)


class Read(unittest.TestCase):
    """O arquivo inteiro: dominios extras, URLs e linhas ignoradas."""

    def test_url_libera_o_host_e_vai_ao_agente(self):
        r = web_domains.read("web_domains: |\n  https://docs.asaas.com/reference\n")
        self.assertEqual(r["domains"], ["docs.asaas.com"])
        self.assertEqual(r["urls"], ["https://docs.asaas.com/reference"])
        self.assertEqual(r["ignored"], [])
        self.assertEqual(web_domains.allow(r), ",WebFetch(domain:docs.asaas.com)")
        self.assertIn("https://docs.asaas.com/reference", web_domains.sentence(r))
        self.assertIn("llms.txt", web_domains.sentence(r))

    def test_repetidos_e_lista_fixa_uma_vez_so(self):
        r = web_domains.read("web_domains: |\n  docs.asaas.com\n  https://docs.asaas.com/reference\n"
                             "  https://docs.asaas.com/docs\n  docs.asaas.com\n  docs.github.com\n"
                             "  https://code.claude.com/docs/en/hooks\n")
        self.assertEqual(r["domains"], ["docs.asaas.com"])
        self.assertEqual(r["urls"], ["https://docs.asaas.com/reference", "https://docs.asaas.com/docs",
                                     "https://code.claude.com/docs/en/hooks"])
        self.assertEqual(web_domains.allow(r).count("docs.asaas.com"), 1)
        self.assertNotIn("docs.github.com", web_domains.allow(r))

    def test_vazias_e_comentarios_sem_aviso(self):
        r = web_domains.read("web_domains: |\n  # fornecedores\n\n  docs.x.com\n   \n")
        self.assertEqual(r["domains"], ["docs.x.com"])
        self.assertEqual(r["ignored"], [])

    def test_invalidas_ignoradas_e_validas_valem(self):
        r = web_domains.read('web_domains: |\n  http://x.com\n  *.x.com\n  x .com\n  "x.com"\n  docs.y.com\n')
        self.assertEqual([line for line, _ in r["ignored"]], ["http://x.com", "*.x.com", "x .com", '"x.com"'])
        self.assertEqual(r["domains"], ["docs.y.com"])

    def test_sem_arquivo_ou_sem_chave(self):
        for text in (None, "quality_checks: make test\n"):
            r = web_domains.read(text)
            self.assertEqual((r["domains"], r["urls"], r["ignored"]), ([], [], []))
            self.assertEqual(web_domains.allow(r), "")
            self.assertEqual(web_domains.sentence(r), "")

    def test_frase_cabe_entre_aspas(self):
        r = web_domains.read("web_domains: |\n  https://docs.x.com/a?b=1&c=2#d\n  docs.y.com\n")
        s = web_domains.sentence(r)
        for ch in '"`$\\\n':
            self.assertNotIn(ch, s)
        self.assertTrue(s.startswith(" "), s)
        self.assertIn("docs.y.com", s)


class Cli(unittest.TestCase):
    """O comando que a action web-domains roda no checkout do consumidor."""

    def run_cli(self, config=None):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="webd-"))
        (tmp / ".github").mkdir()
        if config is not None:
            (tmp / ".github" / "ai-workflows.yml").write_text(config)
        out = tmp / "out"
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), "--github-output", str(out)],
                              cwd=tmp, capture_output=True, text=True)
        return proc, out.read_text() if out.exists() else ""

    def test_avisa_cada_linha_invalida_e_segue(self):
        proc, out = self.run_cli("web_domains: |\n  http://x.com\n  https://docs.asaas.com/reference\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.count("::warning"), 1, proc.stdout)
        self.assertIn("http://x.com", proc.stdout)
        self.assertIn("allow=,WebFetch(domain:docs.asaas.com)\n", out)

    def test_sem_arquivo_nao_avisa(self):
        proc, out = self.run_cli()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("::warning", proc.stdout)
        self.assertIn("allow=\n", out)
        self.assertIn("sentence=\n", out)

    def test_lista_falha(self):
        proc, _ = self.run_cli("web_domains:\n  - docs.x.com\n")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("::error file=.github/ai-workflows.yml::web_domains precisa ser texto", proc.stdout)


if __name__ == "__main__":
    unittest.main()
