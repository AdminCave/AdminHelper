(() => {
  const LANG_KEY = 'srm_docs_lang';
  const DOC_PAGES = new Set(['index.html', 'developer.html', 'administration.html']);

  function safeGetLangPreference() {
    try {
      const value = localStorage.getItem(LANG_KEY);
      return value === 'de' || value === 'en' ? value : null;
    } catch (_error) {
      return null;
    }
  }

  function safeSetLangPreference(lang) {
    if (lang !== 'de' && lang !== 'en') return;
    try {
      localStorage.setItem(LANG_KEY, lang);
    } catch (_error) {
      // Ignore storage issues and continue.
    }
  }

  function detectBrowserLang() {
    const raw =
      (Array.isArray(navigator.languages) && navigator.languages.length > 0 && navigator.languages[0]) ||
      navigator.language ||
      '';
    const normalized = String(raw).toLowerCase();
    return normalized.startsWith('de') ? 'de' : 'en';
  }

  function resolveDocRoute(pathname) {
    if (!pathname.includes('/docs')) return null;

    let file = pathname.split('/').pop() || '';
    const isDocsRootLike =
      pathname.endsWith('/docs') ||
      pathname.endsWith('/docs/') ||
      pathname.endsWith('/docs/en') ||
      pathname.endsWith('/docs/en/');

    if (!file || !file.endsWith('.html')) {
      if (isDocsRootLike) {
        file = 'index.html';
      } else {
        return null;
      }
    }

    if (!DOC_PAGES.has(file)) return null;

    const isEn = pathname.includes('/docs/en/') || pathname.endsWith('/docs/en');
    return { file, isEn };
  }

  function toLangPath(pathname, targetLang) {
    if (targetLang === 'en') {
      if (pathname.includes('/docs/en/') || pathname.endsWith('/docs/en')) return pathname;
      if (pathname.includes('/docs/')) return pathname.replace('/docs/', '/docs/en/');
      if (pathname.endsWith('/docs')) return `${pathname}/en`;
      return null;
    }

    if (targetLang === 'de') {
      if (pathname.includes('/docs/en/')) return pathname.replace('/docs/en/', '/docs/');
      if (pathname.endsWith('/docs/en')) return pathname.slice(0, -3);
      return pathname;
    }

    return null;
  }

  function applyAutoLanguageRouting() {
    const route = resolveDocRoute(window.location.pathname);
    if (!route) return false;

    const preferredLang = safeGetLangPreference() || detectBrowserLang();
    const currentLang = route.isEn ? 'en' : 'de';
    if (preferredLang === currentLang) return false;

    const targetPath = toLangPath(window.location.pathname, preferredLang);
    if (!targetPath || targetPath === window.location.pathname) return false;

    const target = `${targetPath}${window.location.search}${window.location.hash}`;
    window.location.replace(target);
    return true;
  }

  if (applyAutoLanguageRouting()) return;

  const langLinks = document.querySelectorAll('.lang-switch a');
  langLinks.forEach((link) => {
    const href = link.getAttribute('href') || '';
    const lang = href.includes('/en/') ? 'en' : 'de';
    link.addEventListener('click', () => safeSetLangPreference(lang));
  });

  const header = document.querySelector('.site-header');
  const menuBtn = document.querySelector('.menu-btn');
  const navLinks = document.querySelectorAll('.primary-nav a');
  const page = document.body.dataset.page;

  if (page) {
    navLinks.forEach((link) => {
      const target = link.dataset.page;
      if (target === page) link.classList.add('active');
    });
  }

  if (menuBtn && header) {
    menuBtn.addEventListener('click', () => {
      header.classList.toggle('open');
    });

    navLinks.forEach((link) => {
      link.addEventListener('click', () => header.classList.remove('open'));
    });
  }

  const revealEls = document.querySelectorAll('.reveal');
  if ('IntersectionObserver' in window && revealEls.length > 0) {
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('visible');
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach((el, index) => {
      el.style.transitionDelay = `${Math.min(index * 40, 180)}ms`;
      obs.observe(el);
    });
  } else {
    revealEls.forEach((el) => el.classList.add('visible'));
  }

  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());
})();
