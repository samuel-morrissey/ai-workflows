# Brief

> **Skill ainda nao criada:** `issue-discovery` e citada neste arquivo como
> proximo passo, mas ainda nao existe neste plugin. Ao indica-la, avise que
> nao e possivel usar a skill referenciada porque ela ainda nao foi criada.

Formatos do que a triagem escreve depois de investigar o codigo: o **brief
completo**, que vira o corpo de um issue de tipo pontual, e a **leitura de
codigo**, que
vai em comentario de `[MAP]`/`[SPEC]`. A `issue-break-down` usa o mesmo brief
completo no corpo de cada `[SUB-TASK]`, e a `issue-refinement` segue os
mesmos principios no comentario de refinamento.

## Principios

Valem para os dois formatos.

**Duravel.** O issue pode esperar dias ou semanas, e o codigo muda no meio.
Descreva contratos, tipos e comportamentos, com nomes reais de simbolos,
comandos e conceitos. Caminho de arquivo e numero de linha apodrecem: fora.

**Comportamental, nao procedural.** Descreva o que o sistema deve fazer, nao
como implementar. Quem executa explora o codigo de novo e decide a
implementacao sozinho.

- Bom: "O comando `/issue-triage` sem argumento informa que precisa do numero do issue"
- Ruim: "Adicione um if no inicio da funcao principal"

**Criterios de aceite verificaveis, com fronteira nomeada.** Quem executa
precisa saber quando terminou e **onde olhar**. Cada criterio e testavel de
forma independente e nomeia a fronteira (seam) em que o comportamento se
observa sem abrir a implementacao: funcao publica, endpoint, comando, tela.
E nessa fronteira que o `/issue-remote-implement` escreve o teste antes do codigo — por
isso a fronteira e decidida aqui, nao la. Fronteira e fato do codigo: a
triagem a descobre lendo o repositorio, nao pergunta. So vira pergunta
quando e escolha de desenho (expor por HTTP ou por funcao interna? API
publica nova sem forma definida?).

- Bom: "`gh issue list --label ready-for-agent` retorna o issue apos a triagem"
- Bom: "`POST /orders` com cupom expirado responde 422 e nao cria pedido"
- Ruim: "A triagem deve funcionar corretamente"
- Ruim: "A funcao interna `applyCoupon` retorna `null`" (fronteira colada na
  implementacao: qualquer refatoracao quebra o teste)

**Fora de escopo explicito.** O que NAO muda, dito com todas as letras —
evita gold-plating e suposicoes sobre features vizinhas.

## Brief completo (tipos pontuais)

Vira o corpo do issue: e o contrato do `/issue-remote-implement` (os criterios de aceite
do corpo sao o que o agente cobre, com teste na fronteira de cada um) ou o
guia da execucao humana.

**O brief e editavel.** O `/issue-remote-implement` e disparado manualmente e le o corpo
na hora de rodar. Se o humano discorda de uma fronteira, de um criterio ou
do escopo, o gesto normal e editar o brief antes de comentar `/implement` —
nao abrir rodada de perguntas.

A citacao no comeco preserva o **titulo e o texto originais** do issue, na
integra. Com o original registrado ali, o titulo do issue pode ser reescrito
para algo mais claro.

**Executor:** agente por padrao. Humano quando a execucao exige o que o
agente nao tem: acesso externo (dashboard, credencial, servico de terceiro),
teste manual, ou decisao de design tomada durante a execucao.

```markdown
> **<titulo original do issue>**
>
> <texto original do issue, na integra>

**Categoria:** bug / feature / docs / infra / refactor
**Executor:** agente / humano — <se humano, por que em uma frase>

## Contexto
<comportamento atual e como o pedido se relaciona com o codigo: o que ja
existe, contratos e conceitos envolvidos>

## Comportamento esperado
<o que deve acontecer depois da mudanca, especifico em casos e condicoes>

## Casos de borda
<entradas e situacoes limite e o que fazer em cada uma>

## Fora de escopo
<o que NAO entra nesta issue>

## Criterios de aceite
- [ ] <fronteira onde se observa> <comportamento verificavel>
- [ ] <fronteira onde se observa> <comportamento verificavel>
```

### Exemplo bom

```markdown
> **triagem quebrada**
>
> O comando de triagem quebra quando o issue nao existe

**Categoria:** bug
**Executor:** agente

## Contexto
A skill `issue-triage` le o issue com `gh issue view` e segue para os passos
seguintes sem tratar falha do comando. Com numero inexistente, o `gh`
retorna erro e a rodada termina com saida confusa, sem registro no issue.

## Comportamento esperado
Quando `gh issue view` falha, a skill reporta o erro exato ao usuario e
encerra a rodada sem aplicar label nem comentar.

## Casos de borda
- Numero de issue de outro repositorio: mesmo tratamento de falha.
- Issue fechado: nao e falha; segue o fluxo normal de "ja triado".

## Fora de escopo
- Validar o formato do argumento antes de chamar o `gh`.

## Criterios de aceite
- [ ] `/issue-triage 99999` (inexistente) termina com o erro do `gh` reportado
      e nenhuma alteracao no repositorio
- [ ] `/issue-triage <issue fechado>` segue o fluxo de issue ja triado
```

### Exemplo ruim

```markdown
**Resumo:** Corrigir o bug da triagem

A triagem esta quebrada. Olhe o arquivo principal e corrija.
A funcao perto da linha 150 tem o problema.

Arquivos: src/triage/handler.ts (linha 150)
```

Ruim porque: vago ("esta quebrada"), aponta caminho e linha que apodrecem,
nao descreve comportamento atual vs esperado, sem criterios de aceite, sem
fora de escopo.

## Leitura de codigo ([MAP]/[SPEC])

Mapa superficial que adianta a `/issue-discovery` ou o `/issue-refinement`: mostra onde o
pedido toca o codigo atual, sem tentar fechar requisitos — isso e da proxima
etapa.

```markdown
### Leitura do codigo

**O que ja existe:** <comportamento atual que o pedido toca ou estende>
**Conceitos e contratos envolvidos:** <nomes reais: tipos, comandos, fluxos>
**Riscos e pontos de atencao:** <o que pode complicar ou conflitar>
**Em aberto para a proxima etapa:** <lacunas que discovery/refinement fecha>
```
