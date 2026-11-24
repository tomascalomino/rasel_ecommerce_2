// Shipping UI regression: stale AJAX replies, pickup switches and safe content.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/checkout.js'), 'utf8');
class CustomEvent {constructor(type) {this.type = type;}}

function browser(overrides = {}, clock = Date) {
  function element(value = '') {
    return {value, textContent: '', hidden: false, children: [], events: {},
      classList: {toggle() {}}, closest() {return this;},
      addEventListener(name, fn) {const previous = this.events[name]; this.events[name] = previous ? (...args) => {previous(...args); fn(...args);} : fn;},
      appendChild(child) {this.children.push(child);}, replaceChildren() {this.children = [];},
    };
  }
  const ids = {};
  for (const id of ['id_postal_code', 'ship-confirm', 'sum-subtotal', 'sum-shipping', 'payment-discount-row', 'sum-payment-discount', 'coupon-discount-row', 'sum-coupon-discount', 'sum-total', 'sum-total-label', 'cod-hint', 'ship-fields', 'pickup-fields', 'id_shipping_quote_token']) ids[id] = element();
  const summary = element();
  const attrs = {'data-subtotal': '7780', 'data-offline-discount': '780', 'data-discount-percent': '10', 'data-quote-url': '/shipping/quote/', 'data-shop-url': '/shop/'};
  Object.assign(attrs, overrides);
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
  vm.runInNewContext(source, {document, Intl, Number, Date: clock, sessionStorage: {getItem: () => '{}', setItem() {}},
    setTimeout(fn) {timers.set(++timerId, fn); return timerId;}, clearTimeout(id) {timers.delete(id);},
    fetch(url) {return new Promise((resolve, reject) => calls.push({url, resolve, reject}));},
  });
  return {ids, calls, events,
    pay(method) {payment.forEach(r => {r.checked = r.value === method;}); payment.find(r => r.checked).events.change();},
    cp(value) {ids.id_postal_code.value = value; ids.id_postal_code.events.input(); for (const [id, fn] of [...timers]) {timers.delete(id); fn();}},
    pickup() {delivery[0].checked = false; delivery[1].checked = true; delivery[1].events.change();},
  };
}

const quote = (token, cost = '0.00', promotion = {url: '/promociones/demo/'}) => ({ok: true, cp: 1425, cost, free: cost === '0.00', cod_allowed: true, location_label: '<img onerror=attack()>', zone_name: 'CABA', promotion, quote_token: token});
async function reply(call, data) {call.resolve({ok: true, json: () => Promise.resolve(data)}); await new Promise(setImmediate);}

async function promotionBoundary() {
  let now = Date.parse('2026-10-04T12:00:00Z');
  const end = '2026-10-04T12:01:00Z';
  const campaign = {id: 1, url: '/promociones/demo/', state: 'active', dates: 'Del 04/10 al 04/10', ends_at: end};
  const parts = {'a': {}, '[data-promotion-heading]': {}, '[data-promotion-copy]': {}};
  const banner = {hidden: false, querySelector: key => parts[key]};
  const infoParts = {'a': {}, '[data-promotion-heading]': {}, '[data-promotion-copy]': {}};
  const info = {hidden: false, querySelector: key => infoParts[key]};
  const detail = {dataset: {}};
  const events = {}, timers = [];
  let statusRequests = 0;
  class Clock extends Date {static now() {return now;}}
  const config = {textContent: JSON.stringify({status_url: '/shipping/promotion-status/', state: {server_now: new Date(now).toISOString(), campaign, detail: campaign, next_change_at: end}})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/shipping-promotion.js'), 'utf8'), {
    Date: Clock, CustomEvent,
    document: {hidden: false, getElementById: id => ({'shipping-promotion-config': config, 'shipping-promotion-banner': banner, 'shipping-promotion-info': info})[id], querySelector: () => detail, addEventListener: (name, fn) => {events[name] = fn;}, dispatchEvent() {}},
    window: {addEventListener: (name, fn) => {events[name] = fn;}},
    setTimeout: fn => {timers.push(fn); return timers.length;}, clearTimeout() {},
    fetch: () => {statusRequests++; return Promise.reject(new Error('offline'));},
  });
  assert.equal(banner.hidden, false);
  assert.equal(parts['[data-promotion-copy]'].textContent, 'Sin mínimo de compra');
  events.pageshow({persisted: false});
  assert.equal(statusRequests, 0);
  events.pageshow({persisted: true});
  assert.equal(statusRequests, 0);
  now = Date.parse(end);
  timers[0]();
  await new Promise(setImmediate);
  assert.equal(statusRequests, 1);
  assert.equal(banner.hidden, true);
  assert.equal(info.hidden, true);
  assert.equal(detail.textContent, 'Promoción finalizada');
}

