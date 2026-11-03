// Exercise request failure and duplicate-submit behavior without external requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/cart-add.js', 'utf8');

function browser({supported = true} = {}) {
  const requests = [], formEvents = {}, dialogEvents = {}, documentEvents = {};
  const badge = {textContent: '0'};
  const error = {hidden: true, textContent: '', appendChild(link) { this.link = link; }};
  const submit = {innerHTML: 'Agregar', disabled: false, isConnected: true, focus() { this.focused = true; }};
  const checkout = {focus() { this.focused = true; }};
  const content = {querySelector: selector => selector === '[data-cart-added-checkout]' ? checkout : {href: '/cart/'}};
  const dialog = {
    querySelector: selector => selector === '[data-cart-added-content]' ? content : {addEventListener() {}},
    addEventListener: (name, fn) => { dialogEvents[name] = fn; },
    showModal: supported ? function () { this.open = true; } : undefined,
    close() { this.open = false; dialogEvents.close(); },
  };
  const form = {
    action: '/cart/add/',
    querySelector: selector => selector === 'button[type="submit"]' ? submit : error,
    addEventListener: (name, fn) => { formEvents[name] = fn; },
    closest: () => null,
    setAttribute() {}, removeAttribute() {},
  };
  const classes = new Set();
  const document = {
    getElementById: () => dialog,
    querySelectorAll: selector => selector === '[data-cart-add-form]' ? [form] : [badge],
    addEventListener: (name, fn) => { documentEvents[name] = fn; },
    dispatchEvent(event) { this.lastEvent = event; },
    createElement: () => ({}),
    documentElement: {classList: {add: name => classes.add(name), remove: name => classes.delete(name)}},
  };
  const window = {fetch: true, addEventListener() {}};
  const fetch = (url, options) => new Promise((resolve, reject) => requests.push({url, options, resolve, reject}));
  let timeout;
  vm.runInNewContext(source, {
    document, window, fetch, AbortController,
    FormData: class {}, CustomEvent: class {constructor(name, init) { this.type = name; this.detail = init.detail; }},
    setTimeout: fn => { timeout = fn; return 1; }, clearTimeout() {},
  });
  documentEvents.DOMContentLoaded();
  return {
    requests, dialog, badge, submit, error, content, checkout, document, formEvents, classes,
    send: () => formEvents.submit({preventDefault() {}}),
    timeout: () => timeout(),
  };
}

(async () => {
  const success = browser();
  const pending = success.send();
  await success.send();
  assert.equal(success.requests.length, 1, 'Double tap sends only one POST');
  assert.equal(success.submit.disabled, true);
  success.requests[0].resolve({ok: true, json: async () => ({html: '<p>Confirmed</p>', cart_quantity: 3, meta_events: [{token: 'signed'}]})});
  await pending;
  assert.equal(success.dialog.open, true);
  assert.equal(success.badge.textContent, 3);
  assert.equal(success.checkout.focused, true);
  assert.equal(success.submit.disabled, false);
  assert.equal(success.document.lastEvent.type, 'rasel:cart-added');
  success.dialog.close();
  assert.equal(success.submit.focused, true);
  assert.equal(success.classes.size, 0);

  const invalid = browser();
  const rejected = invalid.send();
  invalid.requests[0].resolve({ok: false, json: async () => ({error: 'No hay stock suficiente.'})});
  await rejected;
  assert.equal(invalid.error.hidden, false);
  assert.equal(invalid.error.textContent, 'No hay stock suficiente.');
  assert.ok(!invalid.dialog.open);

  const lost = browser();
  const missingResponse = lost.send();
  lost.timeout();
  assert.equal(lost.requests[0].options.signal.aborted, true);
  lost.requests[0].reject(new Error('Response lost after POST'));
  await missingResponse;
  assert.equal(lost.requests.length, 1, 'An uncertain POST is never retried automatically');
  assert.equal(lost.error.hidden, false);
  assert.equal(lost.error.link.href, '/cart/');
  assert.equal(lost.submit.disabled, false);

  const unsupported = browser({supported: false});
  assert.equal(unsupported.formEvents.submit, undefined, 'Unsupported dialogs keep native form submission');
  console.log('Cart add: duplicate submit, confirmation, focus, stock errors, timeout, uncertain response and native fallback passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
