---
name: evidencias
description: Como capturar evidencias de uso neste repositorio - o que mostrar, como rodar os scripts, qual repositorio usar como alvo, como obter o antes e o que nao fazer. Use antes de capturar saidas para um PR.
---

# Evidencias deste repositorio

Este repositorio nao tem app nem servidor. Ele guarda as skills do plugin
`samuel-morrissey-skills` (`skills/`), os workflows reutilizaveis do fluxo de
issues (`.github/workflows/`) e dois scripts em Python puro (`scripts/`). A
evidencia de uma mudanca aqui e **saida de comando** ou **trecho de texto**,
nunca print de tela.

## Evidencia ideal

Depende do que a mudanca toca:

- **`scripts/doctor.py`**: o relatorio de `doctor check` contra um
  repositorio real, colado como saiu. Com `--json` quando a mudanca e no
  formato do relatorio; sem `--json` quando e na mensagem de um item. Corte
  para os itens que a mudanca afeta.
- **`scripts/sub_tasks.py`**: a saida de `stack`, `plan`, `status` ou `base`
  para um issue pai real deste repositorio, ou de um consumidor com
  sub-tasks, como saiu.
- **`scripts/test_doctor.py`**: so quando a mudanca e na propria suite; a
  saida do `unittest` vai em Qualidade de codigo, nao aqui.
- **Uma skill em `skills/`**: o trecho da skill que mudou, antes e depois,
  mais o efeito observavel quando ele existe (ex.: o texto que a skill agora
  produz num issue ou PR de teste). Mudanca so de redacao fica sem evidencia
  de uso e diz isso.
- **Um workflow em `.github/workflows/`**: o trecho do log da run que mostra
  o passo novo ou corrigido, quando ha uma run disponivel; senao, o trecho
  do YAML antes e depois com uma linha dizendo o que o runner passa a fazer.

## Como subir

Nada sobe. Os scripts rodam direto do checkout, com Python 3 da biblioteca
padrao, sem instalar nada:

    python3 -I scripts/doctor.py check samuel-morrissey/ai-workflows     # ~5 s, le o GitHub pelo gh
    python3 -I scripts/doctor.py check samuel-morrissey/ai-workflows --json
    python3 -I scripts/sub_tasks.py status <numero-do-pai>                 # ~3 s
    python3 scripts/test_doctor.py                                         # ~1 s, sem rede

O `doctor` e o `sub_tasks` falam com o GitHub pelo `gh`. No fluxo remoto, o
token do workflow ja esta em `GH_TOKEN` e o repositorio em `GH_REPO`. Esse
token nao lista secrets nem variaveis: os itens `secrets` e `vars` do
`doctor` saem como `manual` no runner, e isso e esperado, nao e defeito.

## Dados e acesso

- Alvo padrao do `doctor`: este proprio repositorio,
  `samuel-morrissey/ai-workflows`. Ele esta configurado e e publico, entao o
  `check` responde com a maioria dos itens em `ok`.
- Para um item que precisa de algo faltando ou divergente, use `--template`
  com um arquivo local alterado, ou `--config-env` com um `.env` temporario
  em `$RUNNER_TEMP`. Nao altere o repositorio alvo para forcar um estado.
- `sub_tasks.py` precisa de um issue pai com sub-issues. Use um que ja
  exista neste repositorio ou em um consumidor publico. Nao crie issues
  para isso.
- Sem seed, sem login, sem variavel de ambiente alem de `GH_TOKEN` e
  `GH_REPO`, que o workflow ja define.

## Antes

`git switch --detach origin/main` no mesmo checkout e rode o mesmo comando.
Os scripts nao tem build nem cache: a troca de branch basta. Volte para a
branch do PR com `git switch -` antes de capturar o depois.

Para `doctor`, o antes e o depois usam o mesmo repositorio alvo e as mesmas
opcoes. Para `sub_tasks`, o mesmo issue pai.

## Limites

- Nunca rode `doctor fix`: ele grava secrets, variaveis, labels, topic e
  abre PR no repositorio alvo. So `check`.
- Nunca rode `sub_tasks.py` com `finish` nem qualquer acao que escreva:
  so `plan`, `stack`, `status` e `base`.
- Nao coloque label em issue de nenhum repositorio (`go`, `needs-triage`,
  `ready-for-agent`...): isso dispara o fluxo inteiro em outro runner.
- Nao abra issue, PR nem comentario em outro repositorio para servir de
  evidencia.
- Nao use `--config-env` apontando para um arquivo com valor real: o
  relatorio imprime nomes, nao valores, mas o arquivo nao deve existir no
  runner.
