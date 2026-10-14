# Solo-MCP

Ponte experimental **ChatGPT ↔ GitHub Issues (privadas) ↔ agente Python local** para trabalhar em arquivos e projetos do próprio computador sem instalar uma API de modelo. Compatível com Linux/macOS e com Windows via WSL (MVP). Apenas biblioteca padrão do Python 3.10+.

> **Importante:** esta versão **não implementa um servidor MCP nativo**. Usa as APIs oficiais do GitHub como transporte. Não substitui Codex/Work, não aumenta limites da assinatura do ChatGPT e não permite que uma conversa rode autonomamente em segundo plano. A IA precisa poder criar Issues no repositório privado e consultar seus comentários.

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

## Instalar

1. Faça um **repositório GitHub separado e PRIVADO** (ex.: `seu-usuario/solo-mcp-control`) apenas para tarefas e logs. **Não use `Solo-MCP` público como controle.**
2. Conecte o repositório privado ao mesmo conector GitHub do ChatGPT. Para contas com GitHub App, selecione-o nas permissões da instalação.
3. No computador (Python 3.10+), clone a ferramenta e rode:

```bash
git clone https://github.com/trajanoeliane75-arch/Solo-MCP.git
cd Solo-MCP
python3 solo_mcp.py init --control SEU_USUARIO/SEU_REPO_PRIVADO
python3 solo_mcp.py add-project --name sumup --path "$HOME/projetos/sumup-solo-lab" --repo trajanoeliane75-arch/sumup-solo-lab
```

4. Instale o GitHub CLI (`gh`) e execute `gh auth login`, **ou** forneça seu token somente pelo ambiente local. A configuração de projetos fica em `~/.config/solo-mcp/config.json` (permissões `0600`), fora do repositório.
5. Inicie o agente:

```bash
python3 solo_mcp.py serve
# ou, para testar uma única consulta:
python3 solo_mcp.py serve --once
```

O processo permanece em espera **sem imprimir "Tarefas executadas: 0"**. Ao encontrar uma nova tarefa, executa-a e mostra o resultado no terminal. A consulta é feita a cada **10 segundos**, por padrão (configure com `--interval 30`, por exemplo). Use `Ctrl+C` para parar. Não precisa de porta exposta nem tunnel. Isso é *polling* automático, não um webhook ou hot reload do código: tarefas novas são detectadas sem reiniciar o agente, mas atualizações do programa ainda exigem `git pull` e reinicialização.

## Serviço em segundo plano no Linux (systemd --user)

Não precisa manter um terminal aberto. Pare o agente interativo com Ctrl+C, atualize o repositório e, após confirmar que `gh auth token` funciona, instale o serviço:

```bash
python3 solo_mcp.py service install
python3 solo_mcp.py service status
python3 solo_mcp.py service logs
```

Se o Linux acusar **"Unit solo-mcp.service has a bad unit file setting"** em uma versão antiga, há um reparo seguro do gerador WorkingDirectory=:

```bash
cd ~/Solo-MCP
git pull --ff-only
python3 -m unittest discover -s tests -v
python3 solo_mcp.py service repair
python3 solo_mcp.py service status
```

O comando repair preserva a configuração dos seus projetos, salva um backup da unidade anterior em ~/.config/systemd/user/solo-mcp.service.bak, recarrega o systemd e reinicia o serviço. O reparo se recusa a substituir uma unidade que não parece pertencer ao Solo-MCP. Se houver erro, envie a saída de `systemctl --user status solo-mcp.service --no-pager` e `python3 solo_mcp.py service logs`. Não use sudo para o serviço do usuário.

O serviço inicia automaticamente ao entrar na sessão Linux e consulta a fila em silêncio a cada 10 segundos, enquanto estiver ativo. Para parar: `python3 solo_mcp.py service stop`; reiniciar: `python3 solo_mcp.py service restart`; remover apenas o serviço: `python3 solo_mcp.py service uninstall`.

