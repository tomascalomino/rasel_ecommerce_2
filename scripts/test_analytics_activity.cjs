// Browser-independent regression tests for visibility timing and payload privacy.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/js/analytics-activity.js'), 'utf8');

function browser(visibilityState = 'visible') {
  let now = 0, next = 0;
  const timers = new Map(), events = {}, calls = [];
  const document = {
    visibilityState,
    querySelector: () => ({content: 'signed-page-token', dataset: {endpoint: '/analytics/activity/', csrf: 'csrf-token'}}),
    addEventListener: (name, handler) => { events[name] = handler; },
  };
  const fetch = (url, options) => { calls.push({url, ...options}); return Promise.resolve({status: 204}); };
  vm.runInNewContext(source, {
    document, fetch, performance: {now: () => now},
    window: {fetch, addEventListener: (name, handler) => { events[name] = handler; }},
    setTimeout: (fn, delay) => { timers.set(++next, {fn, at: now + delay}); return next; },
    clearTimeout: id => timers.delete(id),
  });
  return {
    document, events, calls,
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
    },
    visibility(value) { document.visibilityState = value; events.visibilitychange(); },
  };
}

const hidden = browser('hidden');
hidden.advance(60000);
assert.equal(hidden.calls.length, 0);
hidden.visibility('visible');
hidden.advance(4000);
hidden.visibility('hidden');
hidden.advance(60000);
assert.equal(hidden.calls.length, 0);
hidden.visibility('visible');
hidden.advance(6500);
assert.equal(hidden.calls.length, 1);
assert.deepEqual(JSON.parse(hidden.calls[0].body), {event: 'visible', token: 'signed-page-token'});

const interaction = browser();
interaction.events.click({isTrusted: false});
assert.equal(interaction.calls.length, 0);
interaction.events.pointerdown({isTrusted: true});
interaction.events.click({isTrusted: true});
interaction.advance(20000);
assert.equal(interaction.calls.length, 1);
assert.equal(JSON.parse(interaction.calls[0].body).event, 'interaction');

const restored = browser();
restored.advance(4000);
restored.events.pagehide();
restored.advance(60000);
restored.events.pageshow();
assert.equal(restored.calls.length, 0);
restored.advance(6500);
assert.equal(restored.calls.length, 1);

const prerender = browser('hidden');
prerender.document.prerendering = true;
prerender.visibility('visible');
prerender.advance(20000);
assert.equal(prerender.calls.length, 0);
prerender.document.prerendering = false;
prerender.events.prerenderingchange();
prerender.advance(10500);
assert.equal(prerender.calls.length, 1);
console.log('Activity script: visibility, interaction, restoration and prerender checks passed.');
