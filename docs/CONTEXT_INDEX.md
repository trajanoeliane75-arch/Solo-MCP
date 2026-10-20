# Solo Context — busca local no código

Ação de leitura `context_search` para encontrar trechos de código sem transferir
o projeto inteiro pelo GitHub. Não requer Ollama, TensorFlow, GPU ou serviços
externos; usa apenas SQLite FTS5 da biblioteca padrão Python.

## Exemplo para o ChatGPT

Crie uma Issue no repositório privado de controle com o corpo:

```text
SOLO_MCP_TASK_V1
{"version":1,"workspace":"speedynote-mint","action":"context_search","query":"pen stroke selection cursor","limit":8}
```

O Solo indexa os arquivos autorizados somente quando essa ação é recebida,
reutiliza os arquivos inalterados, remove entradas de arquivos apagados e
retorna até 12 trechos com `path`, `line_start`, `line_end` e `excerpt`.
O número `limit` é opcional (padrão 8). Pesquisas combinam termos por OR
e classificam relevância com BM25. É busca lexical, **não reconhecimento
semântico**: use palavras presentes no código ou variantes em inglês.

## Privacidade e limites

- Exige a permissão `read` do workspace. Não exige `terminal`, `write`
  nem `share_context`; não lê o arquivo privado `CONTEXT.md` do Solo.
- O banco local fica em `~/.local/state/solo-mcp/context-indexes/` ou
  `$XDG_STATE_HOME/solo-mcp/context-indexes/`, com permissões 0600.
- Não percorre links simbólicos de diretório nem lê arquivos simbólicos;
  ignora pastas ocultas, Git, node_modules, build, venv, cache, dist e
  diretórios conhecidos de segredos, além de extensões não permitidas.
- Indexa apenas arquivos de código e documentação até 96 KB cada, com limites
  de 1.600 arquivos e 16 MB de leitura por consulta; o resultado informa se
  a varredura foi truncada.
- A consulta não executa o código encontrado e não concede novos direitos.
- **Atenção:** nomes ignorados e uma substituição simples de padrões não
  garantem proteção contra segredos embutidos no código. Revise o conteúdo
  do workspace antes de autorizar acesso remoto de leitura. Trechos retornados
  são publicados no repositório privado de Issues, onde permanecem no histórico.
- Não há serviço adicional, monitoração de arquivos nem consumo recorrente
  de CPU. Cada pesquisa faz uma verificação incremental dos arquivos.

### Futuro

Um índice de símbolos com Tree-sitter e um seletor de testes relevantes
podem usar esta base. Modelos compactos só serão adicionados após medir
a qualidade das buscas e o custo de CPU/memória.
