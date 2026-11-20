// Fotos zu Schuelern (0.25.0): Vorschaubild (rund, ohne Foto die Initialen), grosses Foto, Aufnehmen mit Kamera bzw.
// Datei und Zuschnitt im Browser (Hochformat 4:5, 400 x 500 Pixel, JPEG), Fotoliste der Klasse als Raster.
// Fotos gelten fuer alle Lehrkraefte der Klasse, wie die Schuelerliste.
'use strict';

const Fotos = (() => {
  const el = L.el;
  const BREITE = 240, HOEHE = 300;           // Zuschnitt-Fenster (4:5)
  const AUS_B = 400, AUS_H = 500;            // gespeichertes Foto

  const url = s => '/api/schueler/' + s.id + '/foto?v=' + encodeURIComponent(s.foto || '');
  // Initialen "VN"; ohne Vor-/Nachname aus "Nachname, Vorname"
  const initialen = s => {
    let nach = s.nachname, vor = s.vorname;
    if (nach === undefined && s.name) [nach, vor] = s.name.split(',').map(x => x.trim());
    return (((vor || '')[0] || '') + ((nach || '')[0] || '')).toUpperCase() || '?';
  };

  // Rundes Vorschaubild; s braucht id, foto (Stand oder null) und Namen
  function avatar(s, groesse = 28) {
    const stil = 'width:' + groesse + 'px;height:' + groesse + 'px;font-size:' + Math.max(10, Math.round(groesse * 0.38)) + 'px';
    if (s && s.foto) return el('img', { class: 'avatar', src: url(s), alt: '', loading: 'lazy', style: stil });
    return el('span', { class: 'avatar', style: stil, 'aria-hidden': 'true', text: initialen(s || {}) });
  }

  // Grosses Foto im Hochformat (ohne Foto: Initialen auf grauem Grund)
  function gross(s, klasse = '') {
    if (s && s.foto) return el('img', { class: 'foto-gross ' + klasse, src: url(s), alt: 'Foto von ' + (s.name || '') });
    return el('div', { class: 'foto-gross ' + klasse, 'aria-hidden': 'true', text: initialen(s || {}) });
  }

  // Name mit Vorschaubild davor
  function mitName(s, groesse = 24, fett = true) {
    return el('span', { class: 'mit-avatar' }, avatar(s, groesse), el(fett ? 'b' : 'span', { text: s.name }));
  }

  // Bild waehlen (Kamera bzw. Datei) -> Zuschnitt -> hochladen. Rueckgabe true, wenn ein Foto gespeichert wurde.
  async function aufnehmen(s, kamera) {
    const datei = await dateiWaehlen(kamera);
    if (!datei) return false;
    const bild = await zuschneiden(datei, s);
    if (!bild) return false;
    try {
      await L.api('POST', '/api/schueler/' + s.id + '/foto', { bild });
      L.meldung('Foto gespeichert.');
      return true;
    } catch (e) { L.meldung(e.message, true); return false; }
  }

  function dateiWaehlen(kamera) {
    return new Promise(fertig => {
      const input = el('input', { type: 'file', accept: 'image/*', hidden: true });
      if (kamera) input.setAttribute('capture', 'environment');
      input.addEventListener('change', () => { fertig(input.files[0] || null); input.remove(); });
      input.addEventListener('cancel', () => { fertig(null); input.remove(); });
      document.body.appendChild(input);
      input.click();
    });
  }

  // Ausschnitt waehlen: ziehen verschiebt, der Regler vergroessert; Rueckgabe data:image/jpeg;base64,... oder null
  async function zuschneiden(datei, s) {
    const quelle = URL.createObjectURL(datei);
    const img = el('img', { alt: '', draggable: 'false' });
    try {
      await new Promise((ok, fehler) => { img.onload = ok; img.onerror = () => fehler(new Error('Das Bild lässt sich nicht öffnen.')); img.src = quelle; });
    } catch (e) { L.meldung(e.message, true); URL.revokeObjectURL(quelle); return null; }
    const w = img.naturalWidth, h = img.naturalHeight;
    const basis = Math.max(BREITE / w, HOEHE / h);
    let zoom = 1, x = 0, y = 0;
    const massstab = () => basis * zoom;
    const begrenzen = () => {
      x = Math.min(0, Math.max(BREITE - w * massstab(), x));
      y = Math.min(0, Math.max(HOEHE - h * massstab(), y));
    };
    const zeichnen = () => { img.style.transform = 'translate(' + x + 'px,' + y + 'px) scale(' + massstab() + ')'; };
    img.style.width = w + 'px';
    img.style.height = h + 'px';
    x = (BREITE - w * massstab()) / 2;
    y = (HOEHE - h * massstab()) / 2;
    zeichnen();
    const fenster = el('div', { class: 'zuschnitt' }, img);
    let ziehen = null;
    fenster.addEventListener('pointerdown', ev => { ziehen = { px: ev.clientX, py: ev.clientY, x, y }; fenster.setPointerCapture(ev.pointerId); fenster.classList.add('zieht'); });
    fenster.addEventListener('pointermove', ev => {
      if (!ziehen) return;
      x = ziehen.x + ev.clientX - ziehen.px;
      y = ziehen.y + ev.clientY - ziehen.py;
      begrenzen(); zeichnen();
    });
    const loslassen = () => { ziehen = null; fenster.classList.remove('zieht'); };
    fenster.addEventListener('pointerup', loslassen);
    fenster.addEventListener('pointercancel', loslassen);
    const regler = el('input', { type: 'range', min: 1, max: 4, step: 0.01, value: 1, 'aria-label': 'Vergrößern', oninput: () => {
      const mx = (BREITE / 2 - x) / massstab(), my = (HOEHE / 2 - y) / massstab();
      zoom = Number(regler.value);
      x = BREITE / 2 - mx * massstab();
      y = HOEHE / 2 - my * massstab();
      begrenzen(); zeichnen();
    } });
    const r = await L.dialog({
      titel: 'Ausschnitt · ' + (s.name || ''), knopf: 'Foto speichern', fokus: false,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, fenster,
        el('label', { class: 'feld' }, 'Vergrößern', regler),
        el('p', { class: 'leise klein', text: 'Bild mit dem Finger oder der Maus verschieben, bis das Gesicht im Rahmen sitzt.' })),
      speichern: () => {
        const leinwand = el('canvas', { width: AUS_B, height: AUS_H });
        const ctx = leinwand.getContext('2d');
        ctx.imageSmoothingQuality = 'high';
        ctx.drawImage(img, -x / massstab(), -y / massstab(), BREITE / massstab(), HOEHE / massstab(), 0, 0, AUS_B, AUS_H);
        return leinwand.toDataURL('image/jpeg', 0.85);
      },
    });
    URL.revokeObjectURL(quelle);
    return r;
  }

  // Foto-Bereich fuer den Schueler-Dialog: grosses Foto, Knoepfe Kamera / Datei / Entfernen. nachher() nach Aenderung.
  function feld(s, nachher) {
    const neu = async kamera => { if (await aufnehmen(s, kamera)) nachher(); };
    return el('div', { class: 'foto-feld' }, gross(s),
      el('div', { class: 'stapel', style: 'gap:6px' },
        el('span', { class: 'leise klein', text: 'Foto – sehen alle Lehrkräfte der Klasse' }),
        el('div', { class: 'zeile' },
          el('button', { type: 'button', class: 'klein', onclick: () => neu(true) }, L.symbol('kamera'), 'Kamera'),
          el('button', { type: 'button', class: 'klein', onclick: () => neu(false) }, L.symbol('hoch'), 'Datei wählen')),
        s.foto ? el('div', {}, el('button', { type: 'button', class: 'warnen klein', onclick: async () => {
          try { await L.api('POST', '/api/schueler/' + s.id + '/foto/loeschen', {}); L.meldung('Foto entfernt.'); nachher(); }
          catch (e) { L.meldung(e.message, true); }
        } }, 'Foto entfernen')) : null));
  }

  // Fotoliste: Raster aus Karten mit Foto und Namen; waehlen(s) beim Antippen
  function raster(schueler, waehlen) {
    return el('div', { class: 'foto-raster' }, schueler.map(s => el('button', { type: 'button', class: 'foto-karte' + (s.aktiv ? '' : ' aus'),
      onclick: () => waehlen(s) }, gross(s), el('b', { text: s.nachname }), el('span', { class: 'leise klein', text: s.vorname || '' }))));
  }

  return { avatar, gross, mitName, aufnehmen, feld, raster };
})();
