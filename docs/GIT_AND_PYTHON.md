# Git local e ambientes Python no Solo-MCP

## Aba Repositórios — o que funciona

A aba **Repositórios** agora consulta o Git **na pasta real do workspace**,
sem pedir o endereço do projeto e sem consultar a internet.

Quando a pasta é um clone Git, mostra:
- Caminho real da raiz Git encontrada
- Branch atual (ou HEAD separado)
- Quantidade de arquivos modificados/rastreados e não rastreados
- Nome do remoto Git escolhido (`origin`, se existir)
- Identificação segura de um remoto GitHub, quando reconhecido

O botão **Abrir repositório no GitHub** só fica disponível se foi encontrado
um remoto com URL do GitHub válido. Ele abre esse endereço no navegador.
A URL usada para abrir **nunca contém senha ou token**, mesmo que o
remoto local tenha credenciais embutidas.

**Verificar Git local** repete a consulta, útil depois de alterações no projeto.
As consultas executam apenas comandos locais de leitura do Git. A aba
**não executa** `clone`, `fetch`, `pull`, `push`, `commit`,
`checkout` ou instalação de extensões.

### Referências manuais continuam sendo apenas anotações

A lista inferior foi renomeada para **Referências cadastradas manualmente**,
e o botão deixa claro **Adicionar referência (não conecta)**.

Isso preserva os registros anteriores e evita confundir uma anotação no
workspace com um clone local ou uma conexão GitHub autenticada. A UI não
faz login, não clona repositórios de contas diferentes e não instala Git.

### Teste real sem modificar seu projeto

1. Abra Solo-MCP → **Workspaces** → workspace `brazil` ou `sumup`.
2. Acesse **Repositórios**. O estado do Git local deve ser consultado.
3. Confira a branch e a contagem de alterações.
4. Se houver remoto GitHub reconhecido, clique em **Abrir repositório no GitHub**.
5. Faça alguma alteração fora do Solo-MCP e clique em **Verificar Git local**.
   A contagem deve refletir as alterações reais.

O resultado depende da pasta cadastrada. Se ela não for um clone Git,
a interface explica que não há repositório local. Isso não impede
acesso aos arquivos daquele workspace.

## Kit essencial independente dos projetos

O Solo-MCP prepara seu próprio Playwright e Chromium no primeiro uso da interface, com autorização do usuário. O kit fica em `~/.local/share/solo-mcp/kit-v1` e é separado do Python principal e dos ambientes de cada workspace. A página **Ferramentas** permite preparar/reparar o kit e verificar se funciona. Não é preciso conhecer pip ou venv para utilizar as inspeções.

O suporte X11 para capturar janelas pode exigir a instalação de pacotes do sistema operacional, com confirmação e autenticação administrativa separadas. [Detalhes da inspeção visual](INSPECTION.md).

## Aba Ambiente — para que serve Podman?

**Podman** executa contêineres: ambientes separados para Python, pacotes,
bibliotecas e testes. No Solo-MCP, as operações existentes
`sandbox_install` e `sandbox_run` usam Podman rootless:

- Instalação de dependências: acesso de rede, mas **sem montar o projeto**,
  com pacotes gravados num volume isolado.
- Execução de testes: sem rede, pasta do projeto somente leitura,
  dependências somente leitura e limites de recursos.

Elas requerem as permissões do workspace e aprovação local.
Não equivalem a uma máquina virtual nem a uma sandbox impenetrável.

**`venv`** cria um ambiente virtual Python que separa bibliotecas do
Python do sistema. Ele é mais simples, mas não restringe o que o código pode
ler ou modificar no computador como um contêiner.

A página **Ferramentas** mantém a verificação do serviço e agora informa
se o Podman está instalado, se roda sem root e se a imagem Python já
está baixada. Ela **não instala** Podman por conta própria.

Quando a aba disser **Podman: não instalado**, o Solo-MCP ainda consegue
ler arquivos, gerenciar workspaces e consultar Git. O recurso de execução
por contêiner só fica disponível depois de preparar Podman.

### Preparação opcional no Linux Mint / Ubuntu

Se você quiser usar os contêineres Python, faça uma vez:

```bash
sudo apt install podman
podman pull docker.io/library/python:3.12-slim
```

Depois, volte à página **Ferramentas** e clique em **Verificar tudo**.
O comando `sudo` instala o programa pela distribuição; **não** execute
o contêiner com `sudo`. Prefira operar com seu usuário normal (rootless).

Esta versão ainda não oferece um instalador gráfico de bibliotecas Python.
A funcionalidade está no executor do Solo-MCP, com aprovação local, e sua
primeira execução deve ser validada no computador real.

## Limites intencionais

Git local e Podman são funções distintas: o Git mostra o estado do código,
e o Podman prepara a execução de Python. Nada é sincronizado ou executado
automaticamente só porque um workspace foi selecionado.

Priorizamos **detectar → entender → validar** antes de acrescentar
operações remotas que alteram código ou instalam software.
