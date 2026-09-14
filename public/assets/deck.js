(() => {
  if (!['localhost', '127.0.0.1', '[::1]', ''].includes(location.hostname)) {
    const analytics = document.createElement('script');
    analytics.src = '/_vercel/insights/script.js';
    analytics.defer = true;
    document.head.append(analytics);
  }
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  const targets = document.querySelectorAll('[data-reveal], .deck-digest .tone-section, .deck-digest .card-icon, .deck-digest .reader-tally, .deck-digest .callout-disagreement, .deck-digest .readers-section h2, .deck-digest .readers-section table');
  let observer;
  if (!preference.matches && 'IntersectionObserver' in window) {
    observer = new IntersectionObserver(entries => {
      let delay = 0;
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const element = entry.target;
        const detail = element.matches('.card-icon, .reader-tally, .callout-disagreement, .readers-section h2, .readers-section table');
        const entrance = detail ? 'detail-enter' : 'reveal-enter';
        element.style.animationDelay = `${detail ? 0 : delay}ms`;
        element.classList.add(entrance);
        delay += 45;
        const finish = event => {
          // Tally marks animate individually; wait for the final mark to settle.
          const last = element.matches('.reader-tally') ? element.lastElementChild : element;
          if (event.target !== last) return;
          element.classList.remove(entrance);
          element.style.animationDelay = '';
          element.removeEventListener('animationend', finish);
        };
        element.addEventListener('animationend', finish);
        observer.unobserve(element);
      });
    }, { threshold: 0, rootMargin: '0px 0px 24px 0px' });
    targets.forEach(element => observer.observe(element));
  }
  preference.addEventListener('change', () => {
    if (preference.matches) {
      observer?.disconnect();
      targets.forEach(element => {
        element.classList.remove('reveal-enter', 'detail-enter');
        element.style.animationDelay = '';
      });
    }
  });
})();
