(() => {
  const LANG_KEY = 'adminhelper_docs_lang';

  /* ─── Sprach-Persistenz ─────────────────────────────────────────── */
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
      /* storage gesperrt (Private Mode) – still weiter */
    }
  }

  function detectBrowserLang() {
    const raw =
      (Array.isArray(navigator.languages) && navigator.languages.length > 0 && navigator.languages[0]) ||
      navigator.language ||
      '';
    return String(raw).toLowerCase().startsWith('de') ? 'de' : 'en';
  }

  /* ─── Pfad-Logik für DE/EN-Spiegelung ───────────────────────────
     Struktur:
       /docs/                          DE-Landing
       /docs/en/                       EN-Landing
       /docs/admin/<page>.html         DE-Admin
       /docs/en/admin/<page>.html      EN-Admin
       /docs/developer/<page>.html     DE-Dev
       /docs/en/developer/<page>.html  EN-Dev
     Jede Seite unter /docs/en/ entspricht 1:1 dem gleichen Pfad unter /docs/.
  ─────────────────────────────────────────────────────────────── */
  function isDocsPath(pathname) {
    return pathname === '/docs' || pathname.startsWith('/docs/') || pathname.endsWith('/docs');
  }

  function getLangFromPath(pathname) {
    if (pathname === '/docs/en' || pathname === '/docs/en/' || pathname.startsWith('/docs/en/')) {
      return 'en';
    }
    return 'de';
  }

  function toLangPath(pathname, targetLang) {
    const currentLang = getLangFromPath(pathname);
    if (currentLang === targetLang) return pathname;

    if (targetLang === 'en') {
      if (pathname === '/docs' || pathname === '/docs/') return '/docs/en/';
      if (pathname.startsWith('/docs/')) return pathname.replace('/docs/', '/docs/en/');
      return null;
    }

    if (targetLang === 'de') {
      if (pathname === '/docs/en' || pathname === '/docs/en/') return '/docs/';
      if (pathname.startsWith('/docs/en/')) return pathname.replace('/docs/en/', '/docs/');
      return null;
    }

    return null;
  }

  function applyAutoLanguageRouting() {
    if (!isDocsPath(window.location.pathname)) return false;
    if (document.documentElement.dataset.noAutoLang === 'true') return false;

    const preferredLang = safeGetLangPreference() || detectBrowserLang();
    const currentLang = getLangFromPath(window.location.pathname);
    if (preferredLang === currentLang) return false;

    const targetPath = toLangPath(window.location.pathname, preferredLang);
    if (!targetPath || targetPath === window.location.pathname) return false;

    window.location.replace(`${targetPath}${window.location.search}${window.location.hash}`);
    return true;
  }

  if (applyAutoLanguageRouting()) return;

  /* ─── Sprach-Switch im Header ───────────────────────────────────── */
  document.querySelectorAll('.lang-switch a').forEach((link) => {
    const href = link.getAttribute('href') || '';
    const lang = href.includes('/en/') || href.endsWith('/en') ? 'en' : 'de';
    link.addEventListener('click', () => safeSetLangPreference(lang));
  });

  /* ─── Aktiven Sidebar-Eintrag markieren ─────────────────────────
     Setzt .is-active auf den Link, dessen href zum aktuellen Pfad passt.
     Präfer längster Match (damit /docs/admin/monitoring.html nicht
     fälschlich /docs/admin/ als aktiv markiert).
  ─────────────────────────────────────────────────────────────── */
  const sidebarLinks = document.querySelectorAll('.sidebar-nav a[href]');
  if (sidebarLinks.length > 0) {
    const current = window.location.pathname.replace(/\/index\.html$/, '/');
    let bestMatch = null;
    let bestLen = -1;
    sidebarLinks.forEach((link) => {
      const href = link.getAttribute('href') || '';
      const normalized = href.replace(/\/index\.html$/, '/');
      if (current === normalized || current.endsWith(normalized)) {
        if (normalized.length > bestLen) {
          bestMatch = link;
          bestLen = normalized.length;
        }
      }
    });
    if (bestMatch) bestMatch.classList.add('is-active');
  }

  /* ─── Mobile-Sidebar-Toggle ─────────────────────────────────────
     Button .menu-toggle öffnet/schließt die .sidebar. Ein .sidebar-backdrop
     wird bei Bedarf erzeugt und schließt beim Klick die Sidebar.
  ─────────────────────────────────────────────────────────────── */
  const sidebar = document.querySelector('.sidebar');
  const menuToggle = document.querySelector('.menu-toggle');

  if (sidebar && menuToggle) {
    let backdrop = document.querySelector('.sidebar-backdrop');
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.className = 'sidebar-backdrop';
      document.body.appendChild(backdrop);
    }

    const openSidebar = () => {
      sidebar.classList.add('is-open');
      backdrop.classList.add('is-visible');
      menuToggle.setAttribute('aria-expanded', 'true');
    };

    const closeSidebar = () => {
      sidebar.classList.remove('is-open');
      backdrop.classList.remove('is-visible');
      menuToggle.setAttribute('aria-expanded', 'false');
    };

    menuToggle.addEventListener('click', () => {
      if (sidebar.classList.contains('is-open')) closeSidebar();
      else openSidebar();
    });

    backdrop.addEventListener('click', closeSidebar);
    sidebar.querySelectorAll('a').forEach((a) => a.addEventListener('click', closeSidebar));

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') closeSidebar();
    });
  }

  /* ─── Reveal-Animation ──────────────────────────────────────────── */
  const revealEls = document.querySelectorAll('[data-reveal]');
  if ('IntersectionObserver' in window && revealEls.length > 0) {
    const obs = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );
    revealEls.forEach((el, i) => {
      el.style.transitionDelay = `${Math.min(i * 40, 180)}ms`;
      obs.observe(el);
    });
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }

  /* ─── Copy-Button für <pre> ─────────────────────────────────────
     Fügt automatisch in jede .code-header einen „Copy"-Button ein.
  ─────────────────────────────────────────────────────────────── */
  document.querySelectorAll('pre').forEach((pre) => {
    if (pre.dataset.noCopy === 'true') return;
    const btn = document.createElement('button');
    btn.className = 'btn btn-ghost btn-sm code-copy';
    btn.type = 'button';
    btn.textContent = 'Copy';
    btn.style.position = 'absolute';
    btn.style.top = '8px';
    btn.style.right = '8px';
    btn.style.opacity = '0';
    btn.style.transition = 'opacity .15s';

    pre.addEventListener('mouseenter', () => (btn.style.opacity = '1'));
    pre.addEventListener('mouseleave', () => (btn.style.opacity = '0'));

    btn.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(pre.innerText);
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => (btn.textContent = original), 1200);
      } catch {
        /* Clipboard-API nicht verfügbar – still weiter */
      }
    });

    pre.appendChild(btn);
  });

  /* ─── Jahr im Footer ────────────────────────────────────────────── */
  const yearEl = document.getElementById('year');
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());
})();
