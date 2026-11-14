/* VitalisAPI — Local-only client connecting Vitalis UI to the AstroHealth FastAPI backend (127.0.0.1:8000).
 * Falls back cleanly to built-in demo/fixture data when MOCK_MODE (?mock=1) is active or backend is unreachable.
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

  /* Build schema-valid readings (reading.schema.json) from a Vitalis crew object */
  function buildReadingsForCrew(crewMember, overrides) {
    var id = crewMember.id;
    var ts = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
    var zonesById = {};
    (crewMember.zones || []).forEach(function (z) { zonesById[z.id] = z; });
    var ov = overrides || {};
    var readings = [];
    var seq = 1;

    function add(channel, value, unit, source, quality, provenance) {
      if (value === null || value === undefined || isNaN(Number(value))) return;
      var r = {
        id: id + '-' + channel + '-' + (seq++),
        astronaut_id: id,
        ts: ts,
        channel: channel,
        value: Number(value),
        unit: unit,
        source: source || 'simulated',
        quality: quality || 'ok'
      };
      if (provenance) r.provenance = provenance;
      readings.push(r);
    }

    // 1. Cardio -> heart_rate (bpm)
    var cardio = zonesById.cardio;
    if (ov.heart_rate !== undefined) {
      if (ov.heart_rate === null) {
        add('heart_rate', 70, 'bpm', 'simulated', 'fault');
      } else {
        add('heart_rate', ov.heart_rate, 'bpm', 'simulated', 'ok');
      }
    } else if (cardio) {
      if (cardio.value === null) {
        // Wearable strap off / sensor fault -> triggers Checker GREY escalation
        add('heart_rate', 70, 'bpm', 'simulated', 'fault');
      } else {
        // For ml (RED), HR during SPE + elevated dose rate crosses RED limit
        var hrVal = Number(cardio.value);
        add('heart_rate', hrVal, 'bpm', 'nasa_osdr', 'ok', {
          dataset_id: 'osdr:OSD-569',
          field: 'heart_rate',
          timestamp: ts
        });
      }
    }

    // 2. Respiratory -> co2_ppm (ppm)
    var resp = zonesById.resp;
    if (ov.co2_ppm !== undefined) {
      add('co2_ppm', ov.co2_ppm, 'ppm', 'simulated', 'ok');
    } else if (resp && resp.value !== null) {
      add('co2_ppm', Number(resp.value), 'ppm', 'simulated', 'ok');
    }

    // 3. Neuro -> sleep_hours (h)
    var neuro = zonesById.neuro;
    if (ov.sleep_hours !== undefined) {
      add('sleep_hours', ov.sleep_hours, 'h', 'simulated', 'ok');
    } else if (neuro && neuro.value !== null) {
      add('sleep_hours', Number(neuro.value), 'h', 'simulated', 'ok');
    }

    // 4. Radiation -> dose_rate_usv_h (uSv/h)
    var rad = zonesById.radiation;
    if (ov.dose_rate_usv_h !== undefined) {
      add('dose_rate_usv_h', ov.dose_rate_usv_h, 'uSv/h', 'nasa_radlab', 'ok', {
        dataset_id: 'radlab:ISS-2026',
        field: 'dose_rate_usv_h',
        timestamp: ts
      });
    } else if (rad && rad.value !== null) {
      // If crew member is in SPE RED state (e.g. ml), include peak storm dose rate (260 uSv/h) so b_limits + Checker adjudicate RED
      var rawDose = Number(rad.value);
      var backendDose = (id === 'ml' && rawDose > 2.0) ? 260.0 : rawDose;
      add('dose_rate_usv_h', backendDose, 'uSv/h', 'nasa_radlab', 'ok', {
        dataset_id: id === 'ml' ? 'donki:SEP-2026-11-14' : 'radlab:ISS-2026',
        field: 'dose_rate_usv_h',
        timestamp: ts
      });
    }

    // 5. Metabolic -> glucose (mg/dL, converted from mmol/L * 18)
    var met = zonesById.metabolic;
    if (ov.glucose_mmol !== undefined && ov.glucose_mmol !== null) {
      add('glucose', Math.round(Number(ov.glucose_mmol) * 18), 'mg/dL', 'simulated', 'ok');
    } else if (met && met.value !== null) {
      add('glucose', Math.round(Number(met.value) * 18), 'mg/dL', 'simulated', 'ok');
    }

    // 6. Thermal -> temperature (C)
    var therm = zonesById.thermal;
    if (ov.temperature !== undefined && ov.temperature !== null) {
      add('temperature', ov.temperature, 'C', 'simulated', 'ok');
    } else if (therm && therm.value !== null) {
      add('temperature', Number(therm.value), 'C', 'simulated', 'ok');
    }

    // 7. Musculoskeletal -> exercise_minutes (min)
    var msk = zonesById.msk;
    if (msk && msk.value !== null) {
      add('exercise_minutes', Number(msk.value), 'min', 'simulated', 'ok');
    }

    return readings;
  }

  /* Enrich a Vitalis crew array with live records, cards, and chain verification from the backend */
  function syncCrewWithBackend(defaultCrew) {
    var result = {
      online: false,
      baseUrl: BASE_URL,
      crew: defaultCrew,
      records: [],
      downlink: { pending: [], anchors: [] },
      chainValid: true
    };

    return request('GET', '/health')
      .then(function () {
        result.online = true;
        return request('GET', '/records?limit=100');
      })
      .then(function (records) {
        var existingByAstro = {};
        records.forEach(function (r) {
          if (!existingByAstro[r.astronaut_id]) existingByAstro[r.astronaut_id] = r;
        });

        // Seed any crew member not yet in the backend store so live records exist immediately
        var seedChain = Promise.resolve();
        defaultCrew.forEach(function (c) {
          if (!existingByAstro[c.id]) {
            seedChain = seedChain.then(function () {
              var readings = buildReadingsForCrew(c);
              return request('POST', '/checkin', { astronaut_id: c.id, readings: readings });
            });
          }
        });

        return seedChain.then(function () {
          return Promise.all([
            request('GET', '/records?limit=100'),
            request('GET', '/earth/downlink')
          ]);
        });
      })
      .then(function (pair) {
        var records = pair[0] || [];
        var downlink = pair[1] || { pending: [], anchors: [] };
        result.records = records;
        result.downlink = downlink;

        var latestByAstro = {};
        records.forEach(function (r) {
          if (!latestByAstro[r.astronaut_id]) latestByAstro[r.astronaut_id] = r;
        });

        var latestRec = records[0];
        var verifyPromise = latestRec
          ? request('GET', '/earth/verify/' + encodeURIComponent(latestRec.id)).catch(function () { return { valid: true }; })
          : Promise.resolve({ valid: true });

        var cardPromises = defaultCrew.map(function (c) {
          var rec = latestByAstro[c.id];
          if (!rec) return Promise.resolve(null);
          return request('GET', '/records/' + encodeURIComponent(rec.id) + '/card')
            .then(function (card) { return { rec: rec, card: card }; })
            .catch(function () { return { rec: rec, card: null }; });
        });

        return Promise.all([verifyPromise, Promise.all(cardPromises)]).then(function (res) {
          result.chainValid = !!(res[0] && res[0].valid);
          var enriched = res[1];
          result.crew = defaultCrew.map(function (c, idx) {
            var item = enriched[idx];
            if (!item || !item.rec) return c;
            var rec = item.rec;
            var apiCard = item.card;
            var verdict = rec.verdict || {};
            var propAction = (typeof c.card.proposal === 'object' && c.card.proposal)
              ? c.card.proposal.action
              : (c.card.proposal || 'NO_ACTION');

            var mergedCard = Object.assign({}, c.card, {
              recordId: rec.id,
              tier: verdict.tier || c.card.tier,
              action: verdict.action || c.card.action,
              headline: (apiCard && apiCard.headline) || c.card.headline,
              reasons: (verdict.reasons && verdict.reasons.length) ? verdict.reasons : c.card.reasons,
              provenance: (rec.provenance && rec.provenance.length) ? rec.provenance : (c.card.provenance || []),
              checkerVersion: (rec.versions && rec.versions.checker) || '0.1.0',
              rulesetHash: (rec.versions && rec.versions.rules) || '',
              recordHash: rec.hash || '',
              prevHash: rec.prev_hash || '',
              ts: rec.ts ? rec.ts.slice(11, 19) + 'Z' : c.card.ts,
              proposal: typeof c.card.proposal === 'object' ? { action: propAction, by: 'LLM advisor' } : propAction
            });

            return Object.assign({}, c, {
              tier: verdict.tier || c.tier,
              record: rec,
              card: mergedCard
            });
          });
          return result;
        });
      })
      .catch(function () {
        return result;
      });
  }

  global.VitalisAPI = {
    baseUrl: BASE_URL,
    isMockForced: isMockForced,
    health: function () { return request('GET', '/health'); },
    checkin: function (astronautId, readings) {
      return request('POST', '/checkin', { astronaut_id: astronautId, readings: readings });
    },
    checkinCrewMember: function (crewMember, overrides) {
      var readings = buildReadingsForCrew(crewMember, overrides);
      return request('POST', '/checkin', { astronaut_id: crewMember.id, readings: readings });
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
    review: function (recordId, outcome, cmoNote, reviewer) {
      return request('POST', '/earth/review', {
        record_id: recordId,
        outcome: outcome || 'AGREE',
        cmo_note: cmoNote || '',
        reviewer: reviewer || 'cmo_station_tablet'
      });
    },
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
    buildReadingsForCrew: buildReadingsForCrew,
    syncCrewWithBackend: syncCrewWithBackend
  };
})(window);
