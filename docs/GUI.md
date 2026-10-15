# Aplicativo desktop Solo

O aplicativo reúne **Início, Workspaces, Aprovações, Ferramentas,
Configurações e Como funciona** em uma janela. Os dados existentes continuam
em `~/.config/solo-mcp/`; a migração não altera permissões ou compartilha contexto.

## Instalar e abrir

No Linux, abra **Solo-MCP.desktop** pelo gerenciador de arquivos. Se o Linux
solicitar, marque o arquivo como confiável / “Permitir iniciar”. Você também
pode abrir `install.sh` e escolher executar. Uma alternativa para a instalação inicial é
`./install.sh` na pasta clonada. A preparação registra **Solo** no menu de
aplicativos. As próximas aberturas são pelo ícone, com `Terminal=false`.

O caminho da cópia instalada fica no atalho. Se mover o repositório, execute
`install.sh` novamente para atualizar o caminho. Não é necessário terminal
para abrir, criar workspaces, salvar contexto, instalar ferramentas ou gerenciar
o serviço após essa preparação.

A janela usa **Python 3 + PyGObject + GTK 3 + WebKitGTK 4.1**. HTML, CSS,
JavaScript e ícones são distribuídos localmente, sem CDN, build de frontend,
Node, Electron ou servidor HTTP na aplicação de produção.

| Sistema | Componentes da interface |
| --- | --- |
| Debian / Ubuntu | `python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 xdg-utils` |
| Fedora | `python3-gobject gtk3 webkit2gtk4.1 xdg-utils` |
| Arch | `python-gobject gtk3 webkit2gtk-4.1 xdg-utils` |

Em Debian/Ubuntu, o primeiro lançamento usa **diálogos nativos GTK3** com a
identidade visual do Solo para apresentar a autorização, o progresso e erros
de instalação. Não depende de Zenity. Se o GTK3 estiver ausente, instale
primeiro `python3-gi` e `gir1.2-gtk-3.0` pelo gerenciador de pacotes; sem GTK
não há interface gráfica disponível para exibir essa etapa. O instalador só
chama `pkexec`/`apt-get` para os pacotes fixos indicados acima e após seu
consentimento. Em outras distribuições, use o gerenciador do sistema.
Versões antigas sem WebKitGTK 4.1 precisam atualizar esse componente. A interface desktop continua sendo Linux; macOS e WSL não
foram validados nesta migração.

**Tkinter não é dependência do aplicativo.** O kit Playwright/Chromium continua
separado da interface e é preparado somente quando o usuário solicita.

## Primeiro uso

1. **Adicionar workspace:** escolha uma pasta de projeto. O nome aceita de
   1 a 50 caracteres; o contador e a mensagem indicam entradas inválidas.
2. **Configurações → Conectar conta pelo navegador:** o GitHub CLI conduz a
   autenticação. Se necessário, instale o componente em Ferramentas. O código
   de acesso aparece nos detalhes da operação, com botão para abrir o GitHub.
3. **Verificar e salvar conexão:** informe `usuario/repositorio`. O aplicativo
   verifica as credenciais, a privacidade e a disponibilidade de Issues antes
   de salvar. O repositório privado de controle é separado do código público.
4. **Ativar serviço:** começa a consulta em segundo plano. A janela pode fechar;
   tarefas sensíveis continuam esperando aprovação local.
5. **Ferramentas → Preparar kit:** baixa Playwright e Chromium no ambiente
   privado do Solo. Mostra progresso real, erro e conclusão.

É possível organizar workspaces e escrever contexto antes de conectar GitHub.
Não há credenciais em JavaScript nem no arquivo de configuração do aplicativo;
o GitHub CLI gerencia a autenticação. A disponibilidade de um cofre de
credenciais depende do ambiente e do próprio `gh`.

## Workspaces

- **Visão geral:** pasta, estado do Git, contexto e próximo passo.
- **Contexto:** editor Markdown, contador de bytes, estado de alterações,
  `Ctrl+S`, confirmação com horário e aviso antes de descartar um rascunho.
  O limite real do backend é **16.000 bytes UTF-8**, não 16.000 caracteres.
- **Repositórios:** consulta Git local sem operações de rede; referências
  adicionais são identificadas como anotações, sem promessa de conexão.
- **Permissões:** descrições das capacidades. Concessões novas exigem revisão;
  remover capacidades não gera uma confirmação adicional. Cada tarefa sensível
  ainda depende de aprovação.

