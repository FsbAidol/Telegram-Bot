/**
 * app.js — логика Эмодзи-студии: загрузка каталога, галерея, поиск,
 * модалка просмотра, копипаст и фоновые частицы.
 */
(() => {
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const searchInput = document.getElementById('search');
  const modal = document.getElementById('modal');
  const modalPreview = document.getElementById('modal-preview');
  const modalTitle = document.getElementById('modal-title');
  const toastEl = document.getElementById('toast');

  let emojis = [];
  let current = null;
  let currentSvgText = '';

  // ---- Тост ----
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 1900);
  }

  // ---- Каталог ----
  async function loadEmojis() {
    try {
      const resp = await fetch('/api/emoji');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      emojis = await resp.json();
      render();
    } catch (e) {
      console.error(e);
      grid.innerHTML = '<p class="empty">⚠️ Не удалось загрузить каталог. Запусти Java-сервер (run.sh).</p>';
    }
  }

  // ---- Рендер галереи ----
  function render() {
    const q = searchInput.value.trim().toLowerCase();
    const list = emojis.filter(e =>
      !q || e.name.toLowerCase().includes(q) ||
      e.unicode.toLowerCase().includes(q) ||
      e.tags.some(t => t.toLowerCase().includes(q))
    );

    grid.innerHTML = '';
    empty.hidden = list.length > 0;

    const cards = list.map(e => {
      const card = document.createElement('button');
      card.className = 'card';
      card.type = 'button';
      card.innerHTML =
        `<img src="${e.svg}" alt="${e.name}" loading="lazy">
         <span class="card-name">${e.name}</span>
         <span class="card-code">${e.unicode}</span>`;
      card.addEventListener('click', () => openModal(e));
      grid.appendChild(card);
      return card;
    });

    if (list.length) {
      // Плавное появление со сдвигом по времени
      cards.forEach((c, i) => c.style.animationDelay = `${i * 45}ms`);
      EmojiScripts.stagger(cards, 'shimmer', { step: 45 });
    }
  }

  // ---- Модалка ----
  async function openModal(emoji) {
    current = emoji;
    modalPreview.innerHTML = `<img src="${emoji.svg}" alt="${emoji.name}">`;
    modalTitle.textContent = `${emoji.unicode} ${emoji.name}`;
    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    // Плавный запуск «скрипта» анимации превью
    const img = modalPreview.querySelector('img');
    img.style.translate = '0 0';
    EmojiScripts.run(emoji.anim || 'float', img, { amp: 8 });

    try {
      const resp = await fetch(emoji.svg);
      currentSvgText = await resp.text();
    } catch { currentSvgText = ''; }
  }

  function closeModal() {
    modal.hidden = true;
    document.body.style.overflow = '';
    modalPreview.innerHTML = '';
  }

  modal.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closeModal));
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });

  // ---- Копипаст ----
  async function copyText(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label} скопирован ✅`);
    } catch {
      // Фолбэк для окружений без clipboard API
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
      toast(`${label} скопирован ✅`);
    }
  }

  document.getElementById('modal-copy-unicode').addEventListener('click', () => {
    if (!current) return;
    EmojiScripts.run('confetti', document.querySelector('.modal-card'));
    copyText(current.unicode, 'Эмодзи');
  });

  document.getElementById('modal-copy-svg').addEventListener('click', () => {
    if (!currentSvgText) return;
    copyText(currentSvgText, 'SVG');
  });

  // ---- Поиск ----
  searchInput.addEventListener('input', render);

  // ---- Фон: летящие частицы-искорки ----
  function initParticles() {
    const canvas = document.getElementById('particles');
    const ctx = canvas.getContext('2d');
    let w, h, parts;

    function resize() {
      w = canvas.width = window.innerWidth * window.devicePixelRatio;
      h = canvas.height = window.innerHeight * window.devicePixelRatio;
      canvas.style.width = window.innerWidth + 'px';
      canvas.style.height = window.innerHeight + 'px';
      const count = Math.min(90, Math.floor(w * h / 26000));
      parts = Array.from({ length: count }, () => makePart());
    }
    function makePart() {
      return {
        x: Math.random() * w,
        y: Math.random() * h,
        r: (Math.random() * 1.6 + 0.5) * window.devicePixelRatio,
        vy: -(Math.random() * 0.25 + 0.05) * window.devicePixelRatio,
        vx: (Math.random() - 0.5) * 0.2 * window.devicePixelRatio,
        a: Math.random() * 0.5 + 0.2,
        tw: Math.random() * Math.PI * 2
      };
    }

    function tick() {
      ctx.clearRect(0, 0, w, h);
      for (const p of parts) {
        p.x += p.vx;
        p.y += p.vy;
        p.tw += 0.02;
        if (p.y < -10) { p.y = h + 10; p.x = Math.random() * w; }
        if (p.x < -10) p.x = w + 10;
        if (p.x > w + 10) p.x = -10;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(186, 230, 253, ${(p.a * (0.6 + Math.sin(p.tw) * 0.4)).toFixed(2)})`;
        ctx.shadowColor = 'rgba(125, 211, 252, 0.8)';
        ctx.shadowBlur = 6;
        ctx.fill();
      }
      requestAnimationFrame(tick);
    }

    window.addEventListener('resize', resize, { passive: true });
    resize();
    tick();
  }

  // ---- Telegram WebApp: тема и разложение ----
  function initTelegram() {
    const tg = window.Telegram?.WebApp;
    if (!tg) return;
    tg.ready?.();
    tg.expand?.();
    const bg = getComputedStyle(document.body).backgroundColor;
    try { tg.setBackgroundColor(bg); } catch { /* игнорируем */ }
  }

  // ---- Hero-логотип (анимированный SVG) ----
  function initHeroLogo() {
    const hero = document.getElementById('hero-logo');
    hero.innerHTML = '<img src="emoji/rocket.svg" alt="🎨">';
    const img = hero.querySelector('img');
    EmojiScripts.run('float', img, { amp: 4 });
  }

  initTelegram();
  initParticles();
  initHeroLogo();
  loadEmojis();
})();
