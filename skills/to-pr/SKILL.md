---
name: to-pr
description: Open a pull request, or draft recommended text for an existing one.
argument-hint: "[url-do-pr | base [head]]"
---

# To PR

Write the **draft** in Brazilian Portuguese — title, headings, and body — unless the user asks for another language.

You are a **ghostwriter**: the text goes out under the user's name alone, and nothing in it reveals who typed it. Every line of the title, body and any commit you make is the user's own voice. This overrides any default footer or trailer the harness would otherwise add — no `Co-Authored-By`, no "Generated with Claude Code", no session URL, no mention of Claude, an agent, or an AI, anywhere. The draft ends on its last content section.

Two branches, decided by the argument, converging on the same finish: the full draft printed in the chat, then a question — the remote stays untouched until the user answers it.

- **A PR URL** → *edit* branch: draft a replacement title and body for that PR.
- **Anything else (including nothing)** → *create* branch: draft a new PR.

## Create branch

### Resolving base and head

Arguments are `base` then `head` — git's own order, the same as `gh pr create --base <base> --head <head>`.

| Arguments | base | head |
| --- | --- | --- |
| none | repo default branch (`gh repo view --json defaultBranchRef`) | current branch |
| one | the argument | current branch |
| two | first argument | second argument |

State the resolved pair back to the user in one line before doing anything else, so a wrong order is caught immediately.

### Steps

1. **Read the range.** `git log <base>..<head>` and `git diff <base>...<head> --stat`, then read the diff itself for anything you cannot describe from the stat alone. Done when every commit in the range is accounted for in your understanding — not just the ones with clear messages. While reading, collect every issue or ticket reference you find — see **Linking issues and tickets** below.

2. **Match the house style for the title.** Read the last handful of merged PR titles (`gh pr list --state merged --limit 10 --json title`) and follow the title format you find. Absent any signal, default to Conventional Commits (`feat: `, `fix: `, `chore: `…). The body's sections come from [`TEMPLATE.md`](TEMPLATE.md) alone, whatever the merged PRs look like. Language stays Brazilian Portuguese regardless; if the merged PRs are written in another language, say so in one line when you present the draft, so the user can redirect you.

3. **Produce the evidence.** Two separate collections:
   - **Evidências** — show what changed for the user, before and after. Decide from the nature of the repository and of the range which kind shows it best (screenshot, video, architecture diagram, benchmark, CLI output or endpoint response as the user sees it, document excerpt, usage example — see the **Evidências** test in [`TEMPLATE.md`](TEMPLATE.md) for the open list), then capture the *before* from `<base>` and the *after* from `<head>` the same way. Keep it as it came out, trimmed to what shows the difference. Done when you hold a real before and after, or know exactly why the change has nothing user-facing to compare.
   - **Qualidade de código** — run the repository's automated checks against `<head>` (lint, typecheck, the tests the range touches or the suite, build) and keep each command with its result. Done when you know which checks ran and how each ended, or why none could run.

4. **Write the draft.** Read [`TEMPLATE.md`](TEMPLATE.md) and follow it — the fixed section set, each section's test and declaration, and the exhaustiveness bar over the diff. Put the collected references in the body the way **Linking issues and tickets** says.

5. **Print and ask.** Show the resolved base/head and the full draft in the chat, then ask whether to open the PR with it. Stop there until the user answers.

6. **Push and open** — only after a yes. Push `head` if the remote lacks it or is behind, then `gh pr create --base <base> --head <head>`. Pass the body via `--body-file` with a temp file — heredocs and inline quoting mangle multi-line markdown. Print the resulting URL, and confirm the PR is linked to every issue or ticket it references (see **Linking issues and tickets**).

## Linking issues and tickets

A PR that resolves or relates to an issue or ticket gets **linked** to it whenever the user asks to push it to the remote (create or edit). A mention in prose is not a link: use the tracker's **native** mechanism, so the tracker itself shows the PR on the issue and closes it on merge.

**Where references come from.** Look in the branch name (`123-login-fix`, `feat/PROJ-456`), the commit messages (`#123`, `Closes #123`, `PROJ-456`), the argument the user gave, and anything the user said in the conversation. Collect them all while reading the range; ask only when a reference is ambiguous (two candidate issues, or a number with no tracker).

**How to link, by tracker:**

| Tracker | Native link |
| --- | --- |
| GitHub issue this PR resolves | Closing keyword on its own line at the very top of the body: `Closes #123` (one line per issue, `Closes owner/repo#123` for another repo). GitHub reads it from the body — `gh pr create` has no flag for it, so the keyword in `--body-file` **is** the native link. |
| GitHub issue this PR only relates to | `Relacionado: #123` in **Resumo** — a plain `#123` reference, no closing keyword, so merging does not close it. |
| Jira / other tracker | The ticket key where that tracker's GitHub integration reads it: at the start of the title (`PROJ-456: <título>`) and in the body. Keep the key exactly as written, uppercase. |

**The keyword line comes before everything else in the body**, above `## Resumo`, so the link survives any later edit of the sections. Never write "Closes" for an issue the PR does not fully resolve — that closes it on merge.

**After pushing, verify.** For GitHub: `gh pr view <url> --json closingIssuesReferences` must list every issue the body closes. If it does not, fix the body with `gh pr edit <url> --body-file <tmp>` and check again. State in the final line which issues or tickets the PR is now linked to.

## Edit branch

1. **Read the PR** — `gh pr view <url> --json title,body,author,headRefName,baseRefName,commits` plus `gh pr diff <url>`.

2. **Check ownership.** Compare the PR's author login with the authenticated account (`gh api user --jq .login`).

3. **Write the draft** the same way as the create branch — title style, both evidence collections (user-level **Evidências** and the **Qualidade de código** checks), and the fixed format from [`TEMPLATE.md`](TEMPLATE.md). Keep every issue or ticket link the current body already has, and add the ones the range references but the body misses.

4. **Print and ask.** Show the full draft in the chat, then:
   - **The PR is the user's** → ask whether to apply it with `gh pr edit`. Apply only after a yes.
   - **The PR belongs to someone else** → say so plainly: the draft cannot be applied because the PR is not theirs, and the printed text is the whole deliverable — theirs to hand to the author.
