# Revisão do painel (frontend/index.html + login)

## O que mudou

### Estrutura
- **Uma seção por vez.** As 4 abas antigas, a barra "Central Omnichannel" com 11 botões e os 5 selos do topo viraram uma barra fixa com 6 abas: Escritório, Candidaturas, Radar de vagas, Aprovações, Redes e estúdio e Dossiê. Integrações e Dicas ficam à direita.
- **Escritório como página inicial**, com 4 indicadores clicáveis: candidaturas em andamento, itens aguardando seu aval, vagas no radar e nova candidatura.
- **Radar de vagas em aba própria.** Antes ele ficava no meio da esteira de candidaturas.
- **Endereço por aba** (`#candidaturas`, `#aprovacoes`...). Recarregar a página ou salvar o link abre a aba certa.
- **Barra de status enxuta:** Censura LGPD, Gemini, Ganchos, Aguardando seu aval e **Sair**. Antes não havia botão de logout.
- **Avisos no canto da tela** no lugar dos `alert()`. Eles não travam a página, ficam verdes para sucesso e vermelhos para erro.
- **Estados vazios** com texto explicando o próximo passo em Em andamento, Histórico, Radar e Aprovações.

### Visual
- Um só sistema de componentes: card, campo, botão principal (azul preenchido), secundário, discreto e de perigo.
- Rótulos em frases normais, sem CAIXA ALTA longa e sem emoji em todo botão. Campos com 40px de altura e borda de foco visível.
- Rótulos `<label for>` ligados aos campos e link "Pular para o conteúdo", para quem usa teclado ou leitor de tela.
- Funciona no celular: as abas e os status rolam na horizontal e nada empurra a página para o lado. Antes havia rolagem horizontal no celular.

### Bugs corrigidos
- O clique no mapa do escritório disparava **dois** handlers. Um deles usava escala errada (tiles de 16px num mapa de 8px), então as salas Gerência e Depósito nunca respondiam, e qualquer clique no chão levava para a aba de vagas. Agora existe um handler só: Gerência abre Aprovações, Recepção abre Redes, Contabilidade abre o histórico e Depósito entrevista o Deploy. Clique no chão não faz nada.
- `var(--end)` não existia, e as etapas "VETADO" do histórico ficavam sem cor.

### Segurança do login (servidor_dunder_mifflin.py)
- **Sessão expira** em `PANEL_SESSION_HOURS` horas (padrão 12). Antes o cookie valia para sempre.
- Cookie com `Max-Age` e `Secure` quando o acesso vem por HTTPS (túnel).
- Comparação de usuário e senha em tempo constante, mais 1 segundo de espera após senha errada.
- O formulário não vem mais com "admin" preenchido. Ganhou botão "Mostrar" senha.
- Aviso no terminal quando `PANEL_PASSWORD` ou `PERFECTENSCHLAG_SECRET_KEY` estão com o valor de fábrica.

## O que fazer no `.env`
```
PANEL_PASSWORD=uma-senha-forte
PERFECTENSCHLAG_SECRET_KEY=um-texto-aleatorio-longo
PANEL_SESSION_HOURS=12
```

## Fora do escopo desta revisão
- `frontend/lead_manager.html` e `assistant-to-the-lead-manager/frontend/index.html` (outros painéis).
- O HTML gerado pelo JavaScript nos cards de candidatura e vagas ainda usa estilos inline. Ele herdou os botões novos, mas vale migrar para classes.
- `claudecode_ide.py`: veja o aviso na conversa.

---

# Revisão do backend: currículos e formato de candidatura

