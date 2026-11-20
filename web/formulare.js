'use strict';
// Formularcenter (Stufe F1): Ablage mit Stand (erstellt, abgegeben, genehmigt) und die Stundenplanaenderung /
// Beurlaubung, die das Schul-PDF aus den Ausfaellen und Vertretungen einer Woche fuellt. Gestartet wird auch dort,
// wo die Daten entstehen: nach dem Eintragen eines Ausfalls („jetzt erstellen?“), aus der Woche und aus einem Termin.
const Formulare = (() => {
  const el = L.el;
  const STAND = { erstellt: ['erstellt', ''], abgegeben: ['abgegeben', 'gelb'], genehmigt: ['genehmigt', 'gruen'] };
  const NAECHSTER = { erstellt: 'abgegeben', abgegeben: 'genehmigt', genehmigt: 'erstellt' };
  let ort = null;
  let U = null;           // Uebersicht: formulare, vorlagen, unterschrift, gruende
  let filter = 'alle';

  const tagKurz = iso => iso ? L.tag(iso).trim() : '';
  const montagVon = iso => { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); };

  async function laden() { U = await L.api('GET', '/api/formulare'); return U; }

  async function zeigen(ortEl) {
    ort = ortEl;
    await laden();
    zeichnen();
  }

  function zeichnen() {
    const vorlage = !!U.vorlagen.stundenplanaenderung;
    const liste = U.formulare.filter(f => filter === 'alle' || f.stand !== 'genehmigt');
    L.setzen(ort,
      el('div', { class: 'werkzeug' }, el('h1', { class: 'dreieck', text: 'Formulare' })),
      el('div', { class: 'raster formular-karten' },
        el('div', { class: 'karte stapel' }, el('div', { class: 'zeile' }, L.symbol('formular'), el('h3', { text: 'Stundenplanänderung / Beurlaubung' })),
          el('p', { class: 'leise klein', text: 'Füllt das Schulformular aus den Ausfällen und Vertretungen einer Woche – mit deiner Unterschrift.' }),
          !vorlage ? el('div', { class: 'banner warnung klein', text: 'Die Schul-Vorlage fehlt noch. Der Admin lädt sie unter Grunddaten → Schule und Logo hoch.' }) : null,
          vorlage && !U.unterschrift ? el('div', { class: 'banner klein' }, 'Noch keine Unterschrift – das Formular entsteht dann ohne. ',
            el('a', { href: '#einstellungen-konto', text: 'Unterschrift zeichnen' })) : null,
          el('div', {}, el('button', { type: 'button', class: 'haupt', disabled: vorlage ? null : true, onclick: () => neu({}) }, L.symbol('plus'), 'Neu erstellen'))),
        el('div', { class: 'karte stapel' }, el('div', { class: 'zeile' }, L.symbol('formular'), el('h3', { text: 'Entlassung aus der Berufsschule' })),
          el('p', { class: 'leise klein', text: 'Ausschulung während des Schuljahres: füllt den Teil Klassenleitung aus, der Teil der Abteilungsleitung bleibt ausfüllbar. Der Schüler ist danach nicht mehr in der Klasse.' }),
          !U.vorlagen.entlassung ? el('div', { class: 'banner warnung klein', text: 'Die Schul-Vorlage fehlt noch. Der Admin lädt sie unter Grunddaten → Schule und Logo hoch.' }) : null,
          el('div', {}, el('button', { type: 'button', class: 'haupt', disabled: U.vorlagen.entlassung ? null : true, onclick: () => entlassung(null, zeigenNeu) }, L.symbol('plus'), 'Ausschulung …'))),
        el('div', { class: 'karte stapel aus' }, el('div', { class: 'zeile' }, L.symbol('formular'), el('h3', { text: 'Weitere Formulare' })),
          el('p', { class: 'leise klein', text: 'z. B. Unterrichtsgang, Dienstreise' }), el('div', {}, el('span', { class: 'chip', text: 'später' })))),
      el('div', { class: 'zeile' }, el('h2', { text: 'Meine Formulare' }),
        el('div', { class: 'segment', role: 'group', 'aria-label': 'Filter' },
          [['alle', 'alle'], ['offen', 'noch nicht genehmigt']].map(([w, t]) => el('button', { type: 'button', class: filter === w ? 'an' : null,
            onclick: () => { filter = w; zeichnen(); } }, t)))),
      liste.length ? el('div', { class: 'r-scroll' }, el('table', { class: 'liste formulare' },
        el('thead', {}, el('tr', {}, ['Formular', 'Betrifft', 'Erstellt', 'Stand', ''].map(t => el('th', { text: t })))),
        el('tbody', {}, liste.map(f => {
          const [text, farbe] = STAND[f.stand] || [f.stand, ''];
          return el('tr', {},
            el('td', { text: f.artname.split(' / ')[0] }),
            el('td', { text: f.betrifft }),
            el('td', { class: 'mono klein', text: tagKurz(f.erstellt.slice(0, 10)) }),
            el('td', {}, el('button', { type: 'button', class: 'chip-knopf stand ' + farbe, title: 'Tippen: weiter auf „' + NAECHSTER[f.stand] + '“',
              onclick: () => stand(f, NAECHSTER[f.stand]) }, text)),
            el('td', { class: 'knoepfe' },
              el('button', { type: 'button', class: 'klein', title: 'PDF in neuem Tab öffnen (drucken, speichern)', onclick: () => pdf(f) }, L.symbol('auge'), 'PDF'),
              Dokumente.ablegenKnopf('formular', { id: f.id, titel: f.artname.split(' / ')[0] + ' ' + f.betrifft, datum: f.von,
                was: f.artname + ' · ' + f.betrifft }, 'Paperless'),
              el('button', { type: 'button', class: 'leicht klein', 'aria-label': 'Löschen', onclick: () => loeschen(f) }, L.symbol('muell'))));
        }))))
        : el('div', { class: 'leer', text: filter === 'alle' ? 'Noch keine Formulare.' : 'Alles genehmigt.' }));
  }

  async function stand(f, neu) {
    try { U.formulare = (await L.api('POST', '/api/formular/' + f.id + '/stand', { stand: neu })).formulare; zeichnen(); }
    catch (e) { L.meldung(e.message, true); }
  }

  async function pdf(f) {
    try { await L.ansehen('/api/formular/' + f.id + '.pdf'); } catch (e) { L.meldung(e.message, true); }
  }

  async function loeschen(f) {
    // Entlassung: nachfragen, ob der Schueler wieder in die Klasse soll
    const zurueck = f.art === 'entlassung' ? el('input', { type: 'checkbox', checked: true }) : null;
    const r = await L.dialog({ titel: 'Formular löschen?', knopf: 'Löschen', gefaehrlich: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, el('p', { text: f.artname + ' · ' + f.betrifft + ' wird aus der Ablage gelöscht.' }),
        zurueck ? el('label', { class: 'haken' }, zurueck, 'Schüler wieder in die Klasse aufnehmen (die Ausschulung gilt dann nicht mehr)') : null),
      speichern: () => L.api('POST', '/api/formular/' + f.id + '/loeschen', { reaktivieren: zurueck ? zurueck.checked : false }) });
    if (r) { U.formulare = r.formulare; zeichnen(); }
  }

  const zeigenNeu = async () => { if (ort && document.body.contains(ort)) { await laden(); zeichnen(); } };

  // --- Ausschulung: Formular "Entlassung aus der Berufsschule" (0.27.0) ---
  // sid: Schueler (ohne: erst Klasse und Schueler waehlen); nachher() nach dem Erstellen
  async function entlassung(sid, nachher) {
    try {
      if (!sid) sid = await schuelerWaehlen();
      if (!sid) return false;
      const V = await L.api('GET', '/api/entlassung/vorschlag?schueler=' + sid);
      if (!V.vorlage) { L.meldung('Die Schul-Vorlage „Entlassung“ fehlt noch (Admin: Grunddaten → Schule und Logo).', true); return false; }
      if (V.schueler.entlassen_zum) { L.meldung(V.schueler.name + ' ist schon zum ' + L.tag(V.schueler.entlassen_zum, true) + ' ausgeschult.', true); return false; }
      const lehrer = el('input', { maxlength: 80, value: V.klassenlehrer });
      const durch = el('select', {}, V.mitteilung_durch.map(m => el('option', { value: m, text: m })));
      const zusatz = el('input', { maxlength: 120, placeholder: 'z. B. telefonisch am ' + L.tag(L.heute()).trim().slice(3) });
      const letzter = el('input', { type: 'date', value: V.letzter_tag });
      const datum = el('input', { type: 'date', value: V.datum });
      const leistung = el('div', { class: 'stapel', style: 'gap:6px' }, [['moeglich', 'möglich'], ['nicht_moeglich', 'nicht möglich']].map(([w, t]) =>
        el('label', { class: 'haken' }, el('input', { type: 'radio', name: 'leistung', value: w }), t)));
      const grund = el('textarea', { rows: 2, maxlength: 2000, placeholder: 'z. B. Ausbildungsverhältnis gelöst' });
      const r = await L.dialog({
        titel: 'Ausschulung · ' + V.schueler.name, knopf: 'Formular erstellen',
        inhalt: el('div', { class: 'felder' },
          el('p', { class: 'leise klein', text: V.schueler.klasse + ' · Das Formular „Entlassung aus der Berufsschule“ wird mit deiner Unterschrift ausgefüllt (Teil Klassenleitung); den Teil der Abteilungsleitung füllt die Schulleitung im PDF aus.' }),
          L.feld('Klassenlehrer(in)', lehrer),
          el('div', { class: 'felder zwei' }, L.feld('Grund mitgeteilt durch', durch), L.feld('Zusatz (freiwillig)', zusatz)),
          el('div', { class: 'felder zwei' }, L.feld('Letzter Unterrichtstag', letzter, 'Vorschlag: deine letzte Stunde in der Klasse'), L.feld('Datum', datum)),
          el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'leise klein', style: 'font-weight:600', text: 'Eine Leistungsbeurteilung (Zeugnisnoten) ist' }), leistung),
          L.feld('Grund (nur für dich, kommt nicht aufs Formular)', grund, 'wird als Beobachtung im Verlauf des Schülers gespeichert'),
          el('p', { class: 'banner klein', text: 'Nach dem letzten Unterrichtstag ist ' + V.schueler.name + ' für alle Lehrkräfte der Klasse „nicht mehr in der Klasse“; sie sehen einen Hinweis auf der Startseite.' })),
        speichern: () => {
          const l = leistung.querySelector('input:checked');
          if (!l) throw new Error('Bitte wählen, ob eine Leistungsbeurteilung möglich ist.');
          return L.api('POST', '/api/formulare/entlassung', { schueler_id: sid, klassenlehrer: lehrer.value, mitteilung: durch.value,
            mitteilung_zusatz: zusatz.value, letzter_tag: letzter.value, leistung: l.value, datum: datum.value, grund: grund.value });
        },
      });
      if (!r) return false;
      if (U) U.formulare = r.formulare;
      if (nachher) await nachher();
      await L.dialog({ titel: 'Formular erstellt', knopf: 'PDF ansehen', abbrechen: 'Schließen', fokus: false,
        inhalt: el('p', { text: 'Die Entlassung liegt im Formularcenter (Stand „erstellt“). Ausdrucken bzw. an die Schulleitung weitergeben.' }),
        speichern: () => L.ansehen('/api/formular/' + r.id + '.pdf').then(() => true) });
      return true;
    } catch (e) { L.meldung(e.message, true); return false; }
  }

  // Klasse und Schueler waehlen (nur Schueler, die noch in der Klasse und nicht ausgeschult sind)
  async function schuelerWaehlen() {
    const K = (await L.api('GET', '/api/schueler/klassen')).klassen;
    if (!K.length) { L.meldung('Du hast noch keine Klassen.', true); return null; }
    const klasse = el('select', {}, K.map(k => el('option', { value: k.id, text: k.name, selected: k.meine ? true : null })));
    const schueler = el('select', {});
    const fuellen = async () => {
      const S = await L.api('GET', '/api/schueler?klasse=' + klasse.value);
      const offen = S.schueler.filter(s => s.aktiv && !s.entlassen_zum);
      L.setzen(schueler, offen.length ? offen.map(s => el('option', { value: s.id, text: s.name })) : el('option', { value: '', text: '– keine Schüler –' }));
    };
    klasse.addEventListener('change', fuellen);
    await fuellen();
    const r = await L.dialog({ titel: 'Ausschulung', knopf: 'Weiter',
      inhalt: el('div', { class: 'felder' }, L.feld('Klasse', klasse), L.feld('Schüler', schueler)),
      speichern: () => { if (!schueler.value) throw new Error('Bitte einen Schüler wählen.'); return Number(schueler.value); } });
    return r || null;
  }

  // Assistent: Woche waehlen -> Stunden aus dem Wochenplan, Zeitraum, Begruendung -> PDF erzeugen und ablegen.
  // vorgabe: { woche, von, bis, grund, felder }
  async function neu(vorgabe) {
    if (!U) await laden();
    if (!U.vorlagen.stundenplanaenderung) { L.meldung('Die Schul-Vorlage fehlt noch (Admin: Grunddaten → Schule und Logo).', true); return false; }
    const heute = new Date().toISOString().slice(0, 10);
    const woche = el('input', { type: 'date', value: vorgabe.woche || vorgabe.von || heute });
    const von = el('input', { type: 'date', value: vorgabe.von || '' });
    const bis = el('input', { type: 'date', value: vorgabe.bis || '' });
    const grund = el('select', {}, U.gruende.map(g => el('option', { value: g.key, text: g.name, selected: g.key === (vorgabe.grund || 'fortbildung') ? true : null })));
    const felderOrt = el('div', { class: 'felder zwei' });
    const eingaben = {};
    const felderZeigen = () => {
      const g = U.gruende.find(x => x.key === grund.value);
      L.setzen(felderOrt, g.felder.map(f => {
        eingaben[f.key] = eingaben[f.key] || el('input', { maxlength: 200, value: (vorgabe.felder || {})[f.key] || '' });
        return L.feld(f.name, eingaben[f.key]);
      }));
    };
    grund.addEventListener('change', felderZeigen);
    felderZeigen();
    const stundenOrt = el('div', { class: 'stapel', style: 'gap:6px' });
    let vonAuto = !vorgabe.von, bisAuto = !vorgabe.bis;
    let V = null;   // Ausfaelle und Vertretungen der gewaehlten Woche
    // Nur Stunden im Zeitraum „am / von“ bis „bis“ kommen ins Formular; die uebrigen der Woche werden ausgegraut gezeigt
    const stundenZeigen = () => {
      if (!V) return;
      const drin = e => (!von.value || e.datum >= von.value) && (!bis.value || e.datum <= bis.value);
      const anzahl = V.eintraege.filter(drin).length;
      L.setzen(stundenOrt,
        V.eintraege.length ? el('table', { class: 'liste klein formular-stunden' }, el('tbody', {}, V.eintraege.map(e => el('tr', { class: drin(e) ? null : 'aus',
          title: drin(e) ? null : 'liegt außerhalb des Zeitraums – kommt nicht ins Formular' },
          el('td', { text: tagKurz(e.datum) }), el('td', { class: 'mono', text: (e.block + 1) + '. Block' }), el('td', { text: e.klasse }),
          el('td', { class: 'leise', text: drin(e) ? e.vertretung : 'nicht im Zeitraum' }))))) :
          el('p', { class: 'leise klein', text: 'In dieser Woche ist kein Ausfall und keine Vertretung eingetragen. Das Formular geht trotzdem (z. B. für die Versicherung) – mit dem Zeitraum unten.' }),
        V.eintraege.length && anzahl < V.eintraege.length ? el('p', { class: 'leise klein', text: anzahl + ' von ' + V.eintraege.length + ' Stunden der Woche liegen im Zeitraum und kommen ins Formular.' }) : null,
        V.vorhanden ? el('div', { class: 'banner klein', text: 'Für diese Woche gibt es schon eine Stundenplanänderung in der Ablage.' }) : null);
    };
    von.addEventListener('input', () => { vonAuto = false; stundenZeigen(); });
    bis.addEventListener('input', () => { bisAuto = false; stundenZeigen(); });
    von.addEventListener('change', stundenZeigen);
    bis.addEventListener('change', stundenZeigen);
    const vorschau = async () => {
      L.setzen(stundenOrt, el('p', { class: 'leise klein', text: 'Lade die Woche …' }));
      try {
        V = await L.api('GET', '/api/formulare/vorschau?woche=' + woche.value);
        if (vonAuto) von.value = V.von || '';
        if (bisAuto) bis.value = V.bis || '';
        stundenZeigen();
      } catch (e) { V = null; L.setzen(stundenOrt, el('div', { class: 'banner warnung klein', text: e.message })); }
    };
    woche.addEventListener('change', vorschau);
    vorschau();
    const r = await L.dialog({
      titel: 'Stundenplanänderung / Beurlaubung', knopf: 'Erstellen', breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        el('div', { class: 'felder zwei' }, L.feld('Woche', woche, 'Ausfälle und Vertretungen dieser Woche im Zeitraum kommen in die Tabelle'), el('span')),
        el('div', { class: 'stapel', style: 'gap:4px' }, el('span', { class: 'etikett', text: 'Betroffene Stunden' }), stundenOrt),
        el('div', { class: 'felder zwei' }, L.feld('am / von', von), L.feld('bis', bis)),
        L.feld('Begründung', grund), felderOrt,
        !U.unterschrift ? el('p', { class: 'leise klein', text: 'Hinweis: Ohne gezeichnete Unterschrift (Einstellungen → Konto) bleibt die Unterschriftszeile leer.' }) : null),
      speichern: () => L.api('POST', '/api/formulare/stundenplanaenderung', {
        woche: woche.value, von: von.value || null, bis: bis.value || null, grund: grund.value,
        felder: Object.fromEntries(Object.entries(eingaben).map(([k, i]) => [k, i.value])) }),
    });
    if (!r) return false;
    U.formulare = r.formulare;
    L.meldung('Formular erstellt und abgelegt.');
    try { await L.ansehen('/api/formular/' + r.id + '.pdf'); } catch (e) { L.meldung(e.message, true); }
    if (ort && ort.isConnected) zeichnen();
    return true;
  }

  // Nach dem Eintragen eines Ausfalls oder einer Vertretung: fuer diese Woche jetzt erstellen?
  async function nachfragen(datum, grundText) {
    try {
      if (!U) await laden();
      if (!U.vorlagen.stundenplanaenderung) return;
      const v = await L.api('GET', '/api/formulare/vorschau?woche=' + datum);
      if (v.vorhanden) return;
      const ja = await L.dialog({ titel: 'Stundenplanänderung jetzt erstellen?', knopf: 'Jetzt erstellen', abbrechen: 'Später',
        inhalt: el('p', { text: 'Für die Woche ab ' + tagKurz(v.montag) + ' gibt es noch kein Formular. ' + v.eintraege.length + (v.eintraege.length === 1 ? ' Stunde ist' : ' Stunden sind') + ' betroffen.' }),
        speichern: () => true });
      if (ja) await neu({ woche: datum, grund: grundRaten(grundText) });
    } catch (e) { /* Hinweis ist freiwillig */ }
  }

  function grundRaten(text) {
    const t = (text || '').toLowerCase();
    if (t.includes('fortbild')) return 'fortbildung';
    if (t.includes('prüf') || t.includes('pruef')) return 'pruefung';
    if (t.includes('konferenz') || t.includes('sitzung')) return 'sitzung';
    if (t.includes('fahrt') || t.includes('exkursion') || t.includes('unterrichtsgang')) return 'klassenfahrt';
    if (t.includes('urlaub') || t.includes('beurlaub')) return 'beurlaubung';
    return 'sonstige';
  }

  // Aus einem Termin: Zeitraum und Begruendung vorbelegen
  function ausTermin(t) {
    return neu({ woche: t.datum, von: t.datum, bis: t.bis || t.datum, grund: grundRaten(t.titel),
      felder: grundRaten(t.titel) === 'fortbildung' ? { thema: t.titel } : grundRaten(t.titel) === 'sonstige' ? { text: t.titel } : {} });
  }

  // Karte fuer Einstellungen -> Konto: Unterschrift und Paraphe zeichnen
  function unterschriftKarte() {
    const ort_ = el('div', { class: 'karte stapel' });
    const zeichne = async () => {
      let da = { unterschrift: false, paraphe: false };
      try { U = await L.api('GET', '/api/formulare'); da = { unterschrift: U.unterschrift, paraphe: U.paraphe }; } catch (e) { /* ohne Stand */ }
      const zeile = (art, titel, hilfe) => el('div', { class: 'stapel', style: 'gap:6px' },
        el('div', { class: 'zeile' }, el('b', { text: titel }), el('span', { class: 'leise klein', text: hilfe })),
        da[art] ? el('div', { class: 'usz-vorschau klein' }, el('img', { src: '/api/unterschrift/' + art + '?t=' + Date.now(), alt: titel, class: art === 'paraphe' ? 'usz-v-paraphe' : 'usz-v-sig' }),
          el('div', { class: 'usz-v-linie' })) : el('p', { class: 'leise klein', text: 'noch nicht gezeichnet' }),
        el('div', { class: 'zeile' },
          el('button', { type: 'button', onclick: () => Unterschrift.zeichnen({ art, danach: zeichne }) }, L.symbol('stift'), da[art] ? 'Neu zeichnen' : 'Zeichnen'),
          da[art] ? L.nebenknopf('Löschen', async () => { await L.api('POST', '/api/unterschrift', { art, bild: '' }); zeichne(); }) : null));
      L.setzen(ort_, el('h2', { text: 'Unterschrift' }),
        el('p', { class: 'leise klein', text: 'Mit Stift oder Finger zeichnen. Die Unterschrift kommt auf die Formulare (z. B. Stundenplanänderung), die Paraphe später auf Protokolle. Nur du siehst sie.' }),
        zeile('unterschrift', 'Unterschrift', ''), zeile('paraphe', 'Paraphe', 'Kürzel'));
    };
    zeichne();
    return ort_;
  }

  return { zeigen, neu, nachfragen, ausTermin, unterschriftKarte, entlassung };
})();
