#!/usr/bin/env python3
"""Transcricao da sessao do agente como artifact `transcript`.

Dois modos, um por passo da action:

- `decidir`: escreve `publicar=true|false` e `motivo=<texto>` no
  $GITHUB_OUTPUT. Publica so com o EXECUTION_FILE existente e o repositorio
  privado (REPO_PRIVATE = `true`, de `github.event.repository.private`). Num
  repositorio publico qualquer leitor da run baixaria a transcricao, que traz
  prompts e saidas de ferramentas. O conteudo nao e lido: arquivo ilegivel ou
  truncado sobe assim mesmo, porque e o caso que se quer analisar.
- `registrar`: escreve no $GITHUB_STEP_SUMMARY se a transcricao foi publicada
  (e com qual retencao) ou por que nao foi, a partir de PUBLICAR, MOTIVO e
  UPLOAD_OUTCOME (o `outcome` do passo de upload).

Nunca falha a run: o passo que chama este script engole qualquer erro.
"""

import os
import sys

ARTIFACT = "transcript"
RETENTION_DAYS = 7
LABEL = "**Transcrição da sessão:**"


def decide(env):
    path = env.get("EXECUTION_FILE", "")
    if not path:
        return False, "sem `execution_file` (agente pulado, etapa sem agente ou falha antes da sessão)"
    if not os.path.isfile(path):
        return False, "sem `execution_file`: o arquivo informado não existe"
    if env.get("REPO_PRIVATE", "") != "true":
        return False, "repositório público, e qualquer leitor da run baixaria o artifact"
    return True, ""


def record(env):
    if env.get("PUBLICAR") != "true":
        reason = env.get("MOTIVO") or "a decisão de publicar não rodou"
        return f"{LABEL} não publicada: {reason}.", None
    if env.get("UPLOAD_OUTCOME") == "success":
        return (f"{LABEL} publicada no artifact `{ARTIFACT}`, com retenção de {RETENTION_DAYS} dias.",
                None)
    warning = "O upload da transcricao falhou; o artifact metrics nao e afetado."
    return f"{LABEL} não publicada: o upload do artifact falhou; veja o log do passo.", warning


def main(argv):
    env = os.environ
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "decidir":
        publish, reason = decide(env)
        with open(env["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"publicar={'true' if publish else 'false'}\nmotivo={reason}\n")
        print(f"publicar={'true' if publish else 'false'} {reason}".rstrip())
        return 0
    if mode == "registrar":
        line, warning = record(env)
        if warning:
            print(f"::warning::{warning}")
        print(line)
        with open(env["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(f"\n{line}\n")
        return 0
    print(f"modo desconhecido: {mode!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
