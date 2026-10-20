/**
 * StitchSmart Client Application JavaScript
 */

async function api(endpoint, method = 'GET', data = null) {
  const options = {
    method,
    headers: {
      'Accept': 'application/json',
    },
  };
  if (data) {
    if (data instanceof FormData) {
      options.body = data;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(data);
    }
  }
  try {
    const res = await fetch(endpoint, options);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = Array.isArray(errData.detail)
        ? errData.detail.map(item => item.msg || String(item)).join('; ')
        : errData.detail;
      throw new Error(detail || `Request failed with status ${res.status}`);
    }
    if (res.status === 204) return null;

    const contentType = res.headers.get('content-type') || '';
    if (contentType.includes('application/json')) return await res.json();
    return await res.text();
  } catch (err) {
    console.error(`API Error [${method} ${endpoint}]:`, err);
    showToast(err.message, 'error');
    throw err;
  }
}

/** Escape untrusted text before interpolating it into an HTML template. */
function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

/** Escape values used inside quoted HTML attributes. */
function escapeAttr(value) {
  return escapeHtml(value).replaceAll('`', '&#096;');
}

function showToast(message, type = 'success') {
  let toast = document.getElementById('toastNotification');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'toastNotification';
    toast.className = 'fixed top-20 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl transition-all duration-300 pointer-events-none transform translate-y-[-100px] opacity-0';
    document.body.appendChild(toast);
  }

  if (type === 'error') {
    toast.className = 'fixed top-20 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl transition-all duration-300 pointer-events-none bg-red-800 text-white transform translate-y-0 opacity-100';
    toast.innerHTML = `<span class="material-symbols-outlined text-[20px]">error</span><span class="text-sm font-medium">${escapeHtml(message)}</span>`;
  } else {
    toast.className = 'fixed top-20 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl transition-all duration-300 pointer-events-none bg-slate-900 text-white transform translate-y-0 opacity-100';
    toast.innerHTML = `<span class="material-symbols-outlined text-teal-400 text-[20px]">check_circle</span><span class="text-sm font-medium">${escapeHtml(message)}</span>`;
  }

  setTimeout(() => {
    toast.classList.add('opacity-0', 'translate-y-[-100px]');
    toast.classList.remove('opacity-100', 'translate-y-0');
  }, 3500);
}

// Global Keyboard Shortcuts (Cmd+K / Ctrl+K for search)
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    const searchInput = document.querySelector('header input[type="search"]');
    if (searchInput) searchInput.focus();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.querySelector('header input[type="search"]');
  if (!searchInput) return;

  searchInput.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const query = searchInput.value.trim();
    if (!query) return;

    const courseSearch = document.getElementById('courseSearchInput');
    if (courseSearch && typeof filterCourses === 'function') {
      courseSearch.value = query;
      filterCourses();
      courseSearch.focus();
      return;
    }
    window.location.assign(`/courses?q=${encodeURIComponent(query)}`);
  });
});
