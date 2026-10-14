# Interface gráfica do Solo-MCP

A experiência de uso passa a ter duas janelas separadas:

- **Solo-MCP · Aprovações:** painel compacto no canto da tela, sempre visível,
  que recebe pedidos de execução enviados pelo ChatGPT e permite aceitar ou recusar.
- **Solo-MCP · Gerenciar workspaces:** janela principal para cadastro de pastas,
  repositórios vinculados, permissões, contexto e verificação de ambientes.

## Abrir sem usar comandos de gerenciamento

Depois da atualização inicial do código, o painel de aprovações inclui um botão
**Gerenciar**. Clique nele para abrir a janela principal. O painel continua
executando normalmente em sua própria janela.

Na janela principal:

| Aba | Uso |
| --- | --- |
| Visão geral | Exibe a pasta local, workspace selecionado e um botão para abrir a pasta |
| Repositórios | Adiciona e remove associações a repositórios GitHub e aliases de conta |
| Permissões | Altera leitura, escrita, terminal, aplicativos e ambientes por projeto |
| Contexto | Edita o Markdown privado, salva e controla leitura remota explicitamente |
| Ambiente | Consulta status do serviço e disponibilidade de Podman rootless |

À esquerda, **+ Novo** pede um nome e abre o seletor gráfico de pastas,
sem exigir o caminho digitado. Cadastros antigos são mostrados automaticamente.
**Remover cadastro** não apaga diretórios, repositórios ou arquivos do computador.

A janela de gerenciamento não solicita credenciais do GitHub, não faz instalações
e não ativa privilégios administrativos. Ela gerencia apenas a configuração local.

## Atualização inicial (uma vez)

Quando estiver no computador, com a janela de aprovações aberta:

```bash
cd ~/Solo-MCP
git pull --ff-only
python3 -m unittest discover -s tests -v
python3 solo_mcp.py service restart
```

Feche a janela compacta anterior e abra novamente:

```bash
python3 solo_mcp.py desktop
```

A partir daí, clique em **Gerenciar** dentro do próprio painel.
Como alternativa para diagnóstico, a janela principal também abre com:

```bash
python3 solo_mcp.py manager
```

O objetivo é eliminar esses comandos no uso normal; esta etapa de atualização
continua manual, porque a versão anterior instalada não tem atualizador gráfico.

## Como testar diretamente na interface

1. Clique em **Gerenciar**. Selecione o workspace antigo `sumup`.
2. Na aba **Visão geral**, confirme o diretório local que já estava vinculado.
3. Na aba **Repositórios**, teste adicionar um repositório usando
   `proprietario/nome`; um alias de conta é opcional. Não concede acesso a
   repositórios privados nem autentica automaticamente.
4. Na aba **Permissões**, marque as capacidades necessárias e clique em
   **Salvar permissões**; uma confirmação adicional é solicitada.
   Evite habilitar **Terminal direto** enquanto a sandbox não estiver pronta.
5. Na aba **Contexto**, anote o objetivo do projeto e clique em
   **Salvar contexto**. O texto fica no arquivo privado do computador.
   **Permitir leitura remota** permanece desligado até sua ativação explícita.
6. Na aba **Ambiente**, clique em **Verificar serviço e Podman**.
   O botão faz apenas uma consulta, sem instalar bibliotecas.
7. Clique em **+ Novo**, escolha uma pasta de testes existente e veja o
   novo workspace aparecer na lista com **somente leitura**.

As mudanças de permissões são lidas pelo serviço a cada novo ciclo e pelo
painel no momento da aprovação. Não é necessário editar o JSON manualmente.

## Testes automatizados com janela real

O CI executa testes da lógica de projetos em Python 3.10, 3.12 e 3.13 e usa
`xvfb-run` para abrir a interface Tkinter em um ambiente gráfico virtual.
O teste gráfico exercita a seleção de workspace, atualização das permissões,
edição do contexto privado, compartilhamento opt-in e criação por seletor de pasta
(simulado nos testes). Isso **não** substitui uma validação final na área de
trabalho real, com seu gerenciador de janelas e sua distribuição Linux.

Para reproduzir localmente com Xvfb (opcional):

```bash
sudo apt install xvfb xauth python3-tk
cd ~/Solo-MCP
xvfb-run -a env SOLO_MCP_GUI_TESTS=1 \
    python3 -m unittest discover -s tests -p test_manager.py -v
```

A interface ainda não implementa integração nativa com o gerenciador de
credenciais do Linux, múltiplas contas GitHub autenticadas, múltiplos diretórios
montados num único workspace, acesso remoto às opções gráficas ou atualizações
do código por botão. O sistema de transporte atual continua GitHub Issues privadas.
