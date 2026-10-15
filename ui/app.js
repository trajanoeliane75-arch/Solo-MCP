'use strict';
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = (name, cls = '') => `<img src="icons/${name}.svg" class="${cls}" alt="">`;
const tag = (text, kind = '') => `<span class="tag ${kind}">${esc(text)}</span>`;
const button = (label, action, props = '', kind = '', ico = '') => `<button class="button ${kind}" data-action="${action}" ${props}>${ico ? icon(ico) : ''}${label}</button>`;
const state = {data:null, page:'home', name:null, tab:'overview', detail:null, dirty:false, permissionsDirty:false, connectionDirty:false, tasks:[], queueKnown:false, queueError:'', job:null, finishedJob:null, routeId:0};
const serviceLabel = value => ({active:'Em execução',inactive:'Pausado',failed:'Falha no serviço',activating:'Iniciando',deactivating:'Pausando',unavailable:'Serviço indisponível',unknown:'Não instalado'})[value] || 'Não instalado';
const titles = {home:'Início',workspaces:'Workspaces',approvals:'Aprovações',tools:'Ferramentas',settings:'Configurações',help:'Como funciona'};
let sequence = 0, pending = new Map(), toastTimer, previousFocus, modalAction, modalDismiss, polling = false;

function api(method, params = {}) {
  if (window.webkit?.messageHandlers?.solo) {
    return new Promise((resolve, reject) => {
      const id = ++sequence;
      const timer = setTimeout(() => {pending.delete(id);reject(new Error('A operação demorou mais que o esperado. Verifique o estado antes de tentar novamente.'));}, method === 'choose_folder' ? 135000 : 120000);
      pending.set(id, {resolve,reject,timer});
      window.webkit.messageHandlers.solo.postMessage(JSON.stringify({id,method,params}));
    });
  }
  // Explicit development harness only. Production uses the native bridge above.
  if (location.protocol === 'http:' && ['127.0.0.1','localhost'].includes(location.hostname)) {
    return fetch('/api', {method:'POST',headers:{'Content-Type':'application/json','X-Solo-Preview':'1'},body:JSON.stringify({method,params})})
      .then(r => r.json()).then(r => {if(r.error) throw new Error(r.error); return r.result;});
  }
  return Promise.reject(new Error('Abra o Solo pelo ícone do aplicativo para usar suas funções.'));
}
window.soloResolve = reply => {const p=pending.get(reply.id);if(!p)return;clearTimeout(p.timer);pending.delete(reply.id);reply.error?p.reject(new Error(reply.error)):p.resolve(reply.result);};

