/* OrbitalPulseAPI — Local-only client connecting OrbitalPulse UI to the OrbitalPulse FastAPI backend.
 * Every value shown in a view comes from this client's live responses. There is no
 * demo or fixture fallback: when the backend is unreachable, requests reject and the
 * views show their explicit no-link state (with ?mock=1 every request rejects, so a
 * view's no-link state can be checked without stopping the backend).
 */
(function (global) {
  'use strict';

  var LOOPBACK_HOSTS = { '127.0.0.1': true, 'localhost': true, '::1': true, '[::1]': true };

  function resolveBaseUrl() {
    var params = new URLSearchParams(global.location ? global.location.search : '');
    var override = params.get('api');
    if (override) {
      try {
        var u = new URL(override);
        if (!LOOPBACK_HOSTS[u.hostname]) {
          throw new Error('Local-only policy violation: non-loopback API host ' + u.hostname);
        }
        return u.origin;
      } catch (e) {
        console.warn(e.message);
      }
    }
    if (global.location && LOOPBACK_HOSTS[global.location.hostname] && global.location.port === '8000') {
      return global.location.origin;
    }
    // Served by the backend itself (it mounts this UI at /ui): talk to that same
    // server. This is what lets another machine on the local network use the UI
    // when the backend is started with --host 0.0.0.0; the page never calls any
    // host other than the one it was loaded from.
    if (global.location && /^https?:$/.test(global.location.protocol) &&
        global.location.pathname.indexOf('/ui/') === 0) {
      return global.location.origin;
    }
    return 'http://127.0.0.1:8000';
  }

  function isMockForced() {
    var params = new URLSearchParams(global.location ? global.location.search : '');
    return params.get('mock') === '1' || params.get('MOCK_MODE') === '1';
  }

  var BASE_URL = resolveBaseUrl();

  function request(method, path, body) {
    if (isMockForced()) {
      return Promise.reject(new Error('MOCK_MODE=1'));
    }
    var opts = {
      method: method,
      headers: { 'Accept': 'application/json' }
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(BASE_URL + path, opts).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (txt) {
          throw new Error('HTTP ' + resp.status + ': ' + txt);
        });
      }
      return resp.json();
    });
  }

  global.OrbitalPulseAPI = {
    baseUrl: BASE_URL,
    isMockForced: isMockForced,
    health: function () { return request('GET', '/health'); },
    checkin: function (astronautId, readings) {
      return request('POST', '/checkin', { astronaut_id: astronautId, readings: readings });
    },
    status: function (astronautId) {
      return request('GET', '/status/' + encodeURIComponent(astronautId));
    },
    records: function (astronautId, limit) {
      var q = [];
      if (astronautId) q.push('astronaut_id=' + encodeURIComponent(astronautId));
      if (limit) q.push('limit=' + encodeURIComponent(limit));
      return request('GET', '/records' + (q.length ? '?' + q.join('&') : ''));
    },
    record: function (recordId) {
      return request('GET', '/records/' + encodeURIComponent(recordId));
    },
    card: function (recordId) {
      return request('GET', '/records/' + encodeURIComponent(recordId) + '/card');
    },
    verify: function (recordId) {
      return request('GET', '/earth/verify/' + encodeURIComponent(recordId));
    },
    replay: function (recordId, rulesOverride) {
      return request('POST', '/earth/replay', { record_id: recordId, rules_override: rulesOverride || null });
    },
    review: function (recordId, outcome, cmoNote, reviewer, confirmedTier) {
      // confirmedTier: the tier the control centre says it should have been.
      // Feeds the onboard advisor's lesson ledger; never changes the record.
      return request('POST', '/earth/review', {
        record_id: recordId,
        outcome: outcome || 'AGREE',
        cmo_note: cmoNote || '',
        reviewer: reviewer || 'cmo_station_tablet',
        confirmed_tier: confirmedTier || null
      });
    },
    llmFeedback: function () { return request('GET', '/earth/llm-feedback'); },
    llmNasaExamples: function () { return request('POST', '/earth/llm-feedback/nasa-examples'); },
    rulechange: function (rulesOverride, astronautId) {
      return request('POST', '/earth/rulechange', {
        rules_override: rulesOverride || {},
        astronaut_id: astronautId || null
      });
    },
    downlink: function () {
      return request('GET', '/earth/downlink');
    },
    releaseDownlink: function (oneWayDelayS, flush) {
      return request('POST', '/earth/downlink/release', {
        one_way_delay_s: oneWayDelayS != null ? oneWayDelayS : 1.3,
        flush: !!flush
      });
    },
    ack: function (recordId, acknowledgedBy, note) {
      return request('POST', '/records/' + encodeURIComponent(recordId) + '/ack', {
        acknowledged_by: acknowledgedBy,
        note: note || ''
      });
    },
    handoff: function (recordId) {
      return request('GET', '/records/' + encodeURIComponent(recordId) + '/handoff');
    },
    link: function () { return request('GET', '/link'); },
    earthHandoffs: function () { return request('GET', '/earth/handoffs'); },
    setLink: function (preset, oneWayDelayS, label) {
      return request('POST', '/link', { preset: preset || null, one_way_delay_s: oneWayDelayS == null ? null : oneWayDelayS, label: label || null });
    },
    acks: function (recordId) {
      return request('GET', '/records/' + encodeURIComponent(recordId) + '/acks');
    },
    trust: function (recordId) {
      return request('GET', '/records/' + encodeURIComponent(recordId) + '/trust');
    },
    reviews: function () {
      return request('GET', '/earth/reviews');
    },
    governanceChecks: function () {
      return request('GET', '/earth/governance-checks');
    },
    nasaSources: function () { return request('GET', '/nasa/sources'); },
    spaceWeather: function () { return request('GET', '/nasa/space-weather'); },
    radiation: function (hourly) { return request('GET', '/nasa/radiation' + (hourly === false ? '?hourly=false' : '')); },
    bloodPanels: function (subject) {
      return request('GET', '/nasa/blood-panels' + (subject ? '?subject=' + encodeURIComponent(subject) : ''));
    },
    baselines: function () { return request('GET', '/nasa/baselines'); },
    anchor: function () {
      return request('GET', '/earth/anchor');
    },
    verifyAnchor: function (checkpoint) {
      return request('POST', '/earth/anchor/verify', checkpoint);
    }
  };
})(window);
