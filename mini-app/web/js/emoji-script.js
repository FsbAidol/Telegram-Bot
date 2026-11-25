/**
 * emoji-script.js — движок «скриптов» анимации SVG-эмодзи.
 *
 * Каждый «скрипт» — агрегированная функция, которая управляет элементом через
 * плавные таймлайны на requestAnimationFrame (с easing). Скрипты регистрируются
 * в движке и применяются к карточкам/превью эмодзи.
 */
const EmojiScripts = (() => {
  // ---- Easing: плавные функции интерполяции ----
  const easing = {
    linear: t => t,
    easeOut: t => 1 - Math.pow(1 - t, 3),
    easeInOut: t => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2,
    elastic: t => {
      const c4 = (2 * Math.PI) / 3;
      return t === 0 ? 0 : t === 1 ? 1 :
        Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * c4) + 1;
    },
    bounce: t => {
      const n1 = 7.5625, d1 = 2.75;
      if (t < 1 / d1) return n1 * t * t;
      if (t < 2 / d1) return n1 * (t -= 1.5 / d1) * t + 0.75;
      if (t < 2.5 / d1) return n1 * (t -= 2.25 / d1) * t + 0.9375;
      return n1 * (t -= 2.625 / d1) * t + 0.984375;
    }
  };

  const scripts = new Map();

  // Запускает функцию скрипта один раз
  function register(name, fn) { scripts.set(name, fn); }

  function run(name, el, opts = {}) {
    const fn = scripts.get(name);
    if (!fn) return;
    try { fn(el, opts); } catch (e) { console.warn('[emoji-script]', name, e); }
  }

  // ---- Вспомогательное: таймлайн ----
  function timeline(el, steps) {
    // steps: [{ from, to, dur, ease, prop }]
    let start = null;
    return new Promise(resolve => {
      function frame(ts) {
        if (start === null) start = ts;
        const elapsed = ts - start;
        let done = true;
        for (const step of steps) {
          const t = Math.min(1, elapsed / step.dur);
          const v = step.from + (step.to - step.from) * (step.ease || easing.easeOut)(t);
          el.style.setProperty(step.prop, v);
          if (t < 1) done = false;
        }
        if (!done) requestAnimationFrame(frame);
        else resolve();
      }
      requestAnimationFrame(frame);
    });
  }

  // ---- Loop: циклическая анимация через rAF ----
  function loop(el, update, opts = {}) {
    const dur = opts.dur || 2000;
    let start = null;
    function frame(ts) {
      if (start === null) start = ts;
      update(((ts - start) % dur) / dur);
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
    return el;
  }

  // ---- Скрипты ----

  // Появление карточки: эластичный пасхальный эффект
  register('pop', (el) => {
    el.style.opacity = '0';
    timeline(el, [
      { from: 0.94, to: 1, dur: 550, ease: easing.elastic, prop: '--scale' },
      { from: 0, to: 1, dur: 450, ease: easing.easeOut, prop: 'opacity' }
    ]).then(() => { el.style.opacity = ''; });
  });

  // Двусторонний блеск при наведении (через CSS-класс)
  register('shimmer', (el) => {
    el.addEventListener('pointerenter', () => el.classList.add('is-shimmer'), { passive: true });
    el.addEventListener('pointerleave', () => el.classList.remove('is-shimmer'), { passive: true });
  });

  // Плавное парение
  register('float', (el, opts = {}) => {
    const amp = opts.amp || 6;
    loop(el, t => {
      const y = Math.sin(t * Math.PI * 2) * amp;
      const r = Math.sin(t * Math.PI * 4) * 2;
      el.style.translate = `0 ${y.toFixed(2)}px`;
      el.style.rotate = `${r.toFixed(2)}deg`;
    }, { dur: 2600 });
  });

  // Мягкое пульсирование (пропорции)
  register('pulse', (el, opts = {}) => {
    const base = opts.base || 1;
    const amp = opts.amp || 0.06;
    loop(el, t => {
      const s = base + Math.sin(t * Math.PI * 2) * amp;
      el.style.setProperty('--scale', s.toFixed(3));
    }, { dur: 1600 });
  });

  // Мерцание
  register('twinkle', (el, opts = {}) => {
    const base = opts.base || 1;
    loop(el, t => {
      const s = base + Math.sin(t * Math.PI * 3) * 0.05;
      el.style.setProperty('--scale', s.toFixed(3));
    }, { dur: 1200 });
  });

  // Вращение
  register('spin', (el, opts = {}) => {
    const speed = opts.speed || 3000;
    loop(el, t => {
      el.style.rotate = `${(t * 360).toFixed(1)}deg`;
    }, { dur: speed });
  });

  // Парящее свечение
  register('glow', (el, opts = {}) => {
    const amp = opts.amp || 0.08;
    loop(el, t => {
      const s = 1 + Math.sin(t * Math.PI * 2) * amp;
      el.style.setProperty('--scale', s.toFixed(3));
      el.style.filter = `drop-shadow(0 10px 24px rgba(56, 189, 248, ${(0.35 + Math.sin(t * Math.PI * 2) * 0.25).toFixed(2)}))`;
    }, { dur: 2200 });
  });

  // Волна (для радуги: сдвиг по Y)
  register('wave', (el, opts = {}) => {
    const amp = opts.amp || 5;
    loop(el, t => {
      el.style.translate = `0 ${(Math.sin(t * Math.PI * 2) * amp).toFixed(2)}px`;
    }, { dur: 2800 });
  });

  // Конфетти-всплеск при клике
  register('confetti', (el, opts = {}) => {
    const rect = el.getBoundingClientRect();
    const colors = ['#f43f5e', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#38bdf8'];
    const parts = [];
    for (let i = 0; i < 18; i++) {
      const dot = document.createElement('span');
      dot.style.cssText = `
        position: fixed; left: ${rect.left + rect.width / 2}px; top: ${rect.top + rect.height / 2}px;
        width: 8px; height: 8px; border-radius: 2px; background: ${colors[i % colors.length]};
        pointer-events: none; z-index: 90;`;
      document.body.appendChild(dot);
      parts.push({ el: dot, angle: (Math.PI * 2 * i) / 18, dist: 70 + Math.random() * 70, spin: (Math.random() - 0.5) * 720 });
    }
    const start = performance.now();
    function frame(ts) {
      const t = (ts - start) / 1000;
      let alive = false;
      for (const p of parts) {
        if (t < 0.9) {
          const d = p.dist * easing.easeOut(t / 0.9);
          p.el.style.transform = `translate(${Math.cos(p.angle) * d}px, ${Math.sin(p.angle) * d + 240 * t * t}px) rotate(${p.spin * t}deg)`;
          p.el.style.opacity = String(1 - t / 0.9);
          alive = true;
        } else {
          p.el.remove();
        }
      }
      if (alive) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  });

  // Флипка вспышки при клике
  register('flicker', (el, opts = {}) => {
    const original = el.style.filter;
    el.style.filter = `drop-shadow(0 0 18px rgba(255, 160, 60, 0.9))`;
    setTimeout(() => { el.style.filter = original; }, 400);
  });

  // Стаggered запуск: по очереди на каждую карточку
  function stagger(cards, scriptName, opts = {}) {
    const step = opts.step || 60;
    cards.forEach((card, i) => {
      setTimeout(() => run(scriptName, card, opts), i * step);
    });
  }

  return { register, run, stagger, timeline, loop, easing };
})();
