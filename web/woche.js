'use strict';
// Wochenplan (Stufe B, Voransicht H): Stundenplan der Woche nach Uhrzeit, Termine oben, einmalige Aenderungen per Klick,
// Rechtsklick oder ⋯ (Ausfall, vertreten werden, Verschieben, Merker; im freien Block Zusatzstunde und Vertretung).
// Am Handy: Tagesumschalter und Liste. Die Startseite zeigt darueber die Hinweisleiste (Heute: Termine und Merker).
const Woche = (() => {
  const el = L.el;
  let ort = null;
  let W = null;            // geladene Woche
  let montag = null;       // ISO-Datum der angezeigten Woche (null = aktuelle)
  let mobilTag = null;     // ISO-Datum des Tages in der Handy-Ansicht
  let mitLeiste = true;
  let offen = [];          // Stunden ohne Ist-Bestaetigung (neueste zuerst)

  const tagKurz = iso => L.tag(iso).trim();
  const plusTage = (iso, n) => { const d = new Date(iso + 'T12:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
  const farbe = k => (k && W.farben[String(k.id)]) || 'var(--leise)';
  const zeitText = (b, e) => b + (e ? '–' + e : '');
  const blockName = b => (b.klasse ? b.klasse.name : (b.klasse_text || 'Vertretung')) + (b.gruppe ? ' · ' + b.gruppe.name : '');

  async function zeigen(ortEl, optionen = {}) {
    ort = ortEl;
    mitLeiste = optionen.leiste !== false;
    await laden();
  }

  async function laden() {
    const [w, o] = await Promise.all([L.api('GET', '/api/woche' + (montag ? '?montag=' + montag : '')),
      mitLeiste ? L.api('GET', '/api/ist/offen').catch(() => ({ offen: [] })) : Promise.resolve({ offen: [] })]);
    W = w;
    offen = o.offen;
    if (!mobilTag || !W.tage.some(t => t.datum === mobilTag)) {
      mobilTag = (W.tage.find(t => t.heute) || W.tage[0]).datum;
    }
    zeichnen();
  }

  function blattern(tage) {
    montag = plusTage(W.montag, tage);
    laden().catch(e => L.meldung(e.message, true));
  }

  // --- Zeichnen ---

  function zeichnen() {
    const ende = W.tage[W.tage.length - 1].datum;
    const titelText = 'KW ' + W.kw + ' · ' + W.montag.slice(8, 10) + '.' + W.montag.slice(5, 7) + '.–' + ende.slice(8, 10) + '.' + ende.slice(5, 7) + '.' + ende.slice(0, 4);
    const teile = [];
    if (mitLeiste) teile.push(leiste());
    teile.push(el('div', { class: 'zeile wp-werkzeug' },
      el('button', { type: 'button', 'aria-label': 'Vorige Woche', onclick: () => blattern(-7) }, L.symbol('links')),
      el('b', { text: titelText }),
      el('span', { class: 'chip', title: 'A/B-Woche nach Kalenderwoche', text: W.ab + '-Woche' }),
      el('button', { type: 'button', 'aria-label': 'Nächste Woche', onclick: () => blattern(7) }, L.symbol('rechts')),
      el('button', { type: 'button', onclick: () => { montag = null; mobilTag = null; laden(); } }, L.symbol('heute'), 'Heute'),
      W.bloecke.some(b => !b.zustand && b.thema && !b.ist && (b.datum < W.heute || (b.datum === W.heute && b.ende <= new Date().toTimeString().slice(0, 5))))
        ? el('span', { class: 'chip gelb', title: 'Stunden dieser Woche ohne Ist-Bestätigung' }, L.symbol('offen'),
          W.bloecke.filter(b => !b.zustand && b.thema && !b.ist && (b.datum < W.heute || (b.datum === W.heute && b.ende <= new Date().toTimeString().slice(0, 5)))).length + ' ohne Ist')
        : null,
      el('span', { class: 'rechts' },
        el('button', { type: 'button', onclick: () => terminBearbeiten(null, (W.tage.find(t => t.heute) || W.tage[0]).datum) }, L.symbol('plus'), 'Termin'),
        el('a', { class: 'knopf', href: '#einstellungen' }, L.symbol('spalten'), 'Stundenplan'))));
    if (!W.hat_stundenplan) {
      teile.push(el('div', { class: 'banner' }, el('b', { text: 'Noch kein Stundenplan. ' }),
        'Trag zuerst deinen Grundstundenplan ein, dann erscheinen hier deine Stunden. ',
        el('a', { href: '#einstellungen', text: 'Stundenplan einrichten' })));
    }
    teile.push(el('div', { class: 'wp-scroll' }, tabelle()));
    teile.push(tagliste());
    teile.push(legende());
    L.setzen(ort, teile);
  }

  function leiste() {
    const heute = W.tage.find(t => t.heute);
    const karten = [];
    if (offen.length) {
      karten.push(el('div', { class: 'hinweis gelb' },
        el('div', { class: 'k' }, L.symbol('offen'), el('b', { text: 'Ist offen' }), el('span', { class: 'zahl', text: offen.length >= 30 ? '30+' : String(offen.length) })),
        offen.slice(0, 3).map(o => el('button', { type: 'button', class: 'z z-knopf', onclick: () => Stunde.oeffnen(o.datum, o.beginn, laden) },
          el('span', { class: 'mono', text: tagKurz(o.datum) }), el('span', { text: o.strang + ' · ' + o.thema }))),
        el('div', { class: 'zeile' }, offen.length > 3 ? el('span', { class: 'leise klein', text: 'und ' + (offen.length - 3) + ' weitere' }) : null,
          el('button', { type: 'button', class: 'klein rechts', onclick: alleBestaetigen }, L.symbol('ok'), 'Alle wie geplant'))));
    }
    if (heute) {
      const z = [];
      W.termine.filter(t => t.datum <= heute.datum && (t.bis || t.datum) >= heute.datum).forEach(t =>
        z.push(el('div', { class: 'z' }, el('span', { class: 'mono', text: t.beginn || 'ganztags' }), el('span', { text: t.titel }))));
      W.bloecke.filter(b => b.datum === heute.datum).forEach(b => b.merker.forEach(m =>
        z.push(el('div', { class: 'z' }, el('span', { class: 'mono', text: b.beginn }),
          el('span', {}, L.symbol('merker'), ' ', (b.klasse ? b.klasse.name + ': ' : ''), m.text)))));
      const anders = W.bloecke.filter(b => b.datum === heute.datum && (b.zustand || b.art !== 'regulaer'));
      anders.forEach(b => z.push(el('div', { class: 'z' }, el('span', { class: 'mono', text: b.beginn }),
        el('span', { text: blockName(b) + ': ' + zustandText(b) }))));
      if (z.length) {
        karten.push(el('div', { class: 'hinweis' },
          el('div', { class: 'k' }, L.symbol('heute'), el('b', { text: 'Heute' }), el('span', { class: 'zahl', text: String(z.length) })), z));
      }
    }
    return karten.length ? el('div', { class: 'leiste' }, karten) : null;
  }

  async function alleBestaetigen() {
    const ok = await L.dialog({
      titel: 'Alle offenen Stunden bestätigen?', knopf: 'Alle wie geplant',
      inhalt: el('p', { text: 'Alle ' + (offen.length >= 30 ? 'offenen' : offen.length) + ' Stunden ohne Ist-Bestätigung werden als „wie geplant“ eingetragen. Einzelne kannst du danach im Stunden-Overlay noch ändern.' }),
      speichern: () => L.api('POST', '/api/ist/alle', {}),
    });
    if (ok) { L.meldung(ok.bestaetigt + ' Stunden bestätigt.'); await laden(); }
  }

  function kopfzelle(t) {
    return el('th', { class: (t.heute ? 'heute' : '') + (t.frei ? ' frei' : '') },
      t.tag, el('span', { class: 'd', text: t.datum.slice(8, 10) + '.' + t.datum.slice(5, 7) + '.' + (t.heute ? ' · heute' : '') }),
      t.frei ? el('span', { class: 'frei-name', text: t.frei }) : null);
  }

  function zeitZelle(z) {
    return el('td', { class: 'zeit' + (z.raster ? ' eigen' : '') },
      el('b', { text: z.bezeichnung || 'außerhalb' }), z.beginn + '–' + z.ende, z.raster ? el('span', { class: 'r', text: z.raster }) : null);
  }

  function tabelle() {
    const kopf = el('tr', {}, el('th', { class: 'zeit', text: 'Block' }), W.tage.map(kopfzelle));
    const termine = el('tr', { class: 'termine' }, el('td', { class: 'zeit', text: 'Termine' }),
      W.tage.map(t => el('td', { class: t.heute ? 'heute' : null },
        termineAm(t.datum).map(terminKarte),
        el('button', { type: 'button', class: 'leicht klein wp-plus', 'aria-label': 'Termin am ' + tagKurz(t.datum), onclick: () => terminBearbeiten(null, t.datum) }, L.symbol('plus')))));
    const zeilen = W.zeilen.map(z => el('tr', {}, zeitZelle(z), W.tage.map(t => {
      const hier = W.bloecke.filter(b => b.datum === t.datum && b.beginn === z.beginn);
      const td = el('td', { class: (t.heute ? 'heute' : '') + (t.frei ? ' frei' : '') });
      if (hier.length) hier.forEach(b => td.appendChild(karte(b)));
      else if (!t.frei) td.appendChild(leer(t, z));
      return td;
    })));
    return el('table', { class: 'wp' }, el('thead', {}, kopf), el('tbody', {}, termine, zeilen));
  }

  function termineAm(datum) {
    return W.termine.filter(t => t.datum <= datum && (t.bis || t.datum) >= datum);
  }

  function terminKarte(t) {
    return el('button', { type: 'button', class: 'wp-ev ' + t.art, onclick: () => terminBearbeiten(t) },
      L.symbol(t.art === 'dienst' ? 'kalender' : 'konto'), el('span', { text: (t.beginn ? t.beginn + ' ' : '') + t.titel }));
  }

  function zustandText(b) {
    if (b.zustand === 'ausfall') return 'fällt aus' + (b.grund ? ': ' + b.grund : '');
    if (b.zustand === 'vertreten') return 'vertreten' + (b.wer ? ' durch ' + b.wer : '') + (b.thema_weiter ? ' · mit deinem Thema' : ' · eigener Stoff') + (b.grund ? ' · ' + b.grund : '');
    if (b.zustand === 'verschoben') return 'verschoben auf ' + tagKurz(b.ziel.datum) + ' ' + b.ziel.beginn;
    if (b.art === 'verschoben') return 'verschoben von ' + tagKurz(b.herkunft.datum) + ' ' + b.herkunft.beginn;
    if (b.art === 'zusatz') return 'Zusatzstunde' + (b.grund ? ': ' + b.grund : '');
    if (b.art === 'vertretung') return 'Vertretung' + (b.wer ? ' für ' + b.wer : '') + (b.grund ? ' · ' + b.grund : '');
    return '';
  }

  function karte(b) {
    const name = blockName(b);
    const klassen = ['wp-b'];
    if (b.jetzt) klassen.push('jetzt');
    if (b.zustand === 'ausfall' || b.zustand === 'verschoben') klassen.push('aus');
    if (b.zustand === 'vertreten') klassen.push('vertreten');
    if (b.art === 'vertretung' || b.zustand === 'vertreten') klassen.push('vertr');
    if (b.art === 'zusatz' || b.art === 'verschoben') klassen.push('zusatz');
    const st = [];
    if (b.zustand === 'ausfall') st.push(el('span', {}, L.symbol('ausfall'), zustandText(b)));
    else if (b.zustand === 'vertreten') st.push(el('span', {}, L.symbol('vertretung'), zustandText(b)));
    else if (b.zustand === 'verschoben') st.push(el('span', {}, L.symbol('verschieben'), zustandText(b)));
    else if (b.art === 'verschoben') st.push(el('span', { class: 'zus' }, L.symbol('verschieben'), zustandText(b)));
    else if (b.art === 'zusatz') st.push(el('span', { class: 'zus' }, L.symbol('zusatz'), zustandText(b)));
    else if (b.art === 'vertretung') st.push(el('span', {}, L.symbol('vertretung'), zustandText(b)));
    else if (b.jetzt) st.push(el('span', { class: 'jetzt' }, L.symbol('jetzt'), 'jetzt'));
    if ((!b.zustand || b.thema_weiter) && b.thema && !b.jetzt) {
      const vergangen = b.datum < W.heute || (b.datum === W.heute && b.ende <= new Date().toTimeString().slice(0, 5));
      if (b.ist === 'ok') st.push(el('span', { class: 'ok' }, L.symbol('ok'), 'gehalten'));
      else if (b.ist === 'mehr') st.push(el('span', { class: 'offen' }, L.symbol('plus'), '1 Block mehr'));
      else if (b.ist === 'fertig') st.push(el('span', { class: 'ok' }, L.symbol('haken'), 'Thema fertig'));
      else if (vergangen && !b.zustand) st.push(el('span', { class: 'offen' }, L.symbol('offen'), 'Ist fehlt'));
    }
    const k = el('div', { class: klassen.join(' '), style: '--kl:' + farbe(b.klasse), tabindex: '0', role: 'button',
      'aria-label': name + ', ' + tagKurz(b.datum) + ' ' + b.beginn + (st.length ? ', ' + zustandText(b) : '') + ' – Aktionen' },
    el('div', { class: 'kl' }, el('span', { text: b.klasse ? b.klasse.name : (b.klasse_text || 'Vertretung') }),
      b.gruppe ? el('span', { class: 'chip gr', text: b.gruppe.name }) : null,
      b.klasse && b.klasse.stufe ? el('span', { class: 'chip', text: b.klasse.stufe }) : null,
      b.thema && b.thema.lernfeld ? el('span', { class: 'chip', text: b.thema.lernfeld }) : null,
      b.woche && b.woche !== 'alle' ? el('span', { class: 'chip', title: 'nur in ' + b.woche + '-Wochen', text: b.woche }) : null),
    b.thema ? el('div', { class: 'th', title: b.thema.titel + (b.thema.ls ? ' · ' + b.thema.ls : '') },
      b.thema.titel, b.thema.von > 1 ? el('span', { class: 'teil', text: ' · ' + b.thema.teil + '/' + b.thema.von }) : null) : null,
    st.length ? el('div', { class: 'st' }, st) : null,
    b.merker.map(m => el('div', { class: 'st' }, el('span', { class: 'merk' }, L.symbol('merker'), m.text))),
    el('button', { type: 'button', class: 'mehr', 'aria-label': 'Aktionen für diese Stunde', 'aria-haspopup': 'menu',
      onclick: ev => { ev.stopPropagation(); const r = ev.currentTarget.getBoundingClientRect(); menue(r.right + scrollX - 240, r.bottom + scrollY + 4, b); } },
    L.symbol('mehr')));
    const menueAuf = ev => { const r = k.getBoundingClientRect(); menue(ev && ev.pageX ? ev.pageX : r.left + scrollX, ev && ev.pageY ? ev.pageY : r.bottom + scrollY, b); };
    const oeffnen = ev => (gehalten(b) ? Stunde.oeffnen(b.datum, b.beginn, laden) : menueAuf(ev));
    k.addEventListener('click', oeffnen);
    k.addEventListener('contextmenu', ev => { ev.preventDefault(); menueAuf(ev); });
    k.addEventListener('keydown', ev => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); oeffnen(null); } });
    return k;
  }

  // Stunden, die ich halte (mit Klasse aus der Liste): Klick oeffnet das Stunden-Overlay, sonst das Aktionsmenue
  const gehalten = b => b.klasse && ['regulaer', 'zusatz', 'verschoben'].includes(b.art) && (!b.zustand || (b.zustand === 'vertreten' && b.thema_weiter));

  function leer(t, z) {
    const d = el('button', { type: 'button', class: 'wp-leer', 'aria-label': 'Freier Block ' + tagKurz(t.datum) + ' ' + z.beginn + ' – Zusatzstunde oder Vertretung',
      onclick: ev => menueFrei(ev.pageX || 0, ev.pageY || 0, t, z) });
    d.addEventListener('contextmenu', ev => { ev.preventDefault(); menueFrei(ev.pageX, ev.pageY, t, z); });
    return d;
  }

  function tagliste() {
    const tag = W.tage.find(t => t.datum === mobilTag) || W.tage[0];
    const bloecke = W.bloecke.filter(b => b.datum === tag.datum);
    return el('div', { class: 'wp-tagliste' },
      el('div', { class: 'segment', role: 'group', 'aria-label': 'Tag', style: 'display:flex' },
        W.tage.map(t => el('button', { type: 'button', class: t.datum === tag.datum ? 'an' : null, style: 'flex:1',
          onclick: () => { mobilTag = t.datum; zeichnen(); } }, t.tag + (t.heute ? ' ·' : '')))),
      el('div', { class: 'zeile' }, el('b', { text: L.tag(tag.datum, true) + (tag.heute ? ' · heute' : '') }),
        tag.frei ? el('span', { class: 'chip gelb', text: tag.frei }) : null,
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => terminBearbeiten(null, tag.datum) }, L.symbol('plus'), 'Termin'))),
      termineAm(tag.datum).map(terminKarte),
      bloecke.length ? bloecke.map(b => {
        const z = W.zeilen.find(x => x.beginn === b.beginn);
        return el('div', { class: 'wp-zeile' }, el('div', { class: 'mono klein leise' },
          el('b', { style: 'color:var(--text);display:block', text: z && z.bezeichnung ? z.bezeichnung : b.beginn }), b.beginn), karte(b));
      }) : el('p', { class: 'leise', text: tag.frei ? 'Unterrichtsfrei.' : 'Kein Unterricht an diesem Tag.' }));
  }

  function legende() {
    const benutzt = {};
    W.bloecke.forEach(b => { if (b.klasse) benutzt[b.klasse.id] = b.klasse; });
    return el('div', { class: 'legende' },
      Object.values(benutzt).sort((a, b) => a.name.localeCompare(b.name)).map(k =>
        el('span', {}, el('i', { class: 'farbe', style: 'background:' + farbe(k) }), k.name)),
      el('span', {}, L.symbol('jetzt'), 'jetzt'), el('span', {}, L.symbol('ausfall'), 'Ausfall'),
      el('span', {}, L.symbol('vertretung'), 'Vertretung (gestrichelt)'), el('span', {}, L.symbol('zusatz'), 'Zusatzstunde'),
      el('span', {}, L.symbol('merker'), 'Merker'));
  }

  // --- Aktionsmenue ---

  function menueZu() {
    const m = document.getElementById('wp-menue');
    if (m) m.remove();
  }

  function menueOeffnen(x, y, kopfText, punkte) {
    menueZu();
    const m = el('div', { class: 'wp-menue', id: 'wp-menue', role: 'menu' },
      el('div', { class: 'mk', text: kopfText }),
      punkte.map(([sym, text, aktion, klasse]) => el('button', { type: 'button', role: 'menuitem', class: klasse || null,
        onclick: () => { menueZu(); aktion(); } }, L.symbol(sym), text)));
    document.body.appendChild(m);
    const breite = m.offsetWidth || 250;
    m.style.left = Math.max(8, Math.min(x, document.documentElement.clientWidth + scrollX - breite - 8)) + 'px';
    m.style.top = Math.max(8, Math.min(y, scrollY + innerHeight - m.offsetHeight - 8)) + 'px';
    const erstes = m.querySelector('button');
    if (erstes) erstes.focus();
  }

  document.addEventListener('click', ev => {
    if (!ev.target.closest('#wp-menue') && !ev.target.closest('.wp-b') && !ev.target.closest('.wp-leer')) menueZu();
  });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') menueZu(); });
  window.addEventListener('hashchange', menueZu);

  function menue(x, y, b) {
    const name = blockName(b);
    const punkte = [];
    if (gehalten(b)) punkte.push(['auge', 'Stunde öffnen', () => Stunde.oeffnen(b.datum, b.beginn, laden)]);
    if (b.art === 'regulaer' && !b.zustand) {
      punkte.push(['ausfall', 'Ausfall eintragen …', () => ausfall(b)]);
      punkte.push(['vertretung', 'Ich werde vertreten …', () => vertreten(b)]);
      punkte.push(['verschieben', 'Stunde verschieben …', () => verschieben(b)]);
    } else if (b.art === 'regulaer') {
      punkte.push(['undo', 'Änderung zurücknehmen (' + zustandText(b).split(':')[0] + ')', () => zuruecknehmen(b)]);
    } else {
      punkte.push(['muell', (b.art === 'verschoben' ? 'Verschiebung zurücknehmen' : b.art === 'zusatz' ? 'Zusatzstunde entfernen' : 'Vertretung entfernen'),
        () => zuruecknehmen(b), 'warnen']);
    }
    if (b.klasse) {
      b.merker.forEach(m => punkte.push(['merker', 'Merker: ' + (m.text.length > 28 ? m.text.slice(0, 27) + '…' : m.text), () => merker(b, m)]));
      if (!b.merker.length) punkte.push(['merker', 'Merker für diese Stunde …', () => merker(b, null)]);
    }
    menueOeffnen(x, y, tagKurz(b.datum) + ' · ' + zeitText(b.beginn, b.ende) + ' · ' + name, punkte);
  }

  function menueFrei(x, y, t, z) {
    if (!x && !y) { const r = document.activeElement.getBoundingClientRect(); x = r.left + scrollX; y = r.bottom + scrollY; }
    menueOeffnen(x, y, tagKurz(t.datum) + ' · ' + zeitText(z.beginn, z.ende) + ' · frei', [
      ['zusatz', 'Zusatzstunde hier …', () => zusatzOderVertretung('zusatz', t.datum, z)],
      ['vertretung', 'Vertretung hier …', () => zusatzOderVertretung('vertretung', t.datum, z)],
      ['kalender', 'Termin an diesem Tag …', () => terminBearbeiten(null, t.datum, z.beginn)],
    ]);
  }

  // --- Dialoge ---

  async function aendern(daten) {
    await L.api('POST', '/api/aenderung', daten);
    return true;
  }

  const grundFeld = wert => Aenderung.grundFeld(wert);

  function stundeText(b) {
    return el('p', { class: 'klein' }, el('b', { text: blockName(b) }), ' · ' + L.tag(b.datum, true) + ' · ' + zeitText(b.beginn, b.ende));
  }

  const info = b => ({ datum: b.datum, beginn: b.beginn, ende: b.ende, name: blockName(b) });

  async function ausfall(b) {
    if (await Aenderung.ausfall(info(b))) await laden();
  }

  async function vertreten(b) {
    if (await Aenderung.vertreten(info(b))) await laden();
  }

  async function verschieben(b) {
    const k = W.klassen.find(x => x.id === b.klasse.id);
    const bloecke = (k ? k.bloecke : W.zeilen.map(z => z.beginn + '-' + z.ende)).map(x => {
      const [beginn, ende] = x.split('-');
      const z = W.zeilen.find(y => y.beginn === beginn);
      return { beginn, ende, bezeichnung: z ? z.bezeichnung : '' };
    });
    if (await Aenderung.verschieben(info(b), bloecke)) await laden();
  }

  async function zuruecknehmen(b) {
    const ok = await L.dialog({
      titel: 'Änderung zurücknehmen?', knopf: 'Zurücknehmen', gefaehrlich: b.art !== 'regulaer',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(b), el('p', { text: zustandText(b) }),
        el('p', { class: 'leise klein', text: b.art === 'regulaer' || b.art === 'verschoben' ? 'Danach gilt wieder der Stundenplan.' : 'Der Block verschwindet aus dem Wochenplan.' })),
      speichern: () => L.api('POST', '/api/aenderung/' + b.aenderung_id + '/loeschen', {}),
    });
    if (ok) await laden();
  }

  async function zusatzOderVertretung(art, datum, z) {
    const passend = W.klassen.filter(k => k.bloecke.includes(z.beginn + '-' + z.ende));
    const klasse = el('select', {}, el('option', { value: '', text: art === 'vertretung' ? 'andere Klasse (eintippen)' : '– Klasse wählen –' }),
      passend.map(k => el('option', { value: k.id, text: k.name })));
    const gruppe = el('select', { 'aria-label': 'Gruppe' });
    const gruppeFeld = L.feld('Gruppe', gruppe);
    const andere = el('input', { maxlength: 40, placeholder: 'z. B. IT 23' });
    const andereFeld = L.feld('Klasse', andere);
    const wer = el('input', { maxlength: 80, placeholder: 'z. B. Kollegin M.' });
    const [grund, liste] = grundFeld();
    const umschalten = () => {
      andereFeld.hidden = art !== 'vertretung' || !!klasse.value;
      const gs = klasse.value ? W.gruppen.filter(g => g.klasse_id === Number(klasse.value)) : [];
      L.setzen(gruppe, el('option', { value: '', text: 'ganze Klasse' }), gs.map(g => el('option', { value: g.id, text: g.name })));
      gruppeFeld.hidden = !gs.length;
    };
    klasse.addEventListener('change', umschalten);
    umschalten();
    const ok = await L.dialog({
      titel: art === 'zusatz' ? 'Zusatzstunde' : 'Ich vertrete', knopf: 'Eintragen',
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
        el('p', { class: 'klein', text: L.tag(datum, true) + ' · ' + (z.bezeichnung ? z.bezeichnung + ' · ' : '') + zeitText(z.beginn, z.ende) }),
        L.feld(art === 'vertretung' ? 'Klasse aus der Liste' : 'Klasse', klasse, passend.length ? null : 'Keine Klasse hat laut Zeitraster diesen Block.'),
        gruppeFeld, andereFeld,
        art === 'vertretung' ? L.feld('Für wen?', wer, 'freiwillig') : null,
        L.feld(art === 'zusatz' ? 'Anlass' : 'Notiz', grund, 'freiwillig'), liste),
      speichern: () => aendern({ art, datum, beginn: z.beginn, ende: z.ende, klasse_id: klasse.value || null, gruppe_id: gruppe.value || null,
        klasse_text: andere.value,
        wer: wer.value, grund: grund.value }),
    });
    if (ok) await laden();
  }

  async function merker(b, m) {
    const text = el('textarea', { maxlength: 200, rows: 3, placeholder: 'z. B. Aufgabe 4 besprechen' });
    text.value = m ? m.text : '';
    const weitere = m ? [{ text: 'Entfernen', klasse: 'warnen', speichern: () => L.api('POST', '/api/termin/' + m.id + '/loeschen', {}) }] : [];
    const ok = await L.dialog({
      titel: 'Merker', knopf: 'Speichern', weitere,
      inhalt: el('div', { class: 'stapel', style: 'gap:10px' }, stundeText(b), L.feld('Woran willst du in dieser Stunde denken?', text)),
      speichern: () => L.api('POST', m ? '/api/termin/' + m.id : '/api/termin',
        { art: 'merker', titel: text.value, datum: b.datum, beginn: b.beginn, klasse_id: b.klasse.id }),
    });
    if (ok) await laden();
  }

  async function terminBearbeiten(t, datum, beginnVorgabe) {
    const titel = el('input', { maxlength: 200, value: t ? t.titel : '', placeholder: 'z. B. Fachkonferenz Mechatronik' });
    const art = el('select', {}, [['dienst', 'Dienstlich'], ['privat', 'Privat']].map(([w, x]) =>
      el('option', { value: w, text: x, selected: (t ? t.art : 'dienst') === w ? true : null })));
    const von = el('input', { type: 'date', value: t ? t.datum : datum });
    const bis = el('input', { type: 'date', value: t && t.bis ? t.bis : '' });
    const beginn = el('input', { type: 'time', value: t ? (t.beginn || '') : (beginnVorgabe || '') });
    const ende = el('input', { type: 'time', value: t && t.ende ? t.ende : '' });
    const notiz = el('textarea', { maxlength: 2000, rows: 2 });
    notiz.value = t ? t.notiz : '';
    const weitere = t ? [{ text: 'Löschen', klasse: 'warnen', speichern: () => L.api('POST', '/api/termin/' + t.id + '/loeschen', {}) }] : [];
    const ok = await L.dialog({
      titel: t ? 'Termin' : 'Neuer Termin', knopf: 'Speichern', weitere,
      inhalt: el('div', { class: 'felder' }, L.feld('Titel', titel),
        el('div', { class: 'felder zwei' }, L.feld('Art', art), L.feld('Tag', von)),
        el('div', { class: 'felder zwei' }, L.feld('von (Uhrzeit)', beginn, 'leer = ganztags'), L.feld('bis (Uhrzeit)', ende, 'freiwillig')),
        L.feld('Letzter Tag', bis, 'nur bei mehrtägigen Terminen'), L.feld('Notiz', notiz)),
      speichern: () => L.api('POST', t ? '/api/termin/' + t.id : '/api/termin', { art: art.value, titel: titel.value, datum: von.value,
        bis: bis.value || null, beginn: beginn.value || null, ende: ende.value || null, notiz: notiz.value }),
    });
    if (ok) await laden();
  }

  return { zeigen };
})();
