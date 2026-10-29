// Chat tab, sidebar history and tab switching. Runs entirely against the local server (no external requests).
(() => {
  const el = id => document.getElementById(id);
  const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const J = async (url, opts) => { const r = await fetch(url, opts); const j = await r.json(); if (r.status === 401) { location.reload(); throw new Error('Signed out'); } if (!r.ok) throw new Error(j.error || r.statusText); return j; };
  const ME = window.ME || { name: 'you', kind: 'user' };
  const post = (url, body) => J(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

  // ---------- remember where you were across page refreshes
  let tabNow = 'chat';
  const saveView = () => Store.set('jacobai-view', { tab: tabNow, chat: cur && !cur.incognito && cur.id || null });
  const loadView = () => Store.get('jacobai-view') || {};
  setInterval(saveView, 1500);

  // ---------- tab switching
  window.showTab = name => {
    ['chat', 'music', 'cover', 'library', 'console'].forEach(t => { el('tab-' + t).style.display = t === name ? '' : 'none'; });
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    el('side').classList.remove('open');
    { const t = el('tab-' + name); t.classList.remove('tab-in'); void t.offsetWidth; t.classList.add('tab-in'); }
    tabNow = name; saveView();
    if (name === 'cover') { checkImg(); loadHist(); }
    if (name === 'music') draw();
    if (name === 'library') loadLib();
    if (name === 'console') renderCon();
    if (name === 'chat') { scrollDown(true); el('input').focus(); }
  };
  document.querySelectorAll('.nav button').forEach(b => b.onclick = () => showTab(b.dataset.tab));
  el('menu').onclick = () => el('side').classList.toggle('open');
  el('mnew').onclick = () => newChat(false);
  // tapping the dimmed area closes the drawer on phones
  document.querySelector('.content').addEventListener('click', e => { if (el('side').classList.contains('open')) { el('side').classList.remove('open'); e.preventDefault(); e.stopPropagation(); } }, true);
  // swipe from the left edge opens it, swipe left closes it
  let sx = null, sy = 0;
  document.addEventListener('touchstart', e => { sx = e.touches[0].clientX; sy = e.touches[0].clientY; }, { passive: true });
  document.addEventListener('touchend', e => {
    if (sx === null) return; const dx = e.changedTouches[0].clientX - sx, dy = Math.abs(e.changedTouches[0].clientY - sy);
    if (dy < 60 && innerWidth <= 860) { if (sx < 24 && dx > 70) el('side').classList.add('open'); else if (dx < -70) el('side').classList.remove('open'); }
    sx = null;
  }, { passive: true });

  // ---------- console (live log of what the AI is doing)
  let conLines = [], conLast = 0, conHidden = new Set();
  const fmtT = t => new Date(t * 1000).toTimeString().slice(0, 8);
  const conHtml = filt => conLines.filter(l => !filt || !conHidden.has(l.src)).map(l =>
    `<div class="cl s-${l.src}"><span class="ct">${fmtT(l.t)}</span><span class="cs">${l.src}</span>${esc(l.text)}</div>`).join('');
  function paint(node, html, stick) { const near = node.scrollHeight - node.scrollTop - node.clientHeight < 40; node.innerHTML = html; if (stick || near) node.scrollTop = node.scrollHeight; }
  function renderCon() {
    paint(el('conbig'), conHtml(true), el('conauto').checked);
    paint(el('conmini'), conLines.filter(l => l.src === 'img').slice(-60).map(l => `<div class="cl"><span class="ct">${fmtT(l.t)}</span>${esc(l.text)}</div>`).join(''), true);
  }
  async function pollCon() {
    try {
      const r = await J('/api/console?since=' + conLast);
      if (r.lines.length) { conLines = conLines.concat(r.lines).slice(-3000); conLast = r.last; renderCon(); }
    } catch (e) {}
    setTimeout(pollCon, document.hidden ? 4000 : 1200);
  }
  document.querySelectorAll('.cf').forEach(cb => cb.onchange = () => { cb.checked ? conHidden.delete(cb.value) : conHidden.add(cb.value); renderCon(); });
  el('conclear').onclick = () => { conLines = []; renderCon(); };
  el('concopy').onclick = () => navigator.clipboard && navigator.clipboard.writeText(conLines.filter(l => !conHidden.has(l.src)).map(l => `${fmtT(l.t)} [${l.src}] ${l.text}`).join('\n'));
  pollCon();

  // ---------- markdown (small, safe: everything is escaped first)
  const inline = t => esc(t)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  function blocks(text) {
    const lines = text.split('\n'); let out = '', i = 0, para = [];
    const flush = () => { if (para.length) { out += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; } };
    while (i < lines.length) {
      const l = lines[i];
      let m;
      if (!l.trim()) { flush(); i++; continue; }
      if ((m = l.match(/^(#{1,4})\s+(.*)/))) { flush(); out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; i++; continue; }
      if (/^\s*[-*]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l)) {
        flush(); const ord = /^\s*\d+/.test(l); const re = ord ? /^\s*\d+[.)]\s+/ : /^\s*[-*]\s+/; let items = '';
        while (i < lines.length && re.test(lines[i])) { items += '<li>' + inline(lines[i].replace(re, '')) + '</li>'; i++; }
        out += (ord ? '<ol>' : '<ul>') + items + (ord ? '</ol>' : '</ul>'); continue;
      }
      if (/^>\s?/.test(l)) { flush(); let q = []; while (i < lines.length && /^>\s?/.test(lines[i])) { q.push(lines[i].replace(/^>\s?/, '')); i++; } out += '<blockquote>' + q.map(inline).join('<br>') + '</blockquote>'; continue; }
      if (l.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flush(); const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
        let t = '<table><thead><tr>' + cells(l).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>'; i += 2;
        while (i < lines.length && lines[i].trim().startsWith('|')) { t += '<tr>' + cells(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>'; i++; }
        out += t + '</tbody></table>'; continue;
      }
      para.push(l); i++;
    }
    flush(); return out;
  }
  function md(src) {
    return src.split('```').map((p, i) => {
      if (i % 2) { const nl = p.indexOf('\n'); const lang = (nl < 0 ? '' : p.slice(0, nl)).trim().replace(/[^\w+#.-]/g, ''); const code = (nl < 0 ? '' : p.slice(nl + 1)).replace(/\n$/, ''); return `<div class="codeblk"><div class="codehead"><span>${esc(lang || 'text')}</span><button type="button" class="cp">${ico('copy')}<span>Copy</span></button></div><pre${/^(text|txt|plain|plaintext|markdown|md)?$/i.test(lang) ? ' class="wrap"' : ''}><code>${window.hl ? hl(code, lang) : esc(code)}</code></pre></div>`; }
      return blocks(p);
    }).join('');
  }

  // ---------- state
  let chats = [], cur = { id: null, messages: [], title: 'New chat' }, streaming = false, ctrl = null, attached = null, files = [];
  const S = Store.get('chat-settings') || {};
  const settings = { model: S.model || 'gpt-oss:20b', think: S.think || 'low', tools: S.tools !== false, system: S.system || '' };
  const PF = Object.assign({ name: '', about: '', style: 'default', instr: S.system || '', size: 'm', enter: true, memory: true, web: false, warnheavy: true, speak: false, voice: '' }, Store.get('prefs') || {});
  const savePrefs = () => Store.set('prefs', PF);
  const saveSettings = () => Store.set('chat-settings', settings);

  // ---------- models + status
  let modelLabels = {}, macDown = false, bannerText = '', bannerGone = '';
  // Warnings show as a small toast in the bottom right corner and slide out to the right by themselves after BANNER_MS. They can also be closed with the x or by swiping them right; a closed one stays closed until the message changes.
  const BANNER_MS = 9000; let bannerTimer = null;
  function setBanner(text, force) {
    const b = el('banner');
    if (!text) {   // the condition went away: slide out instead of snapping shut
      const was = bannerText; bannerGone = ''; bannerText = ''; clearTimeout(bannerTimer);
      if (was && b.style.display === 'flex') slideOut(b); else b.style.display = 'none';
      return;
    }
    const changed = text !== bannerText, wasHidden = b.style.display !== 'flex';
    if (changed) { bannerText = text; b.innerHTML = '<span class="btxt"></span><button class="bclose" type="button" aria-label="Dismiss">' + (window.ico ? ico('x') : '&times;') + '</button>'; b.querySelector('.btxt').textContent = text; b.style.transform = ''; b.style.opacity = ''; }
    const show = !(bannerGone === text && !force);
    b.style.display = show ? 'flex' : 'none';
    if (show && (changed || wasHidden || force)) { clearTimeout(bannerTimer); bannerTimer = setTimeout(dismissBanner, BANNER_MS); }
  }
  function slideOut(b) {
    b.style.transition = 'transform .35s cubic-bezier(.4,0,.2,1), opacity .35s ease'; b.style.transform = 'translateX(calc(100% + 40px))'; b.style.opacity = '0';
    clearTimeout(b._hide); b._hide = setTimeout(() => { if (b.style.opacity === '0') b.style.display = 'none'; b.style.transition = ''; b.style.transform = ''; b.style.opacity = ''; }, 360);
  }
  function dismissBanner() { bannerGone = bannerText; clearTimeout(bannerTimer); slideOut(el('banner')); }
  (() => {   // drag it sideways (finger or mouse); past 60px it flies off, otherwise it springs back
    const b = el('banner'); let x0 = null, dx = 0;
    b.addEventListener('click', e => { if (e.target.closest('.bclose')) dismissBanner(); });
    b.addEventListener('pointerdown', e => { if (e.target.closest('.bclose')) return; x0 = e.clientX; dx = 0; b.setPointerCapture(e.pointerId); b.style.transition = 'none'; clearTimeout(bannerTimer); });
    b.addEventListener('pointermove', e => { if (x0 === null) return; dx = Math.max(0, e.clientX - x0); b.style.transform = `translateX(${dx}px)`; b.style.opacity = String(Math.max(.2, 1 - dx / 220)); });
    const end = () => { if (x0 === null) return; x0 = null; if (dx > 60) dismissBanner(); else { b.style.transition = 'transform .2s, opacity .2s'; b.style.transform = ''; b.style.opacity = ''; bannerTimer = setTimeout(dismissBanner, BANNER_MS); } };
    b.addEventListener('pointerup', end); b.addEventListener('pointercancel', end);
  })();
  async function loadModels() {
    try {
      const s = await J('/api/chat/status'); macDown = false;
      setBanner(s.ok ? (s.training && PF.warnheavy !== false ? 'A heavy job (picture editing or training) is running on this Mac. The language model shares its memory, so chatting now will be slow and will slow that job down. For fast chat, wait until it finishes.' : '') : 'Ollama is not running, so there is no language model to chat with. Open the Ollama app (or run "ollama serve") and reload. The Music and Album cover tabs still work.');
      el('stat').innerHTML = (ME.kind === 'guest' ? 'Guest session · ' : 'Signed in · ') + `<span class="dotstat ${s.ok ? 'ok' : 'bad'}" title="${s.ok ? 'Language model connected' : 'Language model offline'}"></span>`;
      modelLabels = Object.fromEntries(s.models.map(m => [m.name, m.label || m.name]));
      const opts = s.models.map(m => `<option value="${m.name}" data-desc="${esc(m.desc || '')}">${m.label || m.name}</option>`).join('');
      if (el('model').innerHTML !== opts) el('model').innerHTML = opts;
      if (!s.models.find(m => m.name === settings.model) && s.models.length) settings.model = s.models[0].name;
      el('model').value = settings.model; syncModelBtn();
    } catch (e) { macDown = true; setBanner("Can't reach your Mac right now. You can still read your saved chats; sending needs the Mac (awake, JacobAI running, same network or VPN).", true); el('stat').innerHTML = '<span class="dotstat bad"></span> Mac unreachable'; }
  }
  el('model').onchange = () => { settings.model = el('model').value; saveSettings(); };
  el('think').value = settings.think; el('think').onchange = () => { settings.think = el('think').value; saveSettings(); };
  el('tools').checked = settings.tools; el('tools').onchange = () => { settings.tools = el('tools').checked; saveSettings(); };

  // ---------- history list
  let listSig = '';
  async function loadList() { const f = await J('/api/chat/list'), sig = JSON.stringify(f) + '|' + (cur && cur.id); if (sig === listSig) return; listSig = sig; chats = f; renderList(); }
  // ---------- projects
  const PROJ = window.PROJ = {
    list: [], active: LS.get('active-project') || '',
    async load() { try { this.list = (await J('/api/projects')).items; } catch (e) {} if (this.active && !this.list.find(p => p.id === this.active)) this.active = ''; syncProj(); },
    name(id) { return (this.list.find(p => p.id === id) || {}).name || ''; },
    set(id) { this.active = id || ''; LS.set('active-project', this.active); syncProj(); renderList(); if (el('tab-library').style.display !== 'none') loadLib(); },
  };
  function menuOf(menu, rows) { menu.innerHTML = ''; for (const [label, id, on] of rows) { const b = document.createElement('button'); b.type = 'button'; b.textContent = label; if (on) b.classList.add('on'); b.dataset.id = id; menu.appendChild(b); } }
  function syncProj() {
    el('projname').textContent = PROJ.name(PROJ.active) || 'All chats';
    menuOf(el('projmenu'), [['All chats', '', !PROJ.active], ...PROJ.list.map(p => [p.name, p.id, p.id === PROJ.active]), ['Manage projects…', '#manage', false]]);
    const tag = el('projtag'); tag.hidden = !PROJ.list.length || !!(cur && cur.incognito);
    const pn = cur && PROJ.name(cur.project); tag.textContent = pn || 'No project'; tag.classList.toggle('on', !!pn);
    menuOf(el('tagmenu'), [['No project', '', !(cur && cur.project)], ...PROJ.list.map(p => [p.name, p.id, !!cur && cur.project === p.id])]);
    el('libscope').textContent = PROJ.active ? 'project: ' + PROJ.name(PROJ.active) : 'your own documents, searchable by the chat models';
  }
  el('projbtn').onclick = e => { e.stopPropagation(); el('projmenu').hidden = !el('projmenu').hidden; };
  el('projmenu').onclick = e => { const b = e.target.closest('button'); if (!b) return; el('projmenu').hidden = true; if (b.dataset.id === '#manage') return window.openSettings && window.openSettings('projects'); PROJ.set(b.dataset.id); };
  el('projtag').onclick = e => { e.stopPropagation(); el('tagmenu').hidden = !el('tagmenu').hidden; };
  el('tagmenu').onclick = async e => { const b = e.target.closest('button'); if (!b) return; el('tagmenu').hidden = true; cur.project = b.dataset.id || undefined; if (cur.id) await post('/api/chat/project', { id: cur.id, project: b.dataset.id }); syncProj(); loadList(); };
  document.addEventListener('click', e => { if (!e.target.closest('.projrow')) el('projmenu').hidden = true; if (!e.target.closest('.tagwrap')) el('tagmenu').hidden = true; });
  function renderList() {
    const day = 86400, now = Date.now() / 1000, groups = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] };
    for (const c of chats.filter(x => !PROJ.active || x.project === PROJ.active)) { const d = now - c.updated; (d < day ? groups.Today : d < 2 * day ? groups.Yesterday : d < 7 * day ? groups['Previous 7 days'] : groups.Older).push(c); }
    const h = el('hist'); h.innerHTML = '';
    for (const [name, list] of Object.entries(groups)) {
      if (!list.length) continue;
      h.insertAdjacentHTML('beforeend', `<h4><span>${name}</span>${h.children.length ? '' : `<button type="button" class="hnew" title="New chat">${ico('compose')}</button>`}</h4>`);
      h.querySelector('.hnew') && (h.querySelector('.hnew').onclick = e => { e.stopPropagation(); newChat(false); });
      for (const c of list) {
        const r = document.createElement('div'); r.className = 'row' + (cur.id === c.id ? ' on' : '');
        r.innerHTML = `<span title="${esc(c.title)}">${esc(c.title)}</span><button data-a="r" title="Rename">${ico('pencil')}</button><button data-a="d" title="Delete">${ico('x')}</button>`;
        r.onclick = e => { const a = (e.target.closest('button') || {}).dataset?.a; if (a === 'r') return renameChat(c); if (a === 'd') return deleteChat(c); openChat(c.id); };
        h.appendChild(r);
      }
    }
    if (!chats.length) h.innerHTML = '<h4>No chats yet</h4>';
  }
  // click the title above the chat to rename it in place (the pencil in the sidebar list works too)
  function editTitle() {
    if (!cur.id || cur.incognito || el('ttl').querySelector('input')) return;
    const old = cur.title || '', inp = document.createElement('input');
    inp.className = 'ttl-edit'; inp.value = old; inp.maxLength = 80;
    el('ttl').innerHTML = ''; el('ttl').appendChild(inp); inp.focus(); inp.select();
    let done = false;
    const finish = async save => {
      if (done) return; done = true;
      const t = inp.value.trim();
      if (save && t && t !== old) { try { await post('/api/chat/rename', { id: cur.id, title: t }); cur.title = t; loadList(); } catch (e) { UI.alert(e.message); } }
      setTitle();
    };
    inp.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); finish(true); } else if (e.key === 'Escape') finish(false); };
    inp.onblur = () => finish(true);
  }
  el('ttl').title = 'Click to rename this chat'; el('ttl').onclick = editTitle;
  async function renameChat(c) { const t = await UI.prompt('Rename chat', { value: c.title, ok: 'Rename' }); if (t && t.trim()) { await post('/api/chat/rename', { id: c.id, title: t }); if (cur.id === c.id) cur.title = t; loadList(); setTitle(); } }
  async function deleteChat(c) { if (!await UI.confirm(`"${c.title}" will be deleted.`, { title: 'Delete chat?', ok: 'Delete', danger: true })) return; await J('/api/chat/item?id=' + c.id, { method: 'DELETE' }); if (cur.id === c.id) newChat(); loadList(); }
  async function openChat(id) {
    if (streaming) return;
    leaveIncognito();
    cur = await J('/api/chat/get?id=' + id); showTab('chat'); render(); renderList(); syncProj();
  }
  function newChat(incognito) { if (streaming) return; leaveIncognito(); cur = { id: null, messages: [], title: incognito === true ? 'Incognito chat' : 'New chat', incognito: incognito === true, project: incognito === true ? undefined : PROJ.active || undefined }; syncProj(); attached = null; renderAttach(); showTab('chat'); render(); renderList(); el('input').focus(); }
  el('newchat').onclick = () => newChat(false);
  const expMenu = el('expmenu');
  el('expbtn').onclick = e => { e.stopPropagation(); expMenu.hidden = !expMenu.hidden; };
  document.addEventListener('click', e => { if (!e.target.closest('.expwrap')) expMenu.hidden = true; });
  expMenu.onclick = e => { const b = e.target.closest('button'); if (!b) return; expMenu.hidden = true; if (!cur || !cur.messages || !cur.messages.length) return UI.alert('There is nothing in this chat to export yet.'); location.href = '/api/chat/export?id=' + encodeURIComponent(cur.id) + '&format=' + b.dataset.f; };
  el('brand').onclick = () => el('newchat').click();
  el('brand').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); el('newchat').click(); } };
  el('incog').onclick = () => newChat(!(cur && cur.incognito));
  function leaveIncognito() { if (cur && cur.incognito) fetch('/api/chat/end-incognito', { method: 'POST' }).catch(() => {}); }
  const setTitle = () => { el('ttl').innerHTML = (cur.incognito ? ico('incognito') + ' ' : '') + esc(cur.title || 'New chat'); el('tab-chat').classList.toggle('incognito', !!cur.incognito); el('incog').classList.toggle('on', !!cur.incognito); el('incog').setAttribute('aria-pressed', !!cur.incognito); el('incog').innerHTML = ico(cur.incognito ? 'eye' : 'incognito'); el('incog').title = cur.incognito ? 'Leave incognito: start a normal chat' : 'Incognito chat: not saved, gone when you leave it'; };

  // ---------- rendering
  // Follow the stream only while the reader is at the bottom; scrolling up stops it, and the arrow button brings them back.
  let stuck = true;
  const msgsEl = el('msgs'), toBottom = el('tobottom');
  toBottom.innerHTML = ico('arrowdown');
  const gap = () => msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight;
  const syncArrow = () => { toBottom.hidden = gap() < 120; };
  // Any user scroll gesture releases the lock at once (a small flick up used to be undone by the next streamed token); reaching the bottom again re-locks.
  const release = () => { stuck = false; };
  msgsEl.addEventListener('wheel', e => { if (e.deltaY < 0) release(); }, { passive: true });
  msgsEl.addEventListener('touchmove', release, { passive: true });
  msgsEl.addEventListener('pointerdown', e => { if (e.target === msgsEl) release(); });   // dragging the scrollbar
  document.addEventListener('keydown', e => { if (['PageUp', 'ArrowUp', 'Home'].includes(e.key) && !/INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || '')) release(); });
  msgsEl.addEventListener('scroll', () => { if (gap() < 24) stuck = true; syncArrow(); }, { passive: true });
  const scrollDown = force => { if (force) stuck = true; if (stuck) msgsEl.scrollTop = msgsEl.scrollHeight; syncArrow(); };
  toBottom.onclick = () => { stuck = true; msgsEl.scrollTo({ top: msgsEl.scrollHeight, behavior: 'smooth' }); };
  new ResizeObserver(syncArrow).observe(el('inner'));
  function toolCard(name, args, text, card, running) {
    const d = document.createElement('div'); d.className = 'tool' + (running ? '' : ' done');
    const label = { generate_music: 'Making music', edit_picture: 'Editing picture', list_music: 'Looking up your music', look_at_picture: 'Looking at the picture', ask_about_picture: 'Looking closer at the picture', search_documents: 'Searching your documents', remember: 'Saving to memory', forget: 'Removing from memory', search_past_chats: 'Searching earlier chats', run_python: 'Running code', generate_image: 'Creating a picture', web_search: 'Searching the web', fetch_page: 'Reading a web page' }[name] || name;
    d.innerHTML = `<div class="h"><i></i>${running ? label + '…' : label}</div><div class="b"></div>`;
    const b = d.querySelector('.b');
    if (running) { b.textContent = args && Object.keys(args).length ? JSON.stringify(args) : ''; return d; }
    if (card && card.kind === 'music') {
      musicPlayer(b, card.id);
    } else if (card && card.kind === 'run') {
      runCard(b, card);
    } else if (card && card.kind === 'music_draft') {
      musicDraft(b, card);
    } else if (card && card.kind === 'music_job') {
      b.textContent = 'Starting…'; pollMusic(card.job, b);
    } else if (card && card.kind === 'image_job') {
      b.textContent = 'Starting…'; pollImage(card.job, b);
    } else b.textContent = (text || '').slice(0, 300);
    return d;
  }
  function runCard(b, c) {
    const u = n => '/api/run/file?run=' + c.id + '&name=' + encodeURIComponent(n);
    if (c.code) { const det = document.createElement('details'); det.className = 'rundet'; const sm = document.createElement('summary'); sm.textContent = c.ok ? 'Code' : 'Code (failed)';
    const pre = document.createElement('div'); pre.className = 'codeblk'; pre.innerHTML = '<div class="codehead"><span>python</span></div><pre><code></code></pre>';
    pre.querySelector('code').innerHTML = window.hl ? hl(c.code, 'python') : esc(c.code); det.append(sm, pre); b.appendChild(det); }
    if (c.stdout && c.stdout.trim()) { const o = document.createElement('pre'); o.className = 'runout'; o.textContent = c.stdout.trim(); b.appendChild(o); }
    if (c.stderr && c.stderr.trim()) { const o = document.createElement('pre'); o.className = 'runout err'; o.textContent = c.stderr.trim(); b.appendChild(o); }
    for (const f of c.files || []) {
      if (f.image && /\.(png|jpe?g|gif|webp)$/i.test(f.name)) { const im = document.createElement('img'); im.className = 'runimg'; im.src = u(f.name); im.alt = f.name; b.appendChild(im); }
      const a = document.createElement('a'); a.className = 'runfile'; a.href = u(f.name) + '&download=1'; a.download = f.name; a.innerHTML = ico('file') + '<span></span><small></small>'; a.querySelector('span').textContent = f.name; a.querySelector('small').textContent = fmtSize(f.size); b.appendChild(a);
    }
  }
  const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;

  // ---------- music inside the chat: live progress, then an audio player with a download
  async function pollMusic(job, b) {
    b.innerHTML = '<div class="ijtxt">Starting the music model…</div><div class="pbar" style="display:block"><i class="ijfill"></i></div><div class="ijacts"><button class="ijcancel">Stop generating</button></div>';
    b.querySelector('.ijcancel').onclick = e => { e.target.disabled = true; e.target.textContent = 'Stopping...'; fetch('/api/music/cancel?id=' + job, { method: 'POST' }); };
    const txt = b.querySelector('.ijtxt'), fill = b.querySelector('.ijfill'); let fake = 4;
    for (;;) {
      let j; try { j = await J('/api/job?id=' + job); } catch (e) { txt.textContent = 'Lost track of this job.'; return; }
      if (j.message === 'unknown job') { txt.textContent = 'This piece was interrupted by a server restart. Check the Music tab, or ask again.'; b.querySelector('.pbar').remove(); return; }
      if (j.status === 'running' || j.status === 'queued') {
        const el = Date.now() / 1000 - (j.started || Date.now() / 1000);
        fake = Math.min(92, fake + (92 - fake) * 0.06); fill.style.width = fake.toFixed(1) + '%';
        txt.textContent = (j.message || 'Composing…') + ` · ${mmss(el)}`;
        await new Promise(r => setTimeout(r, 1200)); continue;
      }
      if (j.status === 'done' && j.results && j.results.length) {
        b.innerHTML = ''; musicPlayer(b, j.results[0]);
        return;
      }
      txt.textContent = j.status === 'cancelled' ? 'Stopped. No song was made.' : (j.message || 'No song came out. Ask again.'); b.querySelector('.pbar')?.remove(); b.querySelector('.ijacts')?.remove(); return;
    }
  }
  // the chat model's caption and lyrics, editable: nothing is generated until the user presses the button
  function musicDraft(b, card) {
    b.innerHTML = `<div class="mdraft"><label>Caption (the sound)</label><textarea class="mdcap" rows="3"></textarea>
      <label>Lyrics (empty for instrumental)</label><textarea class="mdlyr" rows="8"></textarea>
      <div class="mdacts"><select class="mdlen"><option value="short">Short, about 1 minute</option><option value="medium">Medium, about 2 minutes</option><option value="long">Long, about 3 minutes</option></select>
      <button class="primary mdgo" style="width:auto;margin:0">Generate song</button></div><div class="hint mdmsg">Review or edit, then press Generate song. Nothing is made until you do.</div></div>`;
    b.querySelector('.mdcap').value = card.caption || ''; b.querySelector('.mdlyr').value = card.lyrics || ''; b.querySelector('.mdlen').value = card.length || 'medium';
    b.querySelector('.mdgo').onclick = async () => {
      const caption = b.querySelector('.mdcap').value.trim();
      if (!caption) { b.querySelector('.mdmsg').textContent = 'The caption cannot be empty.'; return; }
      b.querySelector('.mdgo').disabled = true;
      try {
        const r = await fetch('/api/music/make', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ caption, lyrics: b.querySelector('.mdlyr').value, length: b.querySelector('.mdlen').value, incognito: !!cur.incognito }) });
        const j = await r.json(); if (!r.ok) throw new Error(j.error || 'failed');
        pollMusic(j.job, b);
      } catch (e) { b.querySelector('.mdmsg').textContent = 'Error: ' + e.message; b.querySelector('.mdgo').disabled = false; }
    };
  }
  function musicPlayer(b, id) {
    const q = '/audio?id=' + encodeURIComponent(id);
    b.innerHTML = `<div class="mp"><audio controls preload="metadata" src="${q}"></audio>
      <div class="mpdl"><a href="${q}&download=1" download>${ico('download')} Download (.wav)</a><button class="mpopen">Open in Music tab</button></div></div>`;
    b.querySelector('.mpopen').onclick = async () => { showTab('music'); await loadLibrary(id); };
  }
  async function pollImage(job, b) {
    b.innerHTML = `<div class="ijtxt">Starting the image model…</div><div class="pbar" style="display:block"><i class="ijfill"></i></div>
      <img class="ijprev" style="display:none"><div class="ijacts"><button class="ijcancel">Cancel</button></div>`;
    const txt = b.querySelector('.ijtxt'), fill = b.querySelector('.ijfill'), prev = b.querySelector('.ijprev'), acts = b.querySelector('.ijacts');
    b.querySelector('.ijcancel').onclick = () => fetch('/api/img/cancel?id=' + job, { method: 'POST' });
    for (;;) {
      let j; try { j = await J('/api/img/job?id=' + job); } catch (e) { txt.textContent = 'Lost track of this job.'; return; }
      if (j.message === 'unknown job') { txt.textContent = 'This edit was interrupted by a server restart. Ask again to redo it.'; b.querySelector('.pbar').remove(); acts.remove(); return; }
      if (j.status === 'running' || j.status === 'queued') {
        const total = j.steps * j.variations, done = (Math.max(j.variation, 1) - 1) * j.steps + j.step, el = Date.now() / 1000 - j.started;
        fill.style.width = (done / total * 100).toFixed(1) + '%';
        txt.textContent = j.step ? `${j.kind === 'generate' ? 'Creating' : 'Editing'}… step ${j.step} of ${j.steps} · ${mmss(el)} elapsed` + (done > 2 ? ` · about ${mmss(el / done * (total - done))} left` : '') : `Loading the model… ${mmss(el)}`;
        if (j.preview) { prev.src = '/img/' + j.preview + '?n=' + j.preview_n; prev.style.display = ''; }
        await new Promise(r => setTimeout(r, 1500)); continue;
      }
      b.querySelector('.pbar').remove(); prev.remove();
      if (j.status === 'done') {
        const f = j.results[0];
        txt.textContent = `Done in ${mmss(Date.now() / 1000 - j.started)}.`;
        b.insertAdjacentHTML('beforeend', `<img src="/img/${f}">`);
        acts.innerHTML = `<a href="/img/${f}" download="${f}"><button>Download</button></a>` + (j.input ? ' <button class="cmp">Compare with original</button>' : '');
        if (j.input) acts.querySelector('.cmp').onclick = () => { showTab('cover'); showResult(j, 0); };
      } else { txt.textContent = j.status === 'cancelled' ? 'Cancelled.' : (j.message || j.status); acts.remove(); }
      return;
    }
  }
  function msgEl(m, i, last) {
    const wrap = document.createElement('div');
    if (m.role === 'user') {
      wrap.className = 'msg user';
      if (m.images) wrap.innerHTML = m.images.map(f => `<img class="userimg" src="/img/${f}">`).join('');
      else if (m._local) wrap.innerHTML = `<img class="userimg" src="${m._local}">`;
      if (m.files && m.files.length) { const fr = document.createElement('div'); fr.className = 'mfiles'; fr.innerHTML = m.files.map(f => `<span class="achip">${ico('file')}<span class="an">${esc(f.name)}</span><span class="as">${fmtSize(f.size)}</span></span>`).join(''); wrap.appendChild(fr); }
      if (!/^\((picture|file) attached\)$/.test(m.content) || !(m.files && m.files.length) && !m.images && !m._local) { const b = document.createElement('div'); b.className = 'bubble'; b.textContent = m.content; wrap.appendChild(b); }
    } else if (m.role === 'assistant') {
      wrap.className = 'msg assistant';
      if (m.thinking) wrap.insertAdjacentHTML('beforeend', `<details class="think"><summary>Thought process</summary><div>${esc(m.thinking)}</div></details>`);
      if (m.content) { const b = document.createElement('div'); b.className = 'bubble'; b.innerHTML = md(m.content); wrap.appendChild(b); }
      if (m.content || m.thinking) wrap.insertAdjacentHTML('beforeend', `<div class="acts"><button data-a="c" title="Copy">${ico('copy')}</button><button data-a="s" title="Read aloud">${ico('speaker')}</button>${last ? `<button data-a="g" title="Regenerate">${ico('refresh')}</button>` : ''}</div>`);
      wrap.querySelector('.acts')?.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.a === 'c') { navigator.clipboard.writeText(m.content || ''); b.innerHTML = ico('check'); setTimeout(() => b.innerHTML = ico('copy'), 1200); } if (b.dataset.a === 's') speak(m.content || '', b); if (b.dataset.a === 'g') send(null, true); });
    } else if (m.role === 'tool') {
      wrap.className = 'msg assistant'; wrap.appendChild(toolCard(m.name, null, m.content, m.card, false));
    }
    return wrap;
  }
  let shown = { id: null, n: 0 };
  function render() {
    el('tab-chat').classList.toggle('is-empty', !cur.messages.length);
    setTitle(); const inner = el('inner'); inner.innerHTML = '';
    if (!cur.messages.length) {
      inner.innerHTML = `<div class="empty-chat"><img class="logo-big" src="/icons/icon-192.png" alt="" width="56" height="56"><h2>${cur.incognito ? 'Incognito chat' : `What can I help you with${((PF.name || '').trim() || (ME.kind === 'user' ? ME.name : '')) ? ', ' + esc((PF.name || '').trim() || ME.name) : ''}?`}</h2><div>${cur.incognito ? 'This chat is not saved and disappears when you leave it. ' : ''}Everything here runs offline on your Mac, using ${esc(modelLabels[settings.model] || settings.model)}.</div>
        <div class="chips"><button>Make me a new piano and guitar piece</button><button>Help me write something</button><button>Explain something to me simply</button><button>Explain how my music model was trained</button></div></div>`;
      inner.querySelectorAll('.chips button').forEach(b => b.onclick = () => { el('input').value = b.textContent; send(); });
      return;
    }
    const lastAssist = cur.messages.map(m => m.role).lastIndexOf('assistant');
    // only messages that are new since the last render fade in (re-renders while streaming must not flicker)
    const same = shown.id === cur.id, fromN = same ? shown.n : 0;
    cur.messages.forEach((m, i) => { if (m.role === 'assistant' && !m.content && !m.thinking) return; const node = msgEl(m, i, i === lastAssist && !streaming); if (i >= fromN) node.classList.add('fresh'); inner.appendChild(node); });
    shown = { id: cur.id, n: cur.messages.length };
    scrollDown(!same);
  }
  document.addEventListener('click', e => {
    const b = e.target.closest('.cp'); if (!b) return;
    navigator.clipboard.writeText(b.closest('.codeblk').querySelector('code').textContent);
    b.innerHTML = ico('check') + '<span>Copied</span>'; b.classList.add('done');
    setTimeout(() => { b.innerHTML = ico('copy') + '<span>Copy</span>'; b.classList.remove('done'); }, 1500);
  });

  // ---------- attach
  const fmtSize = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';
  function renderAttach() {
    const box = el('attach'); box.innerHTML = '';
    if (attached) { const d = document.createElement('div'); d.className = 'achip img'; d.innerHTML = `<img src="${attached}"><button type="button" aria-label="Remove picture">${ico('x')}</button>`; d.querySelector('button').onclick = () => { attached = null; renderAttach(); }; box.appendChild(d); }
    files.forEach((f, i) => { const d = document.createElement('div'); d.className = 'achip'; d.innerHTML = `${ico('file')}<span class="an">${esc(f.name)}</span><span class="as">${fmtSize(f.size)}</span><button type="button" aria-label="Remove file">${ico('x')}</button>`; d.querySelector('button').onclick = () => { files.splice(i, 1); renderAttach(); }; box.appendChild(d); });
  }
  el('attbtn').onclick = e => { e.stopPropagation(); const m = el('attmenu'); m.hidden = !m.hidden; if (!m.hidden) el('am-toolsbox').checked = settings.tools; };
  el('am-files').onclick = () => { el('attmenu').hidden = true; el('attfile').click(); };
  el('am-toolsbox').onchange = () => { settings.tools = el('am-toolsbox').checked; el('tools').checked = settings.tools; saveSettings(); };
  document.addEventListener('click', e => { if (e.target.isConnected && !el('attmenu').contains(e.target)) el('attmenu').hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') el('attmenu').hidden = true; });
  // pictures go to the picture editor flow; every other file is read by the language model
  function attachFile(f) {
    if (!f) return;
    if (f.size > 25 * 1024 * 1024) { UI.alert(f.name + ' is larger than 25 MB.', { title: 'File too large' }); return; }
    const r = new FileReader();
    r.onload = () => {
      if (f.type.startsWith('image/') && !attached) attached = r.result;
      else if (files.length < 6) files.push({ name: f.name, size: f.size, data: r.result });
      renderAttach(); el('input').focus();
    };
    r.readAsDataURL(f);
  }
  const chatTab = el('tab-chat');
  ['dragenter', 'dragover'].forEach(ev => chatTab.addEventListener(ev, e => { if ([...(e.dataTransfer?.types || [])].includes('Files')) { e.preventDefault(); chatTab.classList.add('dropping'); } }));
  ['dragleave', 'drop'].forEach(ev => chatTab.addEventListener(ev, e => { if (ev === 'dragleave' && chatTab.contains(e.relatedTarget)) return; e.preventDefault(); chatTab.classList.remove('dropping'); }));
  chatTab.addEventListener('drop', e => [...e.dataTransfer.files].forEach(attachFile));
  el('input').addEventListener('paste', e => { const fs = [...(e.clipboardData?.files || [])]; if (fs.length) { e.preventDefault(); fs.forEach(attachFile); } });
  el('attfile').onchange = e => { [...e.target.files].forEach(attachFile); e.target.value = ''; };

  // ---------- sending
  const input = el('input');
  input.oninput = () => { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 200) + 'px'; };
  input.onkeydown = e => { if (e.key === 'Enter' && !e.isComposing && (PF.enter ? !e.shiftKey : (e.metaKey || e.ctrlKey))) { e.preventDefault(); send(); } };
  el('send').onclick = () => { if (streaming) stop(); else send(); };
  async function stop() { if (cur.id) await fetch('/api/chat/stop?id=' + cur.id, { method: 'POST' }); }

  // ---------- voice: dictation (Whisper on this Mac) and reading answers aloud (macOS voices)
  let voiceList = null, audioEl = null, speakBtn = null;
  async function fillVoices() {
    const sel = el('s-voice'); if (!sel) return;
    try { if (!voiceList) voiceList = (await J('/api/voice/voices')).items; } catch (e) { return; }
    const mine = voiceList.filter(v => v.natural || /^en/.test(v.lang)).concat(voiceList.filter(v => !v.natural && !/^en/.test(v.lang)));
    sel.innerHTML = '<option value="">Default</option>' + mine.map(v => `<option value="${esc(v.name)}">${esc(v.label || v.name)}</option>`).join('');
    sel.value = PF.voice || ''; if (sel._ddSync) sel._ddSync();
  }
  function stopSpeech() { if (audioEl) { audioEl.pause(); audioEl = null; } if (speakBtn) { speakBtn.innerHTML = ico('speaker'); speakBtn.classList.remove('on'); speakBtn = null; } }
  async function speak(text, btn) {
    const same = btn && btn === speakBtn; stopSpeech(); if (same) return;
    speakBtn = btn || null; if (btn) { btn.innerHTML = ico('stop'); btn.classList.add('on'); }
    try {
      const r = await fetch('/api/voice/speak', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, voice: PF.voice || null }) });
      if (!r.ok) throw new Error((await r.json()).error);
      if (btn && speakBtn !== btn) return;
      const a = new Audio(URL.createObjectURL(await r.blob())); audioEl = a; a.onended = stopSpeech; a.onerror = stopSpeech; await a.play();
    } catch (e) { stopSpeech(); if (e.name !== 'NotAllowedError') UI.alert(e.message); }
  }
  let rec = null;
  async function toggleMic() {
    const mic = el('mic');
    if (rec) { rec.stop(); return; }
    if (!navigator.mediaDevices || !window.MediaRecorder) return UI.alert('This browser cannot record audio here. On an iPhone the secure address (https) is needed.');
    let stream; try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { return UI.alert('Microphone access was not allowed. Allow it in the browser address bar and try again.'); }
    const chunks = [], mr = new MediaRecorder(stream), ext = /mp4/.test(mr.mimeType) ? 'm4a' : 'webm'; rec = mr;
    mr.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
    mr.onstop = async () => {
      stream.getTracks().forEach(t => t.stop()); rec = null; mic.classList.remove('rec'); mic.innerHTML = ico('mic');
      if (!chunks.length) return; mic.disabled = true; mic.title = 'Transcribing…'; mic.classList.add('busy');
      try {
        const r = await fetch('/api/voice/transcribe?ext=' + ext, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: new Blob(chunks) });
        const j = await r.json(); if (!r.ok) throw new Error(j.error);
        const ta = el('input'); ta.value = (ta.value ? ta.value.replace(/\s*$/, ' ') : '') + j.text; ta.dispatchEvent(new Event('input')); ta.focus();
      } catch (e) { UI.alert(e.message); }
      mic.disabled = false; mic.classList.remove('busy'); mic.title = 'Dictate (speech to text on this Mac)';
    };
    mr.start(); mic.classList.add('rec'); mic.innerHTML = ico('stop'); mic.title = 'Stop recording';
  }
  el('mic').onclick = toggleMic;

  async function send(_e, regenerate = false) {
    stuck = true;
    if (streaming) return;
    const text = input.value.trim();
    if (!regenerate && !text && !attached && !files.length) return;
    if (macDown) { setBanner(bannerText, true); return; }
    if (!cur.id) { const c = await post('/api/chat/new', { model: settings.model, incognito: !!cur.incognito, project: cur.project || '' }); cur.id = c.id; }
    const body = { id: cur.id, model: settings.model, think: settings.think, tools: settings.tools, personal: { name: PF.name, about: PF.about, style: PF.style, instr: PF.instr }, memory: PF.memory !== false, web: PF.web === true, regenerate };
    if (!regenerate) {
      body.content = text; if (attached) body.image = attached;
      if (files.length) body.files = files.map(f => ({ name: f.name, data: f.data }));
      cur.messages.push({ role: 'user', content: text || (attached ? '(picture attached)' : '(file attached)'), _local: attached, files: files.map(f => ({ name: f.name, size: f.size })) });
      input.value = ''; input.style.height = 'auto'; attached = null; files = []; renderAttach();
    } else { while (cur.messages.length && cur.messages[cur.messages.length - 1].role !== 'user') cur.messages.pop(); }
    streaming = true; el('send').innerHTML = ico('stop'); el('send').title = 'Stop'; render();
    const inner = el('inner');
    let wrap = document.createElement('div'); wrap.className = 'msg assistant'; inner.appendChild(wrap);
    let think = null, thinkDiv = null, bubble = null, content = '', thinkText = '', pending = false;
    const paint = () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; if (bubble) { bubble.innerHTML = md(content); bubble.classList.add('cursor'); } if (thinkDiv) thinkDiv.textContent = thinkText; scrollDown(); }); };
    const runningTools = {};
    try {
      ctrl = new AbortController();
      const resp = await fetch('/api/chat/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctrl.signal });
      if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
      const reader = resp.body.getReader(), dec = new TextDecoder(); let buf = '';
      for (;;) {
        const { value, done } = await reader.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let k; while ((k = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, k).trim(); buf = buf.slice(k + 2);
          if (!line.startsWith('data:')) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.type === 'thinking') {
            if (!think) { think = document.createElement('details'); think.className = 'think'; think.open = true; think.innerHTML = '<summary>Thinking…</summary><div></div>'; thinkDiv = think.querySelector('div'); wrap.prepend(think); }
            thinkText += ev.text; paint();
          } else if (ev.type === 'token') {
            if (!bubble) { bubble = document.createElement('div'); bubble.className = 'bubble'; wrap.appendChild(bubble); if (think) { think.open = false; think.querySelector('summary').textContent = 'Thought process'; } }
            content += ev.text; paint();
          } else if (ev.type === 'tool_start') {
            const t = toolCard(ev.name, ev.args, '', null, true); runningTools[ev.name] = t; inner.appendChild(t); scrollDown();
          } else if (ev.type === 'tool_result') {
            const t = toolCard(ev.name, null, ev.text, ev.card, false); (runningTools[ev.name] || inner.appendChild(document.createElement('div'))).replaceWith(t);
            // the model's next text goes in a fresh message after the tool card
            bubble = null; content = ''; think = null; thinkDiv = null; thinkText = '';
            wrap = document.createElement('div'); wrap.className = 'msg assistant'; inner.appendChild(wrap);
          } else if (ev.type === 'error') {
            wrap.insertAdjacentHTML('beforeend', `<div class="err">Error: ${esc(ev.message)}</div>`);
          }
        }
      }
    } catch (e) { if (e.name !== 'AbortError') wrap.insertAdjacentHTML('beforeend', `<div class="err">Error: ${esc(e.message)}</div>`); }
    streaming = false; ctrl = null; el('send').innerHTML = ico('arrowup'); el('send').title = 'Send';
    try { cur = await J('/api/chat/get?id=' + cur.id); } catch (e) {}
    render(); if (PF.speak && content.trim()) speak(content, null); loadList(); setTimeout(loadList, 6000); setTimeout(async () => { await loadList(); const c = chats.find(x => x.id === cur.id); if (c) { cur.title = c.title; setTitle(); } }, 12000);
  }

  // ---------- library (your documents)
  let libTimer = null;
  async function loadLib() {
    let r; try { r = await J('/api/library?project=' + encodeURIComponent(PROJ.active)); } catch (e) { return; }
    const box = el('liblist'); box.innerHTML = '';
    if (!r.items.length) box.innerHTML = '<p class="hint">No documents yet.</p>';
    for (const d of r.items) {
      const row = document.createElement('div'); row.className = 'librow';
      const st = d.status === 'ready' ? d.n + (d.n === 1 ? ' passage' : ' passages') : d.status === 'indexing' ? 'Indexing…' : (d.error || 'Failed');
      row.innerHTML = `<i></i><div class="libmeta"><b></b><small></small></div><button type="button" title="Remove from library"></button>`;
      row.querySelector('i').outerHTML = ico('file'); row.querySelector('b').textContent = d.name;
      row.querySelector('small').textContent = `${fmtSize(d.size)} · ${d.note ? d.note + ' · ' : ''}${st}`;
      if (d.status === 'error') row.classList.add('bad');
      const b = row.querySelector('button'); b.innerHTML = ico('x');
      b.onclick = async () => { if (await UI.confirm(`"${d.name}" will be removed from your library.`, { title: 'Remove document?', ok: 'Remove', danger: true })) { await J('/api/library?id=' + d.id + '&project=' + encodeURIComponent(PROJ.active), { method: 'DELETE' }); loadLib(); } };
      box.appendChild(row);
    }
    clearTimeout(libTimer); if (r.items.some(d => d.status === 'indexing')) libTimer = setTimeout(loadLib, 1500);
  }
  async function addLibFiles(files) {
    for (const f of files) {
      if (f.size > 25 * 1024 * 1024) { UI.alert(f.name + ' is larger than 25 MB.', { title: 'File too large' }); continue; }
      const data = await new Promise(res => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(f); });
      try { await post('/api/library', { name: f.name, data, project: PROJ.active }); } catch (e) { UI.alert(e.message, { title: "Couldn't add " + f.name }); }
      loadLib();
    }
  }
  el('libdrop').onclick = () => el('libfile').click();
  el('libfile').onchange = () => { addLibFiles([...el('libfile').files]); el('libfile').value = ''; };
  ['dragover', 'dragenter'].forEach(ev => el('libdrop').addEventListener(ev, e => { e.preventDefault(); el('libdrop').classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => el('libdrop').addEventListener(ev, e => { e.preventDefault(); el('libdrop').classList.remove('over'); }));
  el('libdrop').addEventListener('drop', e => addLibFiles([...e.dataTransfer.files]));
  async function libSearch() {
    const q = el('libq').value.trim(); if (!q) { el('libhits').innerHTML = ''; return; }
    el('libhits').innerHTML = '<p class="hint">Searching…</p>';
    try {
      const r = await post('/api/library/search', { query: q, project: PROJ.active });
      el('libhits').innerHTML = r.hits.length ? '' : '<p class="hint">No matching passages.</p>';
      for (const h of r.hits) { const d = document.createElement('div'); d.className = 'libhit'; d.innerHTML = '<b></b><p></p>'; d.querySelector('b').textContent = `${h.name} · passage ${h.passage} · ${Math.round(h.score * 100)}% match`; d.querySelector('p').textContent = h.text.slice(0, 420) + (h.text.length > 420 ? '…' : ''); el('libhits').appendChild(d); }
    } catch (e) { el('libhits').innerHTML = ''; UI.alert(e.message, { title: 'Search failed' }); }
  }
  el('libgo').onclick = libSearch; el('libq').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); libSearch(); } };

  // ---------- live updates (sidebar history, model list, Ollama/job banner)
  setInterval(() => { if (!document.hidden) { loadList().catch(() => {}); if (document.activeElement !== el('model')) loadModels(); } }, 4000);

  // ---------- model / reasoning / settings popover (like ChatGPT's model picker)
  const syncModelBtn = () => { el('modelname').textContent = (modelLabels[settings.model] || settings.model) + (settings.think && settings.think !== 'off' ? '' : ''); };
  // Build the effort buttons once and only move the highlight, so the popover stays open after a choice.
  const LEVELS = ['off', 'low', 'medium', 'high'];
  const paintSeg = () => {
    const seg = el('thinkseg'), i = Math.max(0, LEVELS.indexOf(settings.think));
    seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === settings.think));
    seg.style.setProperty('--i', i);
  };
  const buildSeg = () => {
    const seg = el('thinkseg');
    if (!seg.dataset.built) {
      seg.dataset.built = '1';
      seg.innerHTML = '<span class="pill"></span>' + LEVELS.map(v => `<button type="button" data-v="${v}">${v[0].toUpperCase() + v.slice(1)}</button>`).join('');
      seg.querySelectorAll('button').forEach(b => b.onclick = () => { settings.think = b.dataset.v; el('think').value = settings.think; saveSettings(); paintSeg(); });
    }
    paintSeg();
  };
  buildSeg(); syncModelBtn();
  el('model').addEventListener('change', syncModelBtn);
  el('modelbtn').onclick = e => { e.stopPropagation(); el('modelmenu').hidden = !el('modelmenu').hidden; syncModelBtn(); };
  document.addEventListener('click', e => { if (e.target.isConnected && !el('modelmenu').contains(e.target) && e.target !== el('modelbtn') && !e.target.closest('.dd-menu')) el('modelmenu').hidden = true; });
  setInterval(syncModelBtn, 2000);

  // ---------- account chip + menu
  el('av').textContent = (ME.name || '?').slice(0, 1).toUpperCase(); el('whoname').textContent = ME.kind === 'guest' ? 'Guest' : ME.name;
  el('amh').textContent = ME.kind === 'guest' ? 'Guest session. Everything is deleted when you sign out or close the browser.' : `Signed in as ${ME.name}`;
  el('am-out').textContent = ME.kind === 'guest' ? 'End session and delete my data' : 'Sign out';
  if (ME.kind === 'guest') el('am-pw').style.display = 'none';
  if (ME.lan && ME.local) { el('amlan').hidden = false; el('amlan').innerHTML = `Use it from your phone on the same Wi-Fi:<br><code>${esc(ME.lan)}</code><br>Sign in with this account. Your Mac does the work.`; }
  el('acct').onclick = e => { e.stopPropagation(); el('acctmenu').hidden = !el('acctmenu').hidden; };
  document.addEventListener('click', e => { if (e.target.isConnected && !el('acctmenu').contains(e.target)) el('acctmenu').hidden = true; });
  el('am-out').onclick = async () => {
    if (ME.kind === 'guest' && !await UI.confirm('Your chats, pictures and music will be deleted.', { title: 'End guest session?', ok: 'End session', danger: true })) return;
    await fetch('/api/auth/logout', { method: 'POST' }); await clearOfflineData(); location.reload();
  };
  el('am-pw').onclick = async () => {
    const old = await UI.prompt('Change password', { label: 'Current password', type: 'password', ok: 'Next' }); if (old == null) return;
    const nw = await UI.prompt('Change password', { label: 'New password (at least 6 characters)', type: 'password', ok: 'Change' }); if (nw == null) return;
    try { await post('/api/auth/password', { old, new: nw }); UI.alert('Password changed.'); } catch (e) { UI.alert(e.message, { title: 'Could not change password' }); }
  };
  setInterval(() => fetch('/api/me').catch(() => {}), 60000); // keeps a guest session alive while the browser is open

  // ---------- boot
  loadModels(); loadList(); render(); PROJ.load();
  const view = loadView();
  showTab(['chat', 'music', 'cover', 'console'].includes(view.tab) ? view.tab : 'chat');
  if (view.chat) openChat(view.chat).then(() => { if (view.tab && view.tab !== 'chat') showTab(view.tab); }).catch(() => {});

