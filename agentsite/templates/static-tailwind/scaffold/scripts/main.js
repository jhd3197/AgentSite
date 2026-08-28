/*
 * Sitewide scripts: mobile nav toggle + current-page nav highlighting.
 * Vanilla JavaScript only — no frameworks.
 */
(function () {
  'use strict';

  /* ---------- Mobile nav toggle ---------- */
  var toggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');

  if (toggle && nav) {
    toggle.addEventListener('click', function () {
      var isOpen = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });
  }

  /* ---------- Highlight the current page in the nav ---------- */
  var currentPage = window.location.pathname.split('/').pop() || 'index.html';
  var links = document.querySelectorAll('.site-nav__link');

  Array.prototype.forEach.call(links, function (link) {
    if (link.getAttribute('href') === currentPage) {
      link.classList.add('is-active');
      link.setAttribute('aria-current', 'page');
    }
  });
})();
