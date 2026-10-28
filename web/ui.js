// Custom controls: replaces the browser's built-in dropdowns and sliders with ones styled like the rest of the app.
// The real <select>/<input> elements stay in the page (hidden), so all existing code keeps working unchanged.
(function () {
  const chev = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
  const tick = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5 10 17.5 19 7.5"/></svg>';
  let openDD = null;

  function closeMenu() {
    if (!openDD) return;
    openDD.menu.remove(); openDD.btn.setAttribute('aria-expanded', 'false'); openDD.root.classList.remove('open'); openDD = null;
  }

  function enhanceSelect(sel) {
    if (sel.dataset.dd || sel.hidden || sel.closest('[hidden]')) return;
    sel.dataset.dd = '1';
    const root = document.createElement('div'); root.className = 'dd';
    const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'dd-btn'; btn.setAttribute('aria-haspopup', 'listbox'); btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = '<span class="dd-label"></span>' + chev;
    sel.parentNode.insertBefore(root, sel); root.appendChild(btn); root.appendChild(sel); sel.classList.add('dd-native'); sel.tabIndex = -1;
    const label = btn.querySelector('.dd-label');
    const sync = () => { const o = sel.options[sel.selectedIndex]; const t = o ? o.textContent : ''; if (label.textContent !== t) label.textContent = t; btn.disabled = sel.disabled; };
    sync(); sel._ddSync = sync;

    function open() {
      closeMenu();
      const menu = document.createElement('div'); menu.className = 'dd-menu'; menu.setAttribute('role', 'listbox');
      [...sel.options].forEach((o, i) => {
        const it = document.createElement('div'); it.className = 'dd-item' + (i === sel.selectedIndex ? ' sel' : ''); it.setAttribute('role', 'option'); it.dataset.i = i;
        const desc = o.dataset.desc ? '<small>' + o.dataset.desc.replace(/</g, '&lt;') + '</small>' : '';
        it.innerHTML = '<span class="dd-text"><span>' + o.textContent.replace(/</g, '&lt;') + '</span>' + desc + '</span>' + (i === sel.selectedIndex ? tick : '');
        it.onclick = () => { sel.selectedIndex = i; sel.dispatchEvent(new Event('input', { bubbles: true })); sel.dispatchEvent(new Event('change', { bubbles: true })); sync(); closeMenu(); btn.focus(); };
        menu.appendChild(it);
      });
      (btn.closest('dialog') || document.body).appendChild(menu);  // inside an open dialog, or it would sit under the dialog (top layer)
      const r = btn.getBoundingClientRect(), mh = Math.min(menu.scrollHeight, 320), below = innerHeight - r.bottom - 12, up = below < mh && r.top > below;
      menu.style.minWidth = r.width + 'px'; menu.style.left = Math.max(8, Math.min(r.left, innerWidth - Math.max(r.width, 200) - 8)) + 'px';
      menu.style.maxHeight = Math.max(140, Math.min(320, up ? r.top - 12 : below)) + 'px';
      if (up) menu.style.bottom = (innerHeight - r.top + 6) + 'px'; else menu.style.top = (r.bottom + 6) + 'px';
      if (menu.parentNode !== document.body) {  // a dialog can be the containing block for fixed children: shift by however far the menu landed from where it was meant to be
        const m = menu.getBoundingClientRect(), wantTop = up ? r.top - 6 - m.height : r.bottom + 6, wantLeft = Math.max(8, Math.min(r.left, innerWidth - Math.max(r.width, 200) - 8));
        const dx = wantLeft - m.left, dy = wantTop - m.top;
        if (Math.abs(dx) > 1) menu.style.left = (parseFloat(menu.style.left) + dx) + 'px';
        if (Math.abs(dy) > 1) { if (up) menu.style.bottom = (parseFloat(menu.style.bottom) - dy) + 'px'; else menu.style.top = (parseFloat(menu.style.top) + dy) + 'px'; }
      }
      btn.setAttribute('aria-expanded', 'true'); root.classList.add('open'); openDD = { menu, btn, root, sel };
      menu.querySelector('.sel')?.scrollIntoView({ block: 'nearest' });
    }
    btn.onclick = e => { e.stopPropagation(); openDD && openDD.btn === btn ? closeMenu() : open(); };
    btn.onkeydown = e => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); const n = Math.max(0, Math.min(sel.options.length - 1, sel.selectedIndex + (e.key === 'ArrowDown' ? 1 : -1))); sel.selectedIndex = n; sel.dispatchEvent(new Event('change', { bubbles: true })); sync(); }
      else if (e.key === 'Escape') closeMenu();
    };
    new MutationObserver(sync).observe(sel, { childList: true, subtree: true, characterData: true });
  }

  function paintRange(r) {
    const min = +r.min || 0, max = +r.max || 100, v = +r.value;
    r.style.setProperty('--p', (max > min ? (v - min) / (max - min) * 100 : 0) + '%');
  }
  function enhanceRange(r) { if (r.dataset.rg) return; r.dataset.rg = '1'; paintRange(r); r.addEventListener('input', () => paintRange(r)); }

  function scan(root) {
    (root || document).querySelectorAll('select:not([data-dd])').forEach(enhanceSelect);
    (root || document).querySelectorAll('input[type=range]:not([data-rg])').forEach(enhanceRange);
  }
  document.addEventListener('click', e => { if (openDD && !openDD.menu.contains(e.target)) closeMenu(); }, true);
  addEventListener('resize', closeMenu); addEventListener('blur', closeMenu);
  document.addEventListener('scroll', e => { if (openDD && !openDD.menu.contains(e.target)) closeMenu(); }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
  new MutationObserver(() => scan()).observe(document.documentElement, { childList: true, subtree: true });
  // programmatic changes (code setting .value) don't fire events: keep the custom controls in step
  setInterval(() => { document.querySelectorAll('select[data-dd]').forEach(s => s._ddSync && s._ddSync()); document.querySelectorAll('input[type=range][data-rg]').forEach(paintRange); }, 400);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => scan()); else scan();
})();