// ---------- settings dialog
(() => {
  const el = id => document.getElementById(id), dlg = el('setdlg');
  const segs = { 's-theme': [['auto', 'System'], ['light', 'Light'], ['dark', 'Dark']], 's-size': [['s', 'Small'], ['m', 'Medium'], ['l', 'Large']],
    'p-style': [['default', 'Default'], ['concise', 'Concise'], ['detailed', 'Detailed'], ['friendly', 'Friendly']] };
  const store = () => { try { return JSON.parse(localStorage.getItem('chat-settings-ui') || '{}'); } catch (e) { return {}; } };
  const setSeg = (id, v) => { const s = el(id); s.dataset.v = v; const keys = segs[id].map(x => x[0]); s.style.setProperty('--i', Math.max(0, keys.indexOf(v))); s.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === v)); };
  for (const [id, opts] of Object.entries(segs)) {
    const s = el(id); s.style.setProperty('--n', opts.length);
    s.innerHTML = '<span class="pill"></span>' + opts.map(([v, l]) => `<button type="button" data-v="${v}">${l}</button>`).join('');
    s.onclick = e => { const b = e.target.closest('button'); if (!b) return; setSeg(id, b.dataset.v); apply(id, b.dataset.v); };
  }
  const SIZES = { s: '14px', m: '16px', l: '17px' };
  function applySize() { document.documentElement.style.setProperty('--msg-size', SIZES[PF.size] || SIZES.m); }
  function apply(id, v) {
    if (id === 's-theme') window.applyTheme(v);
    if (id === 's-size') { PF.size = v; applySize(); savePrefs(); }
    if (id === 'p-style') { PF.style = v; savePrefs(); }
  }
  function fill() {
    let t = 'auto'; try { t = localStorage.getItem('theme') || 'auto'; } catch (e) {}
    setSeg('s-theme', t); setSeg('s-size', PF.size); setSeg('p-style', PF.style);
    el('s-enter').checked = PF.enter; el('s-web').checked = PF.web === true; el('s-speak').checked = PF.speak === true; el('s-warn').checked = PF.warnheavy !== false; fillVoices(); el('s-tools').checked = settings.tools; el('s-think').value = settings.think;
    el('s-model').innerHTML = el('model').innerHTML; el('s-model').value = settings.model;
    el('p-name').value = PF.name; el('p-about').value = PF.about; el('p-instr').value = PF.instr;
    document.dispatchEvent(new Event('ui-sync'));
  }
  function open(sec) { fill(); show(sec || 'general'); if (!dlg.open) dlg.showModal(); }
  async function loadMem(items) {
    try { items = items || (await J('/api/memory')).items; } catch (e) { return; }
    el('m-list').innerHTML = '';
    for (const it of items.slice().reverse()) {
      const r = document.createElement('div'); r.className = 'memrow'; const t = document.createElement('span'); t.textContent = it.text;
      const b = document.createElement('button'); b.type = 'button'; b.title = 'Forget this'; b.innerHTML = ico('x');
      b.onclick = async () => loadMem((await J('/api/memory?id=' + it.id, { method: 'DELETE' })).items);
      r.append(t, b); el('m-list').appendChild(r);
    }
    el('m-hint').textContent = items.length ? items.length + (items.length === 1 ? ' thing remembered.' : ' things remembered.') : 'Nothing remembered yet. It learns from your chats as you go, or tell it to remember something.';
    el('m-clear').hidden = !items.length;
  }
  window.openSettings = open;
  let pjEdit = null;
  async function loadProjects() {
    await PROJ.load(); el('pj-list').innerHTML = '';
    for (const p of PROJ.list) {
      const r = document.createElement('div'); r.className = 'memrow'; const t = document.createElement('span'); t.innerHTML = '<b></b> <small></small>'; t.firstChild.textContent = p.name; t.lastChild.textContent = (p.instructions || 'no instructions').slice(0, 90);
      const e = document.createElement('button'); e.type = 'button'; e.title = 'Edit'; e.innerHTML = ico('pencil'); e.onclick = () => { pjEdit = p.id; el('pj-name').value = p.name; el('pj-instr').value = p.instructions; el('pj-save').textContent = 'Save changes'; el('pj-cancel').hidden = false; };
      const d = document.createElement('button'); d.type = 'button'; d.title = 'Delete'; d.innerHTML = ico('x');
      d.onclick = async () => { if (!await UI.confirm('The project and the documents in it are deleted. Its chats are kept and move out of the project.', { title: 'Delete "' + p.name + '"?', ok: 'Delete', danger: true })) return; await J('/api/projects?id=' + p.id, { method: 'DELETE' }); if (PROJ.active === p.id) PROJ.set(''); loadProjects(); };
      r.append(t, e, d); el('pj-list').appendChild(r);
    }
    if (!PROJ.list.length) el('pj-list').innerHTML = '<p class="hint">No projects yet.</p>';
  }
  function pjReset() { pjEdit = null; el('pj-name').value = ''; el('pj-instr').value = ''; el('pj-save').textContent = 'Add project'; el('pj-cancel').hidden = true; }
  el('pj-cancel').onclick = pjReset;
  el('pj-save').onclick = async () => { try { const r = await post('/api/projects', { id: pjEdit, name: el('pj-name').value, instructions: el('pj-instr').value }); pjReset(); await loadProjects(); if (!PROJ.active) PROJ.set(r.project.id); } catch (e) { UI.alert(e.message); } };
  async function loadKeys() {
    el('api-url').textContent = location.origin + '/v1';
    let d; try { d = await J('/api/keys'); } catch (e) { return; }
    el('api-list').innerHTML = ''; el('api-add').disabled = el('api-name').disabled = !d.can;
    if (!d.can) { el('api-list').innerHTML = '<p class="hint">Sign in with an account to make API keys.</p>'; return; }
    for (const k of d.items) {
      const r = document.createElement('div'); r.className = 'memrow'; const t = document.createElement('span'); t.innerHTML = '<b></b> <small></small>'; t.firstChild.textContent = k.name;
      t.lastChild.textContent = k.prefix + '… · ' + (k.last_used ? 'used ' + new Date(k.last_used * 1000).toLocaleDateString() : 'never used');
      const b = document.createElement('button'); b.type = 'button'; b.title = 'Revoke'; b.innerHTML = ico('x');
      b.onclick = async () => { if (await UI.confirm('Programs using this key stop working immediately.', { title: 'Revoke "' + k.name + '"?', ok: 'Revoke', danger: true })) { await J('/api/keys?id=' + k.id, { method: 'DELETE' }); loadKeys(); } };
      r.append(t, b); el('api-list').appendChild(r);
    }
    if (!d.items.length) el('api-list').innerHTML = '<p class="hint">No keys yet.</p>';
  }
  el('api-add').onclick = async () => { try { const r = await post('/api/keys', { name: el('api-name').value }); el('api-name').value = ''; await UI.alert(r.key, { title: 'Your new key. Copy it now, it is not shown again.' }); } catch (e) { UI.alert(e.message); } loadKeys(); };
  const ddSync = (...ids) => ids.forEach(i => el(i)._ddSync && el(i)._ddSync());
  let tkEdit = null, tkPoll = null;
  const when = t => t.when.type === 'every' ? 'every ' + t.when.hours + ' h' : 'daily at ' + t.when.time;
  function tkReset() { tkEdit = null; for (const i of ['tk-name', 'tk-prompt', 'tk-folder']) el(i).value = ''; el('tk-type').value = 'daily'; el('tk-time').value = '08:00'; el('tk-hours').value = 24; el('tk-save').textContent = 'Add task'; el('tk-cancel').hidden = true; tkType(); ddSync('tk-type', 'tk-model'); }
  function tkType() { const ev = el('tk-type').value === 'every'; el('tk-time').hidden = ev; el('tk-hours').hidden = !ev; el('tk-hrs').hidden = !ev; }
  async function loadTasks() {
    let d; try { d = await J('/api/tasks'); } catch (e) { return; }
    el('tk-model').innerHTML = [...el('model').options].map(o => `<option value="${esc(o.value)}">${esc(o.textContent)}</option>`).join('');
    el('tk-list').innerHTML = '';
    for (const t of d.items) {
      const r = document.createElement('div'); r.className = 'memrow'; const sp = document.createElement('span'); sp.innerHTML = '<b></b> <small></small>'; sp.firstChild.textContent = t.name;
      const run = d.running.includes(t.id);
      sp.lastChild.textContent = when(t) + ' · ' + (run ? 'running now…' : t.last_run ? 'last ' + new Date(t.last_run * 1000).toLocaleString() + (t.last_status && t.last_status !== 'ok' ? ' (' + t.last_status + ')' : '') : 'not run yet') + (t.enabled ? '' : ' · paused');
      const mk = (title, icon, fn) => { const b = document.createElement('button'); b.type = 'button'; b.title = title; b.innerHTML = ico(icon); b.onclick = fn; return b; };
      r.append(sp,
        mk(run ? 'Running' : 'Run now', 'refresh', async () => { if (run) return; try { await post('/api/tasks/run', { id: t.id }); } catch (e) { UI.alert(e.message); } loadTasks(); }),
        mk(t.enabled ? 'Pause' : 'Resume', t.enabled ? 'stop' : 'arrowup', async () => { await post('/api/tasks', { ...t, ...t.when, enabled: !t.enabled }); loadTasks(); }),
        mk('Edit', 'pencil', () => { tkEdit = t.id; el('tk-name').value = t.name; el('tk-prompt').value = t.prompt; el('tk-folder').value = t.folder; el('tk-type').value = t.when.type; el('tk-time').value = t.when.time; el('tk-hours').value = t.when.hours; el('tk-model').value = t.model; el('tk-save').textContent = 'Save changes'; el('tk-cancel').hidden = false; tkType(); ddSync('tk-type', 'tk-model'); }),
        mk('Delete', 'x', async () => { if (await UI.confirm('The task is removed. Chats it already made stay.', { title: 'Delete "' + t.name + '"?', ok: 'Delete', danger: true })) { await J('/api/tasks?id=' + t.id, { method: 'DELETE' }); loadTasks(); } }));
      el('tk-list').appendChild(r);
    }
    if (!d.items.length) el('tk-list').innerHTML = '<p class="hint">' + (d.can ? 'No tasks yet.' : 'Sign in with an account to schedule tasks.') + '</p>';
    el('tk-save').disabled = !d.can;
    clearTimeout(tkPoll); if (d.running.length && !el('setdlg').hidden) tkPoll = setTimeout(loadTasks, 4000);
  }
  el('tk-type').onchange = tkType; el('tk-cancel').onclick = tkReset;
  el('tk-save').onclick = async () => { try { await post('/api/tasks', { id: tkEdit, name: el('tk-name').value, prompt: el('tk-prompt').value, type: el('tk-type').value, time: el('tk-time').value, hours: el('tk-hours').value, folder: el('tk-folder').value, model: el('tk-model').value }); tkReset(); loadTasks(); } catch (e) { UI.alert(e.message); } };
  let mmBusy = false;
  const gb = n => n >= 1e9 ? (n / 1e9).toFixed(1) + ' GB' : Math.max(1, Math.round(n / 1e6)) + ' MB';
  async function loadMM() {
    let d; try { d = await J('/api/models/installed'); } catch (e) { el('mm-list').textContent = 'Could not reach Ollama.'; return; }
    el('mm-list').innerHTML = '';
    const have = new Set(d.items.map(m => m.name));
    for (const m of d.items) {
      const r = document.createElement('div'); r.className = 'memrow'; const t = document.createElement('span');
      t.innerHTML = '<b></b> <small></small>'; t.firstChild.textContent = m.label === m.name ? m.name : m.label + ' (' + m.name + ')';
      t.lastChild.textContent = gb(m.size) + (m.helper ? ' - used behind the scenes' : '');
      r.appendChild(t);
      if (d.can_manage) { const b = document.createElement('button'); b.type = 'button'; b.title = 'Remove this model'; b.innerHTML = ico('x');
        b.onclick = async () => { if (!await UI.confirm('The files (' + gb(m.size) + ') are deleted from this Mac. You can download it again later.', { title: 'Remove ' + m.name + '?', ok: 'Remove', danger: true })) return; try { await J('/api/models?name=' + encodeURIComponent(m.name), { method: 'DELETE' }); } catch (e) { UI.alert(e.message); } loadMM(); loadModels(); };
        r.appendChild(b); }
      el('mm-list').appendChild(r);
    }
    el('mm-sug').innerHTML = '';
    for (const sg of d.suggest.filter(x => !have.has(x.name))) { const b = document.createElement('button'); b.type = 'button'; b.className = 'chip'; b.textContent = sg.name; b.title = sg.note; b.onclick = () => { el('mm-new').value = sg.name; }; el('mm-sug').appendChild(b); }
    el('mm-go').disabled = !d.can_manage; el('mm-new').disabled = !d.can_manage;
    if (!d.can_manage) el('mm-hint').textContent = 'Sign in with an account to download or remove models.';
  }
  async function pullModel() {
    const name = el('mm-new').value.trim(); if (!name || mmBusy) return; mmBusy = true; el('mm-go').disabled = true;
    el('mm-prog').hidden = false; el('mm-bar').style.width = '0%'; el('mm-txt').textContent = 'Starting...';
    try {
      const r = await fetch('/api/models/pull', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      if (!r.ok) throw new Error((await r.json()).error);
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = '', err = '';
      for (;;) { const { value, done } = await rd.read(); if (done) break; buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf('\n\n')) >= 0) { const ev = JSON.parse(buf.slice(6, i)); buf = buf.slice(i + 2);
          if (ev.error) err = ev.error; else { if (ev.total) el('mm-bar').style.width = Math.round(100 * ev.completed / ev.total) + '%'; el('mm-txt').textContent = (ev.total ? Math.round(100 * (ev.completed || 0) / ev.total) + '% ' : '') + ev.status; } } }
      if (err) throw new Error(err);
      el('mm-new').value = ''; el('mm-txt').textContent = 'Done.';
    } catch (e) { el('mm-txt').textContent = /fetch|network|dial|lookup/i.test(e.message) ? 'No internet connection. ' + e.message : e.message; }
    mmBusy = false; el('mm-go').disabled = false; loadMM(); loadModels();
  }
  function show(sec) {
    if (sec === 'models') loadMM();
    if (sec === 'tasks') loadTasks();
    if (sec === 'api') loadKeys();
    if (sec === 'projects') loadProjects();
    if (sec === 'memory') { el('m-on').checked = PF.memory !== false; loadMem(); } dlg.querySelectorAll('.setnav button').forEach(b => b.classList.toggle('on', b.dataset.s === sec)); dlg.querySelectorAll('.setpane section').forEach(s => { s.hidden = s.dataset.s !== sec; }); }
  el('setnav').onclick = e => { const b = e.target.closest('button'); if (b) show(b.dataset.s); };
  el('setx').innerHTML = window.ico ? ico('x') : '&times;'; el('setx').onclick = () => dlg.close();
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  el('gear').onclick = () => open('general');
  el('s-web').onchange = async () => { if (el('s-web').checked && !await UI.confirm('Searches and the pages the model opens will leave this Mac and go to the internet. Everything else stays local.', { title: 'Allow web access?', ok: 'Allow' })) { el('s-web').checked = false; return; } PF.web = el('s-web').checked; savePrefs(); };
  el('s-warn').onchange = () => { PF.warnheavy = el('s-warn').checked; savePrefs(); loadModels(); };
  el('s-speak').onchange = () => { PF.speak = el('s-speak').checked; savePrefs(); if (!PF.speak) stopSpeech(); };
  el('s-voice').onchange = () => { PF.voice = el('s-voice').value; savePrefs(); };
  el('s-enter').onchange = () => { PF.enter = el('s-enter').checked; savePrefs(); };
  el('s-tools').onchange = () => { settings.tools = el('s-tools').checked; el('tools').checked = settings.tools; saveSettings(); };
  el('s-think').onchange = () => { settings.think = el('s-think').value; el('think').value = settings.think; saveSettings(); el('think').dispatchEvent(new Event('change')); };
  el('s-model').onchange = () => { settings.model = el('s-model').value; el('model').value = settings.model; saveSettings(); el('model').dispatchEvent(new Event('change')); };
  for (const [id, k] of [['p-name', 'name'], ['p-about', 'about'], ['p-instr', 'instr']]) el(id).oninput = () => { PF[k] = el(id).value; savePrefs(); };
  el('mm-go').onclick = pullModel; el('mm-new').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); pullModel(); } };
  el('m-on').onchange = () => { PF.memory = el('m-on').checked; savePrefs(); };
  const addMem = async () => { const t = el('m-new').value.trim(); if (!t) return; el('m-new').value = ''; loadMem((await post('/api/memory', { text: t })).items); };
  el('m-add').onclick = addMem; el('m-new').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); addMem(); } };
  el('m-clear').onclick = async () => { if (await UI.confirm('Everything the model remembers about you will be erased.', { title: 'Clear memory?', ok: 'Clear', danger: true })) loadMem((await J('/api/memory?all=1', { method: 'DELETE' })).items); };
  el('p-reset').onclick = () => { Object.assign(PF, { name: '', about: '', style: 'default', instr: '' }); savePrefs(); fill(); };
  applySize();
})();
})();
