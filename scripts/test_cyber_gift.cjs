const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  let elapsed = 0;
  const state = {active: true, server_now: '2026-11-09T02:58:00Z', ends_at: '2026-11-09T03:00:00Z'};
  const blocks = [{hidden: false}, {hidden: false}];
  const notes = [{hidden: true}];
  const image = {dataset: {giftSrc: '/static/img/mini.jpg'}, getAttribute() {return this.src;}};
  const events = {}, timers = new Map();
  let timerId = 0;
  const fetches = [];
  const document = {
    hidden: false,
    getElementById: () => ({textContent: JSON.stringify(state)}),
    querySelector: () => ({dataset: {statusUrl: '/shop/gift-status/'}}),
    querySelectorAll: selector => selector === '[data-cyber-gift]' ? blocks : selector === '[data-gift-ended]' ? notes : [image],
    addEventListener: (name, fn) => {events[name] = fn;},
  };
  vm.runInNewContext(fs.readFileSync('static/js/cyber-gift.js', 'utf8'), {
    document, window: {addEventListener: (name, fn) => {events[name] = fn;}},
    performance: {now: () => elapsed}, Date, Number,
    setTimeout: (fn, delay) => {timers.set(++timerId, {fn, delay}); return timerId;},
    clearTimeout: id => timers.delete(id),
    fetch: () => new Promise((resolve, reject) => fetches.push({resolve, reject})),
  });
  assert.equal(image.src, '/static/img/mini.jpg');
  events.pageshow({persisted: false});
  assert.equal(fetches.length, 0, 'el HTML ya trae el estado inicial');
  assert.equal([...timers.values()][0].delay, 60000);
  elapsed = 60000;
  [...timers.values()][0].fn();
  assert.equal(fetches.length, 1, 'se refresca durante la campaña');
  elapsed = 120000;
  [...timers.values()][0].fn();
  assert.ok(blocks.every(block => block.hidden));
  assert.equal(notes[0].hidden, false);
  assert.equal(timers.size, 0);
  fetches[0].resolve({ok: true, json: async () => ({...state, server_now: '2026-11-09T02:59:00Z'})});
  await new Promise(setImmediate);
  assert.ok(blocks.every(block => block.hidden), 'una respuesta atrasada no restaura el regalo');
  events.pageshow({persisted: true});
  events.visibilitychange();
  assert.equal(fetches.length, 1, 'el cierre cancela las consultas incluso al volver a la pestaña');
  assert.equal(timers.size, 0);
  assert.equal(notes[0].hidden, false);
  console.log('Cyber gift: cierre local y ausencia de consultas tras vencer OK');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
