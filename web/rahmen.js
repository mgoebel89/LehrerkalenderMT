'use strict';
// Rahmen fuer alle Seiten: die Bereiche der Seitenleiste an einer Stelle (App und Unterrichtsbesuche). Die App
// (app.html, app.js) hat Kopf und Seitenleiste im HTML; die Seiten der Unterrichtsbesuche (eigene Seiten aus dem alten
// Lehrerkalender, eigene Stile) bekommen beides hier mit umUb() dazu, damit die Seitenleiste dort nicht verschwindet.
const Rahmen = (() => {
  const BEREICHE = [
    { a: 'start', text: 'Start', sym: 'start' },
    { a: 'planung', text: 'Planung', sym: 'plan' },
    { a: 'klassen', text: 'Klassen', sym: 'klassen' },
    { a: 'pruefungen', text: 'Prüfungen', sym: 'pruefung' },
    { a: 'formulare', text: 'Formulare', sym: 'formular' },
    { a: 'unterrichtsbesuche', text: 'Unterrichtsbesuche', sym: 'auge', adresse: '/unterrichtsbesuche', nurUb: true },
    { a: 'dokumente', text: 'Dokumente', sym: 'archiv', nurPaperless: true },
    { a: 'einstellungen', text: 'Einstellungen', sym: 'einstellungen' },
    { a: 'admin-konten', text: 'Konten', sym: 'lehrkraefte', admin: true, gruppe: 'Admin' },
    { a: 'admin-grunddaten', text: 'Grunddaten', sym: 'pakete', admin: true },
    { a: 'admin-klassen', text: 'Klassenverwaltung', sym: 'klassen', admin: true },
    { a: 'admin-noten', text: 'Notenschlüssel', sym: 'schluessel', admin: true },
    { a: 'admin-system', text: 'System', sym: 'admin', admin: true },
  ];

  // Seitenleiste fuellen. aktiv: Bereich (a); basis: '' in der App, '/app' auf anderen Seiten (Links dann /app#...)
  function navigation(nav, konto, update, aktiv, basis = '') {
    const el = L.el;
    const teile = [];
    for (const b of BEREICHE) {
      if (b.admin && konto.rolle !== 'admin') continue;
      if (b.nurUb && !konto.ub_an) continue;
      if (b.nurPaperless && !konto.paperless) continue;
      if (b.gruppe) teile.push(el('span', { class: 'etikett', style: 'padding:12px 12px 4px', text: b.gruppe }));
      if (b.spaeter) {
        teile.push(el('span', { class: 'nav-spaeter', title: 'kommt mit ' + b.spaeter }, L.symbol(b.sym), b.text,
          el('span', { class: 'chip klein', text: b.spaeter })));
        continue;
      }
      teile.push(el('a', { href: b.adresse || basis + '#' + b.a, class: b.a === aktiv ? 'an' : null }, L.symbol(b.sym), b.text,
        b.a === 'admin-system' && update ? el('span', { class: 'chip gelb klein', text: 'Update' }) : null));
    }
    L.setzen(nav, teile);
  }

  // Seiten der Unterrichtsbesuche: Kopf und Seitenleiste wie in der App um den vorhandenen Inhalt legen
  async function umUb() {
    const el = L.el;
    let ich;
    try { ich = await L.api('GET', '/api/ich'); } catch (e) { location.href = '/anmelden'; return; }
    const alt = document.querySelector('header.ub-leiste');
    const titel = alt && alt.querySelector('span') ? alt.querySelector('span').textContent : 'Unterrichtsbesuche';
    const logo = ich.schule && ich.schule.logo
      ? el('img', { class: 'lk-schul-logo', src: '/api/schule/logo?v=' + encodeURIComponent(ich.schule.stand), alt: ich.schule.name }) : null;
    const kopf = el('header', { class: 'lk-kopf' },
      el('a', { class: 'lk-marke', href: '/app#start' }, el('img', { src: '/static/symbol.svg', alt: '', width: 26, height: 26 }), 'Lehrerkalender MT'),
      logo, el('span', { class: 'lk-unter', text: titel }),
      el('span', { class: 'lk-rechts' }, el('span', { class: 'lk-wer', text: ich.konto.name }),
        el('button', { type: 'button', class: 'lk-abmelden', onclick: async () => {
          try { await L.api('POST', '/api/abmelden', {}); } catch (e) { /* trotzdem weg */ }
          location.href = '/anmelden';
        } }, 'Abmelden')));
    const nav = el('nav', { class: 'lk-seite', 'aria-label': 'Bereiche' });
    navigation(nav, ich.konto, ich.update, 'unterrichtsbesuche', '/app');
    const inhalt = el('div', { class: 'lk-inhalt' });
    [...document.body.children].filter(k => k.tagName !== 'SCRIPT' && k !== alt && !k.matches('dialog, .ub-overlay, [role=dialog]'))
      .forEach(k => inhalt.appendChild(k));
    if (alt) alt.remove();
    document.body.insertBefore(el('div', { class: 'lk-rahmen' }, nav, inhalt), document.body.firstChild);
    document.body.insertBefore(kopf, document.body.firstChild);
    document.body.classList.add('lk-mit-rahmen');
  }

  return { BEREICHE, navigation, umUb };
})();

// Seiten der Unterrichtsbesuche (body mit data-seite, ausser der Vollbild-Erfassung am Handy): Rahmen gleich dazu
if (document.body && document.body.dataset.seite && document.body.dataset.seite !== 'erfassen') Rahmen.umUb();