// In-app dialogs that replace the browser's prompt(), confirm() and alert(). Each returns a promise.
//   UI.confirm(message, {title, ok, danger})  -> true / false
//   UI.alert(message, {title})                -> resolves when closed
//   UI.prompt(title, {value, label, ok, type, message, placeholder}) -> string, or null when cancelled
window.UI = (function () {
  function open(o) {
    return new Promise(resolve => {
      const d = document.createElement('dialog'); d.className = 'askdlg';
      const form = document.createElement('form'); form.method = 'dialog';
      const h = document.createElement('h3'); h.textContent = o.title || ''; if (o.title) form.appendChild(h);
      if (o.message) { const p = document.createElement('p'); p.textContent = o.message; form.appendChild(p); }
      let inp = null;
      if (o.input) {
        if (o.label) { const l = document.createElement('label'); l.textContent = o.label; form.appendChild(l); }
        inp = document.createElement('input'); inp.type = o.type || 'text'; inp.value = o.value || ''; inp.placeholder = o.placeholder || '';
        inp.autocomplete = o.type === 'password' ? 'off' : 'on'; form.appendChild(inp);
      }
      const row = document.createElement('div'); row.className = 'askrow';
      let cancel = null;
      if (!o.noCancel) { cancel = document.createElement('button'); cancel.type = 'button'; cancel.textContent = 'Cancel'; row.appendChild(cancel); }
      const ok = document.createElement('button'); ok.type = 'submit'; ok.className = 'primary' + (o.danger ? ' danger' : ''); ok.textContent = o.ok || 'OK'; row.appendChild(ok);
      form.appendChild(row); d.appendChild(form); document.body.appendChild(d);
      let result = o.input ? null : false, settled = false;
      const end = () => { if (settled) return; settled = true; d.close(); d.remove(); resolve(result); };
      form.onsubmit = e => { e.preventDefault(); result = o.input ? inp.value : true; end(); };
      if (cancel) cancel.onclick = () => { result = o.input ? null : false; end(); };
      d.addEventListener('cancel', e => { e.preventDefault(); result = o.input ? null : false; end(); });
      d.addEventListener('click', e => { if (e.target === d && cancel) { result = o.input ? null : false; end(); } });
      d.showModal();
      if (inp) { inp.focus(); inp.select(); } else ok.focus();
    });
  }
  return {
    confirm: (message, o = {}) => open({ title: o.title || 'Are you sure?', message, ok: o.ok || 'OK', danger: o.danger }),
    alert: (message, o = {}) => open({ title: o.title || '', message, ok: 'OK', noCancel: true }).then(() => {}),
    prompt: (title, o = {}) => open({ title, input: true, ...o }),
  };
})();