## Problemas encontrados
1. **O currículo ia para o recrutador com campos censurados.** O perfil (`perfil_gerente.json`) só tem a versão pública: nome "Gerente Regional (Perfil Público Censurado)", `[EMAIL_PROTEGIDO]`, `[TELEFONE_PROTEGIDO]`, `[EMPRESA CONFIDENCIAL]`, período "Atual" e formação sem instituição nem ano. Nada impedia o envio desses currículos.
2. **O recrutador recebia o texto interno.** O corpo do e-mail era a seção inteira gerada pela IA: diagnóstico de palavras-chave do ATS + currículo + mensagem, tudo colado, sem anexo.
3. **Prompts com persona e tom agressivo.** "Destruir o filtro", "alta letalidade", "Dwight", "perguntas interrogatórias impiedosas" e "dossiê de ataque" contra a empresa vazavam para currículos e para a preparação de entrevista.
4. **Nenhuma avaliação do formato da vaga.** Gupy, LinkedIn, Greenhouse e e-mail eram tratados do mesmo jeito. Com link de plataforma, o painel só abria a página com o currículo na área de transferência.
5. **Se a IA falhasse,** o "plano B" colava o dossiê bruto ("=== DOSSIÊ CURRICULAR OFICIAL DO GERENTE REGIONAL ===") como currículo.
6. **O Dossiê do painel quebrava a geração.** Ele salvava contatos como texto e listas como texto corrido, e o backend espera um dicionário e listas (`contatos.items()` dava erro).
7. **Respostas de recrutador iam para a candidatura errada.** Sem correspondência, o webhook anexava a resposta à primeira candidatura da lista. A palavra "agenda" também virava "entrevista convocada", inclusive em recusas.
8. **A chave do Gemini ia na URL** (`?key=`), que aparece em logs e mensagens de erro.

## O que mudou
- **`agentes/formato_candidatura.py` (novo):** identifica o canal (e-mail, Gupy, LinkedIn, Greenhouse, Lever, Workday, ATS brasileiros, portais, agregadores remotos, issues do GitHub, formulários) e o idioma da vaga. Também extrai o que ela exige (carta, portfólio, pretensão, inglês, teste, vídeo), modalidade, contrato, assunto obrigatório do e-mail e prazo. Mostra os passos de cada plataforma e só libera envio automático quando o canal é e-mail.
- **`agentes/curriculo_profissional.py` (novo):**
  - monta o currículo a partir do perfil, sem inventar nada;
  - faz a checagem de qualidade: bloqueia marcadores, personagens, texto de controle da IA e falta de e-mail, e avisa sobre emojis, tamanho, idioma errado e nomes temáticos;
  - gera o `.docx` de uma coluna, sem dependências.
- **Esteira (`esteira_golden_ticket.py`):**
  - prompt de recrutador sênior com regra de "só fatos do dossiê";
  - 5 seções separadas: diagnóstico (interno), currículo, mensagem, entrevista e acompanhamento;
  - o envio é bloqueado enquanto houver problema;
  - o e-mail sai com nome no remetente, assunto pedido pela vaga, corpo curto e currículo anexado em `.docx`;
  - plataformas viram candidatura manual com passos.
- **Perfil:** os dados reais ficam em `perfil_gerente.local.json`, fora do Git. O painel salva lá, e o `perfil_gerente.json` público continua intacto. A aba Dossiê ganhou campos separados: e-mail, telefone, LinkedIn, experiências com empresa e período, formação e idiomas.
- **Agentes Toby, Recyclops e Auditor:** mantêm o nome no jogo, mas produzem texto profissional. O "dossiê de ataque" virou um briefing de pesquisa da empresa, com perguntas respeitosas ao entrevistador.
- **`.gitignore` (novo):** o Operador Mose roda `git add -A` e `git push`. Perfil local, candidaturas, logs e `.env` agora ficam fora do Git.
- **`testar_geracao.py` (novo):** gera uma candidatura de teste com a sua chave e o seu perfil, sem enviar nada, e salva o `.docx` para você abrir.

## Para os currículos poderem ser enviados
Complete na aba Dossiê: nome, e-mail, telefone, LinkedIn, a empresa e o período (com ano) de cada experiência, e a formação com instituição e ano. Enquanto faltar algo, o card mostra a lista e o envio fica bloqueado.

Revise também o item "automação de qualificação de leads corporativos com proteção anti-bloqueio" do perfil. Um recrutador pode ler isso como contornar regras do WhatsApp, e o sistema avisa quando esse termo aparece.
