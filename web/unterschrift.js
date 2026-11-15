'use strict';
// Unterschrift und Paraphe mit Stift oder Finger zeichnen (aus dem alten Lehrerkalender uebernommen).
//   Unterschrift.zeichnen({ art: 'unterschrift'|'paraphe', danach })
// Ablauf: Vollbild-Zeichenflaeche -> "Fertig" -> Vorschau, so wie es ins PDF kommt -> "Uebernehmen" speichert.
// Das Bild ist ein PNG mit TRANSPARENTEM Hintergrund, eng zugeschnitten (sonst laege im PDF ein weisser Kasten auf
// der Linie). Stift-Logik: Sobald ein Stift gemeldet wird, zeichnet nur noch der Stift (die aufgelegte Hand nicht);
// der Andruck steuert die Strichstaerke. Gesten-Regel: genau EIN Ende-Pfad (pointerup, pointercancel,
// lostpointercapture); pointerdown mit preventDefault + setPointerCapture.
const Unterschrift = (() => {
  const el = L.el;
  const FARBEN = [{ name: 'Schwarz', wert: '#1a1a1a' }, { name: 'Blau', wert: '#0b3d91' }];
  const BREITE = 1600, STRICH = 5.5, RAND = 12, MAX_BILD = 1200;

  function merke(schluessel, wert) {
    try {
      if (wert === undefined) return localStorage.getItem(schluessel);
      localStorage.setItem(schluessel, wert);
    } catch (e) { /* privater Modus: ohne Gedaechtnis */ }
    return null;
  }

  const dicke = p => STRICH * (p > 0 ? 0.35 + p * 1.3 : 1);

  function strich(ctx, s, f) {
    ctx.strokeStyle = s.f; ctx.fillStyle = s.f; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    if (s.p.length === 1) {
      const a = s.p[0];
      ctx.beginPath(); ctx.arc(a[0] * f, a[1] * f, dicke(a[2]) * f / 2, 0, Math.PI * 2); ctx.fill();
      return;
    }
    for (let i = 1; i < s.p.length; i++) {
      const a = s.p[i - 1], b = s.p[i];
      ctx.lineWidth = dicke((a[2] + b[2]) / 2) * f;
      ctx.beginPath(); ctx.moveTo(a[0] * f, a[1] * f); ctx.lineTo(b[0] * f, b[1] * f); ctx.stroke();
    }
  }

  // Striche transparent und eng zugeschnitten als PNG-Data-URL
  function alsBild(striche) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    striche.forEach(s => s.p.forEach(pt => {
      const r = dicke(pt[2]) / 2;
      x0 = Math.min(x0, pt[0] - r); y0 = Math.min(y0, pt[1] - r); x1 = Math.max(x1, pt[0] + r); y1 = Math.max(y1, pt[1] + r);
    }));
    x0 -= RAND; y0 -= RAND; x1 += RAND; y1 += RAND;
    const f = Math.min(1, MAX_BILD / (x1 - x0));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.ceil((x1 - x0) * f));
    c.height = Math.max(1, Math.ceil((y1 - y0) * f));
    const ctx = c.getContext('2d');
    ctx.translate(-x0 * f, -y0 * f);
    striche.forEach(s => strich(ctx, s, f));
    return c.toDataURL('image/png');
  }

  // Vollbild-Zeichenflaeche -> Promise<striche | null>
  function flaeche(titel, vorher) {
    const quer = window.innerWidth >= window.innerHeight;
    const w = BREITE, h = Math.round(BREITE * (quer ? 0.42 : 0.75));
    let striche = vorher ? vorher.slice() : [];
    const verlauf = [];
    let farbe = merke('lkmt.unterschriftFarbe') || FARBEN[0].wert;
    let nurStift = merke('lkmt.nurStift') === '1';
    return new Promise(fertig => {
      const canvas = el('canvas', { class: 'usz-canvas', width: String(w), height: String(h) });
      const ctx = canvas.getContext('2d');
      const blatt = el('div', { class: 'usz-blatt' }, canvas, el('div', { class: 'usz-linie' }));
      const buehne = el('div', { class: 'usz-buehne' }, blatt);
      const leiste = el('div', { class: 'usz-leiste' });
      const overlay = el('div', { class: 'usz', role: 'dialog', 'aria-label': titel }, leiste,
        el('div', { class: 'usz-hinweis', text: titel + ' – auf der Linie schreiben' }), buehne);
      const alles = () => { ctx.clearRect(0, 0, w, h); striche.forEach(s => strich(ctx, s, 1)); };
      const einpassen = () => {
        const r = buehne.getBoundingClientRect();
        const f = Math.min((r.width - 24) / w, (r.height - 24) / h);
        blatt.style.width = Math.floor(w * f) + 'px';
        blatt.style.height = Math.floor(h * f) + 'px';
      };
      let aktiv = null;
      const lage = ev => {
        const r = canvas.getBoundingClientRect();
        return [Math.round((ev.clientX - r.left) * w / r.width * 10) / 10, Math.round((ev.clientY - r.top) * h / r.height * 10) / 10,
          Math.round((ev.pointerType === 'pen' ? ev.pressure : 0) * 100) / 100];
      };
      canvas.addEventListener('pointerdown', ev => {
        if (ev.pointerType === 'pen' && !nurStift) { nurStift = true; merke('lkmt.nurStift', '1'); leisteZeichnen(); }
        if (nurStift && ev.pointerType !== 'pen') return;
        if (ev.button > 0 || aktiv) return;
        ev.preventDefault();
        try { canvas.setPointerCapture(ev.pointerId); } catch (e) { /* Zeiger schon weg */ }
        verlauf.push(striche.slice());
        const s = { f: farbe, p: [lage(ev)] };
        striche.push(s);
        aktiv = { id: ev.pointerId, s };
        strich(ctx, s, 1);
      });
      canvas.addEventListener('pointermove', ev => {
        if (!aktiv || ev.pointerId !== aktiv.id) return;
        ev.preventDefault();
        const liste = ev.getCoalescedEvents ? ev.getCoalescedEvents() : [];
        (liste.length ? liste : [ev]).forEach(e2 => {
          const pt = lage(e2), s = aktiv.s, letzter = s.p[s.p.length - 1];
          if (Math.abs(letzter[0] - pt[0]) + Math.abs(letzter[1] - pt[1]) < 0.8) return;
          s.p.push(pt);
          strich(ctx, { f: s.f, p: [letzter, pt] }, 1);
        });
      });
      const ende = ev => { if (aktiv && (!ev || ev.pointerId === aktiv.id)) aktiv = null; };
      canvas.addEventListener('pointerup', ende);
      canvas.addEventListener('pointercancel', ende);
      canvas.addEventListener('lostpointercapture', ende);
      const knopf = (inhalt, an, titelText, klick) => el('button', { type: 'button', class: 'usz-k' + (an ? ' an' : ''), title: titelText,
        'aria-label': titelText, 'aria-pressed': an ? 'true' : 'false', onclick: klick }, inhalt);
      function leisteZeichnen() {
        L.setzen(leiste,
          el('button', { type: 'button', onclick: abbrechen }, 'Abbrechen'),
          el('div', { class: 'usz-werkzeuge' },
            FARBEN.map(f => knopf([el('span', { class: 'usz-farbe', style: 'background:' + f.wert }), f.name], farbe === f.wert, 'Tinte ' + f.name, () => {
              farbe = f.wert; merke('lkmt.unterschriftFarbe', f.wert);
              striche.forEach(s => { s.f = f.wert; });   // eine Unterschrift hat eine Farbe
              alles(); leisteZeichnen();
            })),
            el('span', { class: 'usz-trenner' }),
            knopf('↶', false, 'Rückgängig', () => { if (verlauf.length) { striche = verlauf.pop(); alles(); } }),
            knopf('Leeren', false, 'Alles löschen', () => { if (striche.length) { verlauf.push(striche.slice()); striche = []; alles(); } }),
            el('span', { class: 'usz-trenner' }),
            knopf(nurStift ? '✎ Nur Stift' : '☝ Finger', nurStift, nurStift ? 'Nur der Stift zeichnet – tippen, damit auch der Finger zeichnet' : 'Finger zeichnet – tippen für „nur Stift“',
              () => { nurStift = !nurStift; merke('lkmt.nurStift', nurStift ? '1' : '0'); leisteZeichnen(); })),
          el('button', { type: 'button', class: 'haupt', onclick: () => { if (!striche.length) { L.meldung('Bitte erst unterschreiben.', true); return; } schliessen(striche); } }, 'Fertig'));
      }
      function schliessen(ergebnis) {
        window.removeEventListener('resize', einpassen);
        document.removeEventListener('keydown', taste);
        overlay.remove();
        fertig(ergebnis);
      }
      async function abbrechen() {
        if (!striche.length) { schliessen(null); return; }
        const weg = await L.dialog({ titel: 'Zeichnung verwerfen?', knopf: 'Verwerfen', gefaehrlich: true, abbrechen: 'Weiter zeichnen',
          inhalt: el('p', { text: 'Die Zeichnung wird nicht gespeichert.' }), speichern: () => true });
        if (weg) schliessen(null);
      }
      const taste = ev => { if (ev.key === 'Escape' && !document.querySelector('dialog[open]')) abbrechen(); };
      leisteZeichnen();
      document.body.appendChild(overlay);
      einpassen();
      alles();
      window.addEventListener('resize', einpassen);
      document.addEventListener('keydown', taste);
    });
  }

  async function zeichnen({ art, danach }) {
    const titel = art === 'paraphe' ? 'Paraphe' : 'Unterschrift';
    let striche = null;
    for (;;) {
      striche = await flaeche(titel, striche);
      if (!striche) return false;
      const bild = alsBild(striche);
      const wahl = await L.dialog({
        titel: titel + ' übernehmen?', knopf: 'Übernehmen', abbrechen: 'Weiter zeichnen',
        inhalt: el('div', { class: 'stapel' }, el('p', { class: 'leise klein', text: 'So erscheint sie auf den Formularen – ' + (art === 'paraphe' ? 'als Kürzel.' : 'über der Unterschriftslinie.') }),
          el('div', { class: 'usz-vorschau' }, el('img', { src: bild, alt: titel, class: art === 'paraphe' ? 'usz-v-paraphe' : 'usz-v-sig' }), el('div', { class: 'usz-v-linie' }))),
        speichern: () => L.api('POST', '/api/unterschrift', { art, bild }),
      });
      if (!wahl) continue;   // weiter zeichnen, nichts geht verloren
      L.meldung(titel + ' gespeichert.');
      if (danach) danach();
      return true;
    }
  }

  return { zeichnen };
})();
