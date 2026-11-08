#!/usr/bin/env python3
"""Le a chave `web_domains` de .github/ai-workflows.yml do consumidor.

Triagem, refinamento e break-down tem `WebFetch` restrito a uma lista fixa
de dominios (FIXED, espelho do `--allowed-tools` dos tres workflows). A chave
soma a ela os fornecedores do consumidor: um bloco `|`, uma entrada por
linha, cada uma um dominio (`docs.asaas.com`) ou uma URL de entrada
`https://` (`https://docs.asaas.com/reference`). O dominio liberado e o host
da URL, ou o proprio dominio; as URLs vao ao agente pelo system prompt.

Usado pela action web-domains, antes do agente, e pelo doctor.py (item
`config`). So biblioteca padrao: a leitura e so desta chave, sem parser YAML.

- Linha vazia ou so comentario: ignorada sem aviso.
- Linha invalida (esquema que nao e `https://`, curinga, espaco no meio,
  aspas, crase, cifrao, host vazio): ignorada com `::warning`; o resto vale.
- Valor que nao e texto (lista, mapa, numero, vazio): `::error` e saida 1,
  como na agent-env.
- Sem arquivo, ou sem a chave: so a lista fixa, sem aviso.

    web_domains.py [--config .github/ai-workflows.yml] [--github-output <arquivo>]

Sem --github-output, imprime o resultado em JSON.
"""

import argparse
import json
import re
import secrets
import sys
import urllib.parse

CONFIG_FILE = ".github/ai-workflows.yml"
KEY = "web_domains"
FIXED = ("docs.github.com", "code.claude.com", "platform.claude.com")
LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
HOST_RE = re.compile(rf"{LABEL}(?:\.{LABEL})+")
KEY_RE = re.compile(rf"^{KEY}[ \t]*:(.*)$", re.MULTILINE)
BLOCK_RE = re.compile(r"^([|>])([+-]?)[1-9]?([+-]?)$")
NOT_TEXT_RE = re.compile(r"(?i)(?:[-+]?[0-9][0-9_.eE+-]*|true|false|null|~|\.inf|\.nan)")
UNSAFE = "\"'`$\\"


class ConfigError(Exception):
    """`web_domains` com valor que nao e texto."""


def not_text(kind):
    return ConfigError(f"{KEY} precisa ser texto (escalar ou bloco |), e veio como {kind}.")


def strip_comment(value):
    return re.sub(r"(^|\s+)#.*$", "", value).strip()


def extract(text):
    """Valor de texto da chave no topo do arquivo, ou None sem a chave.

    Aceita escalar simples (com ou sem aspas) e bloco `|` ou `>`. Lista, mapa,
    numero, booleano ou vazio levantam ConfigError.
    """
    if text is None:
        return None
    match = KEY_RE.search(text)
    if not match:
        return None
    header = strip_comment(match.group(1))
    rest = text[match.end():].split("\n")[1:]
    if not header:
        nxt = next((l for l in rest if l.strip() and not l.lstrip().startswith("#")), "")
        if nxt.lstrip().startswith("-"):
            raise not_text("lista")
        if nxt[:1] in " \t" and re.match(r"^\s*[^\s:]+\s*:(\s|$)", nxt):
            raise not_text("mapa")
        raise not_text("vazio")
    block = BLOCK_RE.match(header)
    if block:
        return read_block(rest, folded=block.group(1) == ">", chomp=block.group(2) or block.group(3))
    if header[0] in "[":
        raise not_text("lista")
    if header[0] in "{":
        raise not_text("mapa")
    if header[0] in "&*!|>":
        raise not_text("valor que o leitor nao entende")
    if len(header) >= 2 and header[0] == header[-1] and header[0] in "\"'":
        return header[1:-1]
    if NOT_TEXT_RE.fullmatch(header):
        raise not_text("numero, booleano ou nulo")
    return header


def read_block(lines, folded=False, chomp=""):
    """Linhas de um bloco `|`/`>`: as que vem depois, mais indentadas que a chave."""
    block, indent = [], None
    for raw in lines:
        if raw.strip() == "":
            block.append("")
            continue
        cur = len(raw) - len(raw.lstrip(" "))
        if indent is None:
            if cur == 0:
                break
            indent = cur
        if cur < indent:
            break
        block.append(raw[indent:])
    while block and block[-1] == "":
        block.pop()
    if folded:
        return " ".join(l for l in block if l) + ("" if chomp == "-" else "\n")
    return "\n".join(block) + ("\n" if block and chomp != "-" else "")


