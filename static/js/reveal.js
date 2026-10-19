/**
 * ETHPL — scroll reveal
 *
 * Adds `js-motion` to <html> so the CSS only hides content when JS is alive.
 * Without this, a JS failure would leave every [data-reveal] block at
 * opacity: 0 and the page would render blank.
 *
 * Entrances play once, then the observer releases the element.
 */
(function () {
  'use strict';

  var root = document.documentElement;

  var prefersReduced =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // No IntersectionObserver, or the reader asked for less motion:
  // leave everything in its natural, visible state.
  if (prefersReduced || !('IntersectionObserver' in window)) {
    return;
  }

  root.classList.add('js-motion');

  function reveal(el) {
    el.classList.add('is-revealed');
    // Release the compositor hint once the transition has finished.
    window.setTimeout(function () {
      el.classList.add('is-settled');
    }, 700);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var targets = document.querySelectorAll('[data-reveal], [data-reveal-group]');
    if (!targets.length) return;

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          reveal(entry.target);
          observer.unobserve(entry.target);
        });
      },
      {
        // Start slightly before the element reaches the fold so the motion
        // reads as "already arriving" rather than "triggered by me".
        rootMargin: '0px 0px -8% 0px',
        threshold: 0.08
      }
    );

    targets.forEach(function (el) {
      // Anything already in view on load reveals immediately — no scroll
      // should be required to see the first screen.
      var box = el.getBoundingClientRect();
      if (box.top < window.innerHeight * 0.92) {
        reveal(el);
      } else {
        observer.observe(el);
      }
    });
  });
})();
