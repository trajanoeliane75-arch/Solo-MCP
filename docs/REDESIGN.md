# Reconstrução da experiência — outubro de 2026

## Diagnóstico a partir das capturas fornecidas

1. **Entrada / visão geral.** A tela começava numa lista e painel vazio, sem
   indicar o que precisava estar pronto. A nova página inicial apresenta
   primeiros passos, projetos e estados do serviço e da inspeção.
2. **Cadastro.** “Nome curto” não comunicava formato nem limite. O novo diálogo
   agrupa nome e pasta, apresenta contador 0–50 e explica o erro junto ao campo.
3. **Atualização e salvamento.** O hover não confirmava execução. As ações agora
   têm estado em andamento, mensagens de erro, confirmação de conclusão e,
   no contexto, horário de salvamento persistente no editor.
4. **Contexto e compartilhamento.** A captura mostrava uma instrução de CLI para
   um arquivo inexistente. A interface cria o arquivo ao salvar e explica que
   é preciso salvar antes de compartilhar. Alterações não salvas são protegidas.
5. **Preferência local.** “Tornar ativo” sugeria uma conexão ou ativação. O código
   só alterava `active_workspace`; o novo texto é “Definir como padrão”, com
   explicação de seu efeito real.
6. **Ferramentas.** O diagnóstico misturava Podman, Playwright, Chromium e X11.
   Cada recurso agora informa finalidade, requisito, disponibilidade e ação.
   Componentes opcionais não são apresentados como bloqueadores do aplicativo.
7. **Aprovações e pop-ups.** Duas janelas concorrentes e diálogos em cascata
   competiam por atenção. A fila virou uma página da janela principal. Apenas
   decisões de impacto abrem um diálogo de revisão.

A captura de horário acadêmico de julho não pertence ao fluxo do Solo e
não foi usada como referência de produto.

## Direção visual

Superfícies claras, espaçamento consistente, linhas de 1 px, cantos discretos,
texto escuro e verde reservado à ação e ao estado positivo. A navegação fica
menos proeminente que a área de trabalho. Há tema escuro, foco de teclado,
rótulos de formulário, mensagens `aria-live`, diálogo nativo com contenção de
foco e respeito a movimento reduzido. Vermelho é acompanhado de texto, não
usado como único sinal de erro. Ícones Lucide locais, com licença incluída.

Referências consultadas:

- [Linear — A calmer interface for a product in motion, 12/03/2026](https://linear.app/now/behind-the-latest-design-refresh): hierarquia, redução de ruído e estrutura visual discreta.
- [Nielsen Norman Group — Visibility of System Status](https://www.nngroup.com/articles/visibility-system-status/): feedback e comunicação do resultado de ações.
- [Nielsen Norman Group — Empty States](https://www.nngroup.com/articles/empty-state-interface-design/): estados vazios com orientação e próximo passo.
- [WebKitGTK 4.1](https://www.webkitgtk.org/reference/webkit2gtk/stable/index.html): janela nativa com motor do sistema.
- [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry/latest-single/): launcher XDG sem terminal.

## Decisões de implementação

O núcleo Python e o formato dos dados foram preservados. Tkinter saiu das
rotas desktop. A nova camada visual usa arquivos HTML/CSS/JS locais, carregados
em GTK/WebKitGTK. Não há Electron, Node, build de assets, CDN ou servidor HTTP
na aplicação de produção. O desenvolvimento tem uma prévia isolada com dados
temporários, explicitamente sinalizada.

As verificações abrangem regressões de backend, limites UTF-8, permissões,
compartilhamento, estados de jobs, fila de aprovações, troca de repositório,
instalação com comandos fixos e abertura da janela real. Inspeção visual por
si só não comprova conformidade completa de acessibilidade; leitores de tela,
várias distribuições e fluxos reais de autenticação/instalação ainda precisam
de homologação nos ambientes de distribuição.