async function promotionAndQuoteRefresh() {
  let now = Date.parse('2026-10-04T12:00:00Z');
  class Clock extends Date {static now() {return now;}}
  const start = new Date(now + 30000).toISOString();
  const end = new Date(now + 240000).toISOString();
  const active = {id: 7, url: '/promociones/demo/', state: 'active', ends_at: end};
  const state = (campaign, next = null) => ({server_now: new Date(now).toISOString(), campaign, next_change_at: next});
  const config = {textContent: JSON.stringify({status_url: '/shipping/promotion-status/', state: state(null, start)})};
  const checkout = browser({}, Clock);
  checkout.cp('1425');
  await reply(checkout.calls[0], quote('normal', '3000', null));
  const events = {}, status = [], timers = new Map();
  let nextTimer = 0;
  const document = {
    hidden: false, getElementById: id => id === 'shipping-promotion-config' ? config : null,
    querySelector: () => null, addEventListener: (name, callback) => {events[name] = callback;},
    dispatchEvent: event => checkout.events[event.type]?.(),
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/js/shipping-promotion.js'), 'utf8'), {
    Date: Clock, document, CustomEvent,
    window: {addEventListener: (name, callback) => {events[name] = callback;}},
    setTimeout(fn) {timers.set(++nextTimer, fn); return nextTimer;},
    clearTimeout(id) {timers.delete(id);},
    fetch(url) {return new Promise((resolve, reject) => status.push({url, resolve, reject}));},
  });
  function resume() {
    events.visibilitychange();
    events.pageshow({persisted: true});
  }

  resume();
  assert.equal(status.length, 0);
  assert.equal(checkout.calls.length, 1);

  now = Date.parse(start) + 100;
  timers.values().next().value();
  resume();
  assert.equal(status.length, 1);
  await reply(status[0], state(active, end));
  assert.equal(checkout.calls.length, 2);
  await reply(checkout.calls[1], quote('starts'));

  now += 60000;
  resume();
  assert.equal(status.length, 2);
  await reply(status[1], state(active, end));
  assert.equal(checkout.calls.length, 2);

  now += 60000;
  resume();
  await reply(status[2], state({...active, state: 'suspended'}, end));
  assert.equal(checkout.calls.length, 3);
  await reply(checkout.calls[2], quote('suspended', '3000', null));

  now = Date.parse(end) + 100;
  timers.values().next().value();
  await reply(status[3], state(null));
  assert.equal(checkout.calls.length, 3);

  now += 5 * 60000;
  resume();
  await reply(status[4], state(null));
  assert.equal(checkout.calls.length, 4);
  await reply(checkout.calls[3], quote('renewed', '3000', null));
  resume();
  assert.equal(status.length, 5);
  assert.equal(checkout.calls.length, 4);
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
  await promotionAndQuoteRefresh();
  const combined = browser({'data-subtotal':'21000', 'data-offline-discount':'2100', 'data-coupon-mp':'4000', 'data-coupon-offline':'3600'});
  combined.pickup();
  assert.equal(combined.ids['sum-total'].textContent, '$ 15.300');
  assert.equal(combined.ids['sum-coupon-discount'].textContent, '− $ 3.600');
  combined.pay('mp');
  assert.equal(combined.ids['sum-total'].textContent, '$ 17.000');
  assert.equal(combined.ids['payment-discount-row'].hidden, true);
  combined.pay('cod');
  assert.equal(combined.ids['sum-total'].textContent, '$ 15.300');
  const better = browser({'data-subtotal':'21000', 'data-offline-discount':'2100', 'data-coupon-mp':'1000', 'data-coupon-offline':'0'});
  better.pickup();
  assert.equal(better.ids['sum-total'].textContent, '$ 18.900');
  assert.equal(better.ids['coupon-discount-row'].hidden, true);
  better.pay('mp');
  assert.equal(better.ids['sum-total'].textContent, '$ 20.000');
  assert.equal(better.ids['coupon-discount-row'].hidden, false);
  console.log('Shipping checkout scenarios passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