**Workspace padrão** substitui “Tornar ativo”. É apenas a preferência para
comandos locais sem nome explícito. Não modifica permissões, conta GitHub nem
o destino das tarefas remotas. Remover um workspace preserva os arquivos e o
contexto local. Se a pasta tiver sido movida, o contexto continua acessível.

## Aprovações

A fila é consultada a cada 15 segundos enquanto a janela está aberta. Erro de
conexão tem estado próprio: nunca aparece como fila vazia. A prévia mostra o
conteúdo completo da tarefa; capturas e comandos diretos têm explicação
específica. Ao decidir, a ponte consulta novamente a Issue, verifica autor,
privacidade, estado e hash. A interface não concede permissões implicitamente.

A aplicação usa instância única por sessão do usuário. A idempotência entre
clientes CLI e execuções distribuídas ainda segue as limitações do núcleo;
não execute processos `serve` adicionais junto ao serviço.

## Serviço existente e notificações da interface nova

Se o serviço Solo-MCP já estiver **ativo** e apontar para uma instalação
existente, **a interface nova utiliza esse mesmo serviço**. Não é necessário
instalar um segundo serviço, manter o painel antigo aberto ou reparar a
unidade systemd a partir de uma pasta temporária em Downloads. O botão
**Reparar serviço** consulta esse estado e não migra silenciosamente um
serviço ativo nem sobrescreve backups de unidade.

Enquanto a janela unificada estiver aberta e a conexão GitHub funcionando,
a página **Aprovações** atualiza a fila a cada 15 segundos. Ao detectar uma
nova tarefa sensível, o programa tenta emitir **uma notificação do Linux**.
A notificação é complementar: caso o gerenciador de notificações esteja
desativado, as tarefas continuam disponíveis em **Aprovações**. O serviço
de segundo plano permanece independente da janela.

O launcher `launch.py` instala o atalho e os ícones originais em
`~/.local/share/icons/hicolor/`, sem privilégios administrativos. O menu e a
janela usam o ícone próprio do **Solo**. Use esse ícone para iniciar a janela; o terminal não é obrigatório.
Se o código for extraído em `Downloads`, o atalho aponta para essa pasta;
não mova nem apague a pasta enquanto ela for usada pelo atalho. Para uma
instalação permanente, coloque o aplicativo numa pasta estável antes de
registrar o atalho.

## Ferramentas

| Recurso | Papel | Preparação |
| --- | --- | --- |
| WebKitGTK | Interface desktop | Componentes do Linux, no primeiro lançamento |
| GitHub CLI | Autenticação | Instalação guiada opcional com Polkit |
| Playwright + Chromium | Inspeção de páginas locais | Kit privado, com progresso e reparo |
| Podman | Ambientes Python isolados | Opcional, instalação guiada em Debian/Ubuntu |
| x11-utils + ImageMagick | Captura de uma janela | Opcional; exige sessão X11 |
| python3-venv | Criação do kit Python | Instalação guiada se ausente |

“Pacotes instalados” e “captura disponível” são estados diferentes. No Wayland,
instalar ferramentas X11 não habilita a captura nativa. A inspeção web continua
utilizável. A instalação de Podman não garante que ele já esteja configurado:
**Verificar funcionamento** testa o modo rootless e a imagem Python.

## Validação e desenvolvimento

```sh
python3 -m unittest discover -s tests -v
# Com GTK/WebKitGTK e uma sessão gráfica, ou Xvfb:
SOLO_MCP_GUI_TESTS=1 /usr/bin/python3 -m unittest discover -s tests -p test_ui.py -v
# Prévia de desenvolvimento, apenas com projetos temporários:
python3 tools/preview.py
```

A prévia HTTP de desenvolvimento não serve a configuração do usuário e bloqueia
autenticação, instalação, serviço e tarefas remotas. A janela real usa uma ponte
nativa restrita, sem porta aberta. CSP bloqueia scripts remotos, frames e objetos;
a navegação fica restrita ao documento local e links externos são selecionados
pelo backend. Não adicione avaliações de JavaScript provenientes de conteúdo
remoto ou comandos arbitrários à ponte.

Os aliases CLI `python3 solo_mcp.py manager` e `desktop` abrem o novo aplicativo.
O autostart antigo do Solo-MCP pode ser migrado em Configurações. Não há segunda
janela Tkinter mantida como dependência oculta.