def parse_entry(line):
    """(dominio, url de entrada ou None) de uma linha; ValueError com o motivo."""
    if re.search(r"\s", line):
        raise ValueError("espaco no meio")
    if any(ch in line for ch in UNSAFE):
        raise ValueError("aspas, crase, cifrao ou barra invertida")
    if "*" in line:
        raise ValueError("curinga * nao e aceito")
    if "://" in line:
        scheme = line.split("://", 1)[0]
        if scheme != "https":
            raise ValueError("esquema nao e https://")
        try:
            host = urllib.parse.urlsplit(line).hostname or ""
        except ValueError:
            raise ValueError("URL invalida")
        if not host:
            raise ValueError("host vazio")
        url = line
    elif "/" in line or ":" in line:
        raise ValueError("URL de entrada precisa comecar por https://")
    else:
        host, url = line.lower(), None
    host = host.lower()
    if not HOST_RE.fullmatch(host):
        raise ValueError("dominio invalido")
    return host, url


def entries(value):
    """Linhas de entrada do valor, sem vazias nem comentarios."""
    for raw in (value or "").split("\n"):
        line = raw.strip()
        if line and not line.startswith("#"):
            yield line


def read(text):
    """Dominios extras (fora da lista fixa, sem repetir), URLs e ignoradas."""
    result = {"domains": [], "urls": [], "ignored": []}
    for line in entries(extract(text)):
        try:
            host, url = parse_entry(line)
        except ValueError as exc:
            result["ignored"].append((line, str(exc)))
            continue
        if host not in FIXED and host not in result["domains"]:
            result["domains"].append(host)
        if url and url not in result["urls"]:
            result["urls"].append(url)
    return result


def allow(result):
    """Sufixo do `--allowed-tools`: `,WebFetch(domain:<d>)` por dominio extra."""
    return "".join(f",WebFetch(domain:{d})" for d in result["domains"])


def sentence(result):
    """Frase do system prompt, comecando por espaco; vazia sem fonte.

    Sem aspas duplas, crase, cifrao nem barra invertida: vai entre aspas em
    claude_args (as entradas com eles ja foram ignoradas).
    """
    if not result["domains"] and not result["urls"]:
        return ""
    parts = [f"Fontes da web do consumidor (chave {KEY} de {CONFIG_FILE}):"]
    if result["domains"]:
        parts.append(f"alem da lista fixa, o WebFetch libera {', '.join(result['domains'])}.")
    if result["urls"]:
        parts.append(f"URLs de entrada: {' ; '.join(result['urls'])}.")
    parts.append("Em cada dominio, comece pelo llms.txt, quando existir, e depois pela URL de entrada,"
                 " seguindo os links dela em vez de adivinhar caminhos. Com essas fontes navegadas,"
                 " premissa nao verificada quer dizer que nao ha fonte oficial, nao que a URL nao foi"
                 " achada (Uso da web, no AGENT-BRIEF.md da issue-triage).")
    return " " + " ".join(parts)


def emit(path, key, value):
    with open(path, "a", encoding="utf-8") as fh:
        if "\n" in value:
            d = f"EOF_{secrets.token_hex(8)}"
            fh.write(f"{key}<<{d}\n{value}\n{d}\n")
        else:
            fh.write(f"{key}={value}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=CONFIG_FILE)
    parser.add_argument("--github-output", help="arquivo $GITHUB_OUTPUT: grava allow e sentence")
    args = parser.parse_args(argv)
    try:
        with open(args.config, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = None
    try:
        result = read(text)
    except ConfigError as exc:
        print(f"::error file={args.config}::{exc}")
        return 1
    for line, reason in result["ignored"]:
        print(f"::warning file={args.config}::{KEY}: linha ignorada ({reason}): {line}")
    if result["domains"] or result["urls"]:
        print(f"::notice::{KEY}: dominios {' '.join(result['domains']) or '(so a lista fixa)'};"
              f" URLs de entrada {' '.join(result['urls']) or '(nenhuma)'}")
    if args.github_output:
        emit(args.github_output, "allow", allow(result))
        emit(args.github_output, "sentence", sentence(result))
    else:
        print(json.dumps({"domains": result["domains"], "urls": result["urls"],
                          "ignored": [list(i) for i in result["ignored"]],
                          "allow": allow(result), "sentence": sentence(result)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
