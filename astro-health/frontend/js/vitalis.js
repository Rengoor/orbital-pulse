/* @ds-bundle: {"format":4,"namespace":"Vitalis","components":[{"name":"BodyMap"},{"name":"VitalReadout"},{"name":"Sparkline"},{"name":"DoseGauge"},{"name":"DecisionCard"},{"name":"Advisory"},{"name":"TierBadge"},{"name":"SourceLabel"},{"name":"DelayDial"},{"name":"CrewSwitcher"},{"name":"SegmentedControl"},{"name":"Button"},{"name":"Panel"}]} */
(function () {
  var R = window.React;
  var h = R.createElement;
  var F = R.Fragment;

  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(' '); }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  /* ---------- icons (24px grid, stroke = currentColor) ---------- */
  var PATHS = {
    'tier-GREEN': ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M8 12.5l2.6 2.6L16.2 9.5'],
    'tier-YELLOW': ['M12 3.2L22 20.5H2L12 3.2z', 'M12 10v4.5', 'M12 17.4v.2'],
    'tier-RED': ['M8.2 2.8h7.6l5.4 5.4v7.6l-5.4 5.4H8.2l-5.4-5.4V8.2z', 'M9 9l6 6', 'M15 9l-6 6'],
    'tier-GREY': ['M12 3a9 9 0 0 1 0 18', 'M12 21a9 9 0 0 1 0-18', 'M9.8 9.6a2.3 2.3 0 1 1 3.2 2.1c-.7.3-1 .8-1 1.5v.4', 'M12 16.6v.2'],
    clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3.5 2'],
    drop: ['M12 3s6.5 7 6.5 11.2A6.5 6.5 0 0 1 5.5 14.2C5.5 10 12 3 12 3z'],
    card: ['M4 5h16v14H4z', 'M8 9h8', 'M8 13h5'],
    medic: ['M9 3h6v6h6v6h-6v6H9v-6H3V9h6z'],
    antenna: ['M12 12v9', 'M8.5 21h7', 'M7.8 7.8a6 6 0 0 0 0 8.4', 'M16.2 7.8a6 6 0 0 1 0 8.4', 'M5 5a10 10 0 0 0 0 14', 'M19 5a10 10 0 0 1 0 14', 'M12 12.2v-.4'],
    check: ['M5 12.5l4.5 4.5L19 7.5'],
    sun: ['M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8'],
    helmet: ['M12 21a8 8 0 0 0 8-8v-2a8 8 0 0 0-16 0v2a8 8 0 0 0 8 8z', 'M7.5 11.5q4.5-3 9 0q.5 3-1 4.5q-3.5 1.5-7 0q-1.5-1.5-1-4.5z'],
    body: ['M12 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z', 'M6 9.5l6-1 6 1', 'M12 8.5v6', 'M12 14.5l-3 7', 'M12 14.5l3 7'],
    grid: ['M4 4h7v7H4z', 'M13 4h7v4h-7z', 'M13 10h7v10h-7z', 'M4 13h7v7H4z'],
    cube: ['M12 2.8l8 4.6v9.2l-8 4.6-8-4.6V7.4z', 'M4 7.4l8 4.6 8-4.6', 'M12 12v9.2'],
    shield: ['M12 3l7.5 3v5.5c0 4.5-3.2 8.2-7.5 9.5-4.3-1.3-7.5-5-7.5-9.5V6z', 'M8.8 12.2l2.2 2.2 4.3-4.6'],
    arrow: ['M5 12h14', 'M13 6l6 6-6 6'],
    flare: ['M12 3v4M12 17v4M3 12h4M17 12h4', 'M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z', 'M6.3 6.3l2.2 2.2M15.5 15.5l2.2 2.2M6.3 17.7l2.2-2.2M15.5 8.5l2.2-2.2']
  };
  function Icon(p) {
    var d = PATHS[p.name] || [];
    return h('svg', { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: p.strokeWidth || 2, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true, className: p.className },
      d.map(function (s, i) { return h('path', { key: i, d: s, strokeDasharray: p.name === 'tier-GREY' && i < 2 ? '2.6 2.6' : undefined }); }));
  }

  /* ---------- vocab shared with the backend contract (card/verdict schemas) ---------- */
  var TIERS = {
    GREEN: { word: 'Nominal' },
    YELLOW: { word: 'Watch' },
    RED: { word: 'Act now' },
    GREY: { word: 'No data' }
  };
  var ACTIONS = {
    NO_ACTION: { text: 'No action needed', icon: 'check', rank: 0 },
    RECHECK_IN_1H: { text: 'Recheck in 1 hour', icon: 'clock', rank: 1 },
    REST_AND_HYDRATE: { text: 'Rest and hydrate', icon: 'drop', rank: 2 },
    USE_PROTOCOL_CARD: { text: 'Open the protocol card', icon: 'card', rank: 3 },
    ALERT_CMO: { text: 'Alert the crew medical officer', icon: 'medic', rank: 4 },
    CONTACT_GROUND_URGENT: { text: 'Contact ground, urgent', icon: 'antenna', rank: 5 }
  };
  var SOURCES = {
    simulated: { kind: 'sim', text: 'SIMULATED' },
    nasa_osdr: { kind: 'real', text: 'REAL', ds: 'NASA OSDR' },
    nasa_radlab: { kind: 'real', text: 'REAL', ds: 'NASA RadLab' },
    nasa_donki: { kind: 'real', text: 'REAL', ds: 'NASA DONKI' },
    manual: { kind: 'manual', text: 'MANUAL ENTRY' }
  };
  function tierOf(t) { return TIERS[t] ? t : 'GREY'; }

  /* ---------- TierBadge ---------- */
  function TierBadge(p) {
    var t = tierOf(p.tier);
    return h('span', { className: cx('vt-tier', 'vt-tier--' + t, p.size === 'lg' && 'vt-tier--lg', p.pulse && 'vt-tier--pulse', p.className), role: 'status' },
      h(Icon, { name: 'tier-' + t, strokeWidth: 2.2 }),
      p.children || p.label || TIERS[t].word);
  }

  /* ---------- SourceLabel ---------- */
  function SourceLabel(p) {
    var s = SOURCES[p.source] || SOURCES.simulated;
    return h('span', { className: cx('vt-src', 'vt-src--' + s.kind, p.className), title: p.dataset || s.ds || s.text },
      s.text, (p.dataset || s.ds) ? h('b', null, '· ' + (p.dataset || s.ds)) : null);
  }

  /* ---------- Sparkline ---------- */
  function Sparkline(p) {
    var vals = (p.values || []).filter(function (v) { return typeof v === 'number' && isFinite(v); });
    var w = p.width || 160, ht = p.height || 36, pad = 3;
    var band = p.band;
    if (vals.length < 2) {
      return h('svg', { className: 'vt-spark', width: w, height: ht, role: 'img', 'aria-label': 'Not enough readings for a trend' },
        h('line', { x1: 0, x2: w, y1: ht / 2, y2: ht / 2, stroke: 'var(--line-strong)', strokeDasharray: '2 4' }));
    }
    var lo = Math.min.apply(null, vals.concat(band ? [band[0]] : []));
    var hi = Math.max.apply(null, vals.concat(band ? [band[1]] : []));
    if (hi === lo) { hi += 1; lo -= 1; }
    var X = function (i) { return pad + i * (w - pad * 2) / (vals.length - 1); };
    var Y = function (v) { return pad + (1 - (v - lo) / (hi - lo)) * (ht - pad * 2); };
    var d = vals.map(function (v, i) { return (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); }).join('');
    var last = vals[vals.length - 1];
    return h('svg', { className: 'vt-spark', width: w, height: ht, viewBox: '0 0 ' + w + ' ' + ht, role: 'img', 'aria-label': (p.label || 'Trend') + ', latest ' + last },
      band ? h('rect', { className: 'band', x: 0, width: w, y: Y(band[1]), height: Math.max(1, Y(band[0]) - Y(band[1])), rx: 2 }) : null,
      h('path', { className: cx('line', p.animate !== false && 'draw'), d: d }),
      h('circle', { className: 'dot dot--' + tierOf(p.tier), cx: X(vals.length - 1), cy: Y(last), r: 3.5 }));
  }

  /* ---------- VitalReadout ---------- */
  function VitalReadout(p) {
    var t = tierOf(p.tier);
    var noData = p.value === null || p.value === undefined || p.value === '';
    var interactive = !!p.onClick;
    return h('div', {
      className: cx('vt-vital', 'vt-vital--' + t, interactive && 'vt-vital--interactive', p.selected && 'vt-vital--selected', p.className),
      onClick: p.onClick, role: interactive ? 'button' : undefined, tabIndex: interactive ? 0 : undefined,
      'aria-pressed': interactive ? !!p.selected : undefined,
      onKeyDown: interactive ? function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); p.onClick(e); } } : undefined,
      style: p.width ? { width: p.width } : undefined
    },
      h('span', { className: 'vt-lbl' }, p.label),
      h(TierBadge, { tier: t, pulse: t === 'RED' }),
      h('div', { className: 'vt-vital__val' },
        h('span', { className: 'vt-vital__num' }, noData ? '--' : p.value),
        h('span', { className: 'vt-vital__unit' }, p.unit),
        p.delta ? h('span', { className: 'vt-vital__delta' }, p.delta) : null),
      p.trend ? h('div', { style: { gridColumn: '1 / -1' } }, h(Sparkline, { values: p.trend, band: p.band, tier: t, width: (p.width ? p.width - 34 : 200), height: 34, label: p.label })) : null,
      h('div', { className: 'vt-vital__foot' },
        p.source ? h(SourceLabel, { source: p.source, dataset: p.dataset }) : h('span'),
        h('span', null, p.updated || '')));
  }

  /* ---------- BodyMap ---------- */
  var SILHOUETTE =
    'M130 20c11.6 0 21 11.6 21 26s-9.4 26-21 26-21-11.6-21-26 9.4-26 21-26z' +
    'M121 70h18l2 14h-22z' +
    'M92 88q38-10 76 0l8 68q-6 40-14 66H98q-8-26-14-66z' +
    'M92 90q-18 4-22 32l-8 74q-2 18 4 30h10l4-24 10-62z' +
    'M168 90q18 4 22 32l8 74q2 18-4 30h-10l-4-24-10-62z' +
    'M100 222h28l-2 84-4 94h-18l-4-94z' +
    'M132 222h28l0 84-4 96h-18l-4-96z';
  /* EVA suit: parts are unioned for the fill/scan clip and stroked one by one, so segment seams show. Index 0 (life-support pack) sits behind. */
  var SUIT = {
    back: 0,
    parts: [
      'M84 70h92v118q0 8-8 8H92q-8 0-8-8z',
      'M100 44a30 30 0 1 0 60 0a30 30 0 1 0-60 0z',
      'M96 82q34-8 68 0l14 18-2 60q-4 30-10 54H94q-6-24-10-54l-2-60z',
      'M84 92q-20 4-24 32l-6 66q-2 14 2 22h18l4-16 10-56z',
      'M176 92q20 4 24 32l6 66q2 14-2 22h-18l-4-16-10-56z',
      'M52 222a12 12 0 1 0 24 0a12 12 0 1 0-24 0z',
      'M184 222a12 12 0 1 0 24 0a12 12 0 1 0-24 0z',
      'M96 214h32v86l-2 82h-26l-6-82z',
      'M132 214h32l2 86-6 82h-26l-2-82z',
      'M92 382h38v18q0 6-6 6h-26q-6 0-6-6z',
      'M130 382h38v18q0 6-6 6h-26q-6 0-6-6z'
    ],
    details: function () {
      var seams = ['M58 152q14 5 28 0', 'M55 206q10 4 21 0', 'M202 152q-14 5-28 0', 'M205 206q-10 4-21 0',
        'M94 205q36 9 72 0', 'M97 294q15 6 30 0', 'M97 303q15 6 30 0', 'M133 294q15 6 30 0', 'M133 303q15 6 30 0',
        'M98 372h28', 'M134 372h28'];
      return h('g', { className: 'suit' },
        h('rect', { className: 'seam', x: 104, y: 70, width: 52, height: 9, rx: 4 }),
        h('circle', { className: 'seam', cx: 92, cy: 97, r: 8 }),
        h('circle', { className: 'seam', cx: 168, cy: 97, r: 8 }),
        seams.map(function (d, i) { return h('path', { key: i, className: 'seam', d: d }); }),
        h('rect', { className: 'seam', x: 108, y: 142, width: 44, height: 20, rx: 3 }),
        [118, 126, 134].map(function (x) { return h('circle', { key: x, className: 'lamp', cx: x, cy: 152, r: 2 }); }),
        h('rect', { className: 'seam', x: 140, y: 147, width: 8, height: 10, rx: 1 }),
        h('ellipse', { className: 'visor', cx: 130, cy: 48, rx: 22, ry: 16 }),
        h('path', { className: 'visor-glint', d: 'M115 43q5-7 14-8' }),
        h('circle', { className: 'lamp', cx: 104, cy: 30, r: 3 }),
        h('circle', { className: 'lamp', cx: 156, cy: 30, r: 3 }));
    }
  };
  var ZONES = {
    neuro: { x: 130, y: 38, label: 'Neuro · sleep & mood' },
    resp: { x: 114, y: 114, label: 'Respiratory · CO₂' },
    cardio: { x: 142, y: 130, label: 'Cardio · HR & BP' },
    radiation: { x: 160, y: 98, label: 'Radiation dose' },
    metabolic: { x: 124, y: 178, label: 'Metabolic · glucose' },
    thermal: { x: 68, y: 214, label: 'Thermal · skin temp' },
    msk: { x: 114, y: 330, label: 'Musculoskeletal' }
  };
  var GLYPH = {
    GREEN: 'M-3 0.3l2 2 4-4.4',
    YELLOW: 'M0 -3v3.3M0 2.8v.2',
    RED: 'M-2.4 -2.4l4.8 4.8M2.4 -2.4l-4.8 4.8',
    GREY: 'M0 2.8v.2M-1.6 -1.6a1.7 1.7 0 1 1 2.2 1.6c-.5.2-.6.5-.6 1'
  };

  function BodyMap(p) {
    var st = R.useState(p.defaultSelected || null);
    var selected = p.selected !== undefined ? p.selected : st[0];
    var uid = R.useState(function () { return 'vtb' + Math.random().toString(36).slice(2, 8); })[0];
    var suit = p.figure !== 'body';
    var fig = suit ? SUIT : { parts: [SILHOUETTE] };
    var zones = (p.zones || []).map(function (z) {
      var base = ZONES[z.id] || {};
      return Object.assign({}, base, z, { x: z.x != null ? z.x : base.x, y: z.y != null ? z.y : base.y, label: z.label || base.label || z.id });
    }).filter(function (z) { return z.x != null; });
    function pick(id) {
      var next = id === selected ? null : id;
      if (p.selected === undefined) st[1](next);
      if (p.onSelect) p.onSelect(next);
    }
    var lines = [];
    for (var y = 18; y < 412; y += 7) lines.push(h('line', { key: y, className: 'contour', x1: 40, x2: 220, y1: y, y2: y }));
    var ticks = [];
    for (var k = 0; k <= 30; k++) {
      var ty = 20 + k * 13, major = k % 5 === 0;
      ticks.push(h('line', { key: 't' + k, x1: 14, x2: major ? 26 : 21, y1: ty, y2: ty, stroke: 'var(--line-strong)', strokeWidth: 1 }));
      if (major) ticks.push(h('text', { key: 'l' + k, x: 30, y: ty + 3, className: 'call-sub', style: { fontSize: '8px' } }, (k * 6).toString().padStart(3, '0')));
    }
    var sel = zones.filter(function (z) { return z.id === selected; })[0];
    var callout = null;
    if (sel) {
      var by = clamp(sel.y - 34, 6, 362), mid = by + 34, t = tierOf(sel.tier);
      callout = h('g', { key: sel.id },
        h('path', { className: 'leader call-draw', d: 'M' + sel.x + ' ' + sel.y + 'L236 ' + mid + 'H262' }),
        h('circle', { className: 'leader-dot', cx: 262, cy: mid, r: 2.5 }),
        h('g', { className: 'call-in' },
          h('rect', { className: 'call-box', x: 268, y: by, width: 150, height: 68, rx: 6 }),
          h('line', { className: 'call-tick tick--' + t, x1: 269.5, x2: 269.5, y1: by + 10, y2: by + 58 }),
          h('text', { className: 'call-lbl', x: 280, y: by + 18 }, (sel.label || '').toUpperCase()),
          h('text', { className: 'call-val', x: 280, y: by + 44 }, sel.value != null ? String(sel.value) : '--',
            sel.unit ? h('tspan', { className: 'call-sub', dx: 5 }, sel.unit) : null),
          h('text', { className: 'call-sub', x: 280, y: by + 59 }, TIERS[t].word.toUpperCase() + (sel.sub ? ' · ' + sel.sub : ''))));
    }
    return h('div', { className: cx('vt-body', p.animate !== false && 'vt-body--alive', p.className), style: p.style },
      h('svg', { viewBox: '0 0 420 440', role: 'group', 'aria-label': p.ariaLabel || 'Crew member body map. Choose a zone to see its vitals.' },
        h('defs', null, h('clipPath', { id: uid + 'c' }, fig.parts.map(function (d, i) { return h('path', { key: i, d: d }); }))),
        h('g', null, ticks),
        h('g', { className: 'orbits' },
          h('ellipse', { className: 'orbit', cx: 130, cy: 418, rx: 78, ry: 11 }),
          h('ellipse', { className: 'orbit orbit--holo orbit-spin', cx: 130, cy: 418, rx: 104, ry: 16 })),
        h('g', { className: 'rig' },
          h('g', { clipPath: 'url(#' + uid + 'c)' },
            h('rect', { className: 'skin-fill', x: 20, y: 0, width: 240, height: 420 }),
            lines,
            h('rect', { className: 'scanbar', x: 40, y: 14, width: 180, height: 2 })),
          fig.parts.map(function (d, i) { return h('path', { key: 'p' + i, className: cx('shell', fig.back === i && 'shell--back'), d: d }); }),
          fig.details ? fig.details() : null,
          h('g', { className: 'organs' },
            suit ? null : h('ellipse', { className: 'organ', cx: 130, cy: 42, rx: 13, ry: 13 }),
            h('ellipse', { className: 'organ', cx: 114, cy: 122, rx: 11, ry: 21 }),
            h('ellipse', { className: 'organ', cx: 146, cy: 122, rx: 11, ry: 21 }),
            h('path', { className: 'organ', d: 'M138 124c-4-5 2-10 5-6 3-4 9 1 5 6l-5 6z' }),
            h('path', { className: 'organ', d: 'M130 92V220' }),
            h('path', { className: 'organ', d: 'M114 166q16-8 30 2q-2 16-16 16q-14-2-14-18z' })),
          zones.map(function (z) {
            var t = tierOf(z.tier), on = z.id === selected;
            return h('g', {
              key: z.id, className: cx('vt-hot', 'vt-hot--' + t, on && 'vt-hot--sel'), transform: 'translate(' + z.x + ' ' + z.y + ')',
              role: 'button', tabIndex: 0, 'aria-pressed': on,
              'aria-label': z.label + ': ' + (z.value != null ? z.value + ' ' + (z.unit || '') : 'no reading') + ', ' + TIERS[t].word,
              onClick: function () { pick(z.id); },
              onKeyDown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(z.id); } }
            },
              h('circle', { className: 'hit', r: 18 }),
              h('circle', { className: 'ring', r: 9 }),
              on ? h('circle', { className: 'sel', r: 13 }) : null,
              h('circle', { className: 'core', r: 7 }),
              h('path', { className: 'glyph', d: GLYPH[t] }));
          }),
          callout)));
  }

  /* ---------- DoseGauge ---------- */
  function polar(cx0, cy0, r, deg) { var a = deg * Math.PI / 180; return [cx0 + r * Math.cos(a), cy0 + r * Math.sin(a)]; }
  function DoseGauge(p) {
    var limit = p.limit || 50, max = p.max || limit * 1.2, v = Math.max(0, p.value || 0);
    var frac = clamp(v / max, 0, 1), lf = clamp(limit / max, 0, 1);
    var t = p.tier || (v / limit < 0.5 ? 'GREEN' : v / limit < 0.8 ? 'YELLOW' : 'RED');
    var C = [110, 100], r = 80, a0 = 135, sweep = 270, L = r * sweep * Math.PI / 180;
    var s = polar(C[0], C[1], r, a0), e = polar(C[0], C[1], r, a0 + sweep);
    var arc = 'M' + s[0] + ' ' + s[1] + 'A' + r + ' ' + r + ' 0 1 1 ' + e[0] + ' ' + e[1];
    var ticks = [];
    for (var i = 0; i <= 20; i++) {
      var ang = a0 + sweep * i / 20, major = i % 5 === 0;
      var p1 = polar(C[0], C[1], r - 10, ang), p2 = polar(C[0], C[1], r - (major ? 18 : 14), ang);
      ticks.push(h('line', { key: i, className: major ? 'major' : null, x1: p1[0], y1: p1[1], x2: p2[0], y2: p2[1] }));
    }
    var la = a0 + sweep * lf, l1 = polar(C[0], C[1], r - 8, la), l2 = polar(C[0], C[1], r + 9, la);
    return h('div', { className: cx('vt-dose', p.className) },
      h('svg', { viewBox: '0 0 220 190', role: 'img', 'aria-label': 'Mission dose ' + v + ' of ' + limit + ' millisievert limit, ' + TIERS[tierOf(t)].word },
        h('path', { className: 'track', d: arc }),
        h('g', { className: 'ticks' }, ticks),
        h('path', { className: 'fill fill--' + tierOf(t), d: arc, strokeDasharray: L, strokeDashoffset: L * (1 - frac) }),
        h('line', { className: 'limit', x1: l1[0], y1: l1[1], x2: l2[0], y2: l2[1] }),
        h('text', { className: 'v', x: 110, y: 104 }, v.toFixed(v < 10 ? 2 : 1)),
        h('text', { className: 'u', x: 110, y: 122 }, 'mSv of ' + limit + ' limit'),
        p.rate != null ? h('text', { className: 'rate', x: 110, y: 178 }, p.rate + ' µSv/h') : null),
      h(TierBadge, { tier: t }),
      p.event ? h('span', { className: 'vt-dose__event' }, h(Icon, { name: 'flare' }), p.event) : null);
  }

  /* ---------- DelayDial ---------- */
  function fmtDur(s) {
    if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + ' s';
    if (s < 3600) { var m = Math.floor(s / 60), r = Math.round(s % 60); return m + ' min' + (r ? ' ' + r + ' s' : ''); }
    return (s / 3600).toFixed(1) + ' h';
  }
  function DelayDial(p) {
    var ow = Math.max(0, p.oneWaySeconds || 0), lost = !!p.blackout;
    var dur = clamp(1.2 + Math.log10(1 + ow) * 1.4, 1.2, 6).toFixed(2) + 's';
    var path = 'M30 92Q150 -4 270 92';
    var answer = fmtDur(ow * 2 + (p.groundTurnaroundSeconds || 0));
    return h('div', { className: cx('vt-delay', lost && 'vt-delay--lost', p.className) },
      h('svg', { viewBox: '0 0 300 120', role: 'img', 'aria-label': lost ? 'No link to Earth' : 'One-way delay to Earth ' + fmtDur(ow) },
        h('path', { className: 'path', d: path, id: undefined }),
        h('rect', { className: 'ship', x: 22, y: 84, width: 16, height: 16, rx: 2, transform: 'rotate(45 30 92)' }),
        h('circle', { className: 'earth', cx: 270, cy: 92, r: 11 }),
        h('circle', { className: 'earth-core', cx: 270, cy: 92, r: 5 }),
        h('text', { className: 'end', x: 30, y: 116, textAnchor: 'middle' }, p.vehicle || 'Vehicle'),
        h('text', { className: 'end', x: 270, y: 116, textAnchor: 'middle' }, 'Earth'),
        lost ? null : h(F, null,
          h('circle', { className: 'packet', r: 3.5 }, h('animateMotion', { dur: dur, repeatCount: 'indefinite', path: path })),
          h('circle', { className: 'packet packet--down', r: 3 }, h('animateMotion', { dur: dur, begin: (parseFloat(dur) / 2) + 's', repeatCount: 'indefinite', path: path, keyPoints: '1;0', keyTimes: '0;1', calcMode: 'linear' }))),
        h('text', { className: 'big', x: 150, y: 62 }, lost ? 'NO LINK' : fmtDur(ow)),
        h('text', { className: 'small', x: 150, y: 78 }, lost ? 'LOSS OF SIGNAL' : 'ONE-WAY · ' + fmtDur(ow * 2) + ' ROUND TRIP')),
      h('p', { className: 'vt-delay__note' }, lost
        ? h(F, null, h('strong', null, 'Onboard only.'), ' The Checker decides; ground confirms after reacquisition.')
        : h(F, null, 'Earth can answer in ', h('strong', null, '~' + answer), '. Act on the onboard verdict.')));
  }

  /* ---------- DecisionCard ---------- */
  function DecisionCard(p) {
    var t = tierOf(p.tier), act = ACTIONS[p.action] || ACTIONS.NO_ACTION;
    var prop = p.proposal && ACTIONS[p.proposal.action];
    var raised = prop && prop.rank < act.rank;
    return h('article', { className: cx('vt-card', 'vt-card--' + t, p.className) },
      h('div', { className: 'vt-card__top' },
        h(TierBadge, { tier: t, size: 'lg', pulse: t === 'RED' }),
        (p.simulated ? h(SourceLabel, { source: 'simulated' }) : p.source ? h(SourceLabel, { source: p.source }) : null),
        p.ts ? h('span', { className: 'vt-card__ts' }, p.ts) : null),
      h('h3', { className: 'vt-card__head' }, p.headline),
      h('div', { className: 'vt-card__action' }, h(Icon, { name: act.icon }), h('div', null,
        h('div', { className: 'vt-lbl' }, 'Do this'), h('strong', null, act.text))),
      prop ? h('div', { className: 'vt-chain', 'aria-label': 'How this decision was made' },
        h('div', { className: 'vt-chain__step' }, h('span', { className: 'vt-lbl' }, p.proposal.by || 'LLM advisor'),
          h('span', { className: 'vt-chain__what' }, raised ? h('s', null, prop.text) : prop.text)),
        h('span', { className: 'vt-chain__arrow', 'aria-hidden': true }, '→'),
        h('div', { className: 'vt-chain__step vt-chain__step--final' }, h('span', { className: 'vt-lbl' }, raised ? 'Checker raised to' : 'Checker confirmed'),
          h('span', { className: 'vt-chain__what' }, act.text))) : null,
      p.reasons && p.reasons.length ? h('ul', { className: 'vt-card__reasons' }, p.reasons.map(function (r, i) { return h('li', { key: i }, r); })) : null,
      p.children ? h('div', { style: { display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' } }, p.children) : null,
      (p.provenance && p.provenance.length) || p.checkerVersion ? h('footer', { className: 'vt-card__prov' },
        (p.provenance || []).map(function (q, i) { return h('span', { key: i }, q.dataset_id + ':' + q.field + (q.timestamp ? ' @' + q.timestamp : '')); }),
        p.checkerVersion ? h('span', { style: { marginLeft: 'auto' } }, 'checker ' + p.checkerVersion + (p.rulesetHash ? ' · ' + p.rulesetHash.slice(0, 8) : '')) : null) : null);
  }

  /* ---------- Advisory ---------- */
  var STAMP = {
    checked: { icon: 'shield', text: 'Checker confirmed' },
    escalated: { icon: 'tier-YELLOW', text: 'Checker escalated' },
    blocked: { icon: 'tier-RED', text: 'Checker blocked' },
    pending: { icon: 'clock', text: 'Awaiting Checker' }
  };
  function Advisory(p) {
    var text = p.text || '';
    var n = R.useState(p.stream ? 0 : text.length);
    R.useEffect(function () {
      if (!p.stream) { n[1](text.length); return; }
      n[1](0);
      var i = 0, id = setInterval(function () { i += 2; n[1](Math.min(i, text.length)); if (i >= text.length) clearInterval(id); }, 24);
      return function () { clearInterval(id); };
    }, [text, p.stream]);
    var done = n[0] >= text.length, status = STAMP[p.status] ? p.status : 'pending', s = STAMP[status];
    return h('div', { className: cx('vt-adv', status === 'blocked' && 'vt-adv--blocked', p.className), 'aria-live': 'polite' },
      h('svg', { className: 'vt-adv__orb', viewBox: '0 0 26 26', 'aria-hidden': true },
        h('circle', { cx: 13, cy: 13, r: 12, strokeWidth: 1 }), h('circle', { className: 'o2', cx: 13, cy: 13, r: 8, strokeWidth: 1.5 }), h('circle', { className: 'o3', cx: 13, cy: 13, r: 3 })),
      h('div', { className: 'vt-adv__head' }, h('span', { className: 'vt-lbl' }, p.author || 'LLM advisor'), p.model ? h('span', { className: 'vt-panel__meta' }, p.model) : null),
      h('p', { className: 'vt-adv__text' }, text.slice(0, n[0]), done ? null : h('span', { className: 'vt-adv__caret', 'aria-hidden': true })),
      done ? h('span', { className: 'vt-adv__stamp vt-adv__stamp--' + status }, h(Icon, { name: s.icon }), s.text.toUpperCase() + (p.verdictNote ? ' · ' + p.verdictNote : '')) : null);
  }

  /* ---------- CrewSwitcher ---------- */
  function CrewSwitcher(p) {
    return h('div', { className: cx('vt-crew', p.className), role: 'group', 'aria-label': p.ariaLabel || 'Crew' },
      (p.crew || []).map(function (c) {
        var t = tierOf(c.tier), on = c.id === p.value;
        var ini = c.initials || c.name.split(/\s+/).map(function (w) { return w[0]; }).join('').slice(0, 2).toUpperCase();
        return h('button', { key: c.id, type: 'button', 'aria-pressed': on, onClick: function () { p.onChange && p.onChange(c.id); }, 'aria-label': c.name + ', ' + TIERS[t].word },
          h('span', { className: 'vt-crew__av t-' + t }, ini, h(Icon, { name: 'tier-' + t, strokeWidth: 2.4 })),
          h('span', { className: 'vt-crew__name' }, c.name),
          h('span', { className: 'vt-crew__role' }, c.role || ''));
      }));
  }

  /* ---------- SegmentedControl ---------- */
  function SegmentedControl(p) {
    var opts = p.options || [];
    var st = R.useState(p.defaultValue || (opts[0] && opts[0].value));
    var val = p.value !== undefined ? p.value : st[0];
    var idx = Math.max(0, opts.findIndex(function (o) { return o.value === val; }));
    function set(v) { if (p.value === undefined) st[1](v); if (p.onChange) p.onChange(v); }
    function key(e) {
      var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return; e.preventDefault();
      var n = (idx + d + opts.length) % opts.length; set(opts[n].value);
      var b = e.currentTarget.querySelectorAll('button')[n]; if (b) b.focus();
    }
    return h('div', { className: cx('vt-seg', p.className), role: 'radiogroup', 'aria-label': p.ariaLabel || 'View', onKeyDown: key },
      h('span', { className: 'vt-seg__thumb', 'aria-hidden': true, style: { width: 'calc((100% - 8px) / ' + opts.length + ')', transform: 'translateX(' + idx * 100 + '%)' } }),
      opts.map(function (o, i) {
        return h('button', { key: o.value, type: 'button', role: 'radio', 'aria-checked': i === idx, tabIndex: i === idx ? 0 : -1, onClick: function () { set(o.value); } },
          o.icon ? h(Icon, { name: o.icon }) : null, o.label);
      }));
  }

  /* ---------- Button ---------- */
  function Button(p) {
    var rest = Object.assign({}, p);
    ['variant', 'size', 'icon', 'children', 'className'].forEach(function (k) { delete rest[k]; });
    return h('button', Object.assign({ type: 'button' }, rest, { className: cx('vt-btn', 'vt-btn--' + (p.variant || 'secondary'), p.size === 'sm' && 'vt-btn--sm', p.className) }),
      p.icon ? h(Icon, { name: p.icon }) : null, p.children);
  }

  /* ---------- Panel ---------- */
  function Panel(p) {
    return h('section', { className: cx('vt-panel', p.roomy && 'vt-panel--roomy', p.plain && 'vt-panel--plain', p.className), style: p.style, 'aria-label': typeof p.title === 'string' ? p.title : undefined },
      p.scan ? h('span', { className: 'vt-panel__scan', 'aria-hidden': true }) : null,
      (p.title || p.meta) ? h('header', { className: 'vt-panel__head' },
        h('span', { className: 'vt-panel__title vt-lbl' }, p.title),
        p.meta ? h('span', { className: 'vt-panel__meta' }, p.meta) : null) : null,
      p.children);
  }

  window.Vitalis = {
    BodyMap: BodyMap, VitalReadout: VitalReadout, Sparkline: Sparkline, DoseGauge: DoseGauge,
    DecisionCard: DecisionCard, Advisory: Advisory, TierBadge: TierBadge, SourceLabel: SourceLabel,
    DelayDial: DelayDial, CrewSwitcher: CrewSwitcher, SegmentedControl: SegmentedControl, Button: Button, Panel: Panel,
    Icon: Icon, TIERS: TIERS, ACTIONS: ACTIONS, ZONES: ZONES
  };
})();
