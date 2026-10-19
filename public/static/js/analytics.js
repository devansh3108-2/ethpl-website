/**
 * ETHPL — conversion event tracking.
 *
 * Reports the four things worth knowing about this site: that someone opened
 * the enquiry form, that they submitted it, and that they tapped a phone
 * number or a WhatsApp link. Without these, analytics shows traffic but not
 * whether any of it turned into an enquiry, which is the only number that
 * matters here.
 *
 * Everything is defensive: if no analytics ID is configured, gtag and clarity
 * are simply absent and every call here is a no-op. Tracking must never be
 * able to break the form it is measuring.
 */

(function () {
  'use strict';

  /* GA4 recommended names where one fits (generate_lead), descriptive ones
     otherwise. Keeping to the recommended vocabulary means GA4's own reports
     and conversion settings understand the event without configuration. */
  function track(eventName, params) {
    try {
      if (typeof window.gtag === 'function') {
        window.gtag('event', eventName, params || {});
      }
      if (typeof window.clarity === 'function') {
        window.clarity('event', eventName);
      }
    } catch (err) {
      /* Analytics is never load-bearing. A blocked script, an ad blocker or a
         privacy extension must not surface as a broken page. */
    }
  }

  // Exposed so app.js can report a successful submission without importing
  // anything; it checks for the function before calling it.
  window.ethplTrack = track;

  document.addEventListener('DOMContentLoaded', function () {
    /* Form opened. Fired once per page view rather than per click: someone
       opening the modal three times is one interested visitor, and counting
       it three times would overstate the funnel's top. */
    var formOpened = false;
    document.querySelectorAll('.open-rfp-btn').forEach(function (button) {
      button.addEventListener('click', function () {
        if (formOpened) return;
        formOpened = true;
        track('form_start', {
          form_id: 'rfp',
          // Which CTA earned the click — destination card, chip, nav, hero.
          cta_location: button.getAttribute('data-destination')
            || button.getAttribute('data-event-type')
            || button.getAttribute('data-organisation-type')
            || 'generic'
        });
      });
    });

    /* Phone and WhatsApp taps. These are conversions in their own right —
       plenty of buyers in this market will call rather than fill in a form,
       and without this they would be invisible in the funnel. */
    document.querySelectorAll('[data-track]').forEach(function (element) {
      element.addEventListener('click', function () {
        var kind = element.getAttribute('data-track');
        if (kind === 'phone-click') {
          track('phone_click', { method: 'tel' });
        } else if (kind === 'whatsapp-click') {
          track('whatsapp_click', { method: 'whatsapp' });
        }
      });
    });
  });
})();
