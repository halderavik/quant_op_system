<script>
/* Quant OS live quality tracker. Sends behaviour, open-end text, page timing,
   grid answers, and a final check to the bot-detection API. It never blocks the survey.
   The API keeps only these event types: keystroke, mouse_move, mouse_click,
   mouse_drag, scroll, focus, blur, page_load, form_submit. Page time and grid
   answers travel in the element_id of form_submit events (qos-page:, qos-grid:).
   Decipher templates read dollar signs and lines that start with an at sign,
   so this script uses neither. */
(function () {
  var API = "__QOS_API__";
  var SURVEY = "__QOS_SURVEY__";
  var TOKEN = "__QOS_TOKEN__";
  /* Project rules: terminate (bool) and signals (decisive bot signals that end the survey). */
  var RULES = __QOS_RULES__;
  var PLATFORM = "decipher";
  var KEY = "qos_lq_" + SURVEY;
  var MIN_TEXT = 2;
  var pageStart = Date.now();
  var buffer = [];
  var sessionPromise = null;
  var finishing = null;
  var finished = false;

  function storage() {
    try { return window.sessionStorage; } catch (e) { return null; }
  }

  function loadState() {
    var raw = null;
    var s = storage();
    if (s) { try { raw = s.getItem(KEY); } catch (e) { raw = null; } }
    if (!raw && typeof window.name === "string" && window.name.indexOf(KEY + "=") === 0) {
      raw = window.name.slice(KEY.length + 1);
    }
    try { return raw ? JSON.parse(raw) : {}; } catch (e) { return {}; }
  }

  function saveState(state) {
    var raw = JSON.stringify(state);
    var s = storage();
    if (s) { try { s.setItem(KEY, raw); } catch (e) {} }
    try { window.name = KEY + "=" + raw; } catch (e) {}
  }

  function newId() {
    var bytes = new Uint8Array(8);
    if (window.crypto && window.crypto.getRandomValues) { window.crypto.getRandomValues(bytes); }
    else { for (var i = 0; i < bytes.length; i++) { bytes[i] = Math.floor(Math.random() * 256); } }
    var out = "R-";
    for (var j = 0; j < bytes.length; j++) { out += ("0" + bytes[j].toString(16)).slice(-2); }
    return out;
  }

  var state = loadState();
  if (!state.respondent) { state.respondent = newId(); saveState(state); }

  /* Any failed or slow call marks the API unhealthy for this page, and then the
     survey never waits on it. Calls give up after REQUEST_MS. */
  var REQUEST_MS = 5000;
  var apiHealthy = true;
  function post(path, body, keep) {
    var controller = window.AbortController && !keep ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, REQUEST_MS) : null;
    return fetch(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      keepalive: !!keep,
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      if (timer) { clearTimeout(timer); }
      if (!r.ok) { throw new Error("HTTP " + r.status); }
      return r.json();
    }).catch(function (error) {
      if (timer) { clearTimeout(timer); }
      apiHealthy = false;
      throw error;
    });
  }

  function context(target) {
    return {
      page_url: window.location.href,
      user_agent: navigator.userAgent,
      screen_width: window.screen.width,
      screen_height: window.screen.height,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      survey_id: SURVEY,
      respondent_id: state.respondent,
      platform_id: PLATFORM,
      element_id: target && target.id ? target.id : undefined,
      element_type: target && target.tagName ? target.tagName.toLowerCase() : undefined
    };
  }

  function record(type, target, extra) {
    var event = context(target);
    event.event_type = type;
    event.timestamp = new Date().toISOString();
    if (extra) { for (var k in extra) { if (Object.prototype.hasOwnProperty.call(extra, k)) { event[k] = extra[k]; } } }
    buffer.push(event);
    if (buffer.length >= 25) { flush(false); }
  }

  function session() {
    if (state.session) { return Promise.resolve(state.session); }
    if (sessionPromise) { return sessionPromise; }
    var query = "?survey_id=" + encodeURIComponent(SURVEY) +
      "&respondent_id=" + encodeURIComponent(state.respondent) +
      "&platform_id=" + PLATFORM +
      (TOKEN ? "&token=" + encodeURIComponent(TOKEN) : "");
    sessionPromise = post("/detection/sessions" + query).then(function (data) {
      state.session = data.session_id;
      saveState(state);
      return state.session;
    });
    return sessionPromise;
  }

  function flush(keep) {
    if (!state.session || buffer.length === 0) { return Promise.resolve(); }
    var batch = buffer;
    buffer = [];
    return post("/detection/sessions/" + state.session + "/events", batch, keep).catch(function () {
      /* A keepalive send can report failure while the page unloads after it was delivered. */
      if (!keep) { buffer = batch.concat(buffer); }
    });
  }

  function isOurs(el) {
    return !!(el && el.getAttribute && el.getAttribute("data-qos"));
  }

  function questionText(el) {
    var node = el;
    for (var depth = 0; node && depth < 8; depth++) {
      if (node.querySelector) {
        var title = node.querySelector(".question-text, .question-title, h1, h2, legend");
        if (title && title.textContent.replace(/\s+/g, " ").trim().length > 5) {
          return title.textContent.replace(/\s+/g, " ").trim().slice(0, 500);
        }
      }
      node = node.parentNode;
    }
    return document.title || "Open-ended question";
  }

  /* Open ends: register each question when the page loads, send the answer on blur
     or submit. A submit waits briefly when a registration is still in flight. */
  var openQuestions = [];
  function openFor(el) {
    for (var i = 0; i < openQuestions.length; i++) {
      if (openQuestions[i].el === el) { return openQuestions[i]; }
    }
    var entry = { el: el, started: pageStart, sent: "", ready: false,
      initial: el.value || "", length: (el.value || "").length, typed: 0, pasted: 0, inputs: 0 };
    entry.id = session().then(function (sid) {
      return post("/text-analysis/questions", {
        session_id: sid,
        question_text: questionText(el),
        question_type: "open_ended",
        element_id: el.id || el.name || "",
        page_url: window.location.href,
        page_title: document.title
      }).then(function (data) { entry.ready = true; return data.question_id; });
    });
    openQuestions.push(entry);
    return entry;
  }

  function sendOpen(entry, keep) {
    var text = (entry.el.value || "").trim();
    if (text.length < MIN_TEXT || text === entry.sent) { return null; }
    entry.sent = text;
    var elapsed = Date.now() - entry.started;
    return entry.id.then(function (qid) {
      if (!qid) { return; }
      return post("/text-analysis/responses", {
        session_id: state.session,
        question_id: qid,
        response_text: text,
        response_time_ms: elapsed,
        typed_chars: entry.typed,
        pasted_chars: entry.pasted,
        input_events: entry.inputs
      }, keep);
    }).catch(function () {});
  }

  function textPending() {
    for (var i = 0; i < openQuestions.length; i++) {
      var q = openQuestions[i];
      if (!q.ready && (q.el.value || "").trim().length >= MIN_TEXT) { return true; }
    }
    return false;
  }

  function isTextInput(el) {
    if (!el || isOurs(el)) { return false; }
    if (el.tagName === "TEXTAREA") { return true; }
    return el.tagName === "INPUT" && (el.type === "text" || el.type === "") ;
  }

  /* Grids: three or more radio groups on a page are treated as a grid. */
  function radioGroups() {
    var radios = document.querySelectorAll("input[type=radio]");
    var order = [];
    var groups = {};
    for (var i = 0; i < radios.length; i++) {
      var name = radios[i].name;
      if (!name) { continue; }
      if (!groups[name]) { groups[name] = []; order.push(name); }
      groups[name].push(radios[i]);
    }
    return { order: order, groups: groups };
  }

  var gridPage = false;
  function gridValues() {
    var values = [];
    var found = radioGroups();
    for (var i = 0; i < found.order.length; i++) {
      var group = found.groups[found.order[i]];
      for (var j = 0; j < group.length; j++) {
        if (group[j].checked) { values.push(String(j + 1)); break; }
      }
    }
    return values;
  }

  function submitEvents() {
    var page = { event_type: "form_submit", timestamp: new Date().toISOString() };
    var base = context(null);
    for (var k in base) { if (Object.prototype.hasOwnProperty.call(base, k)) { page[k] = base[k]; } }
    page.element_id = "qos-page:" + (Date.now() - pageStart);
    if (honeypot && honeypot.value) { page.honeypot = true; }
    var untyped = 0;
    for (var i = 0; i < openQuestions.length; i++) {
      var q = openQuestions[i];
      var value = q.el.value || "";
      if (value.trim().length >= MIN_UNTYPED && value !== q.initial && q.inputs === 0) { untyped += 1; }
    }
    if (untyped) { page.untyped_answers = untyped; }
    buffer.push(page);
    if (gridPage) {
      var values = gridValues();
      if (values.length >= 3) {
        var grid = JSON.parse(JSON.stringify(page));
        grid.element_id = "qos-grid:" + values.join(",");
        buffer.push(grid);
        sendGrid(values, Date.now() - pageStart);
      }
    }
  }

  /* The grid is also registered as a question so the service's grid (straight-lining)
     and timing (speeder) checks run on it. Rows are not text-scored. */
  var gridQuestion = null;
  function registerGrid() {
    var first = document.querySelector("input[type=radio]");
    gridQuestion = { ready: false, id: null };
    session().then(function (sid) {
      return post("/text-analysis/questions", {
        session_id: sid,
        question_text: questionText(first),
        question_type: "grid",
        page_url: window.location.href,
        page_title: document.title
      });
    }).then(function (data) { gridQuestion.id = data.question_id; gridQuestion.ready = true; }).catch(function () {});
  }

  function sendGrid(values, elapsed) {
    if (!gridQuestion || !gridQuestion.ready || !state.session) { return; }
    for (var i = 0; i < values.length; i++) {
      post("/text-analysis/responses", {
        session_id: state.session,
        question_id: gridQuestion.id,
        response_text: values[i],
        response_time_ms: elapsed
      }, true).catch(function () {});
    }
  }

  /* How each open end is entered: typed (including dictation and autocorrect),
     pasted or dropped, or set by script (no input events at all). */
  var MIN_UNTYPED = 20;
  function trackEntry(e) {
    if (!isTextInput(e.target)) { return; }
    var entry = openFor(e.target);
    var length = (e.target.value || "").length;
    var added = Math.max(length - entry.length, 0);
    entry.length = length;
    entry.inputs += 1;
    var kind = e.inputType || "";
    if (kind.indexOf("insertFromPaste") === 0 || kind === "insertFromDrop") { entry.pasted += added; } else { entry.typed += added; }
  }

  /* Honeypot: an off-screen field people never see or reach with the keyboard.
     It has no name, so Decipher never receives it; only scripts that fill every
     field put a value in it. */
  var honeypot = null;
  function addHoneypot() {
    var form = document.querySelector("form");
    if (!form) { return; }
    var box = document.createElement("div");
    box.setAttribute("aria-hidden", "true");
    box.style.cssText = "position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden;";
    var label = document.createElement("label");
    label.appendChild(document.createTextNode("Leave this empty"));
    honeypot = document.createElement("input");
    honeypot.type = "text";
    honeypot.tabIndex = -1;
    honeypot.setAttribute("autocomplete", "off");
    honeypot.setAttribute("data-qos", "hp");
    label.appendChild(honeypot);
    box.appendChild(label);
    form.appendChild(box);
  }

  /* Final page: hidden fields marked with qos-bot-field spans get the results. */
  function hiddenFields() {
    var marks = document.querySelectorAll(".qos-bot-field");
    var fields = {};
    for (var i = 0; i < marks.length; i++) {
      var node = marks[i];
      var input = null;
      for (var depth = 0; node && depth < 8 && !input; depth++) {
        node = node.parentNode;
        if (node && node.querySelector) { input = node.querySelector("input[type=text], textarea"); }
      }
      if (input && node) {
        node.style.display = "none";
        input.setAttribute("data-qos", "1");
        fields[marks[i].getAttribute("data-field")] = input;
      }
    }
    return fields;
  }

  function fill(fields, name, value) {
    if (fields[name]) { fields[name].value = value === undefined || value === null ? "" : String(value); }
  }

  function finish(fields) {
    if (finishing) { return finishing; }
    fill(fields, "respondent", state.respondent);
    finishing = session().then(function (sid) {
      fill(fields, "session", sid);
      for (var i = 0; i < openQuestions.length; i++) { sendOpen(openQuestions[i], false); }
      return flush(false).then(function () {
        /* composite-analyze runs the behavioural verdict (stored for the reports), grid,
           timing, text, and fraud checks in one call. analyze is the fallback. */
        return post("/detection/sessions/" + sid + "/composite-analyze").then(function (composite) {
          return { composite: composite || {}, behaviour: (composite && composite.behavioral_details) || {} };
        }, function () {
          return post("/detection/sessions/" + sid + "/analyze").catch(function () { return {}; })
            .then(function (behaviour) { return { composite: {}, behaviour: behaviour || {} }; });
        });
      });
    }).then(function (both) {
      var c = both.composite;
      var b = both.behaviour;
      var isBot = (c.is_bot === undefined && b.is_bot === undefined) ? undefined : (c.is_bot === true || b.is_bot === true);
      var score = c.composite_score;
      if (score === undefined || score === null) { score = b.confidence_score; }
      fill(fields, "flag", isBot === undefined ? "unknown" : (isBot ? "bot" : "human"));
      fill(fields, "score", score);
      fill(fields, "risk", b.is_bot === true ? (b.risk_level || "high") : (c.risk_level || b.risk_level || ""));
    }).catch(function () {
      fill(fields, "flag", "unknown");
    }).then(function () { finished = true; });
    return finishing;
  }

  /* Device signals for the service's device check: time zone, languages, platform,
     hardware, and short hashes of how the browser draws text and which graphics
     card it reports. Nothing here identifies a person; it tells devices apart. */
  function hash(text) {
    var h = 5381;
    for (var i = 0; i < text.length; i++) { h = ((h * 33) ^ text.charCodeAt(i)) >>> 0; }
    return h.toString(16);
  }

  function deviceSignals() {
    var out = {};
    try { out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch (e) {}
    try { out.languages = (navigator.languages || [navigator.language]).join(","); } catch (e) {}
    out.platform = navigator.platform || "";
    out.cores = navigator.hardwareConcurrency || 0;
    out.memory = navigator.deviceMemory || 0;
    try {
      var canvas = document.createElement("canvas");
      canvas.width = 200; canvas.height = 40;
      var ctx = canvas.getContext("2d");
      ctx.textBaseline = "top"; ctx.font = "16px Arial"; ctx.fillStyle = "#f60";
      ctx.fillRect(10, 5, 60, 20); ctx.fillStyle = "#069"; ctx.fillText("QuantOS quality 1.0", 4, 12);
      out.canvas = hash(canvas.toDataURL());
    } catch (e) {}
    try {
      var gl = document.createElement("canvas").getContext("webgl");
      var info = gl && gl.getExtension("WEBGL_debug_renderer_info");
      if (info) { out.webgl = hash(String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL))); }
    } catch (e) {}
    return out;
  }

  /* In-survey check: score the behaviour so far. Only decisive signals the project
     enabled fill "bot", which the survey's termination reads. Anything else, a
     failure, or a timeout leaves the respondent in the survey. */
  function earlyCheck(field) {
    return flush(false).then(function () {
      return post("/detection/sessions/" + state.session + "/analyze");
    }).then(function (result) {
      var codes = ((result && result.flagged_patterns) || {}).decisive_codes || [];
      var hit = false;
      for (var i = 0; i < codes.length; i++) {
        if ((RULES.signals || []).indexOf(codes[i]) >= 0) { hit = true; }
      }
      field.value = hit ? "bot" : "human";
    }).catch(function () {});
  }

  /* Send the held page on. Decipher disables its button on the first click, so the
     button is enabled again before clicking. If the page is still here shortly
     after, submit the form directly with the button's name and value. */
  function resubmit(form, button) {
    if (button) {
      button.disabled = false;
      if (button.click) { button.click(); }
    }
    /* A click that reached the submit handler set qosLeaving synchronously; if it
       did not, the survey's own guard swallowed it, so submit now. Otherwise allow
       two seconds before forcing it (the server still validates the answers). */
    setTimeout(function () {
      if (document.visibilityState === "hidden" || form.qosForced) { return; }
      form.qosForced = true;
      if (button && button.name) {
        var marker = document.createElement("input");
        marker.type = "hidden";
        marker.name = button.name;
        marker.value = button.value || "1";
        form.appendChild(marker);
      }
      HTMLFormElement.prototype.submit.call(form);
    }, form.qosLeaving ? 2000 : 0);
  }

  function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

  function start() {
    session().then(function () {
      var signals = deviceSignals();
      signals.webdriver = navigator.webdriver === true;
      signals.touch_points = navigator.maxTouchPoints || 0;
      record("page_load", null, signals);
    }).catch(function () {});
    gridPage = radioGroups().order.length >= 3;
    if (gridPage) { registerGrid(); }
    var fields = hiddenFields();
    var finalPage = !!(fields.respondent || fields.flag);
    if (finalPage) { finish(fields); }
    var earlyField = fields.early || null;

    document.addEventListener("keydown", function (e) {
      if (isOurs(e.target)) { return; }
      record("keystroke", e.target, { key: e.key && e.key.length === 1 ? "char" : e.key, trusted: e.isTrusted });
    });
    document.addEventListener("click", function (e) {
      record("mouse_click", e.target, { button: e.button, x: e.clientX, y: e.clientY, trusted: e.isTrusted, pointer: e.pointerType || undefined });
    });
    var lastMove = 0;
    document.addEventListener("mousemove", function (e) {
      var now = Date.now();
      if (now - lastMove < 100) { return; }
      lastMove = now;
      record("mouse_move", e.target, { x: e.clientX, y: e.clientY });
    });
    document.addEventListener("scroll", function () {
      record("scroll", null, { scroll_y: window.scrollY, scroll_x: window.scrollX });
    });
    document.addEventListener("focusin", function (e) {
      if (isTextInput(e.target)) { openFor(e.target).started = Date.now(); }
      record("focus", e.target, {});
    });
    document.addEventListener("focusout", function (e) {
      if (isTextInput(e.target)) { sendOpen(openFor(e.target), true); }
      record("blur", e.target, {});
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "hidden") { flush(true); }
    });

    var inputs = document.querySelectorAll("textarea, input[type=text]");
    for (var t = 0; t < inputs.length; t++) {
      if (isTextInput(inputs[t])) { openFor(inputs[t]); }
    }
    document.addEventListener("input", trackEntry, true);
    addHoneypot();

    var forms = document.querySelectorAll("form");
    for (var f = 0; f < forms.length; f++) {
      forms[f].addEventListener("submit", function (e) {
        var form = this;
        /* Hold only while the API is healthy and this respondent has a session. */
        var canWait = apiHealthy && !!state.session;
        var waitText = canWait && !form.qosTextDone && textPending();
        var sends = [];
        for (var i = 0; i < openQuestions.length; i++) {
          var sent = sendOpen(openQuestions[i], true);
          if (sent) { sends.push(sent); }
        }
        if (!form.qosSubmitted) { form.qosSubmitted = true; submitEvents(); }
        var waitCheck = canWait && finalPage && !finished;
        var waitEarly = canWait && !!earlyField && RULES.terminate && !form.qosEarlyDone;
        if (waitCheck || waitText || waitEarly) {
          /* Hold the page briefly so answers and checks reach the API (at most 1.5
             seconds for answers, 2.5 for the in-survey check, 3 for the final check). */
          e.preventDefault();
          var button = e.submitter || form.querySelector("[name=continue], [name=finish], button[type=submit], input[type=submit]");
          var work = [Promise.all(sends)];
          if (waitCheck) { work.push(finish(fields)); }
          if (waitEarly) { work.push(earlyCheck(earlyField)); }
          var cap = waitCheck ? 3000 : (waitEarly ? 2500 : 1500);
          Promise.race([Promise.all(work), wait(cap)]).then(function () {
            form.qosTextDone = true;
            form.qosEarlyDone = true;
            if (waitCheck) { finished = true; }
            flush(true);
            resubmit(form, button);
          });
          return;
        }
        /* The submit goes ahead (or the survey's own validation stops it); either
           way the fallback in resubmit must not force it. */
        form.qosLeaving = true;
        flush(true);
      }, true);
    }
    window.addEventListener("pagehide", function () { flush(true); });
    setInterval(function () { flush(false); }, 5000);
  }

  try {
    if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", start); }
    else { start(); }
  } catch (e) {}
})();
</script>
