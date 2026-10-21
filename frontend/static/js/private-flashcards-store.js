/* Browser-only flashcards. No API calls, cookies, or shared-library writes. */
(function (root, factory) {
  const library = factory();
  if (typeof module === 'object' && module.exports) module.exports = library;
  else root.PrivateFlashcards = library;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const KEY = 'studyarchive_private_flashcards_v1';
  const FORMAT = 'studyarchive-private-flashcards';
  const MAX_DECKS = 100;
  const MAX_CARDS = 5000;
  const MAX_BYTES = 4 * 1024 * 1024;
  const fail = message => { throw new Error(message); };
  const object = value => value && typeof value === 'object' && !Array.isArray(value);
  function text(value, name, max, required = false) {
    if (typeof value !== 'string' || value.length > max || (required && !value.trim())) fail(`Invalid ${name}. Maximum ${max} characters.`);
    return value.trim();
  }
  function integer(value, name, min, max) {
    if (!Number.isInteger(value) || value < min || value > max) fail(`Invalid ${name}. Use a number from ${min} to ${max}.`);
    return value;
  }
  function identifier(value) {
    if (typeof value !== 'string' || !/^[a-zA-Z0-9_-]{1,100}$/.test(value)) fail('Invalid flashcard identifier.');
    return value;
  }
  function date(value, empty = false) {
    if (empty && value === '') return '';
    if (typeof value !== 'string' || value.length > 40 || !Number.isFinite(Date.parse(value))) fail('Invalid flashcard date.');
    return new Date(value).toISOString();
  }
  function progress(value = {}) {
    if (!object(value)) fail('Invalid review progress.');
    return {repetitions: integer(value.repetitions ?? 0, 'review count', 0, 100000), interval_days: integer(value.interval_days ?? 0, 'review interval', 0, 3650), next_review: date(value.next_review ?? '', true)};
  }
  function card(value) {
    if (!object(value)) fail('Invalid flashcard.');
    return {id: identifier(value.id), question: text(value.question, 'question', 1000, true), answer: text(value.answer, 'answer', 5000, true), progress: progress(value.progress)};
  }
  function metadata(value) {
    return {title: text(value.title, 'deck name', 120, true), course: text(value.course ?? '', 'course', 100), week: integer(value.week ?? 0, 'week', 0, 52)};
  }
  function validate(value) {
    if (!object(value) || value.version !== 1 || !Array.isArray(value.decks)) fail('This is not a supported private flashcard backup.');
    if (value.decks.length > MAX_DECKS) fail(`You can keep up to ${MAX_DECKS} private decks in this browser.`);
    let total = 0;
    const ids = new Set();
    return {version: 1, decks: value.decks.map(deck => {
      if (!object(deck) || !Array.isArray(deck.cards)) fail('Invalid deck.');
      const id = identifier(deck.id);
      if (ids.has(id)) fail('Duplicate deck identifier.');
      ids.add(id);
      total += deck.cards.length;
      if (total > MAX_CARDS) fail(`Keep no more than ${MAX_CARDS} private cards in this browser.`);
      const cards = deck.cards.map(card);
      if (new Set(cards.map(c => c.id)).size !== cards.length) fail('Duplicate card identifier.');
      return {id, ...metadata(deck), cards, created_at: date(deck.created_at), updated_at: date(deck.updated_at)};
    })};
  }
  function uid() {
    return globalThis.crypto?.randomUUID?.() || `private_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
  }
  function schedule(previous, rating, now = new Date()) {
    const current = progress(previous);
    if (!['again', 'hard', 'good'].includes(rating)) fail('Choose a review rating.');
    const repetitions = rating === 'again' ? 0 : current.repetitions + 1;
    const days = rating === 'again' ? 0 : rating === 'hard' ? 1 : current.interval_days === 0 ? 1 : current.interval_days === 1 ? 3 : Math.min(180, Math.max(7, current.interval_days * 2));
    return {repetitions, interval_days: days, next_review: new Date(now.getTime() + (rating === 'again' ? 10 * 60 * 1000 : days * 86400000)).toISOString()};
  }
  function isDue(c, now = new Date()) { return !c.progress.next_review || Date.parse(c.progress.next_review) <= now.getTime(); }

  class Store {
    constructor(storage) { this.storage = storage; }
    read() {
      let raw;
      try { raw = this.storage.getItem(KEY); }
      catch (_) { fail('Browser storage is unavailable. Enable site storage before creating private cards.'); }
      if (raw === null) return {version: 1, decks: []};
      try { return validate(JSON.parse(raw)); }
      catch (_) { fail('Your saved private cards could not be read. Existing data has not been overwritten. Keep this browser data and contact the site administrator.'); }
    }
    write(data) {
      const safe = validate(data);
      const raw = JSON.stringify(safe);
      // Reserve room for the backup envelope so every saved collection can be restored.
      if (new Blob([raw]).size > MAX_BYTES - 1024) fail('Your private collection is too large. Export a backup, then remove decks you no longer need.');
      try { this.storage.setItem(KEY, raw); }
      catch (_) { fail('Could not save to this browser. Storage may be full or blocked. Your changes were not saved.'); }
      return safe;
    }
    mutate(action) {
      const data = this.read();
      const result = action(data);
      this.write(data);
      return result;
    }
    getDeck(data, id) { return data.decks.find(deck => deck.id === id) || fail('This private deck no longer exists.'); }
    saveDeck(values, id = '') {
      const fields = metadata(values);
      return this.mutate(data => {
        const now = new Date().toISOString();
        if (id) { Object.assign(this.getDeck(data, id), fields, {updated_at: now}); return id; }
        const deck = {id: uid(), ...fields, cards: [], created_at: now, updated_at: now};
        data.decks.push(deck);
        return deck.id;
      });
    }
    deleteDeck(id) {
      this.mutate(data => { this.getDeck(data, id); data.decks = data.decks.filter(deck => deck.id !== id); });
    }
    saveCard(deckId, values, id = '') {
      return this.mutate(data => {
        const deck = this.getDeck(data, deckId);
        const original = id ? deck.cards.find(c => c.id === id) : null;
        if (id && !original) fail('This card no longer exists.');
        const saved = card({id: id || uid(), question: values.question, answer: values.answer, progress: original?.progress});
        if (original) Object.assign(original, saved);
        else deck.cards.push(saved);
        deck.updated_at = new Date().toISOString();
        return saved.id;
      });
    }
    deleteCard(deckId, id) {
      this.mutate(data => {
        const deck = this.getDeck(data, deckId);
        if (!deck.cards.some(c => c.id === id)) fail('This card no longer exists.');
        deck.cards = deck.cards.filter(c => c.id !== id);
        deck.updated_at = new Date().toISOString();
      });
    }
    rate(deckId, id, rating, now = new Date()) {
      this.mutate(data => {
        const deck = this.getDeck(data, deckId);
        const c = deck.cards.find(c => c.id === id) || fail('This card no longer exists.');
        c.progress = schedule(c.progress, rating, now);
        deck.updated_at = now.toISOString();
      });
    }
    backup() { return JSON.stringify({format: FORMAT, exported_at: new Date().toISOString(), ...this.read()}); }
    importBackup(raw) {
      if (typeof raw !== 'string' || new Blob([raw]).size > MAX_BYTES) fail('Choose a private flashcard JSON backup smaller than 4 MB.');
      let value;
      try { value = JSON.parse(raw); } catch (_) { fail('The selected file is not valid JSON. Nothing was imported.'); }
      if (value?.format !== FORMAT) fail('Choose a StudyArchive private flashcard backup. Shared decks and other files are not supported.');
      const incoming = validate(value);
      return this.mutate(data => {
        incoming.decks.forEach(deck => {
          data.decks.push({...deck, id: uid(), cards: deck.cards.map(c => ({...c, id: uid()}))});
        });
        return incoming.decks.length;
      });
    }
  }
  return {Store, KEY, FORMAT, schedule, isDue, validate};
});
