/**
 * ETHPL CORPORATE TRAVEL & EVENT CATALOGUE - CONTROLLER
 */

// CTA_TARGETS and triggerRedirect() used to live here: a frozen map that sent
// package and venue buttons out to the partner domain. Both catalogue sections
// were retired in Phase 1d and every CTA now opens our own enquiry form, so the
// map and the redirect helper are gone rather than left unused. Any code still
// calling triggerRedirect would be a bug, not a fallback.

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initDropdowns();
  initStickyRfpBar();
  initModalAndRFP();
});

/* ── 1. Navbar & Mobile Menu ────────────────────────────────────────── */
function initNavbar() {
  const navbar = document.querySelector('.navbar');
  const toggle = document.querySelector('.mobile-toggle');
  const menu = document.querySelector('.nav-menu');

  window.addEventListener('scroll', () => {
    if (window.scrollY > 30) {
      navbar?.classList.add('scrolled');
    } else {
      navbar?.classList.remove('scrolled');
    }
  }, { passive: true });

  if (toggle && menu) {
    toggle.addEventListener('click', () => {
      const isOpen = menu.classList.toggle('open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    // Close menu when clicking outside
    document.addEventListener('click', (e) => {
      if (!toggle.contains(e.target) && !menu.contains(e.target) && menu.classList.contains('open')) {
        menu.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
}

/* ── 2. Services Dropdown Menu ───────────────────────────────────────── */
function initDropdowns() {
  const dropdowns = document.querySelectorAll('.nav-item-dropdown');
  dropdowns.forEach(dropdown => {
    const toggle = dropdown.querySelector('.nav-dropdown-toggle');
    const menu = dropdown.querySelector('.nav-dropdown-menu');
    if (!toggle || !menu) return;

    toggle.addEventListener('click', (e) => {
      e.preventDefault();
      const isOpen = dropdown.classList.toggle('open');
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target) && dropdown.classList.contains('open')) {
        dropdown.classList.remove('open');
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  });
}

/* ── 3. Sticky RFP Bar with Scroll & Session Storage ─────────────────── */
const RFP_BAR_DISMISSED_KEY = 'ethpl_rfp_bar_dismissed';

/* Storage is unavailable in private windows and wherever the reader has
   blocked site data, and merely touching it throws there. This init runs
   ahead of the catalogue and the RFP modal, so an unguarded read would take
   down the whole conversion path over a dismissable banner. */
function readRfpBarDismissed() {
  try {
    return sessionStorage.getItem(RFP_BAR_DISMISSED_KEY) === 'true';
  } catch (err) {
    return false;
  }
}

function rememberRfpBarDismissed() {
  try {
    sessionStorage.setItem(RFP_BAR_DISMISSED_KEY, 'true');
  } catch (err) {
    /* The bar still stays down for this page view; it just returns on the
       next navigation. Losing that beats breaking the page. */
  }
}

function initStickyRfpBar() {
  const rfpBar = document.getElementById('sticky-rfp-bar');
  const dismissBtn = document.getElementById('dismiss-sticky-rfp');
  const heroSection = document.querySelector('.hero-section');

  if (!rfpBar) return;
  if (readRfpBarDismissed()) return;

  function updateBarVisibility() {
    const heroHeight = heroSection ? heroSection.offsetHeight : 300;
    rfpBar.classList.toggle('visible', window.scrollY > heroHeight * 0.7);
  }

  window.addEventListener('scroll', updateBarVisibility, { passive: true });
  updateBarVisibility();

  dismissBtn?.addEventListener('click', () => {
    /* Detach the listener outright rather than gating it behind a flag. The
       previous version captured `isDismissed` in a const at init, so the
       dismiss handler had no way to change what the scroll handler saw and
       the very next scroll event put the bar straight back. Dismissal is
       final for the session, so there is nothing left to listen for. */
    window.removeEventListener('scroll', updateBarVisibility);
    rfpBar.classList.remove('visible');
    rememberRfpBarDismissed();
  });
}

/* ── 6. Accessible RFP Modal & Honest Lead Submission (F-18, F-19) ───── */
function initModalAndRFP() {
  const modal = document.getElementById('rfp-modal');
  const openBtns = document.querySelectorAll('.open-rfp-btn');
  const closeBtn = document.getElementById('close-rfp-btn');
  const form = document.getElementById('rfp-form');
  const feedback = document.getElementById('rfp-form-feedback');
  let lastFocusedElement = null;

  function clearFieldErrors() {
    form?.querySelectorAll('.field-error-msg').forEach(el => el.remove());
    form?.querySelectorAll('[aria-invalid="true"]').forEach(el => {
      el.removeAttribute('aria-invalid');
      el.removeAttribute('aria-describedby');
      el.classList.remove('input-error');
    });
    if (feedback) {
      feedback.className = 'sr-only';
      feedback.textContent = '';
    }
  }

  /* Pre-select the destination the visitor actually clicked.
     Matching is done against the option's own value rather than by index, so
     adding or reordering destinations in content/destinations/ cannot silently
     select the wrong one. A name with no matching option is left alone — the
     dropdown keeps its "Not decided yet" default rather than guessing. */
  function presetDestination(destinationName) {
    if (!destinationName) return;
    const select = modal?.querySelector('#rfp-destination');
    if (!select) return;
    const match = Array.from(select.options).find(
      option => option.value === destinationName
    );
    if (match) select.value = match.value;
  }

  /* Audience pages pass the organisation type they are written for, so a
     principal arriving from the schools page does not have to re-state it.
     Matched against option values for the same reason as the destination. */
  function presetOrganisationType(typeName) {
    if (!typeName) return;
    const select = modal?.querySelector('#rfp-org-type');
    if (!select) return;
    const match = Array.from(select.options).find(
      option => option.value.toLowerCase() === typeName.toLowerCase()
    );
    if (match) select.value = match.value;
  }

  /* Homepage chips ("Conference", "Offsite", …) open the form with the event
     type already chosen, so the visitor starts a step in rather than facing an
     empty form. Same value-matching rule as the other two prefills. */
  function presetEventType(eventType) {
    if (!eventType) return;
    const select = modal?.querySelector('#rfp-event-type');
    if (!select) return;
    const match = Array.from(select.options).find(
      option => option.value === eventType
    );
    if (match) select.value = match.value;
  }

  function openModal(destinationName, organisationType, eventType) {
    if (!modal) return;
    lastFocusedElement = document.activeElement;
    clearFieldErrors();
    presetDestination(destinationName);
    presetOrganisationType(organisationType);
    presetEventType(eventType);
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    // Focus first interactive element in modal
    const firstInput = modal.querySelector('input, select, textarea, button');
    firstInput?.focus();
  }

  window.openRfpModal = openModal;

  function closeModal() {
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
    if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
      lastFocusedElement.focus();
    }
  }

  openBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      // Destination pages, audience pages and homepage chips each pass their
      // own context; a plain CTA passes nothing and the form opens blank.
      openModal(
        btn.getAttribute('data-destination'),
        btn.getAttribute('data-organisation-type'),
        btn.getAttribute('data-event-type')
      );
    });
  });

  closeBtn?.addEventListener('click', closeModal);

  modal?.addEventListener('click', (e) => {
    if (e.target === modal) {
      closeModal();
    }
  });

  // Keyboard navigation: ESC to close, TAB trapping
  document.addEventListener('keydown', (e) => {
    if (!modal || !modal.classList.contains('open')) return;

    if (e.key === 'Escape') {
      e.preventDefault();
      closeModal();
      return;
    }

    if (e.key === 'Tab') {
      const focusables = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      const focusableList = Array.from(focusables).filter(el => !el.hasAttribute('disabled') && el.offsetParent !== null);
      
      if (focusableList.length === 0) return;
      
      const first = focusableList[0];
      const last = focusableList[focusableList.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
  });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    clearFieldErrors();

    const submitBtn = form.querySelector('button[type="submit"]');
    const originalBtnText = submitBtn ? submitBtn.textContent : 'Submit Proposal Request';
    
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = 'Submitting Request...';
    }

    const formData = new FormData(form);
    const payload = {
      company_name: (formData.get('company_name') || '').toString().trim(),
      contact_name: (formData.get('contact_name') || '').toString().trim(),
      contact_info: (formData.get('contact_info') || '').toString().trim(),
      destination: (formData.get('destination') || 'General Inquiry').toString().trim(),
      pax_count: parseInt(formData.get('pax_count')?.toString() || '100', 10),
      notes: (formData.get('notes') || '').toString().trim() || null,
      /* Qualifying answers. These must also be declared on RFPPayload in
         schemas.py — that model sets extra="forbid", so an undeclared field
         here fails the whole submission with a 422 rather than being ignored. */
      organisation_type: (formData.get('organisation_type') || '').toString().trim() || null,
      event_type: (formData.get('event_type') || '').toString().trim() || null,
      travel_window: (formData.get('travel_window') || '').toString().trim() || null
    };

    /**
     * Honest failure state.
     *
     * There is deliberately no fabricated success message and no reference
     * number here — nothing was received, so nothing is confirmed. The form is
     * left untouched so the user's input survives and a retry costs them
     * nothing.
     */
    function showSubmitFailure(reasonMessage) {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = originalBtnText;
      }
      if (!feedback) return;

      feedback.className = 'disclaimer-banner';
      feedback.textContent = '';

      const banner = document.createElement('div');
      banner.style.color = 'var(--amber-900)';

      const strong = document.createElement('strong');
      strong.textContent = reasonMessage;
      banner.appendChild(strong);
      banner.appendChild(document.createElement('br'));

      banner.appendChild(document.createTextNode(
        'Your request was not sent. Nothing you typed has been lost — please try again in a moment.'
      ));

      feedback.appendChild(banner);
    }

    try {
      const response = await fetch('/api/rfp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': crypto.randomUUID()
        },
        body: JSON.stringify(payload)
      });

      if (response.ok) {
        const resData = await response.json().catch(() => null);
        const reference = resData?.data?.reference || resData?.reference;

        if (reference) {
          if (feedback) {
            feedback.className = 'disclaimer-banner';
            feedback.textContent = `Thank you! Your proposal request has been registered under reference ${reference}. Our team will contact you within 24 hours.`;
          }
          form.reset();

          /* Hand off to the thank-you page so ad and analytics conversions
             fire on a real page view. The server names the destination rather
             than the path being hard-coded here, and a missing or off-site
             value falls back to closing the modal — an open redirect would be
             a gift to anyone who could tamper with the response. */
          /* The conversion that matters. Fired here rather than on the
             thank-you page view so it is recorded even if the redirect is
             blocked or the visitor closes the tab immediately. */
          if (typeof window.ethplTrack === 'function') {
            window.ethplTrack('generate_lead', {
              form_id: 'rfp',
              organisation_type: payload.organisation_type || 'unspecified',
              event_type: payload.event_type || 'unspecified',
              destination: payload.destination || 'unspecified'
            });
          }

          const next = resData?.next;
          const safeNext = typeof next === 'string' && /^\/[^/\\]/.test(next) ? next : null;

          setTimeout(() => {
            if (safeNext) {
              window.location.assign(safeNext);
              return;
            }
            closeModal();
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = originalBtnText;
            }
          }, 1200);
        } else {
          // 2xx response without valid reference
          showSubmitFailure('Online RFP submission is currently in demonstration mode.');
        }
      } else if (response.status === 422) {
        // Field-level validation error from server
        const resData = await response.json().catch(() => null);
        const fields = resData?.fields || {};
        let firstInvalidInput = null;

        Object.entries(fields).forEach(([fieldName, errorMsg]) => {
          const inputEl = form.querySelector(`[name="${fieldName}"]`);
          if (inputEl) {
            inputEl.classList.add('input-error');
            inputEl.setAttribute('aria-invalid', 'true');
            const errId = `err-${fieldName}`;
            inputEl.setAttribute('aria-describedby', errId);

            const errSpan = document.createElement('span');
            errSpan.id = errId;
            errSpan.className = 'field-error-msg';
            errSpan.style.cssText = 'color: var(--amber-700); font-size: 0.78rem; display: block; margin-top: 4px;';
            errSpan.textContent = errorMsg;
            inputEl.parentNode.appendChild(errSpan);

            if (!firstInvalidInput) firstInvalidInput = inputEl;
          }
        });

        if (firstInvalidInput) {
          firstInvalidInput.focus();
        }

        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = originalBtnText;
        }
      } else {
        // 500 or other non-2xx status
        showSubmitFailure('Could not connect to the proposal server.');
      }
    } catch (err) {
      // Network error or endpoint offline
      showSubmitFailure('Unable to submit online right now.');
    }
  });
}

