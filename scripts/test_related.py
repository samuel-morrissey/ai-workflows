#!/usr/bin/env python3
"""Testes dos repositorios relacionados, sem gh, git nem rede: o leitor de
`related_repos` e o comando `ai-related` (scripts/related.py), a action
related-repos, o passo "Ler repositorios relacionados" das seis etapas que
rodam o agente, o repasse do GitHub App pelo ai.yml e pelo router, o item
`config` e `secrets` do doctor e a documentacao.

    python3 scripts/test_related.py
"""

import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doctor  # noqa: E402
import related  # noqa: E402
import web_domains  # noqa: E402
from test_workflows import AGENT, WORKFLOWS, outputs_of, parse_step, steps_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "related.py"
ACTION = ROOT / ".github" / "actions" / "related-repos" / "action.yml"
AGENT_ENV = ROOT / ".github" / "actions" / "agent-env" / "action.yml"
SKILLS = ROOT / "skills"
USES = "samuel-morrissey/ai-workflows/.github/actions/related-repos@main"
STEP = "Ler repositorios relacionados"
ENV_STEP = "Preparar ambiente do agente"
REL_ALLOW = "${{ steps.relacionados.outputs.allow }}"
REL_SENTENCE = "${{ steps.relacionados.outputs.sentence }}"
OWN_SYSPROMPT = ["issue-triage.yml", "issue-refinement.yml", "issue-break-down.yml"]
ENV_SYSPROMPT = ["issue-remote-implement.yml", "issue-sub-task.yml", "pr-fix.yml"]
FILES = OWN_SYSPROMPT + ENV_SYSPROMPT
TOKEN = "ghs_tokenDoApp123"

# gh falso: guarda argumentos, token e stdin de cada chamada em $FAKE_LOG.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "gh", "argv": sys.argv[1:], "token": os.environ.get("GH_TOKEN"),
                          "gh_repo": os.environ.get("GH_REPO"),
                          "stdin": "" if sys.stdin.isatty() else sys.stdin.read()}) + "\n")
sys.stderr.write(os.environ.get("FAKE_GH_ERR", ""))
print("https://github.com/caravela/app/issues/7")
sys.exit(int(os.environ.get("FAKE_GH_RC", "0")))
'''

# git falso: guarda argumentos, pasta e a credencial do ambiente; o clone cria
# a pasta de destino com um .git.
FAKE_GIT = r'''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"tool": "git", "argv": argv, "cwd": os.getcwd(),
                          "key": os.environ.get("GIT_CONFIG_KEY_0"),
                          "header": os.environ.get("GIT_CONFIG_VALUE_0")}) + "\n")
if argv and argv[0] == "clone":
    os.makedirs(os.path.join(argv[-1], ".git"))
