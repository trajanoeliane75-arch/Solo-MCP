# Solo-MCP

Ponte experimental **ChatGPT ↔ GitHub Issues (privadas) ↔ agente Python local** para trabalhar em arquivos e projetos do próprio computador sem instalar uma API de modelo. Compatível com Linux/macOS e com Windows via WSL (MVP). Apenas biblioteca padrão do Python 3.10+.

> **Importante:** esta versão **não implementa um servidor MCP nativo**. Usa as APIs oficiais do GitHub como transporte. Não substitui Codex/Work, não aumenta limites da assinatura do ChatGPT e não permite que uma conversa rode autonomamente em segundo plano. A IA precisa poder criar Issues no repositório privado e consultar seus comentários.

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
| `git_status` | nenhum | Executa `git status --short --branch` |
| `run` | `argv`: lista, `timeout`: segundos | Pede aprovação local, sem shell, até 90 s |
| `write` | `path`, `content`, `expected_sha256` | Pede aprovação; protege contra sobrescrita inesperada |

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
