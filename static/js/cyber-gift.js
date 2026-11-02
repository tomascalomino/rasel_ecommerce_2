(() => {
  const config = document.getElementById('cyber-gift-state');
  const script = document.querySelector('script[data-status-url]');
  if (!config || !script) return;
  let state;
  try { state = JSON.parse(config.textContent); } catch (_) { return; }
  let received = performance.now();
  let timer;
  let pending = false;
  let wasActive = state.active;
  const blocks = document.querySelectorAll('[data-cyber-gift]');
  const serverNow = () => Date.parse(state.server_now) + performance.now() - received;

  function display() {
    const active = state.active && serverNow() < Date.parse(state.ends_at);
    blocks.forEach(block => { block.hidden = !active; });
    if (active) {
      document.querySelectorAll('img[data-gift-src]').forEach(img => {
        if (!img.getAttribute('src')) img.src = img.dataset.giftSrc;
      });
    }
    document.querySelectorAll('[data-gift-ended]').forEach(note => {
      note.hidden = active || !wasActive;
    });
    wasActive = wasActive || active;
    clearTimeout(timer);
    const untilEnd = Date.parse(state.ends_at) - serverNow();
    timer = setTimeout(() => { display(); refresh(); },
      active ? Math.max(1, Math.min(60000, untilEnd)) : 60000);
  }

  async function refresh() {
    if (pending || document.hidden) return;
    pending = true;
    try {
      const response = await fetch(script.dataset.statusUrl, {cache: 'no-store', credentials: 'same-origin'});
      if (!response.ok) return;
      const next = await response.json();
      if (typeof next.active !== 'boolean' || !Number.isFinite(Date.parse(next.server_now)) || !Number.isFinite(Date.parse(next.ends_at))) return;
      state = next;
      received = performance.now();
      display();
    } catch (_) { /* El checkout vuelve a validar en el servidor. */ }
    finally { pending = false; }
  }
  display();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { display(); refresh(); } });
  window.addEventListener('pageshow', () => { display(); refresh(); });
})();
