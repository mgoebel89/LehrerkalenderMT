'use strict';
// VPN (Stufe G, aus TrackingDRS uebernommen): Zugriff von zuhause ueber das bestehende WireGuard-VPN, nur fuer Admins
// (Admin > System). Einrichten, pruefen und ausschalten laufen als root ueber systemd (deploy/vpn.sh "anfrage"); die
// Seite legt nur einen Auftrag ab und liest das Ergebnis. Erreichbar ist der Container von zuhause unter seiner
// Zugriffsadresse (vorbelegt: Schuladresse, aenderbar, bleibt auch bei einer neuen Schuladresse): die Karte zeigt, was
// dafuer auf dem VPS, in der WireGuard-App und im Heimnetz einzutragen ist.
// Einen privaten Schluessel nimmt die Seite nur in einer Client-Datei an (geht direkt an root, wird nie angezeigt).
const Vpn = (() => {
  const el = L.el;

  const STATUS = {
    verbunden: ['gruen', 'verbunden', 'Die Verbindung zum VPS steht.'],
    keine_verbindung: ['gelb', 'keine Verbindung', 'Kein Kontakt zum VPS in den letzten 5 Minuten. Steht der Container in der Server-Config (Schritt 1)? Lässt die Schule ausgehendes UDP zum Port des VPS zu?'],
    aus: ['', 'VPN aus', 'Die VPN-Verbindung ist ausgeschaltet.'],
  };

  function kopieren(text) {
    navigator.clipboard.writeText(text).then(() => L.meldung('Kopiert.'), () => L.meldung('Kopieren ging nicht, bitte markieren und kopieren.', true));
  }

  function vorlage(titel, text, hilfe) {
    return el('div', { class: 'vpn-vorlage stapel', style: 'gap:6px' },
      el('div', { class: 'zeile' }, el('b', { text: titel }),
        el('span', { class: 'rechts' }, el('button', { type: 'button', class: 'klein', onclick: () => kopieren(text) }, L.symbol('kopie'), 'Kopieren'))),
      hilfe ? el('p', { class: 'leise klein', text: hilfe }) : null,
      el('pre', { class: 'vpn-text mono', text }));
  }

  const liste = adressen => adressen.map(a => a + '/32').join(', ');

  // Kopiervorlagen: VPS (Peer + Route fuer die Schuladresse), WireGuard-App, Heimnetz, Kontrolle
  function befehle(e, schule) {
    const wg = e.server_if || 'wg0', datei = '/etc/wireguard/' + wg + '.conf';
    const erlaubt = [e.adresse + '/32'].concat(schule.map(a => a + '/32')).join(', ');
    const peer = ['[Peer]', '# Lehrerkalender MT ' + (e.name || '') + ': VPN-Adresse und Zugriffsadresse, sonst nichts',
      'PublicKey = ' + e.container_schluessel,
      e.psk ? '# PresharedKey = derselbe wie in der Client-Datei (gehört auch hier hinein)' : null,
      'AllowedIPs = ' + erlaubt].filter(Boolean).join('\n');
    const routen = schule.map(a => 'sudo ip -4 route replace ' + a + '/32 dev ' + wg).join('\n');
    const uebernehmen = "sudo bash -c 'wg syncconf " + wg + ' <(wg-quick strip ' + wg + ")'" + (routen ? '\n' + routen : '');
    const eintragen = e.aus_datei
      ? 'sudo nano ' + datei + '\n# beim [Peer] des Containers (PublicKey ' + e.container_schluessel.slice(0, 8) + '…) die Zeile ändern:\n' +
        '#   AllowedIPs = ' + erlaubt + '\n' + uebernehmen
      : 'sudo tee -a ' + datei + " >/dev/null <<'EOF'\n\n" + peer + '\nEOF\n' + uebernehmen;
    const ziel = schule[0] || e.adresse;
    return el('div', { class: 'stapel' },
      el('h3', { text: 'So erreichst du den Lehrerkalender von zuhause' + (schule.length ? ' unter ' + schule.join(', ') : '') }),
      schule.length ? null : el('div', { class: 'banner warnung klein', text: 'Keine Zugriffsadresse bekannt. Dann geht es nur über die VPN-Adresse (mit Zertifikat).' }),
      el('ol', { class: 'vpn-schritte' },
        el('li', {}, vorlage('Auf dem VPS: Container eintragen und übernehmen', eintragen,
          (e.aus_datei ? 'Die Client-Datei kam vom VPS, der Container steht dort also schon: Nur bei seinem [Peer] die Zugriffsadresse unter AllowedIPs ergänzen. ' :
            'Hängt den Block an die Server-Config an. Steht der Container schon in der Datei (z. B. nach „Neu einrichten“), den alten Block vorher löschen. ') +
          '„wg syncconf“ übernimmt das ohne bestehende Verbindungen zu trennen; die Route für die Zugriffsadresse legt es nicht an, dafür die letzte Zeile (nach einem Neustart des VPS macht wg-quick das selbst). ' +
          'Steht dort „SaveConfig = true“: erst sudo wg-quick down ' + wg + ', dann ändern, dann sudo wg-quick up ' + wg + '.')),
        schule.length ? el('li', {}, vorlage('Handy oder Laptop mit WireGuard-App', liste(schule),
          'In der App den Tunnel bearbeiten und bei „Erlaubte IPs“ / AllowedIPs diese Adresse mit Komma anhängen. Ist dort schon 0.0.0.0/0 eingetragen, ist nichts zu tun.')) : null,
        schule.length ? el('li', {}, vorlage('Heimnetz (Router oder Fritzbox mit WireGuard)', liste(schule),
          'Für Geräte ohne eigene WireGuard-App: Das Gerät, das dein Heimnetz mit dem VPS verbindet, braucht diese Adresse bei den Netzen, die über das VPN laufen. Die Adresse darf in deinem Heimnetz nicht selbst vergeben sein.')) : null,
        el('li', {}, vorlage('Kontrollieren', 'sudo wg show ' + wg + '\n# dann von zuhause im Browser:\nhttps://' + ziel + '/',
          'Beim Peer des Containers stehen „latest handshake: … seconds ago“ und ' + (schule.length ? 'die Zugriffsadresse unter „allowed ips“.' : 'seine VPN-Adresse.') +
          ' Die Seite öffnet sich mit demselben Stammzertifikat wie in der Schule.'))));
  }

  function formular(e, schule) {
    e = e || {};
    const m = (e.server || '').match(/^\[?(.*?)\]?:(\d+)$/);
    const f = {
      host: el('input', { required: true, value: m ? m[1] : '', placeholder: 'z. B. 203.0.113.5 oder vpn.example.de', autocomplete: 'off' }),
      port: el('input', { type: 'number', min: '1', max: '65535', required: true, value: m ? m[2] : '51820' }),
      schluessel: el('input', { required: true, value: e.server_schluessel || '', maxlength: '60', class: 'mono', autocomplete: 'off',
        spellcheck: 'false', placeholder: '44 Zeichen, endet auf =' }),
      adresse: el('input', { required: true, value: e.adresse || '', placeholder: 'z. B. 10.0.0.9', autocomplete: 'off' }),
      server_ip: el('input', { value: e.server_ip || '', placeholder: 'leer = erste Adresse im VPN-Netz', autocomplete: 'off' }),
      netze: el('input', { value: (e.netze || []).join(' '), placeholder: 'leer = das Netz der VPN-Adresse (/24)', autocomplete: 'off' }),
      alle: el('input', { type: 'checkbox', checked: e.alle === undefined ? true : !!e.alle }),
      zertifikat: el('input', { type: 'checkbox', checked: !!e.zertifikat }),
      server_if: el('input', { required: true, value: e.server_if || 'wg0', maxlength: '15', autocomplete: 'off' }),
      passwort: el('input', { type: 'password', required: true, autocomplete: 'current-password' }),
      conf: el('textarea', { rows: '11', required: true, class: 'mono vpn-conf', spellcheck: 'false', autocomplete: 'off',
        placeholder: '[Interface]\nPrivateKey = …\nAddress = 10.0.0.9/24\n\n[Peer]\nPublicKey = …\nEndpoint = 203.0.113.5:51820\nAllowedIPs = 10.0.0.0/24' }),
    };
    const datei = el('input', { type: 'file', accept: '.conf,text/plain', onchange: async () => {
      const d = datei.files[0];
      if (!d) return;
      if (d.size > 4000) { L.meldung('Die Datei ist zu groß für eine WireGuard-Config.', true); return; }
      f.conf.value = await d.text();
    } });
    const ohneRahmen = 'border:0;padding:0;margin:0;min-width:0';
    const werte = el('fieldset', { class: 'stapel', style: ohneRahmen + ';gap:12px' },
      el('p', { class: 'leise klein', text: 'Die Angaben stehen in der WireGuard-Config deines VPS. Einen privaten Schlüssel brauchst du ' +
        'hier nicht: Der Container erzeugt seinen eigenen, und der des Servers bleibt auf dem Server.' }),
      el('div', { class: 'felder zwei' },
        L.feld('Öffentliche IP oder Name des VPS', f.host),
        L.feld('Port', f.port, 'ListenPort in der Server-Config')),
      L.feld('Öffentlicher Schlüssel des Servers', f.schluessel, 'auf dem VPS: sudo wg show ' + (e.server_if || 'wg0') + ' public-key'),
      el('div', { class: 'felder zwei' },
        L.feld('VPN-Adresse des Containers', f.adresse, 'frei, bei keinem [Peer] unter AllowedIPs'),
        L.feld('VPN-Adresse des Servers', f.server_ip, 'Address unter [Interface]')),
      L.feld('VPN-Netz', f.netze, 'z. B. 10.0.0.0/24. Dein Heimnetz gehört nicht hierher, dafür ist der Schalter unten.'));
    const ausDatei = el('fieldset', { class: 'stapel', style: ohneRahmen + ';gap:12px' },
      el('p', { class: 'leise klein', text: 'Eine WireGuard-Datei, die du für den Container geschrieben hast: [Interface] mit PrivateKey und ' +
        'Address, [Peer] mit dem Server. Nimm nicht die Datei deines Handys, jedes Gerät braucht eigene Schlüssel. Der private ' +
        'Schlüssel darin geht verschlüsselt an den Container, liegt danach nur in /etc/wireguard und wird nie wieder angezeigt. ' +
        'AllowedIPs 0.0.0.0/0 heißt hier „Alle Teilnehmer meines VPN“: Der Container leitet dafür nichts um. DNS übernimmt er nicht.' }),
      L.feld('Datei wählen', datei),
      L.feld('… oder den Inhalt hier einfügen', f.conf));
    const umschalter = el('div', { class: 'segment', role: 'group', 'aria-label': 'Art der Angaben' });
    let modus;
    const wechseln = m_ => {
      modus = m_;
      werte.disabled = werte.hidden = m_ !== 'werte';
      ausDatei.disabled = ausDatei.hidden = m_ !== 'datei';
      L.setzen(umschalter, [['werte', 'Werte eingeben'], ['datei', 'Config-Datei']].map(([k, t]) =>
        el('button', { type: 'button', class: k === m_ ? 'an' : null, onclick: () => wechseln(k) }, t)));
    };
    wechseln(e.aus_datei ? 'datei' : 'werte');
    const zugriff = el('input', { value: e.zugriff || schule[0] || '', placeholder: schule[0] || 'z. B. 172.20.5.191', autocomplete: 'off',
      required: !schule.length });
    const zertWarnung = el('div', { class: 'banner warnung klein', hidden: !f.zertifikat.checked,
      text: 'Liegt die VPN-Adresse außerhalb des Netzes der Schuladresse (' + (schule.join(', ') || 'unbekannt') + '), entsteht ein neues ' +
        'Stammzertifikat. Die Seite ist dann kurz weg, und ALLE Geräte (auch die der Kolleg*innen) müssen das neue Stammzertifikat installieren.' });
    f.zertifikat.addEventListener('change', () => { zertWarnung.hidden = !f.zertifikat.checked; });
    return L.dialog({
      titel: e.adresse ? 'VPN neu einrichten' : 'VPN einrichten', knopf: 'Einrichten', breit: true,
      inhalt: el('div', { class: 'stapel', style: 'gap:12px' },
        umschalter, werte, ausDatei,
        L.feld('Adresse für den Zugriff von zuhause', zugriff, (schule[0] ? 'Schuladresse jetzt: ' + schule.join(', ') + '. ' : '') +
          'Bleibt fest, auch wenn sich die Schuladresse ändert. Muss im selben Bereich liegen (gleiche ersten beiden Zahlen), sonst bräuchte es ein neues Stammzertifikat.'),
        el('label', { class: 'haken', style: 'align-items:flex-start' }, f.alle, el('span', {}, el('b', { text: 'Alle Teilnehmer meines VPN' }),
          el('span', { class: 'leise klein', style: 'display:block', text: 'Jedes Gerät im VPN und in deinem Heimnetz hinter dem VPN ' +
            'erreicht den Lehrerkalender (nur HTTPS), auch wenn das Heimnetz dieselben Adressen wie das Schulnetz hat. Der ' +
            'Container selbst leitet nichts weiter.' }))),
        el('label', { class: 'haken', style: 'align-items:flex-start' }, f.zertifikat, el('span', {}, el('b', { text: 'VPN-Adresse ins Zertifikat' }),
          el('span', { class: 'leise klein', style: 'display:block', text: 'Normalerweise nicht nötig: Von zuhause öffnest du den Lehrerkalender unter ' +
            'der Zugriffsadresse, das Stammzertifikat bleibt, wie es ist.' }))),
        zertWarnung,
        L.feld('Schnittstelle auf dem VPS', f.server_if, 'Dateiname in /etc/wireguard ohne .conf (nur für die Befehle zum Kopieren)'),
        L.feld('Dein Passwort zur Bestätigung', f.passwort)),
      speichern: () => L.api('POST', '/api/admin/vpn', modus === 'datei'
        ? { aktion: 'einrichten', conf: f.conf.value, server_if: f.server_if.value, alle: f.alle.checked, zertifikat: f.zertifikat.checked,
          zugriff: zugriff.value, passwort: f.passwort.value }
        : { aktion: 'einrichten', server: f.host.value, port: f.port.value, schluessel: f.schluessel.value, adresse: f.adresse.value,
          server_ip: f.server_ip.value, netze: f.netze.value, server_if: f.server_if.value, alle: f.alle.checked,
          zertifikat: f.zertifikat.checked, zugriff: zugriff.value, passwort: f.passwort.value }),
    });
  }

  function karte() {
    const ort = el('div', { class: 'karte stapel vpn-karte' });
    let timer = null, beobachten = false, versuche = 0;
    const kopf = () => el('h2', { text: 'VPN (Zugriff von zuhause)' });
    const weiter = () => { clearTimeout(timer); timer = setTimeout(() => { if (ort.isConnected) laden(); }, 2500); };
    const gestartet = v => { beobachten = true; versuche = 0; zeichnen(v); weiter(); };
    const auftrag = async aktion => {
      try { gestartet(await L.api('POST', '/api/admin/vpn', { aktion })); } catch (e) { L.meldung(e.message, true); }
    };
    const ausschalten = async () => {
      const pw = el('input', { type: 'password', required: true, autocomplete: 'current-password' });
      const v = await L.dialog({
        titel: 'VPN ausschalten?', knopf: 'Ausschalten', gefaehrlich: true,
        inhalt: el('div', { class: 'stapel', style: 'gap:10px' },
          el('p', { text: 'Von zuhause ist der Lehrerkalender dann nicht mehr erreichbar. Schlüssel und Config bleiben, „Wieder einschalten“ ' +
            'genügt. Den Eintrag auf dem VPS kannst du stehen lassen oder löschen.' }),
          L.feld('Dein Passwort zur Bestätigung', pw)),
        speichern: () => L.api('POST', '/api/admin/vpn', { aktion: 'aus', passwort: pw.value }),
      });
      if (v) gestartet(v);
    };

    async function laden() {
      let v;
      try { v = await L.api('GET', '/api/admin/vpn'); } catch (e) {
        if (beobachten && ++versuche < 40) {
          L.setzen(ort, kopf(), el('div', { class: 'banner', text: 'Der Dienst startet neu (neues Zertifikat) … gleich geht es weiter.' }),
            versuche > 8 ? el('p', { class: 'leise klein', text: 'Dauert es länger? Dann ist das Stammzertifikat neu und der Browser traut der ' +
              'Seite noch nicht: Seite neu laden und das neue Stammzertifikat über http://<Container>/ca.crt installieren.' }) : null);
          weiter();
          return;
        }
        L.setzen(ort, kopf(), el('div', { class: 'banner warnung', text: e.message }));
        return;
      }
      if (v.laeuft || v.wartet) beobachten = true;
      else if (beobachten && v.lauf && v.lauf.ende) {
        beobachten = false;
        L.meldung(v.lauf.ergebnis === 'ok' ? 'VPN: erledigt.' : 'VPN: Das hat nicht geklappt. Details im Protokoll.', v.lauf.ergebnis !== 'ok');
      }
      zeichnen(v);
      if (v.laeuft || v.wartet) weiter();
    }

    function zeichnen(v) {
      const e = v.einrichtung, t = v.verbindung, laeuft = v.laeuft || v.wartet, gesperrt = laeuft || !v.eingerichtet;
      const schule = (e && e.schuladressen && e.schuladressen.length ? e.schuladressen : v.schuladressen) || [];
      const knopf = (text, klick, klasse) => el('button', { type: 'button', class: klasse || null, disabled: gesperrt, onclick: klick }, text);
      const einrichten = async () => {
        const r = await formular(e, schule);
        if (!r) return;
        gestartet(r);
        if (r.hinweise && r.hinweise.length) L.meldung('Aus der Datei: ' + r.hinweise.join(' '));
      };
      let status = null;
      if (e && !e.aktiv) status = el('div', { class: 'zeile' }, el('span', { class: 'chip', text: 'VPN aus' }));
      else if (e && t) {
        const [farbe, chip, text] = STATUS[t.ergebnis] || ['', t.ergebnis, ''];
        status = el('div', { class: 'zeile' }, el('span', { class: 'chip ' + farbe, text: chip }), el('span', { class: 'leise klein', text }));
      }
      const lauf = v.lauf && v.lauf.ende ? v.lauf : null;
      const ziele = e && e.zugriff ? [e.zugriff] : schule;   // alte Einrichtung ohne Zugriffsadresse: Schuladresse
      const adressen = e ? ziele.concat(e.zertifikat ? [e.adresse] : []) : [];
      L.setzen(ort, kopf(),
        !v.eingerichtet ? el('p', { class: 'leise klein', text: 'Das Einrichten über diese Seite geht im Container, sobald diese Version dort ' +
          'installiert ist (lehrerkalender-update). Hier läuft es gerade ohne Container.' }) : null,
        laeuft ? el('div', { class: 'stapel', style: 'gap:6px' }, el('div', { class: 'banner', text: 'Auftrag läuft …' }),
          v.protokoll ? el('pre', { class: 'vpn-text mono', text: v.protokoll }) : null) : null,
        !e ? el('p', { class: 'leise', text: 'Der Container wird Teilnehmer in deinem WireGuard-VPN. Von zuhause ist dann nur diese Seite ' +
          'über HTTPS erreichbar, und zwar unter derselben Adresse wie in der Schule' + (schule[0] ? ' (' + schule[0] + ')' : '') +
          '. Du gibst die Daten deines VPS ein oder lädst eine fertige Client-Datei hoch und bekommst die Einträge für VPS, ' +
          'WireGuard-App und Heimnetz zum Kopieren.' }) : null,
        status,
        e ? el('dl', { class: 'vpn-daten' },
          el('dt', { text: 'Von zuhause' }), el('dd', {}, adressen.length ? adressen.map((a, i) => [i ? ' · ' : null,
            el('a', { href: 'https://' + a + '/', target: '_blank', rel: 'noopener', class: 'mono', text: 'https://' + a })]) : '–'),
          e.zugriff && schule.length && !schule.includes(e.zugriff) ? [el('dt', { text: 'Schuladresse' }), el('dd', {},
            el('span', { class: 'mono', text: schule.join(', ') }), el('span', { class: 'leise klein', text: ' (hat sich geändert, die Zugriffsadresse gilt weiter)' }))] : null,
          el('dt', { text: 'VPN-Adresse' }), el('dd', {}, el('span', { class: 'mono', text: e.adresse }),
            e.zertifikat ? null : el('span', { class: 'leise klein', text: ' (nicht im Zertifikat)' })),
          el('dt', { text: 'Server' }), el('dd', { class: 'mono', text: e.server || '–' }),
          el('dt', { text: 'Erreichbar für' }), el('dd', { text: e.alle ? 'alle Teilnehmer deines VPN, auch dein Heimnetz (nur HTTPS)' :
            'nur Geräte mit einer Adresse im VPN-Netz ' + (e.netze || []).join(', ') }),
          t && t.zeit ? [el('dt', { text: 'Geprüft' }), el('dd', { text: L.wann(t.zeit) })] : null) : null,
        el('div', { class: 'zeile' },
          !e ? knopf('VPN einrichten', einrichten, 'haupt') : e.aktiv
            ? [knopf('Verbindung prüfen', () => auftrag('pruefen'), 'haupt'), knopf('Neu einrichten', einrichten), knopf('VPN aus', ausschalten, 'warnen')]
            : [knopf('Wieder einschalten', einrichten, 'haupt')]),
        e && e.aktiv ? befehle(e, ziele) : null,
        e ? el('details', {}, el('summary', { text: 'Config des Containers (/etc/wireguard/wg0.conf)' }),
          vorlage('wg0.conf', e.konf, 'Ist im Container schon aktiv. Der private Schlüssel liegt getrennt in /etc/wireguard/lehrerkalender.key ' +
            'und wird nie angezeigt.')) : null,
        lauf ? el('details', {}, el('summary', { text: 'Letzter Auftrag: ' + L.wann(lauf.ende) + ' · ' + lauf.aktion +
          (lauf.ergebnis === 'ok' ? ' · erledigt' : ' · fehlgeschlagen') }),
          el('pre', { class: 'vpn-text mono', text: v.protokoll || '(kein Protokoll)' })) : null);
    }

    laden();
    return ort;
  }

  return { karte };
})();