sys.exit(int(os.environ.get("FAKE_GIT_RC", "0")))
'''


class Entry(unittest.TestCase):
    """Cada linha da chave: `repo` ou `owner/repo`, do mesmo dono."""

    def test_nome_simples_ganha_o_dono(self):
        self.assertEqual(related.parse_entry("lumeeiro-app", "caravela"), "caravela/lumeeiro-app")

    def test_owner_repo_do_mesmo_dono(self):
        self.assertEqual(related.parse_entry("Caravela/lumeeiro.app_2", "caravela"), "caravela/lumeeiro.app_2")

    def test_outro_dono_e_recusado(self):
        with self.assertRaisesRegex(ValueError, "outro dono"):
            related.parse_entry("outra-org/app", "caravela")

    def test_invalidas(self):
        for line, reason in (("https://github.com/caravela/app", "sem URL"), ("caravela/app.git", "sem URL"),
                             ("a pp", "espaco"), ('"app"', "aspas"), ("$app", "cifrao"), ("a/b/c", "invalido"),
                             ("caravela/", "invalido"), ("..", "invalido"), ("app*", "invalido")):
            with self.assertRaisesRegex(ValueError, reason, msg=line):
                related.parse_entry(line, "caravela")


class Read(unittest.TestCase):
    def read(self, text):
        return related.read(text, "caravela", "caravela/www")

    def test_bloco_sem_repetir_e_sem_o_proprio(self):
        result = self.read("quality_checks: make\nrelated_repos: |\n  app\n  # comentario\n\n  caravela/app\n"
                           "  api\n  www\n  outra/x\nweb_domains: docs.x.com\n")
        self.assertEqual(result["repos"], ["caravela/app", "caravela/api"])
        self.assertEqual([line for line, _ in result["ignored"]], ["www", "outra/x"])
        self.assertIn("proprio repositorio", result["ignored"][0][1])

    def test_sem_arquivo_ou_sem_chave(self):
        for text in (None, "quality_checks: make\n# related_repos: |\n"):
            self.assertEqual(self.read(text), {"repos": [], "ignored": []})

    def test_lista_yaml_falha_com_o_nome_da_chave(self):
        with self.assertRaisesRegex(web_domains.ConfigError, "related_repos precisa ser texto"):
            self.read("related_repos:\n  - app\n")

    def test_web_domains_continua_lendo_a_chave_dele(self):
        text = "related_repos: |\n  app\nweb_domains: |\n  docs.x.com\n"
        self.assertEqual(web_domains.extract(text), "docs.x.com\n")
        with self.assertRaisesRegex(web_domains.ConfigError, "web_domains precisa ser texto"):
            web_domains.extract("web_domains:\n  - docs.x.com\n")


class Sandbox(unittest.TestCase):
    """Pasta temporaria com gh e git falsos no PATH."""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="related-"))
        self.bin = self.tmp / "fake-bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("git", FAKE_GIT)):
            path = self.bin / name
            path.write_text(text)
            path.chmod(path.stat().st_mode | stat.S_IEXEC)
        self.log = self.tmp / "log"
        self.dir = self.tmp / "ai-related"
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "FAKE_LOG": str(self.log),
                    "GH_TOKEN": "token-da-rodada", "GH_REPO": "caravela/www",
                    "GITHUB_SERVER_URL": "https://github.com"}

    def script(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], env={**self.env, **(env or {})},
                              cwd=self.tmp, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def install(self, repos="caravela/app,caravela/api", token=TOKEN, origin="caravela/www#12", reason=""):
        proc = self.script("install", "--repos", repos, "--dir", str(self.dir), "--origin", origin,
                           "--reason", reason, "--github-output", str(self.tmp / "out"),
                           "--github-path", str(self.tmp / "path"), env={"RELATED_TOKEN": token})
        out = outputs_of((self.tmp / "out").read_text()) if (self.tmp / "out").exists() else {}
        return proc, out

    def calls(self, tool="gh"):
        if not self.log.exists():
            return []
        return [c for c in map(json.loads, self.log.read_text().splitlines()) if c["tool"] == tool]


class Cli(Sandbox):
    """O modo read, como a action o chama."""

    def read(self, config):
        if config is not None:
            (self.tmp / "cfg.yml").write_text(config)
        proc = self.script("read", "--config", str(self.tmp / "cfg.yml"), "--owner", "caravela",
                           "--current", "caravela/www", "--github-output", str(self.tmp / "out"))
        out = outputs_of((self.tmp / "out").read_text()) if (self.tmp / "out").exists() else {}
        return proc, out

    def test_repos_e_nomes_para_a_action_do_token(self):
        proc, out = self.read("related_repos: |\n  app\n  caravela/api\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("::warning", proc.stdout)
        self.assertEqual(out, {"repos": "caravela/app,caravela/api", "names": "app,api"})

    def test_linha_ignorada_avisa_e_as_outras_valem(self):
        proc, out = self.read("related_repos: |\n  outra/x\n  www\n  app\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout.count("::warning"), 2, proc.stdout)
        self.assertEqual(out["names"], "app")

    def test_sem_arquivo_ou_sem_chave_sai_vazio_sem_aviso(self):
        for config in (None, "quality_checks: make\n"):
            proc, out = self.read(config)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("::", proc.stdout)
            self.assertEqual((out["repos"], out["names"]), ("", ""))

    def test_lista_yaml_falha_antes_do_agente(self):
        proc, out = self.read("related_repos:\n  - app\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("::error file=", proc.stdout)
        self.assertIn("related_repos precisa ser texto", proc.stdout)
        self.assertNotIn("repos", out)


class Install(Sandbox):
    """O modo install: token em arquivo, comando no PATH, allow e frase."""

    def test_entrega_o_comando_a_allowlist_e_a_frase(self):
        proc, out = self.install()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(out["allow"], ",Bash(ai-related:*)")
        self.assertTrue(out["sentence"].startswith(" Repositorios relacionados"), out)
        for texto in ("caravela/app, caravela/api", "ai-related", "samuel-morrissey-skills:related-repos",
                      "1 hora", "sem alterar nada la"):
            self.assertIn(texto, out["sentence"], texto)
        for ch in '"`$\\\n':
            self.assertNotIn(ch, out["sentence"])
        shim = self.dir / "bin" / "ai-related"
        self.assertTrue(os.access(shim, os.X_OK))
        self.assertEqual((self.tmp / "path").read_text(), f"{self.dir / 'bin'}\n")

    def test_token_so_no_arquivo_fechado(self):
        self.install()
        token_file = self.dir / "token"
        self.assertEqual(token_file.read_text(), TOKEN)
        self.assertEqual(stat.S_IMODE(token_file.stat().st_mode), 0o600)
        for other in (self.dir / "state.json", self.dir / "bin" / "ai-related", self.tmp / "out", self.tmp / "path"):
            self.assertNotIn(TOKEN, other.read_text(), other)

    def test_sem_token_avisa_o_motivo_e_segue_sem_vizinhos(self):
        proc, out = self.install(token="", reason="faltam a variavel e o secret")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("::warning::related_repos: sem acesso", proc.stdout)
        self.assertIn("faltam a variavel e o secret", proc.stdout)
        self.assertEqual((out["allow"], out["sentence"]), ("", ""))
        self.assertFalse(self.dir.exists())


class Command(Sandbox):
    """O comando ai-related, pelo executavel que o install cria."""

    def setUp(self):
        super().setUp()
        self.install()

    def run_cmd(self, *args, env=None):
        return subprocess.run([str(self.dir / "bin" / "ai-related"), *args], env={**self.env, **(env or {})},
                              cwd=self.tmp, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def assertRefused(self, *args, why=None):
        proc = self.run_cmd(*args)
        self.assertEqual(proc.returncode, 2, (args, proc.stdout, proc.stderr))
        self.assertIn("ai-related: recusado:", proc.stderr, args)
        if why:
            self.assertIn(why, proc.stderr, args)
        self.assertEqual(self.calls("gh") + self.calls("git"), [], args)

    def test_repos_lista_os_liberados_e_o_uso(self):
        for args in ((), ("repos",)):
            proc = self.run_cmd(*args)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            for texto in ("caravela/app", "caravela/api", "issue create", "pr comment", "clone"):
                self.assertIn(texto, proc.stdout, texto)
        self.assertEqual(self.calls(), [])

    def test_leitura_usa_o_token_do_app_no_repositorio_pedido(self):
        proc = self.run_cmd("app", "issue", "view", "7", "--comments", "--json", "title,body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [call] = self.calls()
        self.assertEqual(call["argv"], ["issue", "view", "7", "--comments", "--json", "title,body", "-R", "caravela/app"])
        # O token da rodada e o GH_REPO dela nao chegam ao gh do vizinho.
        self.assertEqual((call["token"], call["gh_repo"]), (TOKEN, None))

    def test_todas_as_leituras(self):
        for args in (("issue", "list", "--state", "all", "--search", "contrato"), ("pr", "list"),
                     ("pr", "view", "3"), ("pr", "diff", "3")):
            self.assertEqual(self.run_cmd("Caravela/API", *args).returncode, 0, args)
        self.assertEqual([c["argv"][-2:] for c in self.calls()], [["-R", "caravela/api"]] * 4)

    def test_repositorio_fora_da_chave(self):
        self.assertRefused("outro", "issue", "list", why="nao esta em related_repos")
        self.assertRefused("outra-org/app", "issue", "list")

    def test_acoes_que_alteram_o_vizinho_sao_recusadas(self):
        for args in (("issue", "edit", "7", "--add-label", "go"), ("issue", "close", "7"), ("issue", "reopen", "7"),
                     ("issue", "delete", "7"), ("pr", "merge", "3"), ("pr", "review", "3", "--approve"),
                     ("pr", "edit", "3"), ("pr", "close", "3"), ("pr", "create"), ("pr", "checkout", "3"),
                     ("label", "create", "go"), ("repo", "delete"), ("secret", "list"), ("issue",), ()):
            self.assertRefused("app", *args, why="outra equipe")

    def test_leitura_nao_troca_de_repositorio(self):
        for extra in (("-R", "caravela/www"), ("--repo", "x/y"), ("--repo=x/y",), ("-Rx/y",), ("--web",),
                      ("https://github.com/x/y/issues/1",)):
            self.assertRefused("app", "issue", "view", "7", *extra)

    def test_abrir_issue_leva_a_origem_e_nenhum_label(self):
        proc = self.run_cmd("app", "issue", "create", "--title", "Expor o campo plano", "--body", "## Pedido\n\nx")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("https://github.com/caravela/app/issues/7", proc.stdout)
        [call] = self.calls()
        self.assertEqual(call["argv"], ["issue", "create", "--title", "Expor o campo plano",
                                        "--body-file", "-", "-R", "caravela/app"])
        self.assertEqual(call["stdin"], "## Pedido\n\nx\n\n_Origem: caravela/www#12_\n")
        self.assertEqual(call["token"], TOKEN)

    def test_abrir_issue_so_com_titulo_e_corpo(self):
        for extra in (("--label", "go"), ("-l", "bug"), ("--assignee", "@me"), ("--project", "x"), ("--web",)):
            self.assertRefused("app", "issue", "create", "--title", "t", "--body", "b", *extra)
        self.assertRefused("app", "issue", "create", "--body", "b")
        self.assertRefused("app", "issue", "create", "--title", "t", why="--body ou com --body-file")
        self.assertRefused("app", "issue", "create", "--title", "t", "--body", "b", "--body-file", "f")
        self.assertRefused("app", "issue", "create", "--title", "t", "--body", "  ", why="corpo vazio")

    def test_comentar_em_issue_e_em_pr_pelo_arquivo(self):
        body = self.tmp / "corpo.md"
        body.write_text("Falta o campo plano.\n")
        for group in ("issue", "pr"):
            self.assertEqual(self.run_cmd("app", group, "comment", "7", "--body-file", str(body)).returncode, 0)
        issue, pr = self.calls()
        self.assertEqual(issue["argv"], ["issue", "comment", "7", "--body-file", "-", "-R", "caravela/app"])
        self.assertEqual(pr["argv"][:3], ["pr", "comment", "7"])
        self.assertEqual(issue["stdin"], "Falta o campo plano.\n\n_Origem: caravela/www#12_\n")

    def test_origem_ja_citada_nao_repete(self):
        self.run_cmd("app", "issue", "comment", "7", "--body", "Vem de caravela/www#12, veja la.")
        self.assertEqual(self.calls()[0]["stdin"], "Vem de caravela/www#12, veja la.\n")

    def test_comentario_so_em_numero_e_sem_editar(self):
        for args in (("issue", "comment", "https://github.com/x/y/issues/1", "--body", "b"),
                     ("issue", "comment", "#7", "--body", "b"), ("pr", "comment", "7", "--body", "b", "--edit-last"),
                     ("pr", "comment", "7", "--body", "b", "--delete-last"), ("issue", "comment", "--body", "b"),
                     ("pr", "comment", "7", "--body-file", "nao-existe.md")):
            self.assertRefused("app", *args)

    def test_api_e_so_get_dentro_do_repositorio(self):
        proc = self.run_cmd("app", "api", "pulls/3/comments?per_page=100", "--paginate", "--jq", ".[].body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.calls()[0]["argv"], ["api", "--method", "GET", "repos/caravela/app/pulls/3/comments?per_page=100",
                                                   "--paginate", "--jq", ".[].body"])

    def test_api_recusa_escrita_e_rota_de_fora(self):
        for args in (("issues/7", "-X", "PATCH"), ("issues/7", "--method", "DELETE"), ("issues/7", "-f", "state=closed"),
                     ("issues/7", "-F", "x=1"), ("issues/7", "--input", "f"), ("../www/issues",), ("/user",),
                     ("https://api.github.com/user",), ("issues/7", "-H", "Authorization: x"), ()):
            self.assertRefused("app", "api", *args)

    def test_clone_raso_fora_do_workspace_com_a_credencial_so_no_ambiente(self):
        proc = self.run_cmd("app", "clone")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        dest = self.dir / "repos" / "caravela" / "app"
        self.assertEqual(proc.stdout.strip(), str(dest))
        [call] = self.calls("git")
        self.assertEqual(call["argv"], ["clone", "--quiet", "--depth", "1", "https://github.com/caravela/app.git", str(dest)])
        self.assertEqual(call["cwd"], str(self.dir / "repos"))
        self.assertEqual(call["key"], "http.https://github.com/.extraheader")
        self.assertTrue(call["header"].startswith("AUTHORIZATION: basic "))
        self.assertNotIn(TOKEN, " ".join(call["argv"]))
        # De novo: a pasta ja existe e nada e clonado.
        self.assertEqual(self.run_cmd("caravela/app", "clone").stdout.strip(), str(dest))
        self.assertEqual(len(self.calls("git")), 1)

    def test_clone_numa_ref(self):
        self.assertEqual(self.run_cmd("app", "clone", "--ref", "feat/plano").returncode, 0)
        dest = str(self.dir / "repos" / "caravela" / "app")
        self.assertEqual([c["argv"] for c in self.calls("git")][1:],
                         [["fetch", "--quiet", "--depth", "1", "origin", "feat/plano"],
                          ["checkout", "--quiet", "--detach", "FETCH_HEAD"]])
        self.assertEqual({c["cwd"] for c in self.calls("git")[1:]}, {dest})
        for ref in ("--upload-pack=x", "a..b", "a b"):
            self.assertEqual(self.run_cmd("app", "clone", "--ref", ref).returncode, 2, ref)

    def test_clone_que_falha_diz_o_que_conferir(self):
        proc = self.run_cmd("app", "clone", env={"FAKE_GIT_RC": "128"})
        self.assertEqual(proc.returncode, 128)
        self.assertIn("O GitHub App esta instalado nele", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_token_expirado_explica(self):
        proc = self.run_cmd("app", "issue", "list", env={"FAKE_GH_RC": "1", "FAKE_GH_ERR": "HTTP 401: Bad credentials\n"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("HTTP 401", proc.stderr)
        self.assertIn("expirou (vale 1 hora", proc.stderr)

    def test_erro_comum_do_gh_passa_como_esta(self):
        proc = self.run_cmd("app", "issue", "view", "999", env={"FAKE_GH_RC": "1", "FAKE_GH_ERR": "HTTP 404\n"})
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("expirou", proc.stderr)

    def test_sem_estado_o_comando_diz_que_nao_ha_acesso(self):
        (self.dir / "state.json").unlink()
        proc = self.run_cmd("app", "issue", "list")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("indisponiveis nesta rodada", proc.stderr)


class Shape(unittest.TestCase):
    """As seis etapas que rodam o agente leem os repositorios relacionados."""

    def steps(self, f):
        return steps_of((WORKFLOWS / f).read_text())

    def test_le_antes_do_agente_nas_seis_etapas(self):
        for f in FILES:
            names = [n for n, _ in self.steps(f)]
            self.assertEqual(names.count(STEP), 1, f)
            self.assertGreater(names.index(STEP), names.index("Aplicar work-in-progress"), f)
            self.assertLess(names.index(STEP), names.index(AGENT), f)
            block = dict(self.steps(f))[STEP]
            step = parse_step(block)
            self.assertEqual(step["uses"], USES, f)
            self.assertRegex(block, r"(?m)^        id: relacionados$", f)
            # Valor que nao e texto para a rodada: sem continue-on-error.
            self.assertIsNone(step["continue_on_error"], f)
            self.assertEqual(step["if"], parse_step(dict(self.steps(f))[AGENT])["if"], f)
            self.assertEqual(step["with"], {"number": "${{ steps.target.outputs.number }}",
                                            "client_id": "${{ inputs.app_client_id }}",
                                            "private_key": "${{ secrets.AI_APP_PRIVATE_KEY }}"}, f)

    def test_comando_fecha_a_allowlist(self):
        for f in FILES:
            agent = dict(self.steps(f))[AGENT]
            self.assertRegex(agent, r'--allowed-tools "[^"\n]*%s"\n' % re.escape(REL_ALLOW), f)
            self.assertEqual(agent.count(REL_ALLOW), 1, f)
            # Nenhuma etapa libera o comando sem a action: so pelo sufixo.
            self.assertNotIn("ai-related", agent, f)

    def test_frase_fecha_o_system_prompt(self):
        for f in OWN_SYSPROMPT:
            agent = dict(self.steps(f))[AGENT]
            self.assertRegex(agent, r'--append-system-prompt "[^"\n]*%s"\n' % re.escape(REL_SENTENCE), f)
        for f in ENV_SYSPROMPT:
            names = [n for n, _ in self.steps(f)]
            self.assertLess(names.index(STEP), names.index(ENV_STEP), f)
            env = parse_step(dict(self.steps(f))[ENV_STEP])
            self.assertEqual(env["with"]["prompt_suffix"], f'"{REL_SENTENCE}"', f)
            self.assertNotIn(REL_SENTENCE, env["with"]["prompt_prefix"], f)

    def test_pr_fix_le_a_chave_do_checkout_da_head(self):
        names = [n for n, _ in self.steps("pr-fix.yml")]
        self.assertGreater(names.index(STEP), names.index("actions/checkout@v7"))

    def test_agent_env_fecha_o_system_prompt_com_o_sufixo(self):
        text = AGENT_ENV.read_text()
        self.assertIn("PROMPT_SUFFIX: ${{ inputs.prompt_suffix }}", text)
        self.assertIn('${QUALITY} ${EVIDENCE}${PROMPT_SUFFIX}\\"" >> "$GITHUB_OUTPUT"', text)
        # A chave e conhecida: sem aviso de chave desconhecida na implementacao.
        self.assertRegex(text, r'KEYS="[^"\n]* related_repos"')

    def test_etapas_declaram_o_app_como_opcional(self):
        for f in FILES + ["router.yml"]:
            text = (WORKFLOWS / f).read_text()
            self.assertRegex(text, r"(?m)^      app_client_id:\n(?:        .*\n)+?        required: false\n        default: \"\"$", f)
            self.assertRegex(text, r"(?m)^      AI_APP_PRIVATE_KEY:\n        required: false$", f)

    def test_router_repassa_as_seis_etapas(self):
        router = (WORKFLOWS / "router.yml").read_text()
        for f in FILES:
            job = router.split(f"    uses: samuel-morrissey/ai-workflows/.github/workflows/{f}@main\n", 1)[1].split("\n\n", 1)[0]
            self.assertIn("      app_client_id: ${{ inputs.app_client_id }}\n", job, f)
            self.assertIn("      AI_APP_PRIVATE_KEY: ${{ secrets.AI_APP_PRIVATE_KEY }}", job, f)
        self.assertEqual(router.count("AI_APP_PRIVATE_KEY: ${{ secrets.AI_APP_PRIVATE_KEY }}"), len(FILES))

    def test_ai_yml_repassa_a_variavel_e_o_secret(self):
        ai = (WORKFLOWS / "ai.yml").read_text()
        self.assertIn("      app_client_id: ${{ vars.AI_APP_CLIENT_ID }}\n", ai)
        self.assertIn("      AI_APP_PRIVATE_KEY: ${{ secrets.AI_APP_PRIVATE_KEY }}\n", ai)

    def test_eventos_do_app_no_vizinho_nao_disparam_etapa(self):
        # O agente abre issue e comenta: issue aberto nao e gatilho, e todo
        # gatilho de comentario ou review exige autor que nao e bot.
        ai = (WORKFLOWS / "ai.yml").read_text()
        self.assertIn("  issues:\n    types: [labeled]\n", ai)
        router = (WORKFLOWS / "router.yml").read_text()
        jobs = router.split("\njobs:\n", 1)[1]
        for cond in re.findall(r"github\.event_name == '(?:issue_comment|pull_request_review)' &&\n(?:.*\n){0,5}", jobs):
            self.assertRegex(cond, r"github\.event\.(comment|review)\.user\.type != 'Bot'", cond)


class ActionShape(unittest.TestCase):
    def setUp(self):
        self.text = ACTION.read_text()

    def test_token_so_dos_vizinhos_e_so_com_tres_permissoes(self):
        block = self.text.split("    - name: Criar token do GitHub App\n", 1)[1].split("\n    - name:", 1)[0]
        self.assertIn("uses: actions/create-github-app-token@v3\n", block)
        self.assertEqual(sorted(re.findall(r"^        (permission-[a-z-]+): (\w+)$", block, re.M)),
                         [("permission-contents", "read"), ("permission-issues", "write"),
                          ("permission-pull-requests", "write")])
        self.assertIn("repositories: ${{ steps.read.outputs.names }}", block)
        self.assertIn("owner: ${{ github.repository_owner }}", block)
        # Token que nao sai nao para a rodada, e o token e revogado no fim.
        self.assertIn("continue-on-error: true", block)
        self.assertNotIn("skip-token-revoke", block)

    def test_sem_app_ou_sem_chave_nao_cria_token(self):
        self.assertIn("if: steps.read.outputs.names != '' && inputs.client_id != '' && inputs.private_key != ''", self.text)
        self.assertIn("if: steps.read.outputs.repos != ''", self.text)

    def test_token_nao_vai_para_o_ambiente_dos_outros_passos(self):
        self.assertNotIn("GITHUB_ENV", self.text)
        self.assertEqual(self.text.count("steps.token.outputs.token"), 1)
        self.assertNotIn("token", yaml_outputs(self.text))

    def test_leitor_vem_da_mesma_ref_da_action(self):
        self.assertEqual(self.text.count("RELATED_PY: ${{ github.action_path }}/../../../scripts/related.py"), 2)
        self.assertIn('--origin "$ORIGIN"', self.text)
        self.assertIn("ORIGIN: ${{ github.repository }}#${{ inputs.number }}", self.text)


def yaml_outputs(text):
    """Nomes das saidas declaradas pela composite action."""
    block = text.split("\noutputs:\n", 1)[1].split("\nruns:\n", 1)[0]
    return re.findall(r"^  ([a-z_]+):$", block, re.M)


class DoctorConfig(unittest.TestCase):
    """O doctor conhece a chave e cobra o GitHub App quando ela existe."""

    def repo(self, text, variables=(), secrets=()):
        return SimpleNamespace(full="caravela/www", owner="caravela", config_text=text, config_error=None,
                               inline={}, config=doctor.parse_simple_yaml(text), config_env={},
                               config_env_path="config.env",
                               effective=lambda key: "",
                               variables=lambda: ({n: ("org", "x") for n in variables}, []),
                               secrets=lambda: ({n: "org" for n in secrets}, []))

    BASE = "quality_checks: make\nevidence_tools: make\nweb_domains: docs.x.com\n"

    def test_chave_conhecida_com_o_app_configurado(self):
        f = doctor.check_config(self.repo(self.BASE + "related_repos: |\n  app\n", variables=["AI_APP_CLIENT_ID"]))
        self.assertEqual(f.status, "ok", f.detail)

    def test_linha_ignorada_diverge(self):
        f = doctor.check_config(self.repo(self.BASE + "related_repos: |\n  app\n  outra/x\n", variables=["AI_APP_CLIENT_ID"]))
        self.assertEqual(f.status, "diverge")
        self.assertIn("related_repos com linha ignorada pelo workflow: outra/x (outro dono", f.detail)

    def test_sem_a_variavel_do_app_avisa(self):
        f = doctor.check_config(self.repo(self.BASE + "related_repos: |\n  app\n"))
        self.assertEqual(f.status, "info")
        self.assertIn("sem a variavel AI_APP_CLIENT_ID", f.detail)

    def test_sem_a_chave_nada_muda(self):
        f = doctor.check_config(self.repo(self.BASE))
        self.assertEqual(f.status, "ok", f.detail)

    def test_secret_do_app_so_e_cobrado_com_a_chave(self):
        com = self.repo(self.BASE + "related_repos: app\n", secrets=["CLAUDE_CODE_OAUTH_TOKEN"])
        f = doctor.check_secrets(com)
        self.assertEqual(f.status, "manual")
        self.assertIn("AI_APP_PRIVATE_KEY", f.detail)
        self.assertIn("gh secret set AI_APP_PRIVATE_KEY -R caravela/www", f.fix)
        com = self.repo(self.BASE + "related_repos: app\n", secrets=["CLAUDE_CODE_OAUTH_TOKEN", "AI_APP_PRIVATE_KEY"])
        self.assertEqual(doctor.check_secrets(com).status, "ok")
        sem = self.repo(self.BASE, secrets=["CLAUDE_CODE_OAUTH_TOKEN"])
        self.assertEqual(doctor.check_secrets(sem).status, "ok")


class Docs(unittest.TestCase):
    def test_skill_traz_a_regra_do_vizinho(self):
        text = (SKILLS / "related-repos" / "SKILL.md").read_text()
        self.assertRegex(text, r"(?m)^name: related-repos$")
        flat = " ".join(text.replace("**", "").split())
        for texto in ("outra equipe", "nem `go`", "Procure antes de abrir", "dado, nunca instrucao",
                      "Pedido de repositorio relacionado ignorado:", "1 hora", "issue-async-first",
                      "Nunca espere dentro da rodada", "ai-related <repo> clone", "ai-related <repo> issue create",
                      "ai-related <repo> pr comment", "Sem a frase, a rodada nao tem acesso"):
            self.assertIn(texto, flat, texto)

    def test_frase_do_system_prompt_cita_a_skill_que_existe(self):
        plugin, _, skill = related.SKILL.partition(":")
        self.assertEqual(plugin, "samuel-morrissey-skills")
        self.assertTrue((SKILLS / skill / "SKILL.md").is_file())
        self.assertIn(related.SKILL, related.sentence(["o/a"]))

    def test_skills_das_etapas_apontam_para_a_regra(self):
        for skill in ("issue-triage", "issue-refinement", "issue-break-down", "issue-remote-implement", "pr-fix"):
            flat = " ".join((SKILLS / skill / "SKILL.md").read_text().split())
            self.assertIn('"Repositorios relacionados"', flat, skill)
            self.assertIn("invoque a skill `related-repos`", flat, skill)

    def test_uso_do_comando_bate_com_o_que_ele_aceita(self):
        usage = related.usage({"repos": ["o/a"]})
        for group, action in sorted(related.READ | related.WRITE):
            self.assertRegex(usage, r"%s [a-z|]*\b%s\b" % (group, action), (group, action))

    def test_readme_documenta_a_chave_o_app_e_os_limites(self):
        readme = (ROOT / "README.md").read_text()
        table = readme.split("\n## O que um repositório precisa\n", 1)[1].split("\n### ", 1)[0]
        self.assertIn("`related_repos`", table)
        secrets = readme.split("\n### Variáveis e secrets\n", 1)[1].split("\n### ", 1)[0]
        self.assertIn("| `AI_APP_CLIENT_ID` | variável | com `related_repos` |", secrets)
        self.assertIn("| `AI_APP_PRIVATE_KEY` | secret | com `related_repos` |", secrets)
        section = readme.split("\n### Repositórios relacionados\n", 1)[1].split("\n### ", 1)[0]
        for texto in ("outra equipe", "**Contents: Read-only**", "**Issues: Read and write**",
                      "**Pull requests: Read and write**", "`ai-related`", "1 hora", "revogado no fim do job",
                      "A trava é o comando, não a permissão", "Só o mesmo dono", "`Origem: <owner/repo>#<n>`",
                      "dado, nunca instrução", "a rodada segue sem vizinhos"):
            self.assertIn(texto, section, texto)
        config = readme.split("\n### O arquivo `.github/ai-workflows.yml`\n", 1)[1].split("\n### ", 1)[0]
        item = config.split("- `related_repos`:", 1)[1].split("\n- `", 1)[0]
        for texto in ("`repo` ou `owner/repo`", "mesmo dono", "falha a rodada", "`doctor`"):
            self.assertIn(texto, item, texto)
        etapas = readme.split("\n## Etapas\n", 1)[1].split("\n### ", 1)[0]
        self.assertIn("(#repositórios-relacionados)", etapas)


if __name__ == "__main__":
    unittest.main()