**Aprovações em segundo plano:** o serviço **não executa `run` ou `write` sem confirmação**. Essas Issues permanecem abertas, aguardando revisão. Em qualquer terminal, execute:

```bash
cd ~/Solo-MCP
python3 solo_mcp.py pending
python3 solo_mcp.py approve --issue NUMERO
```

Veja a operação apresentada e digite `s` para autorizar ou `n` para rejeitar. Operações de leitura e diagnóstico continuam automáticas. Não rode o serviço e outro `serve` simultaneamente; no estado atual, execução concorrente não tem garantia de exclusão mútua.

Serviços `systemd --user` são executados na sessão do usuário, **não como root**. Fora da sessão, a inicialização após desligar/logoff depende da configuração de *linger* do Linux; não ativamos isso automaticamente. Se o serviço falhar por não encontrar credenciais, verifique `gh auth token` e os logs. O serviço não consegue pedir `S/N` em segundo plano, por isso delegamos essas aprovações ao CLI.

## Painel de aprovações no canto da tela (Linux)

O serviço continua rodando em segundo plano. Abra o **painel gráfico separado**, que fica sempre visível no canto superior direito, lista tarefas pendentes, mostra o JSON completo e apresenta botões **Autorizar** e **Recusar**:

```bash
# Ubuntu/Debian: instale uma vez se necessário
sudo apt install python3-tk xdg-utils libnotify-bin

cd ~/Solo-MCP
python3 solo_mcp.py desktop
```

Para iniciar automaticamente o painel ao fazer login na interface gráfica, instale um arquivo XDG Autostart (sem alterar o serviço):

```bash
python3 solo_mcp.py desktop-autostart install
# para desativar:
python3 solo_mcp.py desktop-autostart uninstall
```

**Autorização:** antes de executar, o painel consulta a Issue novamente e compara a impressão digital SHA-256 da tarefa à prévia aprovada. Se a tarefa foi editada, exige nova revisão. Nenhuma operação sensível é executada silenciosamente. **Aprovações do painel não conferem privilégios administrativos.** O painel deve rodar na sessão gráfica; o serviço systemd --user permanece sem acesso à interface.

Não inicie vários painéis nem outras instâncias do servidor: ainda precisamos implementar bloqueio distribuído e idempotência completa.

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

**Documentos Word:** use LibreOffice Writer no Linux. Para editar DOCX programaticamente, o Python do Solo-MCP precisa ter a biblioteca opcional python-docx instalada. O Solo-MCP não cola texto arbitrariamente em aplicativos de terceiros; DOCX é alterado como documento e pode depois ser aberto no editor.

**Senhas Linux:** o Solo-MCP não solicita, recebe nem armazena senhas de administrador. Uma versão futura poderá chamar diálogos oficiais da sessão via Polkit, com um auxiliar administrativo restrito e auditável. Não use sudo ou pkexec com comandos vindos diretamente do GitHub.

**Dependências e arquivos não confiáveis:** um ambiente virtual Python **NÃO** protege contra malware; comandos pip/npm e scripts instaladores podem ler ou modificar arquivos do usuário. A instalação de bibliotecas e a inspeção de downloads suspeitos exigirão contêineres rootless (Podman), limites de CPU/memória, rede desativada por padrão e acesso mínimo a diretórios. Essa sandbox ainda **não foi implementada**. Evite executar dependências não confiáveis no computador real.

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
| `run` | `argv`: lista, `timeout`: segundos | Pede aprovação local, sem shell, até 90 s |
| `write` | `path`, `content`, `expected_sha256` | Pede aprovação; protege contra sobrescrita inesperada |
| `sandbox_install` | `packages` | Instala bibliotecas Python num volume Podman, sem acesso ao projeto |
| `sandbox_run` | `argv` | Roda Python sem rede e com projeto somente leitura |

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

Licença MIT. Projeto experimental: examine o código e as permissões antes de rodá-lo.
