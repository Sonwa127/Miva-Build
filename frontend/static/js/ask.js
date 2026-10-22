/* Course Q&A: honest source states, safe rendering, and per-answer feedback. */
(() => {
  // Local SVG icons keep this screen usable when Google Fonts is unavailable.
  const paths = {
    library_books: '<path d="M4 6v15h15M8 3h13v14H8zM11 7h7M11 11h7"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v.1"/>',
    school: '<path d="m2 9 10-5 10 5-10 5-10-5zm4 2v6c4 3 8 3 12 0v-6M22 9v8"/>',
    menu_book: '<path d="M12 5v15M3 4c3-1 6-1 9 1 3-2 6-2 9-1v15c-3-1-6-1-9 1-3-2-6-2-9-1z"/>',
    auto_stories: '<path d="M12 5v15M3 4c3-1 6-1 9 1 3-2 6-2 9-1v15c-3-1-6-1-9 1-3-2-6-2-9-1zM6 8l3 1M15 9l3-1"/>',
    add: '<path d="M12 5v14M5 12h14"/>',
    lightbulb: '<path d="M9 18h6M10 21h4M8 14a6 6 0 1 1 8 0c-1 1-1 2-1 2H9s0-1-1-2z"/>',
    edit_note: '<path d="M4 5h12M4 10h8M4 15h5m5 0 5-5 3 3-5 5-4 1z"/>',
    compare_arrows: '<path d="M3 7h15m-4-4 4 4-4 4M21 17H6m4-4-4 4 4 4"/>',
    arrow_upward: '<path d="M12 20V4m-6 6 6-6 6 6"/>',
    arrow_forward: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    find_in_page: '<path d="M13 3H5v18h14V9zM13 3v6h6m-5 7 3 3"/><circle cx="11" cy="13" r="3"/>',
    description: '<path d="M13 3H5v18h14V9zM13 3v6h6M8 13h8M8 17h6"/>',
    folder_open: '<path d="M3 8V5h7l2 3h9v3M3 8v12h16l3-9H7L3 20"/>',
    style: '<rect x="7" y="3" width="13" height="17" rx="2"/><path d="m7 5-4 1 2 16 12-2M11 8h5M11 12h5"/>',
    favorite: '<path d="M12 20 4 12C-2 6 6 0 12 6c6-6 14 0 8 6z"/>',
    auto_awesome: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5zM20 2v4M18 4h4"/>',
    content_copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    thumb_up: '<path d="M7 10H3v11h4V10zm0 0 5-7c2 0 2 2 1 6h6c2 0 2 1 2 3l-2 7c0 1-1 2-2 2H7"/>',
    thumb_down: '<path d="M7 14H3V3h4v11zm0 0 5 7c2 0 2-2 1-6h6c2 0 2-1 2-3l-2-7c0-1-1-2-2-2H7"/>',
    progress_activity: '<path d="M21 12a9 9 0 1 1-9-9"/>',
    search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>'
  };
  function hydrateIcons(root) {
    const icons = [...(root.matches?.('span.material-symbols-outlined') ? [root] : []), ...root.querySelectorAll('span.material-symbols-outlined')];
    icons.forEach(icon => {
      const name = icon.textContent.trim();
      if (!paths[name]) return;
      icon.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths[name]}</svg>`;
    });
  }
  const page = document.querySelector('.ask-page');
  hydrateIcons(page);
  new MutationObserver(changes => changes.forEach(change => change.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) hydrateIcons(node);
  }))).observe(page, {childList: true, subtree: true});
  const input = document.getElementById('qaQueryInput');
  const course = document.getElementById('courseScopeSelect');
  const messages = document.getElementById('chatMessages');
  const send = document.getElementById('sendQaBtn');
  const clear = document.getElementById('clearChatBtn');
  const welcome = messages.innerHTML;
  const emptySources = document.getElementById('inspectorContent').innerHTML;
  let busy = false;
  let sequence = 0;
  const answers = new Map();
  let lastAsked = null;                       // {question, course} of the last answered question, so "give examples" knows the topic

  function scopeChanged() {
    document.getElementById('inputScopeLabel').textContent = course.value ? `Searching ${course.value} materials` : 'Searching all courses';
    document.getElementById('courseMaterialsLink').href = course.value ? `/courses/${encodeURIComponent(course.value)}` : '/courses';
    document.getElementById('studyLink').href = course.value ? `/study?course_id=${encodeURIComponent(course.value)}` : '/study';
    const name = course.value ? course.selectedOptions[0].textContent.split(' · ').slice(1).join(' · ') : 'your course';
    input.placeholder = course.value ? `What would you like to understand about ${name}?` : 'Name a topic from your notes and tell us what’s unclear…';
  }

  function resetSources(message = '', loading = false) {
    document.getElementById('sourceCount').hidden = true;
    document.getElementById('inspectorContent').innerHTML = message ? `<div class="ask-source-empty"><span class="material-symbols-outlined" aria-hidden="true">search</span><h3>${loading ? 'Checking your readings' : 'No supporting pages to show'}</h3><p>${escapeHtml(message)}</p></div>` : emptySources;
  }

  function sourceUrl(source) {
    const page = Math.max(1, Math.trunc(Number(source.page) || 1));
    return `/viewer/${encodeURIComponent(source.doc_id)}?page=${page}`;
  }

  function showSources(id, index = 0) {
    const record = answers.get(id);
    if (!record?.sources.length) return;
    const source = record.sources[index];
    if (!source) return;
    const count = document.getElementById('sourceCount');
    count.hidden = false;
    count.textContent = record.sources.length;
    document.getElementById('inspectorContent').innerHTML = `
      <div class="ask-source-tabs" role="group" aria-label="Choose a source">${record.sources.map((s, i) => `<button type="button" data-source-answer="${id}" data-source-index="${i}" aria-pressed="${i === index}">Source ${escapeHtml(s.n || i + 1)}</button>`).join('')}</div>
      <h3 class="ask-source-title">${escapeHtml(source.title || source.citation || 'Course reading')}</h3>
      <p class="ask-source-page">Page ${escapeHtml(source.page)}</p>
      <blockquote class="ask-source-excerpt">${escapeHtml(source.text || 'Open the original page to read the full passage.')}</blockquote>
      <a class="ask-open-source" href="${sourceUrl(source)}">Read the original page <span class="material-symbols-outlined" aria-hidden="true">arrow_forward</span></a>
      <p class="ask-source-context">Supporting material for: ${escapeHtml(record.question.slice(0, 160))}</p>`;
  }

  function formatAnswer(answer, sources) {
    // Escape first; only our formatting and validated citation links become HTML.
    let safe = escapeHtml(answer);
    safe = safe.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`\n]+)`/g, '<code>$1</code>');
    safe = safe.replace(/\[(\d+)\]/g, (match, n) => {
      const source = sources.find(s => Number(s.n) === Number(n));
      return source ? `<a class="ask-inline-citation" href="${sourceUrl(source)}" aria-label="Read source ${n}, page ${Number(source.page) || 1}">[${n}]</a>` : match;
    });
    return safe.split(/\n\s*\n/).map(paragraph => `<p>${paragraph}</p>`).join('');
  }

  function renderAnswer(result, question, selectedCourse) {
    const id = ++sequence;
    const sources = Array.isArray(result.sources) ? result.sources : [];
    const supported = sources.length > 0 && !result.low_confidence;
    answers.set(id, {question, answer: String(result.answer || ''), sources, logId: result.log_id});
    const footer = result.log_id ? `<span>Was this useful?</span><button type="button" class="ask-action" data-feedback-id="${id}" data-rating="1" aria-label="Mark answer as helpful" aria-pressed="false"><span class="material-symbols-outlined" aria-hidden="true">thumb_up</span></button><button type="button" class="ask-action" data-feedback-id="${id}" data-rating="-1" aria-label="Mark answer as not helpful" aria-pressed="false"><span class="material-symbols-outlined" aria-hidden="true">thumb_down</span></button>` : '';
    messages.insertAdjacentHTML('beforeend', `<article class="ask-answer" data-answer-id="${id}">
      <div class="ask-answer-heading"><span class="ask-answer-avatar"><span class="material-symbols-outlined" aria-hidden="true">auto_awesome</span></span><strong>StudyArchive AI</strong><span class="ask-answer-status">${supported ? `${sources.length} cited ${sources.length === 1 ? 'page' : 'pages'}` : 'No supported answer'}</span></div>
      ${supported ? `<div class="ask-answer-body">${formatAnswer(String(result.answer || ''), sources)}</div>` : `<div class="ask-no-answer"><strong>I couldn’t support an answer from these materials.</strong><p>${escapeHtml(result.answer || 'No matching passage was found.')}</p><p>Try naming a specific concept, changing the course, or checking the original notes.</p><a href="/resources${selectedCourse ? `?course=${encodeURIComponent(selectedCourse)}` : ''}">Browse available materials →</a></div>`}
      ${sources.length ? `<div class="ask-answer-sources">${sources.map(s => `<a class="ask-source-chip" href="${sourceUrl(s)}"><span class="material-symbols-outlined" aria-hidden="true">description</span>${escapeHtml(s.title || 'Course reading')} · p. ${escapeHtml(s.page)}</a>`).join('')}</div>` : ''}
      <div class="ask-answer-actions">${supported ? `<button type="button" class="ask-action" data-copy-id="${id}"><span class="material-symbols-outlined" aria-hidden="true">content_copy</span>Copy</button>` : ''}${sources.length ? `<button type="button" class="ask-action" data-source-answer="${id}" data-source-index="0"><span class="material-symbols-outlined" aria-hidden="true">menu_book</span>View sources</button>` : ''}${footer}</div></article>`);
    if (sources.length) showSources(id);
    else resetSources('There were no cited pages for this answer. Try a more specific question or a different course.');
  }

  async function sendQuestion(question = input.value.trim()) {
    if (busy || !question) return;
    busy = true;
    send.disabled = clear.disabled = course.disabled = true;
    const selectedCourse = course.value;
    document.getElementById('welcomeChatCard')?.remove();
    messages.insertAdjacentHTML('beforeend', `<article class="ask-question"><p class="ask-message-label">You${selectedCourse ? ` · ${escapeHtml(selectedCourse)}` : ''}</p><p>${escapeHtml(question)}</p></article><div id="aiLoadingCard" class="ask-loading" role="status"><span class="material-symbols-outlined" aria-hidden="true">progress_activity</span>Looking through your course materials…</div>`);
    input.value = '';
    messages.setAttribute('aria-busy', 'true');
    resetSources('Looking for passages that support an answer to this question.', true);
    try {
      const previous = lastAsked && lastAsked.course === (selectedCourse || '') ? lastAsked.question : null;
      const result = await api('/api/qa/ask', 'POST', {question, course_id: selectedCourse || null, previous_question: previous});
      lastAsked = {question, course: selectedCourse || ''};
      document.getElementById('aiLoadingCard')?.remove();
      renderAnswer(result, question, selectedCourse);
    } catch (error) {
      document.getElementById('aiLoadingCard')?.remove();
      const errorCard = document.createElement('div');
      errorCard.className = 'ask-error';
      errorCard.setAttribute('role', 'alert');
      errorCard.innerHTML = `<strong>We couldn’t get an answer just now.</strong><p>${escapeHtml(error.message)}</p><button type="button">Try again</button>`;
      errorCard.querySelector('button').addEventListener('click', () => {
        if (busy) return;
        course.value = selectedCourse;
        scopeChanged();
        errorCard.remove();
        sendQuestion(question);
      });
      messages.appendChild(errorCard);
      if (!input.value) input.value = question;
      resetSources('The request did not complete. Retry your question when you’re ready.');
    } finally {
      busy = false;
      send.disabled = clear.disabled = course.disabled = false;
      messages.setAttribute('aria-busy', 'false');
    }
  }

  document.getElementById('questionForm').addEventListener('submit', event => { event.preventDefault(); sendQuestion(); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendQuestion(); }
  });
  course.addEventListener('change', scopeChanged);
  clear.addEventListener('click', () => {
    if (busy) return;
    messages.innerHTML = welcome;
    answers.clear();
    lastAsked = null;
    resetSources();
    input.value = '';
    input.focus();
  });
  document.querySelector('.ask-page').addEventListener('click', async event => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.dataset.prompt) {
      const prompts = {explain: 'Explain [concept] in simple terms using the course notes.', example: 'Walk me through an example of [topic] from the course notes.', compare: 'What is the difference between [first concept] and [second concept] in the course notes?'};
      input.value = prompts[button.dataset.prompt];
      input.focus();
      const start = input.value.indexOf('[');
      input.setSelectionRange(start, input.value.indexOf(']') + 1);
    }
    if (button.dataset.sourceAnswer) {
      showSources(Number(button.dataset.sourceAnswer), Number(button.dataset.sourceIndex));
      if (button.closest('.ask-answer') && window.matchMedia('(max-width: 760px)').matches) document.getElementById('sourceInspectorCard').scrollIntoView({block: 'start'});
    }
    if (button.dataset.copyId) {
      try { await navigator.clipboard.writeText(answers.get(Number(button.dataset.copyId)).answer); showToast('Answer copied.'); }
      catch (_) { showToast('Copy is unavailable in this browser. You can select and copy the answer text.', 'error'); }
    }
    if (button.dataset.feedbackId) {
      const record = answers.get(Number(button.dataset.feedbackId));
      if (!record?.logId || button.disabled) return;
      const controls = button.closest('.ask-answer-actions').querySelectorAll('[data-feedback-id]');
      controls.forEach(control => control.disabled = true);
      try {
        await api('/api/qa/feedback', 'POST', {query_log_id: record.logId, rating: Number(button.dataset.rating)});
        controls.forEach(control => control.setAttribute('aria-pressed', String(control === button)));
        showToast('Thanks — your feedback has been recorded.');
      } catch (_) { /* The API helper displays the failure; allow a retry. */ }
      finally { controls.forEach(control => control.disabled = false); }
    }
  });
  scopeChanged();
})();
