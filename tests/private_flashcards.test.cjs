const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Store, KEY, schedule, isDue} = require('../frontend/static/js/private-flashcards-store.js');
const memory = () => { const values = new Map(); return {getItem: key => values.has(key) ? values.get(key) : null, setItem: (key, value) => values.set(key, value)}; };
const deck = (store, title = 'Vectors') => store.saveDeck({title, course: 'PHY 101', week: 1});

test('private deck and card CRUD persist without touching shared progress', () => {
  const storage = memory();
  storage.setItem('studyarchive_review_progress_v1', '{"shared":"untouched"}');
  const store = new Store(storage);
  const id = deck(store);
  const cardId = store.saveCard(id, {question: 'What is a vector?', answer: 'A quantity with magnitude and direction.'});
  const fresh = new Store(storage);
  assert.equal(fresh.read().decks[0].cards[0].id, cardId);
  fresh.saveDeck({title: 'Week 1 vectors', course: 'PHY 101', week: 1}, id);
  assert.equal(fresh.read().decks[0].cards.length, 1);
  fresh.saveCard(id, {question: 'Velocity?', answer: 'A vector quantity.'}, cardId);
  assert.equal(store.read().decks[0].cards[0].answer, 'A vector quantity.');
  fresh.deleteCard(id, cardId);
  assert.equal(fresh.read().decks[0].cards.length, 0);
  fresh.deleteDeck(id);
  assert.equal(fresh.read().decks.length, 0);
  assert.equal(storage.getItem('studyarchive_review_progress_v1'), '{"shared":"untouched"}');
});
test('browser profiles have independent collections', () => {
  const a = new Store(memory());
  const b = new Store(memory());
  deck(a);
  assert.equal(a.read().decks.length, 1);
  assert.equal(b.read().decks.length, 0);
});
test('blank and oversized fields, invalid weeks, and missing cards reject atomically', () => {
  const storage = memory(), store = new Store(storage), id = deck(store);
  const raw = storage.getItem(KEY);
  for (const fields of [{title: ' '}, {title: 'x'.repeat(121)}, {title: 'valid', week: -1}, {title: 'valid', week: 1.5}, {title: 'valid', week: 53}]) assert.throws(() => store.saveDeck(fields));
  assert.throws(() => store.saveCard(id, {question: ' ', answer: 'a'}));
  assert.throws(() => store.saveCard(id, {question: 'q', answer: 'a'.repeat(5001)}));
  assert.throws(() => store.saveCard(id, {question: 'q', answer: 'a'}, 'missing'));
  assert.equal(storage.getItem(KEY), raw);
});
test('review scheduling persists and card editing retains progress', () => {
  const store = new Store(memory()), id = deck(store);
  const cid = store.saveCard(id, {question: 'Q', answer: 'A'});
  const now = new Date('2026-10-21T12:00:00Z');
  assert.equal(isDue(store.read().decks[0].cards[0], now), true);
  store.rate(id, cid, 'again', now);
  let saved = store.read().decks[0].cards[0];
  assert.equal(saved.progress.next_review, '2026-10-21T12:10:00.000Z');
  assert.equal(isDue(saved, now), false);
  assert.equal(isDue(saved, new Date('2026-10-21T12:10:00Z')), true);
  store.rate(id, cid, 'good', now);
  assert.equal(store.read().decks[0].cards[0].progress.interval_days, 1);
  store.rate(id, cid, 'good', now);
  assert.equal(store.read().decks[0].cards[0].progress.interval_days, 3);
  store.saveCard(id, {question: 'Edited Q', answer: 'Edited A'}, cid);
  assert.equal(store.read().decks[0].cards[0].progress.interval_days, 3);
  assert.equal(schedule({}, 'hard', now).interval_days, 1);
  assert.throws(() => schedule({}, 'invalid', now));
});
test('JSON backup restore adds new copies including progress without overwriting', () => {
  const source = new Store(memory()), id = deck(source);
  const cid = source.saveCard(id, {question: '<script>not HTML</script>', answer: 'Plain text & symbols'});
  source.rate(id, cid, 'good');
  const target = new Store(memory());
  const existing = deck(target, 'Keep me');
  assert.equal(target.importBackup(source.backup()), 1);
  const saved = target.read().decks;
  assert.equal(saved[0].id, existing);
  assert.notEqual(saved[1].id, id);
  assert.notEqual(saved[1].cards[0].id, cid);
  assert.equal(saved[1].cards[0].question, '<script>not HTML</script>');
  assert.equal(saved[1].cards[0].progress.interval_days, 1);
});
test('malformed, incompatible, duplicate-ID, and oversized imports preserve data', () => {
  const storage = memory(), store = new Store(storage);
  deck(store);
  const raw = storage.getItem(KEY), backup = JSON.parse(store.backup());
  const duplicate = structuredClone(backup); duplicate.decks.push(structuredClone(duplicate.decks[0]));
  const badWeek = structuredClone(backup); badWeek.decks[0].week = '1';
  for (const value of ['no json', '{}', JSON.stringify({...backup, version: 99}), JSON.stringify(duplicate), JSON.stringify(badWeek), ' '.repeat(4 * 1024 * 1024 + 1)]) {
    assert.throws(() => store.importBackup(value));
    assert.equal(storage.getItem(KEY), raw);
  }
});
test('corrupt or unavailable storage fails closed', () => {
  const storage = memory(); storage.setItem(KEY, 'corrupted');
  const store = new Store(storage);
  assert.throws(() => deck(store), /not been overwritten/);
  assert.equal(storage.getItem(KEY), 'corrupted');
  assert.throws(() => new Store({getItem: () => {throw new Error('blocked');}}).read(), /unavailable/);
});
test('failed persistence never reports a successful save or alters stored collection', () => {
  const storage = memory(), store = new Store(storage), id = deck(store);
  const raw = storage.getItem(KEY);
  storage.setItem = () => { throw new Error('quota exceeded'); };
  assert.throws(() => store.saveCard(id, {question: 'Q', answer: 'A'}), /not saved/);
  assert.equal(storage.getItem(KEY), raw);
});
test('separate tabs update the latest collection instead of clobbering other decks', () => {
  const storage = memory(), first = new Store(storage), second = new Store(storage);
  const a = deck(first, 'First');
  const b = deck(second, 'Second');
  first.saveCard(a, {question: 'Q', answer: 'A'});
  assert.deepEqual(second.read().decks.map(d => d.id), [a, b]);
});
