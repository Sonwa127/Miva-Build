/* Private decks never use the shared flashcard API. All writes stay in localStorage. */
(() => {
  'use strict';
  const section = document.getElementById('privateFlashcards');
  if (!section) return;
  const byId = id => document.getElementById(id);
  const library = window.PrivateFlashcards;
  let store;
  let activeId = '';
  let review = null;
  function message(text = '') {
    byId('privateMessage').textContent = text;
    byId('privateMessage').hidden = !text;
  }
  function error(id, text = '') { byId(id).textContent = text; byId(id).hidden = !text; }
  function courseLabel(deck) { return `${deck.course || 'General study'} · ${deck.week ? `Week ${deck.week}` : 'General material'}`; }
  function getDeck(id) {
    const deck = store.read().decks.find(d => d.id === id);
    if (!deck) throw new Error('This private deck no longer exists.');
    return deck;
  }
  function ensureOption(select, value) {
    if (value && !Array.from(select.options).some(option => option.value === value)) {
      select.add(new Option(value, value));
    }
  }
  function render() {
    const decks = store.read().decks;
    const filter = byId('privateCourseFilter');
    decks.forEach(deck => ensureOption(filter, deck.course));
    const visible = decks.filter(deck => !filter.value || deck.course === filter.value);
    byId('privateDeckCount').textContent = `${visible.length} private ${visible.length === 1 ? 'deck' : 'decks'}`;
    byId('privateDecks').innerHTML = visible.length ? visible.map(deck => {
      const due = deck.cards.filter(card => library.isDue(card)).length;
      return `<article class="private-deck" data-private-deck="${deck.id}"><div class="private-deck-meta"><span>${escapeHtml(courseLabel(deck))}</span><span>Private</span></div><h3>${escapeHtml(deck.title)}</h3><p>${deck.cards.length} ${deck.cards.length === 1 ? 'card' : 'cards'} · ${due} ready to review</p><div class="private-deck-actions"><button type="button" class="private-button primary" data-private-action="review" data-deck="${deck.id}" ${deck.cards.length ? '' : 'disabled'}>${due ? `Review ${due} due` : 'Practise all'}</button><button type="button" class="private-button" data-private-action="manage" data-deck="${deck.id}">Manage cards</button></div><div class="private-deck-footer"><button type="button" class="private-link-button" data-private-action="edit-deck" data-deck="${deck.id}">Edit deck</button><button type="button" class="private-link-button danger" data-private-action="delete-deck" data-deck="${deck.id}">Delete</button></div></article>`;
    }).join('') : `<div class="private-empty"><h3>${filter.value ? 'No private decks for this course yet' : 'Make your first private deck'}</h3><p>Create a deck, add a question and answer, then test what you remember.<br>Your cards won’t appear in anyone else’s class library.</p></div>`;
    const deck = visible.find(d => d.id === activeId);
    byId('privateDeckDetail').hidden = !deck;
    if (!deck) { activeId = ''; return; }
    byId('privateDetailTitle').textContent = deck.title;
    byId('privateCardList').innerHTML = deck.cards.length ? deck.cards.map(card => `<article class="private-card-row"><div><strong>${escapeHtml(card.question)}</strong><details><summary>Show your answer</summary><p>${escapeHtml(card.answer)}</p></details></div><div><button type="button" class="private-link-button" data-private-action="edit-card" data-deck="${deck.id}" data-card="${card.id}">Edit</button><button type="button" class="private-link-button danger" data-private-action="delete-card" data-deck="${deck.id}" data-card="${card.id}">Delete</button></div></article>`).join('') : '<div class="private-empty"><h3>Your deck is ready</h3><p>Add your first question and answer to start practising.</p></div>';
  }
  function deckEditor(id = '') {
    byId('privateDeckForm').reset();
    byId('privateDeckId').value = id;
    error('privateDeckError');
    const deck = id ? getDeck(id) : null;
    byId('privateDeckDialogTitle').textContent = id ? 'Edit your private deck' : 'Create a private deck';
    byId('privateDeckTitle').value = deck?.title || '';
    const course = deck?.course ?? byId('privateCourseFilter').value;
    ensureOption(byId('privateDeckCourse'), course);
    byId('privateDeckCourse').value = course;
    byId('privateDeckWeek').value = deck?.week || 0;
    byId('privateDeckDialog').showModal();
    byId('privateDeckTitle').focus();
  }
  function cardEditor(deckId, id = '') {
    const deck = getDeck(deckId);
    const card = id ? deck.cards.find(c => c.id === id) : null;
    if (id && !card) throw new Error('This card no longer exists.');
    byId('privateCardForm').reset();
    byId('privateCardId').value = id;
    byId('privateCardDeckId').value = deckId;
    byId('privateCardDialogTitle').textContent = id ? 'Edit your private card' : 'Add a private card';
    byId('privateCardQuestion').value = card?.question || '';
    byId('privateCardAnswer').value = card?.answer || '';
    error('privateCardError');
    byId('privateCardDialog').showModal();
    byId('privateCardQuestion').focus();
  }
  function showReviewCard() {
    if (!review) return;
    const deck = getDeck(review.deckId);
    const card = deck.cards.find(c => c.id === review.ids[review.index]);
    if (!card) throw new Error('A card changed during this review. Close this window and start again.');
    review.revealed = false;
    byId('privateReviewTitle').textContent = deck.title;
    byId('privateReviewPosition').textContent = `${courseLabel(deck)} · Card ${review.index + 1} of ${review.ids.length}`;
    byId('privateReviewQuestion').textContent = card.question;
    byId('privateReviewAnswer').textContent = card.answer;
    byId('privateAnswerArea').hidden = true;
    byId('privateReveal').hidden = false;
    byId('privateReviewContent').hidden = false;
    const interval = library.schedule(card.progress, 'good').interval_days;
    byId('privateGoodInterval').textContent = `${interval} ${interval === 1 ? 'day' : 'days'}`;
    error('privateReviewError');
  }
  function beginReview(id) {
    const deck = getDeck(id);
    const due = deck.cards.filter(card => library.isDue(card));
    const cards = due.length ? due : deck.cards;
    if (!cards.length) throw new Error('Add a card before starting a review.');
    review = {deckId: id, ids: cards.map(c => c.id), index: 0, revealed: false};
    showReviewCard();
    byId('privateReviewDialog').showModal();
    byId('privateReveal').focus();
  }
  function downloadBackup() {
    const backup = store.backup();
    const url = URL.createObjectURL(new Blob([backup], {type: 'application/json'}));
    const link = document.createElement('a');
    link.href = url;
    link.download = `studyarchive-private-flashcards-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message('Backup download started. Keep the JSON file somewhere safe; it contains your private questions, answers, and review progress. Importing it adds new copies without replacing existing decks.');
  }

  byId('privateDeckForm').addEventListener('submit', event => {
    event.preventDefault();
    try {
      activeId = store.saveDeck({title: byId('privateDeckTitle').value, course: byId('privateDeckCourse').value, week: Number(byId('privateDeckWeek').value)}, byId('privateDeckId').value);
      const deck = getDeck(activeId);
      byId('privateCourseFilter').value = '';
      render();
      byId('privateDeckDialog').close();
      message(`“${deck.title}” saved in this browser. Add cards below to start practising.`);
      byId('privateDeckDetail').scrollIntoView({block: 'nearest'});
    } catch (err) { error('privateDeckError', err.message); }
  });
  byId('privateCardForm').addEventListener('submit', event => {
    event.preventDefault();
    try {
      const deckId = byId('privateCardDeckId').value;
      store.saveCard(deckId, {question: byId('privateCardQuestion').value, answer: byId('privateCardAnswer').value}, byId('privateCardId').value);
      activeId = deckId;
      render();
      byId('privateCardDialog').close();
      message('Your card was saved privately in this browser.');
    } catch (err) { error('privateCardError', err.message); }
  });
  byId('privateCourseFilter').addEventListener('change', () => { try { render(); } catch (err) { message(err.message); } });
  byId('privateImportInput').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error('Choose a backup smaller than 4 MB.');
      const count = store.importBackup(await file.text());
      byId('privateCourseFilter').value = '';
      render();
      message(`Imported ${count} private ${count === 1 ? 'deck' : 'decks'} as new copies. Existing decks were not changed.`);
    } catch (err) { message(err.message); }
    finally { event.target.value = ''; }
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-private-action], [data-private-close], [data-private-rating]');
    if (!button || button.disabled) return;
    try {
      if (button.dataset.privateClose) { byId(button.dataset.privateClose).close(); return; }
      if (button.dataset.privateRating) {
        if (!review?.revealed) return;
        // Saving must succeed before advancing; storage failures keep the current card.
        store.rate(review.deckId, review.ids[review.index], button.dataset.privateRating);
        review.index++;
        if (review.index >= review.ids.length) {
          review = null;
          byId('privateReviewTitle').textContent = 'Practice complete';
          byId('privateReviewPosition').textContent = 'Your review progress is saved in this browser. Come back when your cards are due.';
          byId('privateReviewContent').hidden = true;
          error('privateReviewError');
          render();
        } else { showReviewCard(); byId('privateReveal').focus(); }
        return;
      }
      const id = button.dataset.deck;
      switch (button.dataset.privateAction) {
        case 'new-deck': deckEditor(); break;
        case 'edit-deck': deckEditor(id); break;
        case 'manage': activeId = id; render(); byId('privateDeckDetail').scrollIntoView({block: 'nearest'}); break;
        case 'new-card': cardEditor(activeId); break;
        case 'edit-card': cardEditor(id, button.dataset.card); break;
        case 'delete-card':
          if (confirm('Delete this private card? This cannot be undone. Keep an exported backup if you may need it later.')) { store.deleteCard(id, button.dataset.card); render(); message('Private card deleted from this browser.'); }
          break;
        case 'delete-deck':
          if (confirm(`Delete “${getDeck(id).title}” and all its private cards? This cannot be undone. Export a backup first if you may need it later.`)) { store.deleteDeck(id); render(); message('Private deck and its cards deleted from this browser.'); }
          break;
        case 'review': beginReview(id); break;
        case 'reveal':
          if (!review) break;
          review.revealed = true;
          byId('privateAnswerArea').hidden = false;
          byId('privateReveal').hidden = true;
          document.querySelector('[data-private-rating=good]').focus();
          break;
        case 'export': downloadBackup(); break;
        case 'import': byId('privateImportInput').click(); break;
      }
    } catch (err) {
      if (byId('privateReviewDialog').open) error('privateReviewError', err.message);
      else message(err.message);
    }
  });
  byId('privateReviewDialog').addEventListener('close', () => {
    review = null;
    try { render(); } catch (err) { message(err.message); }
  });
  window.addEventListener('storage', event => {
    if (event.key !== library.KEY && event.key !== null) return;
    if (byId('privateReviewDialog').open) byId('privateReviewDialog').close();
    try { render(); message('Your private collection changed in another tab. Reopen a review to use the latest cards.'); }
    catch (err) { message(err.message); }
  });
  try { store = new library.Store(window.localStorage); render(); }
  catch (err) {
    message(err.message);
    section.querySelectorAll('button').forEach(button => { button.disabled = true; });
  }
})();
