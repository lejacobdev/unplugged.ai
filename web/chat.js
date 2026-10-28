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
    ['chat', 'music', 'cover', 'console'].forEach(t => { el('tab-' + t).style.display = t === name ? '' : 'none'; });
    document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    el('side').classList.remove('open');
    { const t = el('tab-' + name); t.classList.remove('tab-in'); void t.offsetWidth; t.classList.add('tab-in'); }
    tabNow = name; saveView();
    if (name === 'cover') { checkImg(); loadHist(); }
    if (name === 'music') draw();
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
  const PF = Object.assign({ name: '', about: '', style: 'default', instr: S.system || '', size: 'm', enter: true, memory: true }, Store.get('prefs') || {});
  const savePrefs = () => Store.set('prefs', PF);
  const saveSettings = () => Store.set('chat-settings', settings);

  // ---------- models + status
  let modelLabels = {}, macDown = false, bannerText = '', bannerGone = '';
  // Banner can be closed with the x or by swiping it up; it stays closed until the message changes or goes away.
  function setBanner(text, force) {
    const b = el('banner');
    if (!text) { bannerGone = ''; bannerText = ''; b.style.display = 'none'; return; }
    if (text !== bannerText) { bannerText = text; b.innerHTML = '<span class="btxt"></span><button class="bclose" type="button" aria-label="Dismiss">' + (window.ico ? ico('x') : '&times;') + '</button>'; b.querySelector('.btxt').textContent = text; b.style.transform = ''; b.style.opacity = ''; }
    b.style.display = (bannerGone === text && !force) ? 'none' : 'flex';
  }
  function dismissBanner() {
    const b = el('banner'); bannerGone = bannerText;
    b.style.transition = 'transform .2s, opacity .2s'; b.style.transform = 'translateY(-120%)'; b.style.opacity = '0';
    setTimeout(() => { b.style.display = 'none'; b.style.transition = ''; b.style.transform = ''; b.style.opacity = ''; }, 200);
  }
  (() => {
    const b = el('banner'); let y0 = null, dy = 0;
    b.addEventListener('click', e => { if (e.target.closest('.bclose')) dismissBanner(); });
    b.addEventListener('touchstart', e => { y0 = e.touches[0].clientY; dy = 0; b.style.transition = 'none'; }, { passive: true });
    b.addEventListener('touchmove', e => { if (y0 === null) return; dy = Math.min(0, e.touches[0].clientY - y0); b.style.transform = `translateY(${dy}px)`; b.style.opacity = String(1 + dy / 120); }, { passive: true });
    b.addEventListener('touchend', () => { if (y0 === null) return; y0 = null; if (dy < -40) dismissBanner(); else { b.style.transition = 'transform .15s, opacity .15s'; b.style.transform = ''; b.style.opacity = ''; } });
  })();
  async function loadModels() {
    try {
      const s = await J('/api/chat/status'); macDown = false;
      setBanner(s.ok ? (s.training ? 'A heavy job (picture editing or training) is running on this Mac. The language model shares its memory, so chatting now will be slow and will slow that job down. For fast chat, wait until it finishes.' : '') : 'Ollama is not running, so there is no language model to chat with. Open the Ollama app (or run "ollama serve") and reload. The Music and Album cover tabs still work.');
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
  function renderList() {
    const day = 86400, now = Date.now() / 1000, groups = { Today: [], Yesterday: [], 'Previous 7 days': [], Older: [] };
    for (const c of chats) { const d = now - c.updated; (d < day ? groups.Today : d < 2 * day ? groups.Yesterday : d < 7 * day ? groups['Previous 7 days'] : groups.Older).push(c); }
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
    cur = await J('/api/chat/get?id=' + id); showTab('chat'); render(); renderList();
  }
  function newChat(incognito) { if (streaming) return; leaveIncognito(); cur = { id: null, messages: [], title: incognito === true ? 'Incognito chat' : 'New chat', incognito: incognito === true }; attached = null; renderAttach(); showTab('chat'); render(); renderList(); el('input').focus(); }
  el('newchat').onclick = () => newChat(false);
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
    const label = { generate_music: 'Making music', edit_picture: 'Editing picture', list_music: 'Looking up your music' }[name] || name;
    d.innerHTML = `<div class="h"><i></i>${running ? label + '…' : label}</div><div class="b"></div>`;
    const b = d.querySelector('.b');
    if (running) { b.textContent = args && Object.keys(args).length ? JSON.stringify(args) : ''; return d; }
    if (card && card.kind === 'music') {
      musicPlayer(b, card.id);
    } else if (card && card.kind === 'music_draft') {
      musicDraft(b, card);
    } else if (card && card.kind === 'music_job') {
      b.textContent = 'Starting…'; pollMusic(card.job, b);
    } else if (card && card.kind === 'image_job') {
      b.textContent = 'Starting…'; pollImage(card.job, b);
    } else b.textContent = (text || '').slice(0, 300);
    return d;
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
        txt.textContent = j.step ? `Editing… step ${j.step} of ${j.steps} · ${mmss(el)} elapsed` + (done > 2 ? ` · about ${mmss(el / done * (total - done))} left` : '') : `Loading the model… ${mmss(el)}`;
        if (j.preview) { prev.src = '/img/' + j.preview + '?n=' + j.preview_n; prev.style.display = ''; }
        await new Promise(r => setTimeout(r, 1500)); continue;
      }
      b.querySelector('.pbar').remove(); prev.remove();
      if (j.status === 'done') {
        const f = j.results[0];
        txt.textContent = `Done in ${mmss(Date.now() / 1000 - j.started)}.`;
        b.insertAdjacentHTML('beforeend', `<img src="/img/${f}">`);
        acts.innerHTML = `<a href="/img/${f}" download="${f}"><button>Download</button></a> <button class="cmp">Compare with original</button>`;
        acts.querySelector('.cmp').onclick = () => { showTab('cover'); showResult(j, 0); };
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
      if (m.content || m.thinking) wrap.insertAdjacentHTML('beforeend', `<div class="acts"><button data-a="c" title="Copy">${ico('copy')}</button>${last ? `<button data-a="g" title="Regenerate">${ico('refresh')}</button>` : ''}</div>`);
      wrap.querySelector('.acts')?.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.a === 'c') { navigator.clipboard.writeText(m.content || ''); b.innerHTML = ico('check'); setTimeout(() => b.innerHTML = ico('copy'), 1200); } if (b.dataset.a === 'g') send(null, true); });
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
      inner.innerHTML = `<div class="empty-chat"><img class="logo-big" src="/icons/icon-192.png" alt="" width="56" height="56"><h2>${cur.incognito ? 'Incognito chat' : `What can I help with${ME.kind === 'user' ? ', ' + esc(ME.name) : ''}?`}</h2><div>${cur.incognito ? 'This chat is not saved and disappears when you leave it. ' : ''}Everything here runs offline on your Mac, using ${esc(modelLabels[settings.model] || settings.model)}.</div>
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

  async function send(_e, regenerate = false) {
    stuck = true;
    if (streaming) return;
    const text = input.value.trim();
    if (!regenerate && !text && !attached && !files.length) return;
    if (macDown) { setBanner(bannerText, true); return; }
    if (!cur.id) { const c = await post('/api/chat/new', { model: settings.model, incognito: !!cur.incognito }); cur.id = c.id; }
    const body = { id: cur.id, model: settings.model, think: settings.think, tools: settings.tools, personal: { name: PF.name, about: PF.about, style: PF.style, instr: PF.instr }, memory: PF.memory !== false, regenerate };
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
    render(); loadList(); setTimeout(loadList, 6000); setTimeout(async () => { await loadList(); const c = chats.find(x => x.id === cur.id); if (c) { cur.title = c.title; setTitle(); } }, 12000);
  }

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
  loadModels(); loadList(); render();
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
    el('s-enter').checked = PF.enter; el('s-tools').checked = settings.tools; el('s-think').value = settings.think;
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
  function show(sec) {
    if (sec === 'memory') { el('m-on').checked = PF.memory !== false; loadMem(); } dlg.querySelectorAll('.setnav button').forEach(b => b.classList.toggle('on', b.dataset.s === sec)); dlg.querySelectorAll('.setpane section').forEach(s => { s.hidden = s.dataset.s !== sec; }); }
  el('setnav').onclick = e => { const b = e.target.closest('button'); if (b) show(b.dataset.s); };
  el('setx').innerHTML = window.ico ? ico('x') : '&times;'; el('setx').onclick = () => dlg.close();
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  el('gear').onclick = () => open('general');
  el('s-enter').onchange = () => { PF.enter = el('s-enter').checked; savePrefs(); };
  el('s-tools').onchange = () => { settings.tools = el('s-tools').checked; el('tools').checked = settings.tools; saveSettings(); };
  el('s-think').onchange = () => { settings.think = el('s-think').value; el('think').value = settings.think; saveSettings(); el('think').dispatchEvent(new Event('change')); };
  el('s-model').onchange = () => { settings.model = el('s-model').value; el('model').value = settings.model; saveSettings(); el('model').dispatchEvent(new Event('change')); };
  for (const [id, k] of [['p-name', 'name'], ['p-about', 'about'], ['p-instr', 'instr']]) el(id).oninput = () => { PF[k] = el(id).value; savePrefs(); };
  el('m-on').onchange = () => { PF.memory = el('m-on').checked; savePrefs(); };
  const addMem = async () => { const t = el('m-new').value.trim(); if (!t) return; el('m-new').value = ''; loadMem((await post('/api/memory', { text: t })).items); };
  el('m-add').onclick = addMem; el('m-new').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); addMem(); } };
  el('m-clear').onclick = async () => { if (await UI.confirm('Everything the model remembers about you will be erased.', { title: 'Clear memory?', ok: 'Clear', danger: true })) loadMem((await J('/api/memory?all=1', { method: 'DELETE' })).items); };
  el('p-reset').onclick = () => { Object.assign(PF, { name: '', about: '', style: 'default', instr: '' }); savePrefs(); fill(); };
  applySize();
})();
})();
