# Projetos, permissões e ambientes isolados

Esta versão do Solo continua funcionando por GitHub Issues privadas.
A configuração de projetos fica **somente no computador**:
 `~/.config/solo-mcp/config.json` (permissões 0600).

## 1. Atualizar a instalação já existente

```bash
cd ~/Solo-MCP
git pull --ff-only
python3 -m unittest discover -s tests -v
python3 solo_mcp.py service restart
python3 solo_mcp.py projects
```

Não execute novamente `init`. Seus projetos já cadastrados continuam no arquivo privado. **Por segurança, projetos de versões antigas são migrados logicamente para leitura apenas**, até que você escolha permissões. O serviço passa a recarregar a configuração a cada consulta, e o painel lê a versão mais recente ao aprovar.

## 2. Cadastrar e administrar projetos

```bash
# Ver projetos e direitos atuais
python3 solo_mcp.py projects

# Adicionar outro projeto numa pasta existente
python3 solo_mcp.py add-project \
  --name neural \
  --path "$HOME/projetos/neural" \
  --repo seu-usuario/projeto-neural

# Dar ao projeto SumUp apenas leitura, documentos, apps e sandbox
python3 solo_mcp.py set-permissions \
  --project sumup \
  --allow read,write,desktop,environment

# Se PRECISAR executar comandos sem sandbox, adicione terminal
python3 solo_mcp.py set-permissions \
  --project sumup \
  --allow read,write,terminal,desktop,environment

# Remover cadastro sem tocar nos arquivos locais
python3 solo_mcp.py remove-project --name neural
```

Perfis são por projeto, sem privilégios herdados por outro projeto. `set-permissions` substitui o conjunto completo de direitos daquele projeto; os direitos omitidos serão revogados. Confirmações no painel ou terminal continuam obrigatórias para ações sensíveis.

| Direito | Ações liberadas |
| --- | --- |
| read | list, read, archive_list, git_status, file_info, doc_read |
| write | write, doc_create |
| read + write | doc_append |
| terminal | run |
| desktop | open_app, web_search |
| read + desktop | open_document |
| write + environment | venv_create |
| environment | sandbox_install |
| read + environment | sandbox_run |

**ATENÇÃO: terminal executa comandos diretamente no sistema, com as permissões da conta Linux.** Conceder terminal permite executar Python, que pode escrever em outras pastas do usuário. A política de diretórios não é uma sandbox de sistema operacional e não impede que programas executados diretamente ignorem as permissões lógicas. Não conceda terminal a tarefas não confiáveis.

## 3. Preparar isolamento opcional com Podman (Ubuntu)

Apenas se for usar as novas ações de ambiente:

```bash
# No terminal do próprio usuário (o Linux pedirá autenticação sudo)
sudo apt install podman

# Baixe a imagem oficial previamente, revisando sua origem
podman pull docker.io/library/python:3.12-slim

# Confira se Podman está funcionando SEM sudo, em modo rootless
cd ~/Solo-MCP
python3 solo_mcp.py sandbox-check
```

Na fase `sandbox_install`, o contêiner recebe **rede** e um volume persistente apenas para bibliotecas; **não recebe a pasta do projeto**. Na fase `sandbox_run`, o contêiner recebe **rede desligada** (`--network=none`), o projeto em montagem somente leitura, dependências também somente leitura, capacidades Linux removidas e limites de CPU, RAM e processos. Ambos exigem autorização explícita na janela gráfica e imagem previamente baixada (`--pull=never`).

Isso reduz riscos, mas **não garante isolamento absoluto de malware**: contêineres compartilham o kernel, código malicioso pode explorar vulnerabilidades, bibliotecas instaladas podem conter código hostil, e logs podem expor dados de arquivos visíveis no projeto. Não monte pastas com segredos, não use senhas/tokens na tarefa, não execute como root e prefira uma VM descartável para materiais de alto risco. A imagem está fixada por nome/tag na versão experimental; pinagem por digest é necessária antes de oferecer garantias de reprodução.

A instalação de dependências não modifica o Python global nem a pasta do projeto. Pacotes ficam num volume gerenciado por Podman cujo nome é derivado do projeto. As opções de instalação deliberadamente não incluem links arbitrários nem scripts de instalação via shell.

### Exemplos das tarefas do ChatGPT

Instalar NumPy no volume isolado:

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"sandbox_install","packages":["numpy==2.1.0"]}
```

Testar NumPy sem acesso à rede:

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"sandbox_run","argv":["python3","-c","import numpy; print(numpy.__version__)"]}
```

Essas ações só devem ser testadas depois que você configurar `environment` para o projeto. `sandbox_run` também exige `read`.

## 4. Edição de documentos Word sem colagem manual

Instale o parser de DOCX no Python do sistema por pacote da distribuição (se disponível):

```bash
sudo apt install python3-docx
```

O Linux oferece o LibreOffice Writer como editor visual de arquivos DOCX.

Fluxo seguro para acrescentar texto em arquivo existente:

1. `doc_read`: consultar parágrafos do documento (somente leitura; extrai até 20 KB).
2. `file_info`: consultar o SHA-256 do documento binário (até 64 MiB).
3. `doc_append`: enviar o novo texto e aquele `expected_sha256`, exigindo autorização do usuário. Se o arquivo mudar após a leitura, a operação é rejeitada.

Exemplo de pedido:

```text
SOLO_MCP_TASK_V1
{"version":1,"project":"sumup","action":"file_info","path":"docs/relatorio.docx"}
```

Se o arquivo ainda não existir, `doc_create` requer `expected_sha256: null` e grava um novo DOCX; ele recusa sobrescrita. `doc_append` exige que o documento exista e corresponde ao SHA lido. O pacote python-docx não substitui a interface do Word: preservação de formatação avançada, comentários e outros recursos deve ser validada antes de uso em documentos importantes. Trabalhe em cópias de arquivos críticos.

## 5. O que falta

- Assistente CLI interativo para descobrir pastas sem expor o diretório pessoal inteiro.
- Idempotência e leasing distribuído (evitar dupla execução por múltiplos painéis).
- Auditoria completa e mascaramento de segredos dos resultados.
- Integração Polkit com ações administrativas estritamente definidas.
- Padrões fortes de sandbox para cada linguagem e digest fixo das imagens.
- Servidor MCP nativo opcional; o transporte atual é GitHub Issues.
