// Shipping UI regression: stale AJAX replies, pickup switches and safe content.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/checkout.js'), 'utf8');

function browser() {
  function element(value = '') {
    return {value, textContent: '', hidden: false, children: [], events: {},
      classList: {toggle() {}}, closest() {return this;},
      addEventListener(name, fn) {const previous = this.events[name]; this.events[name] = previous ? (...args) => {previous(...args); fn(...args);} : fn;},
      appendChild(child) {this.children.push(child);}, replaceChildren() {this.children = [];},
    };
  }
  const ids = {};
  for (const id of ['id_postal_code', 'ship-confirm', 'sum-subtotal', 'sum-shipping', 'payment-discount-row', 'sum-payment-discount', 'sum-total', 'sum-total-label', 'cod-hint', 'ship-fields', 'pickup-fields', 'id_shipping_quote_token']) ids[id] = element();
  const summary = element();
  const attrs = {'data-subtotal': '7780', 'data-offline-discount': '780', 'data-discount-percent': '10', 'data-quote-url': '/shipping/quote/', 'data-shop-url': '/shop/'};
  summary.getAttribute = key => attrs[key];
  const payment = [element('mp'), element('transfer'), element('cod')];
  payment[1].checked = true;
  const delivery = [element('ship'), element('pickup')];
  delivery[0].checked = true;
  const calls = [], timers = new Map(), events = {};
  let timerId = 0;
  const document = {
    getElementById: key => ids[key] || null,
    createElement: () => element(),
    addEventListener: (name, fn) => {events[name] = fn;},
    querySelectorAll: selector => selector.includes('payment_method') ? payment : delivery,
    querySelector(selector) {
      if (selector === '.ship-summary') return summary;
      if (selector.includes('delivery_method')) return delivery.find(r => r.checked);
      if (selector.includes('value="cod"')) return payment[2];
      if (selector.includes(':checked')) return payment.find(r => r.checked);
      return payment.find(r => !r.disabled);
    },
  };
  vm.runInNewContext(source, {document, Intl, Number, sessionStorage: {getItem: () => '{}', setItem() {}},
    setTimeout(fn) {timers.set(++timerId, fn); return timerId;}, clearTimeout(id) {timers.delete(id);},
    fetch(url) {return new Promise((resolve, reject) => calls.push({url, resolve, reject}));},
  });
  return {ids, calls, events,
    cp(value) {ids.id_postal_code.value = value; ids.id_postal_code.events.input(); for (const [id, fn] of [...timers]) {timers.delete(id); fn();}},
    pickup() {delivery[0].checked = false; delivery[1].checked = true; delivery[1].events.change();},
  };
}

const quote = (token, cost = '0.00', promotion = {url: '/promociones/demo/'}) => ({ok: true, cp: 1425, cost, free: cost === '0.00', cod_allowed: true, location_label: '<img onerror=attack()>', zone_name: 'CABA', promotion, quote_token: token});
async function reply(call, data) {call.resolve({ok: true, json: () => Promise.resolve(data)}); await new Promise(setImmediate);}

async function promotionBoundary() {
  let now = Date.parse('2026-10-04T12:00:00Z');
  const end = '2026-10-04T12:01:00Z';
  const campaign = {url: '/promociones/demo/', state: 'active', dates: 'Del 04/10 al 04/10', ends_at: end};
  const parts = {'a': {}, '[data-promotion-heading]': {}, '[data-promotion-copy]': {}};
  const banner = {hidden: false, querySelector: key => parts[key]};
  const info = {hidden: false, querySelector: key => parts[key]};
  const detail = {dataset: {}};
  const events = {}, timers = [];
  class Clock extends Date {static now() {return now;}}
  const config = {textContent: JSON.stringify({status_url: '/shipping/promotion-status/', state: {server_now: new Date(now).toISOString(), campaign, detail: campaign, next_change_at: end}})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/shipping-promotion.js'), 'utf8'), {
    Date: Clock,
    document: {hidden: false, getElementById: id => ({'shipping-promotion-config': config, 'shipping-promotion-banner': banner, 'shipping-promotion-info': info})[id], querySelector: () => detail, addEventListener: (name, fn) => {events[name] = fn;}, dispatchEvent() {}},
    window: {addEventListener: (name, fn) => {events[name] = fn;}},
    setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {},
    fetch: () => Promise.reject(new Error('offline')),
  });
  assert.equal(banner.hidden, false);
  now = Date.parse(end);
  timers[0]();
  await new Promise(setImmediate);
  assert.equal(banner.hidden, true);
  assert.equal(info.hidden, true);
  assert.equal(detail.textContent, 'Promoción finalizada');
}

(async () => {
  const b = browser();
  b.cp('1425');
  b.cp('1744');
  assert.equal(b.ids.id_shipping_quote_token.value, '');
  await reply(b.calls[1], quote('new', '7000', null));
  assert.equal(b.ids['sum-shipping'].textContent, '$ 7.000');
  await reply(b.calls[0], quote('stale'));
  assert.equal(b.ids.id_shipping_quote_token.value, 'new');
  assert.equal(b.ids['sum-total'].textContent, '$ 14.000');

  b.cp('1425');
  b.pickup();
  await reply(b.calls[2], quote('ignored-pickup'));
  assert.equal(b.ids['sum-shipping'].textContent, 'Retiro sin cargo');
  assert.equal(b.ids.id_shipping_quote_token.value, '');

  const safe = browser();
  safe.cp('1425');
  await reply(safe.calls[0], quote('valid'));
  assert.equal(safe.ids['sum-shipping'].textContent, 'Gratis · promoción CABA');
  assert.equal(safe.ids['ship-confirm'].children[0].textContent, '<img onerror=attack()> — Envío gratis');
  assert.equal(safe.ids['ship-confirm'].innerHTML, undefined);
  safe.cp('1426');
  safe.calls[1].reject(new Error('offline'));
  await new Promise(setImmediate);
  assert.equal(safe.ids.id_shipping_quote_token.value, '');
  assert.equal(safe.ids['sum-total-label'].textContent, 'Total estimado');
  await promotionBoundary();
  console.log('Shipping checkout scenarios passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
