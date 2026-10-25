---
name: hello-issue
description: Skill de exemplo que valida a integracao entre o marketplace pessoal e um repositorio consumidor. Recebe o numero de um issue e publica nele um comentario confirmando que o plugin foi carregado e executado.
argument-hint: "[numero-do-issue]"
arguments: issue
disable-model-invocation: true
allowed-tools: Bash(gh issue view:*) Bash(gh issue comment:*)
---

# Hello Issue

Skill de **smoke test**. Ela nao analisa nem modifica nada — sua unica funcao e
provar, ponta a ponta, que:

1. o marketplace `samuel-morrissey-ai-workflows` foi resolvido pela action;
2. o plugin `samuel-morrissey-skills` foi instalado;
3. esta skill foi encontrada e invocada;
4. o token do workflow tem permissao de escrita no issue.

Use quando estiver conectando um repositorio novo ao marketplace, antes de
ligar as skills de verdade (`/samuel-morrissey-skills:issue-triage`).

## Argumento

`$issue` — o numero do issue onde o comentario deve ser publicado.

Se `$issue` estiver vazio, **pare e informe** que a skill precisa do numero do
issue. Nao tente adivinhar nem procurar um issue "provavel".

## Passos

1. Confirme que o issue existe e capture titulo e URL:

   ```bash
   gh issue view $issue --json number,title,state,url
   ```

   Se o comando falhar, reporte o erro exato e pare — nao publique comentario.

   O campo `url` tem o formato `https://github.com/<owner>/<repo>/issues/<n>`:
   extraia `owner/repo` dele. **Este comando e a unica fonte de dados da skill.**
   Nao rode `gh repo view`, `git remote`, `echo $GITHUB_REPOSITORY` nem leia
   arquivos — nada disso esta na allowlist, e cada tentativa negada consome um
   turno ate o job morrer em `error_max_turns`.

2. Publique o comentario de confirmacao no issue, exatamente com este corpo
   (substituindo apenas os campos entre colchetes):

   ```markdown
   > *Comentario gerado automaticamente pelo Claude Code.*

   ## ✅ Integracao funcionando

   A skill `hello-issue` do plugin `samuel-morrissey-skills` foi invocada com sucesso
   a partir deste issue.

   | Item | Valor |
   |---|---|
   | Marketplace | `samuel-morrissey-ai-workflows` |
   | Plugin | `samuel-morrissey-skills` |
   | Skill | `hello-issue` |
   | Issue | #[numero] — [titulo] |
   | Repositorio | `[owner/repo]` |

   Nenhuma alteracao foi feita no codigo. Este issue pode ser fechado.
   ```

   Passe o corpo por stdin, para nao criar arquivos no repositorio consumidor
   nem quebrar a formatacao no shell:

   ```bash
   gh issue comment $issue --body-file - <<'EOF'
   ...corpo...
   EOF
   ```

3. Responda ao usuario apenas com a URL do comentario publicado.

## Fora de escopo

- Aplicar labels, fechar o issue ou alterar seu titulo/corpo.
- Ler ou modificar qualquer arquivo do repositorio consumidor.
- Comentar em mais de um issue por invocacao.
