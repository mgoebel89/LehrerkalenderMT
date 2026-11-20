// Lernfelder durch Lehrkraefte (0.23.0): fehlende Lernfelder bzw. Module selbst anlegen, in Bildungsgaengen der eigenen
// Klassen (laut Stundenplan); eigene aendern und loeschen. Der Dialog ist derselbe in der Bibliothek, in der Planung
// (Thema), im Stundenplan (Block) und auf der Seite Einstellungen > Lernfelder. Alle sehen alle Lernfelder.
'use strict';

const Lernfelder = (() => {
  const el = L.el;

  const holen = () => L.api('GET', '/api/lernfelder');

  // Dialog zum Anlegen (lf = null) bzw. Aendern eines eigenen Lernfelds. b: Bildungsgang aus /api/lernfelder.
  // Rueckgabe: neuer Stand ({bildungsgaenge, id}) oder null.
  async function dialog(b, lf) {
    const modul = b.einheit === 'modul';
    const nummer = el('input', { value: lf ? lf.nummer : '', placeholder: modul ? 'M 4' : 'LF 7', maxlength: 12, style: 'max-width:120px' });
    const name = el('input', { value: lf ? lf.name : '', placeholder: modul ? 'Automatisierungstechnik' : 'Steuerungen für Anlagen programmieren', maxlength: 80 });
    const stufe = el('select', {}, el('option', { value: '', text: '–' }),
      b.stufen.map(s => el('option', { value: s.id, text: s.name, selected: lf && lf.stufe_id === s.id ? true : null })));
    const stunden = el('input', { type: 'number', min: 0, max: 2000, value: lf ? lf.stunden : '', style: 'max-width:120px' });
    const aktiv = el('input', { type: 'checkbox', checked: !lf || lf.aktiv ? true : null });
    const anteile = {};
    const anteilFelder = modul && b.stufen.length ? el('div', { class: 'felder zwei' }, b.stufen.map(s => {
      anteile[s.id] = el('input', { type: 'number', min: 0, max: 2000, value: lf && lf.anteile[s.id] ? lf.anteile[s.id] : '' });
      return L.feld(s.name + ' (Std)', anteile[s.id]);
    })) : null;
    let loeschen = false;
    const r = await L.dialog({
      titel: lf ? lf.nummer + ' ' + lf.name : (modul ? 'Neues Modul' : 'Neues Lernfeld') + ' · ' + b.name,
      inhalt: el('div', { class: 'felder' },
        lf ? null : el('p', { class: 'leise klein', text: 'Das ' + (modul ? 'Modul' : 'Lernfeld') + ' sehen danach alle im Bildungsgang. Ändern können es nur du und der Admin.' }),
        el('div', { class: 'felder zwei' }, L.feld('Nummer', nummer), L.feld('Stundenansatz gesamt', stunden, 'Unterrichtsstunden laut Lehrplan')),
        L.feld('Name', name), L.feld(modul ? 'Beginnt im Semester' : 'Stufe', stufe),
        anteilFelder ? el('div', { class: 'stapel', style: 'gap:6px' }, el('span', { class: 'etikett', text: 'Stunden je Semester (optional)' }), anteilFelder) : null,
        el('label', { class: 'haken' }, aktiv, 'aktiv'),
        lf ? el('div', {}, el('button', { type: 'button', class: 'warnen klein', text: 'Löschen …', onclick: ev => {
          loeschen = true;
          ev.currentTarget.closest('dialog').dispatchEvent(new Event('cancel'));
        } })) : null),
      speichern: () => {
        const a = {};
        Object.entries(anteile).forEach(([sid, inp]) => { if (inp.value) a[sid] = Number(inp.value); });
        return L.api('POST', lf ? '/api/lernfeld/' + lf.id : '/api/lernfeld', { bildungsgang_id: b.id, nummer: nummer.value, name: name.value,
          stufe_id: stufe.value || null, stunden: Number(stunden.value || 0), aktiv: aktiv.checked, anteile: a });
      },
    });
    if (r || !loeschen) return r;
    // Loeschen: zweite Rueckfrage, nachdem dieses Fenster zu ist
    return L.dialog({ titel: lf.nummer + ' löschen?', knopf: 'Löschen', gefaehrlich: true,
      inhalt: el('p', { text: 'Geht nur, solange es noch nirgends benutzt wird (Bibliothek, Planung, Stundenplan, Prüfungen). Sonst stell es auf „nicht aktiv“.' }),
      speichern: () => L.api('POST', '/api/lernfeld/' + lf.id + '/loeschen', {}) });
  }

  // Neues Lernfeld im Bildungsgang bid anlegen; Rueckgabe wie dialog() oder null (dann mit Meldung, warum nicht)
  async function anlegen(bid) {
    try {
      const stand = await holen();
      const b = stand.bildungsgaenge.find(x => x.id === bid);
      if (!b) { L.meldung('Dieser Bildungsgang ist nicht aktiv.', true); return null; }
      if (!b.darf_anlegen) { L.meldung('Lernfelder kannst du nur in Bildungsgängen anlegen, in denen du laut Stundenplan Klassen hast.', true); return null; }
      const r = await dialog(b, null);
      if (r) L.meldung((b.einheit === 'modul' ? 'Modul' : 'Lernfeld') + ' angelegt.');
      return r;
    } catch (e) { L.meldung(e.message, true); return null; }
  }

  // Kleiner Knopf "+ Lernfeld" neben einer Lernfeld-Auswahl; nachher(stand) laeuft nach dem Anlegen
  function knopf(bid, nachher, text = 'Lernfeld') {
    return el('button', { type: 'button', class: 'leicht klein', title: 'Fehlendes Lernfeld anlegen', onclick: async () => {
      const id = typeof bid === 'function' ? bid() : bid;
      if (!id) { L.meldung('Bitte zuerst eine Klasse wählen.', true); return; }
      const r = await anlegen(id);
      if (r && nachher) await nachher(r);
    } }, L.symbol('plus'), text);
  }

  // Seite Einstellungen > Lernfelder: meine Bildungsgaenge zuerst, je Bildungsgang alle Lernfelder (eigene zum Aendern)
  async function seite(ort) {
    const stand = await holen();
    zeichnen(ort, stand);
  }

  function zeichnen(ort, stand) {
    const neu = async (b, lf) => {
      const r = await dialog(b, lf);
      if (r) zeichnen(ort, r);
    };
    const gaenge = stand.bildungsgaenge.slice().sort((a, b) => (b.meiner ? 1 : 0) - (a.meiner ? 1 : 0));
    L.setzen(ort,
      el('p', { class: 'leise', style: 'max-width:80ch', text: 'Fehlt ein Lernfeld oder Modul, kannst du es hier selbst anlegen – in Bildungsgängen, in denen du laut Stundenplan Klassen hast. Alle sehen es danach; ändern und löschen können es nur du und der Admin.' }),
      gaenge.length ? gaenge.map(b => {
        const einheit = b.einheit === 'modul' ? 'Modul' : 'Lernfeld';
        const stufeName = id => (b.stufen.find(s => s.id === id) || {}).name || '–';
        return el('div', { class: 'karte stapel' },
          el('div', { class: 'zeile' }, el('h2', { text: b.name }), b.kuerzel ? el('span', { class: 'chip', text: b.kuerzel }) : null,
            b.meiner ? el('span', { class: 'chip blau', text: 'meine Klassen' }) : null,
            el('span', { class: 'rechts' }, b.darf_anlegen ? el('button', { type: 'button', class: 'klein', onclick: () => neu(b, null) }, L.symbol('plus'), einheit) : null)),
          el('div', { class: 'rollbar' }, el('table', { class: 'liste' },
            el('thead', {}, el('tr', {}, [einheit, 'Name', b.einheit === 'modul' ? 'beginnt in' : 'Stufe', 'Stundenansatz', 'angelegt von'].map(t => el('th', { text: t })))),
            el('tbody', {}, b.lernfelder.length ? b.lernfelder.map(lf => el('tr', lf.darf_aendern
              ? { class: 'klickbar' + (lf.aktiv ? '' : ' aus'), tabindex: 0, onclick: () => neu(b, lf), onkeydown: ev => { if (ev.key === 'Enter') neu(b, lf); } }
              : { class: lf.aktiv ? null : 'aus' },
              el('td', { class: 'mono' }, el('b', { text: lf.nummer })), el('td', { text: lf.name }), el('td', { text: stufeName(lf.stufe_id) }),
              el('td', { class: 'mono', text: lf.stunden + ' Std' }),
              el('td', { class: 'leise klein', text: lf.besitzer || 'Admin' })))
              : el('tr', {}, el('td', { colspan: 5, class: 'leise', text: 'Noch keine ' + (b.einheit === 'modul' ? 'Module' : 'Lernfelder') + '.' }))))));
      }) : el('div', { class: 'leer', text: 'Es gibt noch keine aktiven Bildungsgänge.' }));
  }

  return { dialog, anlegen, knopf, seite };
})();
