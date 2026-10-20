# Solo Sync — sinais de autorização para o ChatGPT

O Solo usa **GitHub Issues privadas** para transportar tarefas e respostas.
Quando uma operação sensível recebe consentimento na interface gráfica,
ela publica um comentário `SOLO_MCP_STATUS_V1` com o estado `approved`,
antes de executar a operação.

Exemplo:

```text
SOLO_MCP_STATUS_V1
{"version":1,"state":"approved","digest":"<SHA-256>","source":"desktop"}
```

Em seguida, o resultado continua sendo publicado como
`SOLO_MCP_RESULT_V1` e a Issue é fechada. Se a execução falhar,
o comentário de aprovação permanece verdadeiro: houve consentimento,
mas **não significa que a operação foi bem-sucedida**.

Este sinal é apenas informativo. Ele nunca contém código, caminho de
arquivo, credenciais, comandos ou concessão adicional de permissões.
O protocolo de tarefas e os controles de autorização não mudaram.
Falhar ao publicar esse sinal não bloqueia uma operação já autorizada;
o registro de execução SQLite continua impedindo repetição incerta.

## Limitação do ChatGPT

Enquanto a conversa está ativa, o ChatGPT pode consultar os comentários
e acompanhar a aprovação/resultado sem pedir ao usuário para digitar
"já autorizei". Porém, **comentários do GitHub não acordam uma conversa
que já terminou**. Nenhum modelo TinyML, webhook ou comentário sozinho
pode iniciar uma nova mensagem no chat existente.

Para acompanhamento fora de uma conversa ativa, seria necessário
um serviço de notificações ou uma tarefa agendada disponível na plataforma.
Isso é uma funcionalidade separada e não foi implementada aqui.

## Compatibilidade

- No painel gráfico atualizado, o sinal é publicado para autorizações
  concedidas por meio de `solo_desktop.decide`.
- A recusa continua gerando apenas o resultado final `rejected`.
- O executor headless de leitura não envia sinal de aprovação porque não
  solicita autorização.
- O comentário não depende de bibliotecas ML nem de recursos adicionais
  do computador.

O aplicativo `.deb` ou checkout local precisa ser atualizado para esta
versão para publicar os eventos. Atualizar somente o GitHub não altera
o serviço e a janela já instalados.
