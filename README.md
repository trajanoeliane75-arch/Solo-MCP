# Solo

[Português](README.md) · [English](README.en.md) · [Releases](https://github.com/trajanoeliane75-arch/Solo-MCP/releases) · [Instalação detalhada](docs/GUI.md)

![Testes](https://github.com/trajanoeliane75-arch/Solo-MCP/actions/workflows/tests.yml/badge.svg)

**Acabaram os créditos de Work ou Codex no meio do projeto? Continue trabalhando no seu próprio Linux.**

O **Solo** permite que o ChatGPT solicite tarefas por meio de um **repositório privado do GitHub**. O programa roda no seu computador, organiza seus workspaces e exige sua autorização para operações sensíveis. Seus arquivos continuam no Linux.

![Demonstração do Solo: início, fila e revisão de uma tarefa](docs/media/solo-demo.gif)

*Prévia da interface com dados fictícios. Nenhuma tarefa real foi executada para produzir essa demonstração.*

<details>
<summary>Capturas individuais da interface</summary>

**Página inicial**

![Página inicial do Solo](docs/media/solo-home.png)

**Fila de aprovações**

![Fila de aprovações](docs/media/solo-approvals.png)

**Revisar e autorizar**

![Modal de autorização](docs/media/solo-review.png)

</details>

## Como funciona

1. **Peça uma tarefa ao ChatGPT.** A conversa precisa estar conectada ao GitHub e criar uma Issue em seu repositório **privado** de controle.
2. **O Solo verifica o pedido** no Linux, respeitando o workspace e as permissões configuradas.
3. **Você revisa as ações sensíveis.** Após sua autorização, o Solo executa o que for permitido e publica o resultado na Issue privada para o ChatGPT consultar.

O Solo **não é um servidor MCP**, não restaura créditos e não contorna limites do plano de IA. Comandos de terminal usam os direitos da sua conta Linux e não são automaticamente isolados: **revise antes de autorizar**.

## Instalação com pacote .deb (Debian/Ubuntu)

A partir do **Solo v1.0.1**, também é possível [baixar o pacote .deb da página de Releases](https://github.com/trajanoeliane75-arch/Solo-MCP/releases/latest). Escolha o arquivo **solo-agent_1.0.1_all.deb** em *Assets*, abra-o no instalador de pacotes da distribuição ou instale-o pelo gerenciador de pacotes:

~~~bash
sudo apt install ./solo-agent_1.0.1_all.deb
~~~

O pacote coloca **Solo** no menu de aplicativos e inclui o ícone original. **Não instala, substitui nem reinicia automaticamente o seu serviço de tarefas.** Se você já usava Solo por ZIP ou git clone, o atalho anterior e o serviço antigo podem coexistir. Revise-os antes de decidir remover o atalho antigo. Seus workspaces e as configurações em ~/.config/solo-mcp/ permanecem intocados na instalação, atualização e remoção do pacote.

Consulte as [instruções detalhadas do .deb](packaging/deb/README.md). Em Fedora e Arch, mantenha o método de instalação pelo código-fonte.

## Instalação rápida

**Requer Linux.** Debian/Ubuntu são o alvo principal (GTK3, WebKitGTK 4.1 e Polkit). Fedora e Arch exigem a preparação manual das dependências; veja [docs/GUI.md](docs/GUI.md). Captura de janelas do computador exige **X11**.

~~~bash
git clone https://github.com/trajanoeliane75-arch/Solo-MCP.git
cd Solo-MCP
./install.sh
~~~

Também é possível abrir **Solo-MCP.desktop** pelo gerenciador de arquivos e autorizar a execução do atalho quando necessário. O nome exibido no menu é **Solo**; nomes internos antigos foram mantidos por compatibilidade.

Depois de abrir, conecte o GitHub em **Configurações**, crie um **repositório privado separado** para tarefas e adicione seu workspace. Veja o [guia de primeiro uso](docs/GUI.md).

> **Licença:** [PolyForm Noncommercial 1.0.0](LICENSE). Código disponível para colaboração e uso não comercial (*source-available*); **não** é open source aprovado pela OSI.

---

## Nova experiência desktop

- **Início:** próximos passos, projetos e estados reais do serviço e das ferramentas.
- **Workspaces:** cadastro por pasta, validação com contador de caracteres e contexto com confirmação de salvamento.
- **Aprovações:** prévia completa, autorização ou recusa na mesma janela.
- **Ferramentas:** preparação guiada de Playwright/Chromium; Podman e captura X11 separados como opcionais.
- **Configurações:** conexão GitHub pelo navegador, controle do serviço e abertura automática no login.

Os dados já existentes são preservados. O contexto continua privado até você
permitir leitura pelas tarefas. Novos workspaces começam somente com leitura.

**[Instalação e guia da interface](docs/GUI.md)** ·
**[Decisões do redesign](docs/REDESIGN.md)** ·
**[Inspeção visual](docs/INSPECTION.md)** ·
**[Git local e Python](docs/GIT_AND_PYTHON.md)**

## Kit de inspeção autogerenciado

Em **Ferramentas → Preparar kit**, o Solo cria seu ambiente privado em
`~/.local/share/solo-mcp/kit-v1`, instala **Playwright 1.63.0**, baixa Chromium
e testa a abertura do navegador. A operação mostra progresso e resultado;
nenhum pacote é instalado no Python dos seus projetos.

A interface usa o WebKit do sistema. Chromium é utilizado apenas pela inspeção
web, quando solicitada. Captura de janelas exige sessão X11 e suas ferramentas;
Podman é opcional para ambientes Python separados. A instalação de componentes
do Linux usa autenticação administrativa do próprio sistema.

## Workspaces persistentes (como áreas de trabalho do Codex)

O Solo separa o **workspace local** (pasta, permissões e contexto)
dos **repositórios GitHub associados**. Um workspace pode apontar para
repositórios de contas diferentes como metadados, sem trocar as credenciais
ou alterar o repositório privado de controle.

```bash
# Lista os projetos já existentes como workspaces
python3 solo_mcp.py workspace list
python3 solo_mcp.py workspace use sumup
python3 solo_mcp.py workspace status

# Cria contexto Markdown privado para projeto antigo
python3 solo_mcp.py workspace context init --name sumup
python3 solo_mcp.py workspace context path --name sumup
```

O contexto fica no computador e **não é enviado automaticamente ao GitHub**:
a leitura remota requer `workspace context share --name sumup --on` e
permissão `read`. Tarefas remotas devem continuar indicando
`project` ou `workspace` explicitamente.

Instruções completas: **[Workspaces, múltiplos repositórios e contexto persistente](docs/WORKSPACES.md)**.

## Projetos e ambientes isolados

Agora há permissões locais por projeto (leitura, escrita, terminal, desktop e ambiente) e um ambiente experimental com Podman rootless para dependências. **Projetos cadastrados nas versões anteriores continuam somente com leitura até você conceder direitos explicitamente.** Isso é intencional.

Para atualizar e conceder permissões somente ao projeto SumUp:

```bash
cd ~/Solo-MCP
git pull --ff-only
python3 solo_mcp.py projects
python3 solo_mcp.py set-permissions --project sumup --allow read,write,desktop,environment
python3 solo_mcp.py service restart
```

O direito `terminal` **não é concedido neste exemplo**: a operação `run` executa Python e outros programas com os direitos da conta Linux, fora de uma sandbox. Adicione `terminal` apenas quando necessário e para tarefas revisadas. A confirmação pelo painel continua sendo exigida.

Documentação completa: **[Permissões, novos projetos, Podman rootless e DOCX](docs/PROJECTS_SANDBOX.md)**.

## Segurança por padrão

- **O repositório deste código pode ser público, mas o repositório de controle tem que ser PRIVADO.** O agente recusa controle público.
- Credenciais só no computador: autentique com `gh auth login` ou defina `SOLO_MCP_TOKEN` em variável de ambiente, **nunca** numa Issue, arquivo versionado, print ou chat. No controle, o token necessita acesso a Issues de leitura e escrita.
- Arquivos locais são restritos aos projetos cadastrados; diretórios de credenciais e `.git` são protegidos. Os arquivos não são enviados automaticamente ao repo público, mas **resultados de leitura aparecem nas Issues privadas**.
- O agente só aceita Issues abertas com primeira linha `SOLO_MCP_TASK_V1`, criadas pelo **proprietário do repositório de controle**.
- Ações de terminal e gravação de arquivos requerem confirmação local **[s/N]** (`S` ou `s` autoriza, `N`, `n` e Enter cancelam). Os comandos são executados sem shell; há lista de programas admitidos, tempo limite e limite de saída.
- Não configure `sudo`, não execute o agente como root e não use um repositório de controle compartilhado com usuários não confiáveis.

## Instalar e usar pelo desktop

Clone o repositório e abra **Solo-MCP.desktop** pelo gerenciador de arquivos
(“Permitir iniciar”, se solicitado), ou abra `install.sh`. Como alternativa, execute
`./install.sh` uma vez na pasta clonada. O instalador prepara a interface e
registra **Solo** no menu do Linux. Depois disso, abra pelo ícone, sem terminal.

Em **Configurações**, conecte sua conta pelo navegador, informe um repositório
privado de controle e clique em **Verificar e salvar conexão**. Ative o serviço
para receber tarefas em segundo plano. Em **Ferramentas**, prepare a inspeção
web ou instale os recursos opcionais de que precisar.

A instalação guiada de componentes do sistema é oferecida em Debian/Ubuntu com
GTK3 e Polkit, com janelas nativas do Solo. Consulte os pacotes para outras distribuições no
[manual desktop](docs/GUI.md). Não é preciso instalar Tkinter, Node ou Electron.

O serviço usa systemd do usuário. A janela fecha sem parar o serviço; operações
sensíveis aguardam sua decisão em **Aprovações**. Não execute outro processo
`serve` junto ao serviço. A instância única da janela não substitui idempotência
distribuída entre clientes CLI e múltiplos agentes.

Os comandos CLI continuam disponíveis para desenvolvimento e diagnóstico:
`service install|start|stop|restart|repair|status|logs`, `pending`, `approve`,
`manager` e `desktop`. Os dois últimos abrem a nova interface.

### Ações gráficas e de desenvolvimento (experimentais)

As seguintes ações podem ser enviadas pelo ChatGPT via Issue com corpo SOLO_MCP_TASK_V1. Todas exigem autorização no painel (ou na execução interativa do CLI):

| Ação | Parâmetros | Comportamento |
| --- | --- | --- |
| open_app | app = writer, files ou browser | Abre LibreOffice Writer, gerenciador de arquivos ou navegador |
| web_search | query | Pesquisa no Google com navegador padrão; exemplo: "lojas de capa de celular Recife" |
| open_document | path | Abre um arquivo do projeto com o aplicativo padrão |
| doc_create | path e text, expected_sha256 = null | Cria DOCX sem sobrescrever arquivo existente |
| doc_append | path, text e expected_sha256 | Acrescenta parágrafos ao DOCX e verifica integridade SHA-256 |
| venv_create | path (padrão .venv) | Cria ambiente virtual Python em um projeto autorizado |

**Documentos Word:** use LibreOffice Writer no Linux. Para editar DOCX programaticamente, o Python do Solo precisa ter a biblioteca opcional python-docx instalada. O Solo não cola texto arbitrariamente em aplicativos de terceiros; DOCX é alterado como documento e pode depois ser aberto no editor.

**Senhas Linux:** o Solo-MCP não solicita, recebe nem armazena senhas de administrador. Uma versão futura poderá chamar diálogos oficiais da sessão via Polkit, com um auxiliar administrativo restrito e auditável. Não use sudo ou pkexec com comandos vindos diretamente do GitHub.

**Dependências e arquivos não confiáveis:** um ambiente virtual Python **NÃO** protege contra malware; comandos pip/npm e scripts instaladores podem ler ou modificar arquivos do usuário. A instalação de bibliotecas e a inspeção de downloads suspeitos exigirão contêineres rootless (Podman), limites de CPU/memória, rede desativada por padrão e acesso mínimo a diretórios. Uma primeira sandbox experimental com Podman rootless já está implementada, mas ainda não foi auditada ou validada no computador de todos os usuários. Evite executar dependências não confiáveis fora de um ambiente isolado.

Exemplos do protocolo (somente JSON no corpo da Issue, sem comentários fora dele):

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"web_search","query":"lojas de capa de celular Recife"}
```

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"open_app","app":"writer"}
```

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"venv_create","path":".venv"}
```

## Enviar uma tarefa pelo ChatGPT

Peça ao ChatGPT para criar uma Issue no seu repositório **privado** com este corpo exato (a primeira linha é o marcador):

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"list","path":"."}
```

O agente consulta Issues abertas e, após executar, comenta `SOLO_MCP_RESULT_V1` com JSON e fecha a Issue. O ChatGPT pode então consultar os comentários por meio do conector GitHub e interpretar a saída. Cada tarefa requer ao menos um ciclo de chamada das ferramentas do ChatGPT; não há autonomia infinita entre mensagens.

### Ações disponíveis

| `action` | Parâmetros | Observação |
| --- | --- | --- |
| `list` | `path` (padrão `.`) | Lista até 100 itens |
| `read` | `path` | Lê texto até 20 KB, com proteções para segredos |
| `archive_list` | `path` | Lista conteúdo de ZIP/JAR/AAR sem extrair |
| `file_info` | `path` | Retorna tamanho e SHA-256 de arquivo binário, até 64 MiB |
| `doc_read` | `path` | Extrai texto de DOCX (python-docx opcional) |
| `git_status` | nenhum | Executa `git status --short --branch` |
| `workspace_info` | `workspace` ou `project` | Mostra metadados sem expor o texto de contexto |
| `workspace_context` | `workspace` ou `project` | Lê contexto Markdown somente se compartilhamento explícito estiver ativado |
| `run` | `argv`: lista, `timeout`: segundos | Pede aprovação local, sem shell, até 90 s |
| `write` | `path`, `content`, `expected_sha256` | Pede aprovação; protege contra sobrescrita inesperada |
| `sandbox_install` | `packages` | Instala bibliotecas Python num volume Podman, sem acesso ao projeto |
| `sandbox_run` | `argv` | Roda Python sem rede e com projeto somente leitura |
| `inspect_screen` | `mode: web/window`, `url` (web) | Captura página local Playwright ou janela X11 após aprovação e envia imagem à Issue privada |

Exemplo de comando:

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"run","argv":["git","status","--short"]}
```

**Atenção:** o campo `argv` pode solicitar programas capazes de modificar arquivos (como Python e Git); leia o comando integralmente antes de aprovar. O agente jamais deve executar conteúdo de Issues públicas.

## Próximos passos

- Transportes alternativos a GitHub Issues e servidor MCP nativo (se integrado ao cliente)
- Melhorar confinamento/sandbox dos comandos (a aprovação humana não substitui isolamento)
- Suporte a múltiplos projetos, adapters MCP e ferramentas USB com privilégios mínimos
- Redação automática de dados sensíveis nos logs; paginação e anexos de resultados grandes
- Interface de instalação e gerenciamento de credenciais pelo keyring do SO

## Testes

```bash
python3 -m unittest discover -s tests -v
```

**Licença atual:** [PolyForm Noncommercial 1.0.0](LICENSE). Permite estudo, alterações e redistribuição **para finalidades não comerciais**, preservando créditos. Por restringir uso comercial, o código é **source-available, não open source OSI**. Consulte [Contribuições](CONTRIBUTING.md) para participar do projeto.

Projeto experimental: examine o código e as permissões antes de rodá-lo.
