// No external requests: exercise browser consent, navigation, and confirmed actions in a VM.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/meta-marketing.js'), 'utf8');

function browser({state = 'unknown', pixelEnabled = true, product = false, events = []} = {}) {
  let serverState = state;
  let requests = [], inserted = [], cookies = [], claimed = new Set();
  const windowEvents = {}, documentEvents = {};
  const banner = {hidden: state !== 'unknown', style: {}, scrollIntoView() {}, querySelector: () => accept};
  const status = {textContent: ''};
  const close = {hidden: state === 'unknown', addEventListener: (name, fn) => { close[name] = fn; }};
  const button = choice => ({
    dataset: {metaChoice: choice}, disabled: false,
    addEventListener(name, fn) { this[name] = fn; }, focus() {},
  });
  const accept = button('accept'), reject = button('reject');
  const preference = {addEventListener(name, fn) { this[name] = fn; }};
  const configuration = {
    state, pixelId: '1400536168898337', pixelEnabled, product, events,
    csrf: 'signed-csrf-placeholder', pageToken: 'signed-page-placeholder',
    consentEndpoint: '/marketing/consent/', claimEndpoint: '/marketing/claim/',
  };
  const select = {options: [{value: '42', dataset: {price: '7400'}, disabled: false}], selectedIndex: 0};
  const document = {
    visibilityState: 'visible',
    getElementById: id => id === 'rasel-meta-config' ? {textContent: JSON.stringify(configuration)} : select,
    querySelector: selector => ({'[data-meta-banner]': banner, '[data-meta-status]': status, '[data-meta-close]': close}[selector]),
    querySelectorAll: selector => selector === '[data-meta-choice]' ? [accept, reject] : [preference],
    createElement: () => ({}),
    getElementsByTagName: () => [{parentNode: {insertBefore: script => inserted.push(script)}}],
    addEventListener: (name, handler) => { documentEvents[name] = handler; },
    set cookie(value) { cookies.push(value); },
  };
  const window = {
    location: {hostname: 'www.rasel.example.com'},
    localStorage: {setItem() {}},
    addEventListener: (name, handler) => { windowEvents[name] = handler; },
  };
  const fetch = async (url, options = {}) => {
    requests.push({url, ...options});
    if (url === configuration.consentEndpoint) {
      if (options.method === 'POST') {
        serverState = JSON.parse(options.body).accepted ? 'accepted' : 'rejected';
      }
      const snapshot = serverState;
      return {ok: true, json: async () => ({state: snapshot})};
    }
    const event = events.find(item => item.token === JSON.parse(options.body).token);
    const first = event && !claimed.has(event.token);
    if (event) claimed.add(event.token);
    return {ok: true, json: async () => ({claimed: first, name: event.name, id: event.id, data: event.data})};
  };
  const sandbox = {window, document, fetch, Promise, Date, Math, Error, Number, JSON};
  vm.runInNewContext(source, sandbox);
  return {
    accept, reject, preference, close, banner, status, window, document, configuration,
    windowEvents, documentEvents, requests, inserted, cookies,
    server(value) { serverState = value; },
    tracks() {
      // Model the loaded SDK, preserving an observable call history in this fixture.
      if (window.fbq && !window.fbq.callMethod) {
        window.fbq.callMethod = function () { window.fbq.queue.push(arguments); };
      }
      return window.fbq ? Array.from(window.fbq.queue).filter(args => args[0] === 'trackSingle') : [];
    },
    executeAgain() { vm.runInNewContext(source, sandbox); },
  };
}

async function settled() { for (let i = 0; i < 12; i++) await Promise.resolve(); }

(async function () {
  const unanswered = browser();
  await settled();
  assert.equal(unanswered.inserted.length, 0, 'No Meta script before acceptance');
  assert.equal(unanswered.tracks().length, 0);
  unanswered.reject.click();
  await settled();
  assert.equal(unanswered.inserted.length, 0);
  assert.equal(unanswered.banner.hidden, true);
  assert.ok(unanswered.cookies.some(value => value.startsWith('_fbp=;')));

  const product = browser({product: true});
  await settled();
  product.accept.click();
  await settled();
  assert.equal(product.inserted.length, 1);
  assert.deepEqual(product.tracks().map(args => args[2]), ['PageView', 'ViewContent']);
  assert.equal(product.tracks()[1][3].value, 7400);
  assert.equal(product.tracks()[1][3].currency, 'ARS');
  assert.deepEqual(Array.from(product.tracks()[1][3].content_ids), ['42']);
  assert.equal(product.window.fbq.queue.filter(args => args[0] === 'init').length, 1);
  product.windowEvents.pageshow({persisted: false});
  product.windowEvents.focus();
  product.executeAgain();
  await settled();
  assert.equal(product.tracks().length, 2, 'Focus, pageshow and duplicate script do not duplicate events');
  product.windowEvents.pageshow({persisted: true});
  await settled();
  assert.equal(product.tracks().length, 4, 'A bfcache restoration is a new navigation');
  product.preference.click();
  assert.equal(product.banner.hidden, false);
  product.reject.click();
  await settled();
  assert.equal(product.tracks().length, 4);
  product.windowEvents.focus();
  await settled();
  assert.equal(product.tracks().length, 4, 'Withdrawal blocks later tracking');

  const actions = browser({state: 'accepted', events: [
    {token: 'cart-token', name: 'AddToCart', id: 'cart-id', data: {currency: 'ARS', value: 14800}},
    {token: 'checkout-token', name: 'InitiateCheckout', id: 'checkout-id', data: {currency: 'ARS', value: 14800}},
  ]});
  await settled();
  assert.deepEqual(actions.tracks().map(args => args[2]), ['PageView', 'AddToCart', 'InitiateCheckout']);
  assert.equal(actions.tracks()[1][4].eventID, 'cart-id');
  actions.windowEvents.focus();
  await settled();
  assert.equal(actions.tracks().length, 3, 'Confirmed action claims are not repeated');
  actions.server('rejected');
  actions.windowEvents.storage({key: 'rasel-meta-choice-change'});
  await settled();
  assert.equal(actions.tracks().length, 3, 'Withdrawal in another tab prevents tracking');

  const serverOnly = browser({state: 'accepted', pixelEnabled: false});
  await settled();
  assert.equal(serverOnly.inserted.length, 0, 'CAPI-only consent does not load the browser pixel');

  const slowSdk = browser();
  await settled();
  slowSdk.accept.click();
  await settled();
  assert.ok(slowSdk.window.fbq.queue.some(args => args[0] === 'trackSingle'));
  slowSdk.reject.click();
  await settled();
  assert.equal(slowSdk.window.fbq.queue.some(args => args[0] === 'trackSingle'), false,
    'Withdrawal also removes events waiting for the SDK to download');
  console.log('Meta browser: consent, initialization, navigation, bfcache, amounts, action claims and withdrawal passed. No external events sent.');
})().catch(error => { console.error(error); process.exitCode = 1; });