function friendlyError(message) {
  const raw = String(message || '');
  if (/expected_sha256|Arquivo mudou durante aprova|Arquivo foi alterado antes da grava/i.test(raw))
    return 'O arquivo foi alterado desde a última verificação. Por segurança, nenhuma informação foi substituída. Atualize e tente novamente.';
  if (/Traceback \(most recent call last\)|(?:^|\n)\s*File "[^\n]+", line \d+|(?:^|\n)\s*(?:RuntimeError|ValueError|OSError|PermissionError|NameError|TypeError):/i.test(raw))
    return 'Não foi possível concluir a operação. Verifique o estado da tarefa e tente novamente.';
  return raw.length > 320 ? 'Não foi possível concluir a operação. Consulte o histórico da tarefa.' : raw;
}
function toast(message, error=false) {
  clearTimeout(toastTimer); const el=$('#toast');el.textContent=message;el.className=error?'error':'';el.hidden=false;
  toastTimer=setTimeout(()=>el.hidden=true,error?8500:4500);
}
function modal(title, description, body, label, action, danger=false, dismiss=null) {
  if ($('#dialog').open) closeModal();
  // A click handler temporarily disables its trigger, which can blur it to body.
  const focused=document.activeElement;
  const approvalReject=$('#approval-dialog[open] [data-action="reject-task"]');
  previousFocus=focused!==document.body ? focused : (approvalReject || focused);
  modalAction=action;modalDismiss=dismiss;
  $('#dialog-content').innerHTML=`<form id="modal-form" novalidate><div class="modal-head"><div><h2 id="dialog-title">${esc(title)}</h2><p>${esc(description)}</p></div><button type="button" class="icon-button" data-action="close-modal" aria-label="Fechar">${icon('x')}</button></div><div class="modal-body">${body}<div id="modal-error" class="modal-error" role="alert"></div></div><div class="modal-footer"><button type="button" class="button ghost" data-action="close-modal">Cancelar</button><button type="submit" id="modal-submit" class="button ${danger?'danger':'primary'}">${esc(label)}</button></div></form>`;
  $('#dialog').showModal(); const focus=$('input:not([readonly]),textarea', $('#dialog')) || (danger ? $('.modal-footer [data-action="close-modal"]') : $('#modal-submit'));focus.focus();
}
function closeModal() {$('#dialog').close();const cb=modalDismiss;modalAction=null;modalDismiss=null;cb?.();previousFocus?.focus();}
function confirmAction(title, body, label, action, danger=false) {modal(title,'',`<div class="modal-copy">${body}</div>`,label,action,danger);}
async function canLeave() {
  if(!state.dirty && !state.permissionsDirty && !state.connectionDirty)return true;
  return new Promise(resolve => {
    modal('Descartar alterações?', 'Você tem alterações que ainda não foram salvas.', '<p class="modal-copy">Volte para salvar ou descarte as alterações para continuar.</p>', 'Descartar alterações', async()=>{state.dirty=false;state.permissionsDirty=false;state.connectionDirty=false;modalDismiss=null;closeModal();resolve(true);}, true, ()=>resolve(false));
  });
}
async function navigate(page, name=null, tab='overview') {
  if (!(await canLeave()))return;
  state.page=page;state.name=name;state.tab=tab;state.detail=null;
  const route=++state.routeId;
  render();$('#main').focus();
  if(page==='workspace') {
    $('#view-body').innerHTML='<div class="loading-state" role="status">Carregando workspace…</div>';
    try {const detail=await api('workspace',{name});if(route!==state.routeId)return;state.detail=detail;renderWorkspaceBody();}
    catch(error) {if(route===state.routeId)$('#view-body').innerHTML=`<div class="note error" role="alert">${esc(friendlyError(error.message))}</div>`;}
  }
  if(page==='approvals')await loadApprovals();
}
async function refreshData() {state.data=await api('state');renderSidebar();}
async function refreshView() {
  if(!(await canLeave()))return;
  await refreshData();
  if(state.page==='workspace'){state.detail=await api('workspace',{name:state.name});}
  if(state.page==='approvals')await loadApprovals();
  render();toast('Atualizado agora. Todas as informações foram consultadas novamente.');
}
function renderSidebar() {
  if(!state.data)return;
  $('#navigation').innerHTML=[['home','house'],['workspaces','folder'],['approvals','shield-check'],['tools','box']].map(([page,ico])=>`<button class="nav-item ${state.page===page||(page==='workspaces'&&state.page==='workspace')?'active':''}" data-action="nav" data-page="${page}" ${state.page===page?'aria-current="page"':''}>${icon(ico)}${titles[page]}${page==='approvals'&&state.queueKnown&&state.tasks.length?`<span class="badge">${state.tasks.length}</span>`:''}</button>`).join('');
  $('#workspace-nav').innerHTML=state.data.workspaces.length?state.data.workspaces.map(w=>`<button class="nav-item workspace-link ${state.name===w.workspace?'active':''}" data-action="workspace" data-name="${esc(w.workspace)}"><span class="workspace-dot">${esc(w.workspace.slice(0,1).toUpperCase())}</span><span class="name">${esc(w.workspace)}</span>${state.data.preferred===w.workspace?'<span class="dot" title="Workspace padrão"></span>':''}</button>`).join(''):'<p class="tiny muted">Suas pastas aparecerão aqui.</p>';
  const active=state.data.tools.service==='active';
  $('#service-status').innerHTML=`<span class="dot ${active?'':'off'}"></span>${active?'Serviço em execução':serviceLabel(state.data.tools.service)}`;
  $$('[data-page="settings"],[data-page="help"]').forEach(el=>el.classList.toggle('active',el.dataset.page===state.page));
  $('#breadcrumb').innerHTML=state.page==='workspace'?`Workspaces ${icon('chevron-right')} <span>${esc(state.name)}</span>`:esc(titles[state.page]);
}
function heading(title, subtitle, actions='', eyebrow='') {return `<div class="page-heading"><div>${eyebrow?`<div class="eyebrow">${eyebrow}</div>`:''}<h1>${esc(title)}</h1><p>${subtitle}</p></div><div class="button-row">${actions}</div></div>`;}
function empty(title, text, action='', ico='folder') {return `<div class="empty"><div class="workspace-icon">${icon(ico)}</div><h2>${esc(title)}</h2><p>${text}</p>${action}</div>`;}
function workspaceRows(items) {return items.map(w=>`<button class="workspace-row" data-action="workspace" data-name="${esc(w.workspace)}"><span class="workspace-icon">${icon('folder')}</span><span class="workspace-info"><strong>${esc(w.workspace)}</strong><p>${esc(w.root)}</p></span><span class="row-meta">${w.context_available?'Contexto salvo':'Sem contexto'}</span>${state.data.preferred===w.workspace?tag('Padrão','good'):!w.folder_available?tag('Pasta indisponível','warning'):''}${icon('chevron-right')}</button>`).join('');}
function render() {
  if(!state.data)return;renderSidebar();
  const views={home:homeView,workspaces:workspacesView,workspace:workspaceView,approvals:approvalsView,tools:toolsView,settings:settingsView,help:helpView};
  $('#main').innerHTML=(views[state.page]||homeView)();
  if(state.page==='workspace'&&state.detail)renderWorkspaceBody();
}
function homeView() {
  const d=state.data, count=d.workspaces.length, steps=[!!d.control_repo,!!count,d.kit.ready], done=steps.filter(Boolean).length;
  const setup=done<3?`<section class="panel setup-panel" aria-label="Primeiros passos"><div><div class="eyebrow">PRIMEIROS PASSOS · ${done} DE 3</div><h2>Um lugar para seus projetos.<br>Você no controle de cada ação.</h2><p>Conecte o GitHub, escolha uma pasta e prepare as ferramentas para começar.</p><div class="progress-track"><div class="progress-fill step-${done}"></div></div></div><ol class="step-list">${[
    ['Conecte seu GitHub','Um repositório privado recebe as tarefas.','settings','Conectar'],
    ['Adicione um workspace','Escolha a pasta de um projeto no computador.','create','Adicionar'],
    ['Prepare a inspeção web','O kit permite analisar páginas locais.','tools','Preparar']
  ].map(([title,text,action,label],i)=>`<li><span class="step-number ${steps[i]?'complete':''}">${steps[i]?icon('check'):i+1}</span><div class="step-copy"><strong>${title}</strong><p>${text}</p></div>${steps[i]?tag('Pronto','good'):button(label,action==='create'?'create':'nav',`data-page="${action}"`,'small')}</li>`).join('')}</ol></section>`:'';
  return heading(count?'Seu trabalho, em um só lugar.':'Bem-vindo ao seu espaço.', 'Organize projetos, preserve decisões e revise o que a IA pode fazer.',button('Novo workspace','create','','primary','plus'),'SEU PAINEL')+setup+
    `<div class="section-heading"><h2>Seus workspaces <span class="muted">${count ? '· '+count : ''}</span></h2>${button('Ver todos','nav','data-page="workspaces"','ghost small','arrow-right')}</div><div class="workspace-list">${count?workspaceRows(d.workspaces.slice(0,4)):empty('Comece com uma pasta','Um workspace reúne a pasta, as permissões e a memória de um projeto.',button('Adicionar meu primeiro workspace','create','','primary','plus'))}</div>
    <div class="summary-grid"><div class="summary-cell"><span>Aprovações</span><strong>${state.queueKnown?state.tasks.length+' pendente'+(state.tasks.length===1?'':'s'):state.queueError?'Conexão indisponível':d.control_repo?'Verificando conexão':'Aguardando conexão'}</strong><p>${state.queueKnown?'Você revisa cada ação sensível.':state.queueError?'Confira a conexão em Configurações.':d.control_repo?'Consultando sua fila no GitHub.':'Configure o GitHub para receber tarefas.'}</p></div><div class="summary-cell"><span>Inspeção web</span><strong>${d.kit.ready?'Pronta para usar':'Preparação pendente'}</strong><p>Playwright + Chromium, em ambiente privado.</p></div><div class="summary-cell"><span>Serviço de tarefas</span><strong>${serviceLabel(d.tools.service)}</strong><p>${d.tools.service==='active'?'Consulta o GitHub em segundo plano.':'Ative quando sua conexão estiver pronta.'}</p></div></div>
    <div class="helper-line">${icon('lock-keyhole')}<span>Seus projetos ficam no computador. Resultados das tarefas podem ser enviados ao seu repositório privado de controle.</span></div>`;
}
function workspacesView() {return heading('Workspaces','Cada projeto com sua pasta, suas permissões e seu contexto.',button('Atualizar','refresh','','','refresh-cw')+button('Novo workspace','create','','primary','plus'))+`<div class="search-wrap">${icon('search')}<label class="sr-only" for="workspace-search">Buscar workspace</label><input id="workspace-search" type="search" placeholder="Buscar por nome ou pasta…"></div><div id="workspace-results" class="workspace-list">${state.data.workspaces.length?workspaceRows(state.data.workspaces):empty('Seu primeiro projeto começa aqui','Adicione uma pasta existente. Seus arquivos continuam onde estão.',button('Adicionar workspace','create','','primary','plus'))}</div>`;}
function workspaceView() {
  const preferred=state.name===state.data.preferred;
  return heading(state.name,'Uma pasta, suas decisões e o acesso que você permite.',button('Abrir pasta','open-folder','','','folder-open')+(preferred?tag('Workspace padrão','good'):button('Definir como padrão','prefer','','','check')))+
    `<div class="tabs" role="tablist" aria-label="Seções do workspace">${[['overview','Visão geral'],['context','Contexto'],['repositories','Repositórios'],['permissions','Permissões']].map(([id,label])=>`<button class="tab ${state.tab===id?'active':''}" role="tab" aria-selected="${state.tab===id}" data-action="tab" data-tab="${id}">${label}</button>`).join('')}</div><section id="view-body" role="tabpanel"></section>`;
}
function renderWorkspaceBody() {
  const w=state.detail;if(!w||!$('#view-body'))return;
  const pages={overview:workspaceOverview,context:contextView,repositories:repositoriesView,permissions:permissionsView};
  $('#view-body').innerHTML=pages[state.tab](w);
  if(state.tab==='context')updateContextCounter();
}
function workspaceOverview(w) {
  return `<div class="two-column"><section class="panel"><div class="panel-head"><h2>Sobre este workspace</h2>${icon('folder')}</div><dl><div class="detail-line"><dt>Pasta do projeto</dt><dd class="path">${esc(w.root)}</dd></div><div class="detail-line"><dt>Repositório local</dt><dd>${w.git.is_repo?`${icon('git-branch')} ${esc(w.git.branch||'Sem branch')} · ${w.git.changed??0} alteração(ões)`:'Nenhum repositório Git encontrado'}</dd></div><div class="detail-line"><dt>Contexto do projeto</dt><dd>${w.context_available?'Salvo no computador':'Ainda não escrito'} ${w.context_shared?tag('Leitura remota permitida','warning'):tag('Privado','good')}</dd></div></dl></section><section class="panel"><div class="eyebrow">PRÓXIMO PASSO</div><h2>${w.context_available?'Mantenha suas decisões por perto.':'Dê memória ao seu projeto.'}</h2><p class="description mt">O contexto é uma nota com o objetivo, as decisões e os próximos passos. Você escolhe se as tarefas da IA podem ler esse texto.</p><div class="mt">${button(w.context_available?'Editar contexto':'Escrever contexto','tab','data-tab="context"','','file-text')}</div></section></div>
    <div class="inset"><h3>O que significa “workspace padrão”?</h3><p>É a preferência usada quando você não indica um workspace nos comandos locais. Tarefas enviadas pela IA sempre precisam informar o nome do projeto. Isso não muda permissões nem conecta contas.</p></div>
    <div class="danger-zone"><div><h3>Remover da lista</h3><p>Remove apenas o cadastro. A pasta e os arquivos do projeto são preservados.</p></div>${button('Remover workspace','remove','','danger','trash-2')}</div>`;
}
function contextView(w) {
  return `<p class="context-intro">Guarde o objetivo do projeto, decisões importantes e próximos passos. Este texto só é enviado em respostas a tarefas se você permitir a leitura remota.</p><section class="panel"><div class="editor-header"><label for="context-editor">Memória do projeto <span class="muted tiny">· Markdown</span></label>${tag(w.context_shared?'Leitura remota permitida':'Somente neste computador',w.context_shared?'warning':'good')}</div><textarea id="context-editor" class="editor" spellcheck="true" aria-describedby="context-count context-help" placeholder="# Objetivo&#10;O que você está construindo?&#10;&#10;## Decisões&#10;O que vale lembrar nas próximas conversas?&#10;&#10;## Próximos passos&#10;- ...">${esc(w.context)}</textarea><div class="field-footer"><span id="context-help">Não inclua senhas ou chaves de acesso.</span><span id="context-count" class="counter"></span></div><div class="save-bar"><span id="save-status" class="save-status" role="status">${w.context_available?'Salvo no computador':'Escreva seu primeiro contexto'}</span><div class="button-row">${button('Usar modelo','context-template','','ghost small')}${button('Salvar contexto','save-context','id="save-context" disabled','primary','check')}</div></div></section>
    <section class="panel"><div class="toggle-row"><div><label for="share-context">Permitir leitura pelas tarefas da IA</label><p>O texto pode aparecer no histórico das Issues privadas de controle. Requer também a permissão de leitura do workspace.</p></div><input class="switch" type="checkbox" id="share-context" ${w.context_shared?'checked':''} aria-label="Permitir leitura do contexto pelas tarefas da IA"></div></section>`;
}
function repositoriesView(w) {
  const g=w.git;
  return `<section class="panel"><div class="panel-head"><div><h2>Git da pasta local</h2><p>Informações detectadas na pasta deste workspace.</p></div>${button('Verificar novamente','git-refresh','','small','refresh-cw')}</div>${g.is_repo?`<div class="summary-grid"><div class="summary-cell"><span>Branch</span><strong>${esc(g.branch||'Sem branch')}</strong></div><div class="summary-cell"><span>Alterados</span><strong>${g.changed??0}</strong></div><div class="summary-cell"><span>Não rastreados</span><strong>${g.untracked??0}</strong></div></div><div class="mt button-row"><span class="path">${esc(g.github_name||'Nenhum remoto GitHub detectado')}</span>${g.github_url?button('Abrir no GitHub','open-repo','','small','arrow-up-right'):''}</div>`:`<div class="note">${esc(g.message||'Esta pasta ainda não contém um repositório Git.')}</div>`}<div class="helper-line">${icon('circle-help')}<span>Esta consulta não faz login, clone, pull ou push. Ela apenas lê o estado do Git local.</span></div></section>
    <section class="panel"><div class="panel-head"><div><h2>Referências do projeto</h2><p>Anotações de repositórios relacionados, inclusive de outras contas.</p></div>${button('Adicionar','link-repo','','small','plus')}</div>${w.repositories.length?`<div class="workspace-list">${w.repositories.map((r,i)=>`<div class="workspace-row"><span class="workspace-info"><strong>${esc(r.full_name)}</strong><p>${esc(r.account||'Sem identificação de conta')}</p></span>${button('Remover','unlink-repo',`data-index="${i}"`,'ghost small','x')}</div>`).join('')}</div>`:'<p class="description">Nenhuma referência adicionada. Use para registrar onde o código ou os projetos relacionados estão.</p>'}<div class="helper-line">${icon('circle-help')}<span>Adicionar uma referência não concede acesso nem conecta uma conta GitHub.</span></div></section>`;
}
const capabilityCopy={read:['Ler arquivos','Consultar arquivos e metadados dentro desta pasta.'],write:['Criar e editar arquivos','Alterações precisam da sua aprovação antes da execução.'],desktop:['Abrir aplicativos e inspecionar telas','Abrir documentos, navegador e capturar telas após sua aprovação.'],environment:['Usar ambientes Python','Criar ambientes e usar contêineres após sua aprovação.'],terminal:['Executar comandos no computador','Executa programas com os direitos da sua conta, fora de um ambiente isolado. Exige revisão cuidadosa.']};
function permissionsView(w) {
  return `<section class="panel"><div class="panel-head"><div><h2>O que a IA pode solicitar</h2><p>Permissões valem apenas para este workspace. Autorizar uma capacidade não aprova as tarefas.</p></div>${icon('shield-check')}</div>${Object.entries(capabilityCopy).map(([key,[label,desc]])=>`<div class="toggle-row"><div><label for="perm-${key}">${label} ${key==='terminal'?tag('Acesso amplo','warning'):''}</label><p>${desc}</p></div><input class="switch permission" type="checkbox" id="perm-${key}" data-key="${key}" ${w.permissions[key]?'checked':''}></div>`).join('')}<div class="save-bar"><span id="permission-status" class="save-status" role="status">Permissões salvas</span>${button('Salvar permissões','save-permissions','id="save-permissions" disabled','primary','check')}</div></section><div class="helper-line">${icon('lock-keyhole')}<span>Novos workspaces começam com leitura permitida. Escrita, comandos e ações em aplicativos continuam exigindo aprovação local.</span></div>`;
}
function toolsView() {
 const d=state.data, nativePackages=!d.tools.native_missing.length, nativeReady=d.kit.native_ready;
 const card=(ico,category,title,text,status,kind,actions,caption='')=>`<article class="panel tool-card"><div class="panel-head">${icon(ico,'tool-icon')}${tag(status,kind)}</div><div class="eyebrow">${category}</div><h2>${title}</h2><p>${text}</p><div class="button-row">${actions}</div>${caption?`<p class="caption">${caption}</p>`:''}</article>`;
 return heading('Prepare seu ambiente.','Instale apenas o que você precisa. O Solo cuida das próprias ferramentas.',button('Verificar tudo','diagnostics','','','refresh-cw'))+
 `<div class="tools-grid">${card('monitor','KIT DE INSPEÇÃO','Inspeção de páginas web','Permite à IA analisar uma página local com captura de tela. Instala Playwright e Chromium em um ambiente privado.',d.kit.ready?'Pronto para usar':'Preparação pendente',d.kit.ready?'good':'warning',button(d.kit.ready?'Reparar kit':'Preparar kit','prepare-kit','',d.kit.ready?'':'primary','download'),'Não altera as bibliotecas dos seus projetos.')}
 ${card('plug','CONEXÃO','GitHub','Recebe as tarefas pelas Issues de um repositório privado. Sua conta é conectada pelo navegador.',d.tools.gh?'Componente instalado':'Componente ausente',d.tools.gh?'good':'warning',d.tools.gh?button('Configurar conexão','nav','data-page="settings"','','arrow-right'):button('Instalar componente','install-tool','data-tool="github"','','download'))}</div>
 <div class="divider-label">RECURSOS OPCIONAIS</div><div class="tools-grid">${card('box','AMBIENTES','Python em contêineres','Podman executa Python e suas dependências em ambientes separados dos projetos.',d.tools.podman?'Instalado':'Não instalado',d.tools.podman?'good':'',d.tools.podman?button('Verificar funcionamento','diagnostics','','','refresh-cw'):button('Instalar Podman','install-tool','data-tool="podman"','','download'),'Opcional. A leitura dos projetos e a inspeção web funcionam sem ele.')}
 ${card('monitor','CAPTURA LINUX','Janelas do computador',nativeReady?'Capture uma janela escolhida por você depois de aprovar a solicitação.':nativePackages?'As ferramentas estão instaladas, mas a captura exige uma sessão X11. A inspeção web continua disponível.':'Instala as ferramentas de captura. Este recurso funciona em sessões X11.',nativeReady?'Disponível':nativePackages?'Requer sessão X11':'Dependências ausentes',nativeReady?'good':'warning',nativeReady?button('Como funciona','nav','data-page="help"','','arrow-right'):nativePackages?button('Entender a limitação','nav','data-page="help"','','circle-help'):button('Instalar suporte X11','prepare-native','','','download'))}</div>
 <div class="inset"><h3>Problema ao preparar o kit?</h3><p>Se o Python do sistema não tiver suporte a ambientes virtuais, instale esse componente e tente novamente.</p><div class="mt">${button('Preparar ambientes Python','install-tool','data-tool="python"','small','download')}</div></div>`;
}
const actionNames={write:'Alterar arquivo',run:'Executar comando',open_app:'Abrir aplicativo',web_search:'Pesquisar na web',open_document:'Abrir documento',doc_create:'Criar documento',doc_append:'Editar documento',venv_create:'Criar ambiente Python',sandbox_install:'Instalar em contêiner',sandbox_run:'Executar em contêiner',inspect_screen:'Capturar tela'};
function approvalsView() {
 const header=heading('Você decide o próximo passo.','Revise a tarefa completa antes de autorizar alterações no seu computador.',button('Atualizar fila','refresh-approvals','','','refresh-cw'));
 if(!state.data.control_repo)return header+`<section class="panel">${empty('Conecte seu repositório de controle','As tarefas que precisam de autorização vão aparecer aqui assim que o GitHub estiver configurado.',button('Configurar conexão','nav','data-page="settings"','primary'),'plug')}</section>`;
 if(state.queueError)return header+`<div class="note error" role="alert"><strong>Não foi possível consultar a fila.</strong><br>${esc(state.queueError)}</div><div class="mt">${button('Ver conexão','nav','data-page="settings"','','plug')}</div>`;
 if(!state.queueKnown)return header+'<div class="loading-state" role="status">Consultando tarefas no GitHub…</div>';
 return header+(state.tasks.length?`<div class="section-heading"><h2>${state.tasks.length} tarefa(s) aguardando sua decisão</h2><p>Atualização automática a cada 15 segundos</p></div><div class="task-list">${state.tasks.map(t=>`<article class="task-row"><span class="workspace-icon">${icon('shield-check')}</span><div class="workspace-info"><span class="number">SOLICITAÇÃO #${t.number}</span><strong>${esc(actionNames[t.task.action]||t.task.action)}</strong><p>${esc(t.task.workspace||t.task.project)}${t.task.path?' · '+esc(t.task.path):''}</p></div>${button('Revisar tarefa','review',`data-number="${t.number}"`,'','arrow-right')}</article>`).join('')}</div>`:`<section class="panel">${empty('Nenhuma aprovação pendente','Quando uma tarefa solicitar uma alteração, você poderá conferir o que será feito e decidir aqui.','','shield-check')}</section>`)+`<div class="helper-line">${icon('lock-keyhole')}<span>Repositório de controle: ${esc(state.data.control_repo)}. A tarefa é verificada novamente antes da execução; mudanças na prévia exigem uma nova revisão.</span></div>`;
}
function settingsView() {
 const d=state.data, active=d.tools.service==='active';
 return heading('Conexões e preferências.','Configure uma vez. Depois, abra o Solo pelo menu de aplicativos.')+
 `<section class="panel settings-form"><div class="panel-head"><h2>Conexão com o GitHub</h2>${tag(d.control_repo?'Repositório configurado':'Configuração pendente',d.control_repo?'good':'warning')}</div><p>O Solo usa Issues privadas para trocar tarefas e resultados com a IA. A conta conectada precisa de acesso a esse repositório.</p><div class="button-row">${button(d.tools.gh?'Conectar conta pelo navegador':'Instalar conexão GitHub',d.tools.gh?'authenticate':'install-tool','data-tool="github"','','plug')}${button('Criar repositório privado','external','data-target="new_control"','ghost small','arrow-up-right')}</div><form id="connection-form" class="mt"><div class="field"><label for="control-repo">Repositório privado de controle</label><input id="control-repo" type="text" value="${esc(d.control_repo)}" placeholder="seu-usuario/solo-controle" autocomplete="off" required aria-describedby="repo-help"><div class="field-footer"><span id="repo-help">Use um repositório privado separado do código público.</span></div></div>${button('Verificar e salvar conexão','connect','','primary','check')}</form></section>
 <section class="panel settings-form"><div class="panel-head"><h2>Serviço em segundo plano</h2>${tag(serviceLabel(d.tools.service),active?'good':d.tools.service==='failed'?'error':'')}</div><p>Consulta novas tarefas no GitHub mesmo com a janela fechada. Ações sensíveis continuam aguardando aprovação no aplicativo.</p><div class="button-row">${button(active?'Pausar serviço':'Ativar serviço','service',`data-service="${active?'stop':d.tools.service==='inactive'?'start':'install'}"`,'',''+(active?'box':'plug'))}${button('Reparar serviço','service','data-service="repair"','ghost small','refresh-cw')}</div><div class="toggle-row mt"><div><label for="autostart">Abrir o aplicativo ao entrar no Linux</label><p>Deixa a janela disponível para revisar aprovações.</p></div><input class="switch" id="autostart" type="checkbox" ${d.autostart?'checked':''}></div></section>
 <section class="panel settings-form"><h2>Configuração local</h2><p class="path mt">${esc(d.config_path)}</p><span class="tiny muted">Workspaces e permissões existentes são mantidos. Credenciais são gerenciadas pelo GitHub CLI.</span></section>`;
}
function helpView() {
 return heading('Uma ponte para o seu computador.','Entenda o que acontece entre o seu pedido e uma ação no projeto.')+
 `<section class="panel"><h2>Como uma tarefa chega até você</h2><div class="flow"><div><span class="step-number">1</span><h3>Você pede à IA</h3><p>A conversa precisa ter acesso ao GitHub e criar uma Issue no seu repositório privado de controle.</p></div><div><span class="step-number">2</span><h3>O serviço recebe</h3><p>O Solo consulta as Issues. Leituras permitidas são atendidas; ações sensíveis ficam na fila.</p></div><div><span class="step-number">3</span><h3>Você revisa e decide</h3><p>Abra Aprovações, leia a tarefa e autorize ou recuse. O resultado volta para a mesma Issue.</p></div></div><div class="note">Esta versão usa GitHub Issues como transporte. Ainda não é um servidor do protocolo MCP e não torna a conversa autônoma.</div></section>
 <div class="help-block"><h2>Workspace, contexto e repositório</h2><p><strong>Workspace</strong> é uma pasta local com permissões próprias. <strong>Contexto</strong> é a nota que preserva decisões do projeto. <strong>Repositório de controle</strong> é o canal privado que recebe tarefas — ele é diferente das referências de código de cada projeto.</p></div>
 <div class="help-block"><h2>Primeira tarefa</h2><p>Depois de configurar a conexão e ativar o serviço, peça à IA para criar uma Issue privada com o conteúdo abaixo. Troque o nome pelo workspace desejado.</p><pre>${esc('SOLO_MCP_TASK_V1\n'+JSON.stringify({version:1,workspace:state.data.preferred||state.data.workspaces[0]?.workspace||'meu-projeto',action:'list',path:'.'},null,2))}</pre><p>Essa tarefa lista os arquivos permitidos. Ela exige a permissão de leitura e não precisa de aprovação adicional.</p></div>
 <div class="help-block"><h2>Por que a captura de janelas exige X11?</h2><p>O capturador atual usa ferramentas X11. No Wayland, instalar essas ferramentas não habilita a captura. Você pode continuar usando a inspeção web, que abre sua própria sessão do Chromium.</p></div>
 <div class="help-block"><h2>Instalação e dados</h2><p>A interface usa Python 3, PyGObject, GTK 3 e WebKitGTK 4.1 do sistema. Não precisa de Tkinter, Node ou Electron. Em Debian/Ubuntu, a preparação é guiada pelo instalador. Em Fedora: python3-gobject, gtk3 e webkit2gtk4.1. Em Arch: python-gobject, gtk3 e webkit2gtk-4.1.</p></div>
 <div class="mt">${button('Documentação do projeto','external','data-target="docs"','','arrow-up-right')}</div>`;
}
function createDialog() {
 modal('Novo workspace','Escolha uma pasta existente para organizar seu projeto.',`<div class="field"><label for="workspace-name">Nome do workspace</label><input id="workspace-name" type="text" autocomplete="off" placeholder="meu-projeto" aria-describedby="name-help name-count"><div class="field-footer"><span id="name-help">Letras sem acento, números, hífen e sublinhado.</span><span id="name-count" class="counter" aria-live="polite">0 / 50</span></div></div><div class="field"><label for="workspace-folder">Pasta do projeto</label><div class="input-row"><input id="workspace-folder" type="text" placeholder="Escolha a pasta do projeto" aria-describedby="folder-help"><button type="button" class="button" data-action="choose-folder">Escolher…</button></div><div class="field-footer"><span id="folder-help">Seus arquivos continuam nessa pasta.</span></div></div><div class="note">O workspace começa com leitura permitida. Outras permissões podem ser configuradas depois.</div>`,'Criar workspace',async()=>{
   const name=$('#workspace-name').value.trim(),folder=$('#workspace-folder').value.trim();
   if(!validName(name)||!folder)throw new Error('Revise o nome e escolha uma pasta.');
   await api('create_workspace',{name,folder});closeModal();await refreshData();await navigate('workspace',name);toast('Workspace criado. Agora você pode adicionar contexto ou ajustar permissões.');
 });validateCreate();
}
const validName=name=>/^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$/.test(name);
function validateCreate() {
 if(!$('#workspace-name'))return;const raw=$('#workspace-name').value,name=raw.trim(),n=[...raw].length;
 const invalid=n>50||(raw.length>0&&!validName(name));
 $('#name-count').textContent=`${n} / 50`;$('#name-count').classList.toggle('invalid',invalid);$('#workspace-name').setAttribute('aria-invalid',String(invalid));
 $('#name-help').textContent=n>50?'O nome ultrapassou o limite de 50 caracteres.':invalid?'Comece com letra ou número. Use apenas letras sem acento, números, hífen ou sublinhado.':'Letras sem acento, números, hífen e sublinhado.';
 $('#name-help').classList.toggle('invalid',invalid);$('#modal-submit').disabled=!validName(name)||n>50||!$('#workspace-folder').value.trim();
}
function updateContextCounter() {
 const editor=$('#context-editor');if(!editor)return;const size=new TextEncoder().encode(editor.value).length;
 const invalid=size>16000||editor.value.includes('\0');$('#context-count').textContent=`${size.toLocaleString('pt-BR')} / 16.000 bytes`;
 $('#context-count').classList.toggle('invalid',invalid);editor.setAttribute('aria-invalid',String(invalid));
 $('#save-context').disabled=invalid||size===0||!state.dirty;
 if(invalid)$('#save-status').textContent='O contexto ultrapassa 16 KB ou contém um caractere inválido.';
 else if(state.dirty)$('#save-status').textContent='Alterações não salvas · Ctrl + S para salvar';
}
async function saveContext() {
 const editor=$('#context-editor');if(!editor)return;const content=editor.value,name=state.name;
 $('#save-context').disabled=true;$('#save-status').textContent='Salvando…';
 try {
   await api('save_context',{name,content});
   state.detail.context=content;state.detail.context_available=true;
   state.dirty=editor.value!==content;
   $('#save-status').textContent=state.dirty?'Há novas alterações não salvas':'Salvo no computador às '+new Date().toLocaleTimeString('pt-BR',{hour:'2-digit',minute:'2-digit'});
   updateContextCounter();await refreshData();toast('Contexto salvo no computador.');
 }catch(error){$('#save-status').textContent='Não foi possível salvar. Seu texto continua no editor.';updateContextCounter();throw error;}
}
function permissionValues() {return $$('.permission').filter(e=>e.checked).map(e=>e.dataset.key);}
async function savePermissions() {
 const name=state.name,allowed=permissionValues();
 const apply=async()=>{await api('save_permissions',{name,allowed});state.permissionsDirty=false;state.detail.permissions=Object.fromEntries(Object.keys(capabilityCopy).map(k=>[k,allowed.includes(k)]));if($('#dialog').open)closeModal();await refreshData();renderWorkspaceBody();toast('Permissões salvas para '+name+'.');};
 const added=allowed.filter(k=>!state.detail.permissions[k]);
 if(added.length)confirmAction('Confirmar novas permissões',`<p>Você está permitindo novas capacidades em <strong>${esc(name)}</strong>:</p><ul>${added.map(k=>`<li>${esc(capabilityCopy[k][0])}</li>`).join('')}</ul><p>As tarefas que alteram arquivos ou executam ações ainda precisarão da sua aprovação.</p>${added.includes('terminal')?'<p class="note warning">Comandos executam com os direitos da sua conta, fora de um ambiente isolado.</p>':''}`,'Salvar permissões',apply);
 else await apply();
}
function linkRepoDialog() {
 modal('Adicionar referência','Registre um repositório relacionado a este projeto.',`<div class="field"><label for="repo-name">Repositório GitHub</label><input id="repo-name" type="text" placeholder="usuario/repositorio" required></div><div class="field"><label for="repo-account">Identificação da conta <span class="optional">opcional</span></label><input id="repo-account" type="text" placeholder="Ex.: pessoal ou trabalho"></div><div class="note">Esta referência é uma anotação. Não conecta contas nem concede acesso ao código.</div>`,'Adicionar referência',async()=>{
   await api('link_repository',{name:state.name,repo:$('#repo-name').value.trim(),account:$('#repo-account').value.trim()});closeModal();state.detail=await api('workspace',{name:state.name});renderWorkspaceBody();toast('Referência adicionada.');
 });
}
async function loadApprovals(manual=false) {
 if(polling||!state.data?.control_repo)return;polling=true;
 try {const result=await api('approvals');state.tasks=result.items;state.queueKnown=result.connected;state.queueError='';if(manual)toast('Fila consultada agora. '+result.items.length+' tarefa(s) pendente(s).');}
 catch(error){state.queueKnown=false;state.queueError=error.message; if(manual)toast('Não foi possível consultar a fila. Confira a conexão.',true);}
 finally {polling=false;renderSidebar();if(state.page==='approvals')$('#main').innerHTML=approvalsView();else if(state.page==='home')$('#main').innerHTML=homeView();}
}
function taskSummary(t) {
 const workspace=esc(String(t.workspace||t.project||'não informado'));
 const path=t.path?'<p><strong>Arquivo ou pasta:</strong> '+esc(String(t.path))+'</p>':'';
 const description=typeof t.description==='string'&&t.description.trim()?'<p><strong>Objetivo informado:</strong> '+esc(t.description.slice(0,600))+'</p>':'';
 let action='Esta solicitação precisa da sua aprovação para continuar.';
 switch(t.action) {
  case 'run':{
   const program=Array.isArray(t.argv)&&t.argv.length?String(t.argv[0]):'programa não informado';
   action='Executar o programa <strong>'+esc(program)+'</strong> no workspace <strong>'+workspace+'</strong>. O comando pode ler ou modificar arquivos com os direitos da sua conta no Linux.';break;
  }
  case 'write':action='Criar ou alterar o arquivo indicado. Uma proteção impede substituir uma versão inesperada.';break;
  case 'doc_create':action='Criar um documento dentro da pasta do projeto.';break;
  case 'doc_append':action='Acrescentar texto ao documento existente.';break;
  case 'open_app':action='Abrir um aplicativo na sessão gráfica.';break;
  case 'open_document':action='Abrir o arquivo indicado no aplicativo padrão.';break;
  case 'web_search':action='Abrir uma pesquisa no navegador.';break;
  case 'inspect_screen':action='Capturar uma janela ou página. A imagem pode incluir informações pessoais.';break;
  case 'venv_create':action='Criar um ambiente virtual Python no projeto.';break;
  case 'sandbox_run':action='Executar código num contêiner isolado.';break;
  case 'sandbox_install':action='Instalar dependências dentro de um contêiner.';break;
 }
 return '<section class="modal-copy"><h3>O que esta tarefa fará</h3><p>'+action+'</p>'+description+'<p><strong>Workspace:</strong> '+workspace+'</p>'+path+'<p class="muted">A descrição informa a intenção do pedido, mas não garante o comportamento do código. Consulte os detalhes para comandos desconhecidos.</p></section>';
}
function captureNote(t) {
 if (t.action!=='inspect_screen') return '';
 if (t.mode==='window' && t.window_target==='figma')
   return '<div class="note warning mt">A captura pode revelar informações privadas e será enviada à Issue do controle. O Solo vai localizar automaticamente a janela do Figma; não é necessário clicar em nada.</div>';
 if (t.mode==='window')
   return '<div class="note warning mt">A captura pode revelar informações privadas e será enviada à Issue do controle. Após autorizar, clique na janela desejada quando o cursor mudar.</div>';
 return '<div class="note warning mt">A captura pode revelar informações privadas e será enviada à Issue do controle.</div>';
}
let approvalItem = null;
let approvalReturnTaskNumber = null; // Separate from the generic modal previousFocus.
function reviewTask(number) {
 const item=state.tasks.find(t=>t.number===number);if(!item)return;
 approvalItem=item;
 approvalReturnTaskNumber=number;
 const t=item.task,sensitive=t.action==='inspect_screen';
 const capture=captureNote(t);
 const command=t.action==='run'?'<div class="note warning mt">Este comando não será isolado em contêiner; ele usa os direitos da sua conta Linux.</div>':'';
 const details='<details class="mt"><summary>Ver código e parâmetros técnicos</summary><pre>'+esc(JSON.stringify(t,null,2))+'</pre></details>';
 $('#approval-content').innerHTML='<button class="icon-button approval-close" type="button" data-action="close-review" aria-label="Voltar para aprovações">'+icon('x')+'</button>'+
   '<div class="approval-inner">'+
   '<div class="approval-eyebrow">APROVAÇÃO NECESSÁRIA · SOLICITAÇÃO #'+number+'</div>'+
   '<h1 id="approval-title" class="approval-title">'+esc(actionNames[t.action]||t.action)+'</h1>'+
   '<div class="approval-sub">'+esc(t.workspace||t.project||'')+(t.path?' · '+esc(t.path):'')+'</div>'+
   taskSummary(t)+capture+command+details+
   '<div class="button-row mt">'+
     button('Autorizar e executar','authorize-review','','primary','check')+
     button('Recusar tarefa','reject-task','type="button" data-number="'+number+'" data-digest="'+item.digest+'"','danger','x')+
   '</div>'+
   '<div id="approval-error" class="modal-error" role="alert"></div>'+
   '<p class="helper-line">O resultado é publicado na Issue privada de controle.</p>'+
   '</div>';
 $('#approval-dialog').showModal();
 $('#approval-dialog .approval-close').focus();
}
function closeApproval() {
 const number=approvalReturnTaskNumber;
 if ($('#approval-dialog').open) $('#approval-dialog').close();
 approvalItem=null;
 approvalReturnTaskNumber=null;
 // Resolve a live trigger again: it may have been disabled or re-rendered
 // while opening the dialog, and the generic modal has its own focus state.
 const trigger=$$('[data-action="review"]').find(el=>Number(el.dataset.number)===number && !el.disabled);
 if (trigger) trigger.focus();
 else if ($('#main')) $('#main').focus();
}
async function authorizeReview() {
 if (!approvalItem) return;
 const {number,digest}=approvalItem;
 const result=await api('decision',{number,digest,allow:true});
 closeApproval();await beginJob(result);
}
async function beginJob(result) {if(!result?.job_id)return;state.finishedJob=null;await pollJob();}
async function pollJob() {
 try {
  const job=await api('job_status');if(!job)return;state.job=job;
  if(job.id===state.finishedJob)return;
  const el=$('#job-banner');el.hidden=false;
  const alreadyClosed=job.status==='done' && job.result?.result?.status==='already_closed';
  const line=job.status==='error'?'Não foi possível concluir: '+friendlyError(job.error):alreadyClosed?'Esta tarefa já estava encerrada no GitHub. Nenhum comando foi executado novamente; a fila será atualizada.':job.status==='done'?(job.title==='Verificar ferramentas'?'Verificação concluída. As ferramentas foram verificadas. Clique em Ver detalhes para consultar os resultados.':'Operação concluída. Clique em Ver detalhes para consultar os resultados.'):(job.lines.at(-1)||'Em andamento. Aguarde a conclusão…');
  el.innerHTML=`<div class="job-title"><span>${esc(job.title)}</span>${job.status==='running'?icon('loader-circle','spinning'):`<button class="icon-button" data-action="dismiss-job" aria-label="Fechar resultado">${icon('x')}</button>`}</div><div class="job-line ${job.status==='error'?'invalid':''}">${esc(line)}</div><div class="button-row mt">${button('Ver detalhes','job-details','','small')}${job.title==='Conectar conta GitHub'?button('Abrir GitHub','external','data-target="device"','small','arrow-up-right'):''}</div>`;
  if(job.status!=='running') {
    state.finishedJob=job.id;await refreshData();
    if(job.status==='done'&&job.title==='Verificar conexão'&&state.data.control_repo===state.connectingRepo&&$('#control-repo')?.value.trim()===state.connectingRepo)state.connectionDirty=false;
    if(!state.dirty&&!state.permissionsDirty&&!['workspace','settings'].includes(state.page))render();
    if(state.page==='settings'&&!state.connectionDirty&&!$('#control-repo')?.matches(':focus'))render();
    if(state.page==='approvals')await loadApprovals();
    toast(job.status==='error'?'A operação não foi concluída. Veja os detalhes.':alreadyClosed?'Tarefa já encerrada no GitHub; nada foi repetido.':job.title+' · concluído.',job.status==='error');
  }
 } catch(error) {console.error(error.message);}
}
function jobDetails() {
 const job=state.job;if(!job)return;
 const extra=typeof job.result==='string'?job.result:'';
 modal(job.title,job.status==='running'?'Operação em andamento':job.status==='error'?'Não foi possível concluir':'Operação concluída',`<pre id="job-log">${esc(job.lines.join('\n')+(extra?'\n\n'+extra:'')+(job.error?'\n\n'+friendlyError(job.error):''))}</pre>${job.title==='Conectar conta GitHub'?`<div class="note">Use o código exibido acima para autorizar sua conta.</div><div class="mt">${button('Abrir página de autorização','external','type="button" data-target="device"','','arrow-up-right')}</div>`:''}`,'Fechar',async()=>closeModal());
}
async function execute(action, el) {
 switch(action) {
 case 'nav':return navigate(el.dataset.page);
 case 'workspace':return navigate('workspace',el.dataset.name);
 case 'tab':return navigate('workspace',state.name,el.dataset.tab);
 case 'create':if(await canLeave())createDialog();return;
 case 'refresh':return refreshView();
 case 'close-modal':return closeModal();
 case 'choose-folder':{const folder=await api('choose_folder');if(folder&&$('#workspace-folder')){$('#workspace-folder').value=folder;validateCreate();}return;}
 case 'open-folder':await api('open_folder',{name:state.name});toast('Pasta solicitada ao gerenciador de arquivos.');return;
 case 'prefer':if(!(await canLeave()))return;await api('prefer_workspace',{name:state.name});await refreshData();render();toast('Workspace padrão definido. As permissões continuam iguais.');return;
 case 'remove':return confirmAction('Remover '+state.name+' da lista?',`<p>A pasta e os arquivos do projeto <strong>serão preservados</strong>. O contexto local também será mantido para um eventual novo cadastro.</p><p>O projeto deixará de estar disponível para novas tarefas.</p>`,'Remover da lista',async()=>{await api('remove_workspace',{name:state.name});closeModal();await refreshData();await navigate('workspaces');toast('Cadastro removido. Seus arquivos foram preservados.');},true);
 case 'save-context':return saveContext();
 case 'context-template':{
   const apply=()=>{const editor=$('#context-editor');editor.value=`# Objetivo\n\nDescreva o que este projeto pretende resolver.\n\n## Decisões\n\nRegistre escolhas de arquitetura e restrições.\n\n## Próximos passos\n\n- [ ] Definir a próxima entrega\n`;state.dirty=editor.value!==state.detail.context;updateContextCounter();if($('#dialog').open)closeModal();editor.focus();};
   if($('#context-editor').value.trim())confirmAction('Substituir pelo modelo?','<p>O conteúdo atual do editor será substituído. O arquivo salvo só muda quando você clicar em Salvar contexto.</p>','Usar modelo',apply);else apply();return;
 }
 case 'save-permissions':return savePermissions();
 case 'git-refresh':state.detail=await api('workspace',{name:state.name});renderWorkspaceBody();toast('Estado do Git consultado agora.');return;
 case 'open-repo':return api('open_link',{target:'repository',name:state.name});
 case 'link-repo':return linkRepoDialog();
 case 'unlink-repo':{const r=state.detail.repositories[Number(el.dataset.index)];return confirmAction('Remover referência?',`<p>A anotação <strong>${esc(r.full_name)}</strong> será removida. O repositório no GitHub não será alterado.</p>`,'Remover referência',async()=>{await api('unlink_repository',{name:state.name,repo:r.full_name,account:r.account||''});closeModal();state.detail=await api('workspace',{name:state.name});renderWorkspaceBody();toast('Referência removida.');});}
 case 'prepare-kit':return confirmAction(state.data.kit.ready?'Reparar kit de inspeção?':'Preparar inspeção web?',`<p>O Solo vai baixar <strong>Playwright ${esc(state.data.kit.playwright_version)} e Chromium</strong> para sua própria pasta privada.</p><p>O download pode levar alguns minutos. As bibliotecas dos projetos não serão alteradas.</p>`,state.data.kit.ready?'Reparar kit':'Baixar e preparar',async()=>{const r=await api('prepare_kit',{repair:state.data.kit.ready});closeModal();await beginJob(r);});
 case 'prepare-native':return confirmAction('Instalar suporte a janelas X11?','<p>Serão instalados <strong>x11-utils e ImageMagick</strong>. O Linux pode solicitar autorização administrativa.</p><p>A captura de janelas funciona apenas em uma sessão X11.</p>','Instalar suporte',async()=>{const r=await api('prepare_native');closeModal();await beginJob(r);});
 case 'install-tool':{const tool=el.dataset.tool, names={github:'GitHub CLI (gh)',podman:'Podman',python:'python3-venv'};return confirmAction('Instalar '+names[tool]+'?',`<p>O instalador do Linux adicionará <strong>${names[tool]}</strong>. A autenticação administrativa acontece na janela do sistema.</p>`,'Instalar componente',async()=>{const r=await api('install_tool',{tool});closeModal();await beginJob(r);});}
 case 'diagnostics':return beginJob(await api('diagnostics'));
 case 'authenticate':{const r=await api('authenticate');await beginJob(r);jobDetails();return;}
 case 'connect':state.connectingRepo=$('#control-repo').value.trim();return beginJob(await api('connect',{repo:state.connectingRepo}));
 case 'service':return beginJob(await api('service',{action:el.dataset.service}));
 case 'external':return api('open_link',{target:el.dataset.target});
 case 'refresh-approvals':return loadApprovals(true);
 case 'review':return reviewTask(Number(el.dataset.number));
 case 'close-review':return closeApproval();
 case 'authorize-review':return authorizeReview();
 case 'reject-task':{const number=Number(el.dataset.number),digest=el.dataset.digest;return confirmAction('Recusar tarefa #'+number+'?','<p>A recusa será registrada na Issue privada e a tarefa será encerrada sem execução.</p>','Recusar tarefa',async()=>{const r=await api('decision',{number,digest,allow:false});closeModal();closeApproval();await beginJob(r);},true);}
 case 'job-details':return jobDetails();
 case 'dismiss-job':$('#job-banner').hidden=true;return;
 case 'theme':{const dark=document.documentElement.dataset.theme!=='dark';document.documentElement.dataset.theme=dark?'dark':'light';try{localStorage.setItem('solo-theme',dark?'dark':'light');}catch{}$('#theme-toggle').innerHTML=icon(dark?'sun':'moon');toast(dark?'Tema escuro ativado.':'Tema claro ativado.');return;}
 }
}
document.addEventListener('click',async event=>{
 const el=event.target.closest('[data-action]');if(!el||el.disabled)return;event.preventDefault();
 const keep=el.innerHTML;el.disabled=true;if(el.classList.contains('button'))el.innerHTML=icon('loader-circle','spinning')+'<span>'+esc(el.textContent.trim())+'</span>';
 try{await execute(el.dataset.action,el);}catch(error){if($('#dialog').open&&$('#modal-error'))$('#modal-error').textContent=friendlyError(error.message);else if($('#approval-dialog').open&&$('#approval-error'))$('#approval-error').textContent=friendlyError(error.message);else toast(friendlyError(error.message),true);}
 finally{if(el.isConnected){if(el.dataset.action!=='theme')el.innerHTML=keep;el.disabled=false;if(el.id==='save-context')updateContextCounter();}}
});
document.addEventListener('submit',async event=>{
 event.preventDefault();if(event.target.id==='modal-form'){
   if(!modalAction||$('#modal-submit').disabled)return;
   const el=$('#modal-submit'),label=el.textContent;el.disabled=true;el.textContent='Aguarde…';$('#modal-error').textContent='';
   try{await modalAction();}catch(error){if($('#modal-error'))$('#modal-error').textContent=friendlyError(error.message);}
   finally{if(el.isConnected){el.textContent=label;el.disabled=false;validateCreate();}}
 }else if(event.target.id==='connection-form'){try{state.connectingRepo=$('#control-repo').value.trim();await beginJob(await api('connect',{repo:state.connectingRepo}));}catch(error){toast(friendlyError(error.message),true);}}
});
document.addEventListener('input',event=>{
 const el=event.target;
 if(['workspace-name','workspace-folder'].includes(el.id))validateCreate();
 if(el.id==='control-repo')state.connectionDirty=el.value.trim()!==state.data.control_repo;
 if(el.id==='context-editor'){state.dirty=el.value!==state.detail.context;updateContextCounter();if(!state.dirty)$('#save-status').textContent='Sem alterações para salvar';}
 if(el.id==='workspace-search'){const q=el.value.trim().toLowerCase();const items=state.data.workspaces.filter(w=>(w.workspace+' '+w.root).toLowerCase().includes(q));$('#workspace-results').innerHTML=items.length?workspaceRows(items):empty('Nenhum workspace encontrado','Tente outro nome ou caminho.');}
});
document.addEventListener('change',async event=>{
 const el=event.target;
 if(el.classList.contains('permission')){const allowed=permissionValues();state.permissionsDirty=Object.keys(capabilityCopy).some(k=>allowed.includes(k)!==state.detail.permissions[k]);$('#save-permissions').disabled=!state.permissionsDirty;$('#permission-status').textContent=state.permissionsDirty?'Alterações não salvas':'Permissões salvas';}
 if(el.id==='share-context'){
   const enabled=el.checked;el.checked=!enabled;
   if(state.dirty){toast('Salve suas alterações no contexto antes de mudar o compartilhamento.',true);return;}
   if(enabled&&!state.detail.context_available){toast('Escreva e salve o contexto antes de permitir a leitura.',true);return;}
   const apply=async()=>{await api('share_context',{name:state.name,enabled});state.detail.context_shared=enabled;if($('#dialog').open)closeModal();renderWorkspaceBody();await refreshData();toast(enabled?'Leitura do contexto permitida para tarefas autorizadas.':'Leitura remota desativada.');};
   if(enabled)confirmAction('Permitir leitura do contexto?','<p>Tarefas autorizadas poderão ler o texto e publicar o resultado nas <strong>Issues privadas de controle</strong>. O conteúdo pode permanecer no histórico dessas Issues.</p><p>Revise o texto antes de permitir. Você pode desativar a leitura a qualquer momento.</p>','Permitir leitura',apply);
   else {try{await apply();}catch(error){toast(friendlyError(error.message),true);}}
 }
 if(el.id==='autostart'){const value=el.checked;el.disabled=true;try{await api('autostart',{enabled:value});await refreshData();toast(value?'O aplicativo abrirá ao entrar no Linux.':'Inicialização automática desativada.');}catch(error){el.checked=!value;toast(friendlyError(error.message),true);}finally{el.disabled=false;}}
});
$('#dialog').addEventListener('cancel',event=>{event.preventDefault();closeModal();});
$('#approval-dialog').addEventListener('cancel',event=>{event.preventDefault();closeApproval();});
document.addEventListener('keydown',event=>{
 if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'&&$('#context-editor')&&!$('#dialog').open){event.preventDefault();if(!$('#save-context').disabled)saveContext().catch(e=>toast(e.message,true));}
 if(event.target.matches('[role="tab"]')&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const tabs=$$('[role="tab"]'),i=tabs.indexOf(event.target);const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(i+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();}
});
window.soloRequestClose=async()=>{
 if(state.job?.status==='running'){confirmAction('Uma operação está em andamento','<p>Fechar agora pode interromper a operação. Aguarde a conclusão para sair.</p>','Continuar no aplicativo',async()=>closeModal());return;}
 if(await canLeave())api('close_window').catch(()=>{});
};
window.addEventListener('beforeunload',e=>{if(state.dirty||state.permissionsDirty||state.connectionDirty){e.preventDefault();e.returnValue='';}});
window.addEventListener('solo-route',()=>{if(state.data)navigate(window.soloInitialPage||'home');});
async function initialize() {
 try{const theme=localStorage.getItem('solo-theme');if(theme==='dark'){document.documentElement.dataset.theme='dark';$('#theme-toggle').innerHTML=icon('sun');}}catch{}
 try{
  await refreshData();state.page=window.soloInitialPage||'home';render();
  if(state.data.preview)$('#preview-notice').hidden=false;
  if(state.data.control_repo)loadApprovals();
  setInterval(()=>{if(state.data.control_repo&&state.job?.status!=='running')loadApprovals();},15000);
  setInterval(async()=>{if(state.job?.status==='running'){await pollJob();const log=$('#job-log');if(log&&state.job)log.textContent=state.job.lines.join('\n')+(state.job.error?'\n\n'+state.job.error:'')+(typeof state.job.result==='string'?'\n\n'+state.job.result:'');}},700);
 }catch(error){$('#main').innerHTML=heading('Não foi possível abrir seu espaço.','A configuração local pode precisar de atenção.')+`<div class="note error" role="alert">${esc(friendlyError(error.message))}</div><div class="mt">${button('Tentar novamente','refresh','','primary','refresh-cw')}</div>`;}
}
initialize();
