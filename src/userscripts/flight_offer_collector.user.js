// ==UserScript==
// @name         ReverseFlightTickets 机票报价采集
// @namespace    reverse-flight-tickets
// @version      0.2.1
// @description  读取携程/飞猪搜索结果页已渲染航班卡片，可手动采集当前屏幕、已渲染列表或智能滚动当前列表，并导出 JSON/CSV。
// @match        https://flights.ctrip.com/online/list/*
// @match        https://sijipiao.fliggy.com/ie/flight_search_result.htm*
// @match        https://sjipiao.fliggy.com/flight_search_result.htm*
// @match        https://*.fliggy.com/*flight_search_result.htm*
// @grant        GM_setClipboard
// @grant        GM_download
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  const SCHEMA_VERSION = "rft-browser-offers/v1";
  const PANEL_ID = "rft-flight-collector-panel";
  const RESULT_ID = "rft-flight-collector-result";
  const SMART_SCROLL_MAX_STEPS = 80;
  const SMART_SCROLL_DELAY_MS = 650;
  const SMART_SCROLL_IDLE_STEPS = 4;
  const SMART_SCROLL_STEP_RATIO = 0.82;

  const AIRLINE_PATTERNS = [
    "中国国航",
    "国际航空",
    "东方航空",
    "南方航空",
    "海南航空",
    "厦门航空",
    "四川航空",
    "山东航空",
    "春秋航空",
    "吉祥航空",
    "深圳航空",
    "上海航空",
    "长龙航空",
    "祥鹏航空",
    "天津航空",
    "首都航空",
    "华夏航空",
    "西藏航空",
    "成都航空",
    "昆明航空",
    "瑞丽航空",
    "河北航空",
    "奥凯航空",
    "联合航空",
    "澳门航空",
    "香港航空",
    "香港快运",
    "国泰航空",
    "长荣航空",
    "中华航空",
    "星宇航空",
    "立荣航空",
    "台湾虎航",
    "新加坡航空",
    "日本航空",
    "全日空",
    "大韩航空",
    "韩亚航空",
    "泰国航空",
    "亚洲航空",
    "酷航",
    "越南航空",
    "菲律宾航空",
    "马来西亚航空",
    "土耳其航空",
    "阿联酋航空",
    "卡塔尔航空",
    "芬兰航空",
    "汉莎航空",
    "荷兰皇家航空",
    "法国航空",
    "英国航空",
    "美联航",
    "达美航空",
    "美国航空",
    "加拿大航空",
    "澳洲航空",
    "捷星",
    "乐桃",
    "虎航",
    "济州航空",
    "釜山航空",
    "真航空",
    "德威航空",
    "Air China",
    "China Eastern",
    "China Southern",
    "Hainan Airlines",
    "XiamenAir",
    "Cathay Pacific",
    "EVA Air",
    "China Airlines",
    "STARLUX",
    "Singapore Airlines",
    "Japan Airlines",
    "ANA",
    "Korean Air",
    "Asiana",
    "Thai Airways",
    "AirAsia",
    "Scoot",
  ];

  const CARD_SELECTORS = [
    ".flight-item",
    ".flight-card",
    ".flight-list-item",
    ".J_FlightItem",
    "[class*='flight'][class*='item']",
    "[class*='flight'][class*='card']",
    "[class*='Flight'][class*='Item']",
    "[class*='Flight'][class*='Card']",
    "[class*='flight'][class*='list'] > *",
    "[class*='Flight'][class*='list'] > *",
    "[class*='result'][class*='item']",
    "[class*='Result'][class*='Item']",
    "[role='listitem']",
    "article",
    "li",
  ];

  const PRICE_SELECTORS = [
    "[class*='price']",
    "[class*='Price']",
    "[class*='fare']",
    "[class*='Fare']",
    "[class*='amount']",
    "[class*='Amount']",
    "[class*='money']",
    "[class*='Money']",
  ];

  const STOP_HINT_RE = /(直飞|直飛|直航|直達|无中转|無中轉|经停|經停|中转|中轉|转机|轉機|Direct|Nonstop|Transfer|Stop)/i;
  const DIRECT_RE = /(直飞|直飛|直航|直達|无中转|無中轉|Direct|Nonstop)/i;
  const TRANSFER_RE = /(经停|經停|中转|中轉|转机|轉機|Transfer|Stop)/i;

  const SOURCE = detectSource();
  let latestPayload = null;
  let smartScrollRunning = false;
  let smartScrollAbort = false;

  function detectSource() {
    const host = location.hostname.toLowerCase();
    if (host.includes("ctrip.com")) return "ctrip";
    if (host.includes("fliggy.com")) return "fliggy";
    return "unknown";
  }

  function injectPanel() {
    if (document.getElementById(PANEL_ID)) return;

    const style = document.createElement("style");
    style.textContent = `
      #${PANEL_ID} {
        position: fixed;
        right: 16px;
        bottom: 16px;
        z-index: 2147483647;
        width: 282px;
        padding: 10px;
        border: 1px solid rgba(35, 42, 52, 0.18);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.96);
        box-shadow: 0 8px 24px rgba(20, 26, 35, 0.18);
        font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color: #172033;
      }
      #${PANEL_ID} button {
        border: 1px solid #2d6cdf;
        border-radius: 6px;
        background: #2d6cdf;
        color: #fff;
        height: 30px;
        padding: 0 9px;
        cursor: pointer;
        font: inherit;
        white-space: nowrap;
      }
      #${PANEL_ID} button.secondary {
        background: #fff;
        color: #2d6cdf;
      }
      #${PANEL_ID} button.warning {
        border-color: #a23d2d;
        background: #a23d2d;
      }
      #${PANEL_ID} button:disabled {
        opacity: 0.5;
        cursor: default;
      }
      #${PANEL_ID} .rft-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 8px;
      }
      #${PANEL_ID} .rft-row button {
        flex: 1 1 auto;
      }
      #${PANEL_ID} .rft-title {
        font-weight: 600;
        margin-bottom: 7px;
      }
      #${PANEL_ID} #${RESULT_ID} {
        margin-top: 8px;
        min-height: 18px;
        color: #435066;
        word-break: break-word;
      }
    `;
    document.documentElement.appendChild(style);

    const panel = document.createElement("div");
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="rft-title">ReverseFlightTickets</div>
      <div class="rft-row">
        <button type="button" id="rft-collect-screen">采集当前屏幕</button>
        <button type="button" id="rft-collect-rendered">采集已渲染列表</button>
      </div>
      <div class="rft-row">
        <button type="button" id="rft-collect-smart">智能滚动采集</button>
        <button type="button" class="warning" id="rft-stop-smart" disabled>停止</button>
      </div>
      <div class="rft-row">
        <button type="button" class="secondary" id="rft-copy-json" disabled>复制 JSON</button>
        <button type="button" class="secondary" id="rft-copy-csv" disabled>复制 CSV</button>
      </div>
      <div class="rft-row">
        <button type="button" class="secondary" id="rft-download-json" disabled>下载 JSON</button>
        <button type="button" class="secondary" id="rft-download-csv" disabled>下载 CSV</button>
      </div>
      <div id="${RESULT_ID}">未采集</div>
    `;
    document.body.appendChild(panel);

    panel.querySelector("#rft-collect-screen").addEventListener("click", () => {
      latestPayload = collectPayload({ mode: "screen", viewportOnly: true });
      setResult(`已采集 ${latestPayload.offers.length} 条当前屏幕报价`);
      setExportEnabled(true);
    });
    panel.querySelector("#rft-collect-rendered").addEventListener("click", () => {
      latestPayload = collectPayload({ mode: "rendered_list", viewportOnly: false });
      setResult(`已采集 ${latestPayload.offers.length} 条已渲染列表报价`);
      setExportEnabled(true);
    });
    panel.querySelector("#rft-collect-smart").addEventListener("click", () => {
      smartScrollCollect();
    });
    panel.querySelector("#rft-stop-smart").addEventListener("click", () => {
      smartScrollAbort = true;
      setResult("正在停止智能滚动采集...");
    });
    panel.querySelector("#rft-copy-json").addEventListener("click", () => {
      copyText(JSON.stringify(latestPayload, null, 2), "JSON 已复制");
    });
    panel.querySelector("#rft-copy-csv").addEventListener("click", () => {
      copyText(payloadToCsv(latestPayload), "CSV 已复制");
    });
    panel.querySelector("#rft-download-json").addEventListener("click", () => {
      downloadText(
        JSON.stringify(latestPayload, null, 2),
        `rft-${SOURCE}-${timestampForName()}.json`,
        "application/json;charset=utf-8",
      );
    });
    panel.querySelector("#rft-download-csv").addEventListener("click", () => {
      downloadText(
        payloadToCsv(latestPayload),
        `rft-${SOURCE}-${timestampForName()}.csv`,
        "text/csv;charset=utf-8",
      );
    });
  }

  function setResult(message) {
    const node = document.getElementById(RESULT_ID);
    if (node) node.textContent = message;
  }

  function setExportEnabled(enabled) {
    document
      .querySelectorAll(`#${PANEL_ID} button.secondary`)
      .forEach((button) => {
        button.disabled = !enabled;
      });
  }

  function setCollectionControlsEnabled(enabled) {
    ["#rft-collect-screen", "#rft-collect-rendered", "#rft-collect-smart"].forEach((selector) => {
      const button = document.querySelector(`#${PANEL_ID} ${selector}`);
      if (button) button.disabled = !enabled;
    });
    const stop = document.querySelector(`#${PANEL_ID} #rft-stop-smart`);
    if (stop) stop.disabled = enabled;
  }

  function collectPayload(options = {}) {
    const capturedAt = options.capturedAt || new Date().toISOString();
    const request = options.request || inferRequestFromUrl();
    const cards = collectCards({ viewportOnly: options.viewportOnly !== false });
    const offers = dedupeOffers(cards.map((card) => extractOffer(card, request, capturedAt)));
    return buildPayload({
      request,
      capturedAt,
      offers,
      mode: options.mode || "screen",
      collection: {
        viewport_only: options.viewportOnly !== false,
        card_count: cards.length,
      },
    });
  }

  async function smartScrollCollect() {
    if (smartScrollRunning) return;

    smartScrollRunning = true;
    smartScrollAbort = false;
    setCollectionControlsEnabled(false);
    setExportEnabled(false);

    const capturedAt = new Date().toISOString();
    const request = inferRequestFromUrl();
    const offersByKey = new Map();
    const scroller = findResultScroller();
    let stableSteps = 0;
    let previousCount = 0;
    let steps = 0;

    try {
      for (; steps < SMART_SCROLL_MAX_STEPS && !smartScrollAbort; steps += 1) {
        const payload = collectPayload({
          mode: "smart_scroll_step",
          viewportOnly: true,
          capturedAt,
          request,
        });
        mergeOffers(offersByKey, payload.offers);

        const countChanged = offersByKey.size !== previousCount;
        previousCount = offersByKey.size;
        setResult(`智能采集中：${offersByKey.size} 条，已扫 ${steps + 1} 屏`);

        const before = scrollMetric(scroller);
        scrollForward(scroller);
        await wait(SMART_SCROLL_DELAY_MS);
        const after = scrollMetric(scroller);
        const moved = after.top > before.top + 4 || after.height > before.height + 4;

        if (!countChanged && (!moved || isAtScrollEnd(scroller))) {
          stableSteps += 1;
        } else {
          stableSteps = 0;
        }
        if (stableSteps >= SMART_SCROLL_IDLE_STEPS) break;
      }
    } finally {
      const stopped = smartScrollAbort;
      smartScrollRunning = false;
      smartScrollAbort = false;
      latestPayload = buildPayload({
        request,
        capturedAt,
        offers: Array.from(offersByKey.values()),
        mode: "smart_scroll",
        collection: {
          viewport_only: false,
          scroll_steps: steps,
          stopped,
          max_steps: SMART_SCROLL_MAX_STEPS,
          scroll_target: scroller === document.scrollingElement ? "window" : "scroll_container",
        },
      });
      setCollectionControlsEnabled(true);
      setExportEnabled(true);
      setResult(
        stopped
          ? `已停止：采集 ${latestPayload.offers.length} 条报价`
          : `智能采集完成：${latestPayload.offers.length} 条报价`,
      );
    }
  }

  function buildPayload({ request, capturedAt, offers, mode, collection }) {
    return {
      schema_version: SCHEMA_VERSION,
      source: SOURCE,
      page_url: location.href,
      captured_at: capturedAt,
      collection_mode: mode,
      collection,
      request,
      offers: dedupeOffers(offers),
    };
  }

  function inferRequestFromUrl() {
    const url = new URL(location.href);
    const request = {
      allowed_markets: ["CN"],
      allowed_currencies: ["CNY"],
      passenger_count: 1,
      cabin: "economy",
    };

    if (SOURCE === "ctrip") {
      const match = url.pathname.match(/\/online\/list\/([^/-]+)-([a-z0-9]{3,8})-([a-z0-9]{3,8})/i);
      if (match) {
        request.origin = match[2].toUpperCase();
        request.destination = match[3].toUpperCase();
      }
      const depDate = url.searchParams.get("depdate") || "";
      const dates = depDate.split("_").filter(Boolean);
      if (dates[0]) request.departure_date = dates[0];
      if (dates[1]) request.return_date = dates[1];
      const adult = parseInt(url.searchParams.get("adult") || "1", 10);
      const child = parseInt(url.searchParams.get("child") || "0", 10);
      const infant = parseInt(url.searchParams.get("infant") || "0", 10);
      request.passengers = {
        adults: Number.isFinite(adult) ? adult : 1,
        children: Number.isFinite(child) ? child : 0,
        infants: Number.isFinite(infant) ? infant : 0,
      };
      request.passenger_count = request.passengers.adults;
      request.cabin = cabinFromCtrip(url.searchParams.get("cabin"));
    }

    if (SOURCE === "fliggy") {
      const journey = parseFliggyJourney(url.searchParams.get("searchJourney"));
      const firstSegment = journey[0] || {};
      const returnSegment = journey[1] || {};
      request.origin = normalizeCode(url.searchParams.get("depCity") || firstSegment.depCityCode);
      request.destination = normalizeCode(url.searchParams.get("arrCity") || firstSegment.arrCityCode);
      request.departure_date = url.searchParams.get("depDate") || firstSegment.depDate || undefined;
      const tripType = url.searchParams.get("tripType");
      const returnDate =
        url.searchParams.get("retDate") || url.searchParams.get("arrDate") || returnSegment.depDate;
      if ((tripType === "1" || journey.length > 1) && returnDate) request.return_date = returnDate;
      const adult = parseInt(
        url.searchParams.get("adultNum") || url.searchParams.get("adultPassengerNum") || "1",
        10,
      );
      const child = parseInt(
        url.searchParams.get("childNum") || url.searchParams.get("childPassengerNum") || "0",
        10,
      );
      const infant = parseInt(url.searchParams.get("infantPassengerNum") || "0", 10);
      request.passengers = {
        adults: Number.isFinite(adult) ? adult : 1,
        children: Number.isFinite(child) ? child : 0,
        infants: Number.isFinite(infant) ? infant : 0,
      };
      request.passenger_count = request.passengers.adults;
    }

    return removeEmpty(request);
  }

  function cabinFromCtrip(value) {
    if (!value) return "economy";
    const lowered = value.toLowerCase();
    if (lowered.includes("f")) return "first";
    if (lowered.includes("c") || lowered.includes("j")) return "business";
    if (lowered.includes("s") || lowered.includes("p")) return "premium_economy";
    return "economy";
  }

  function normalizeCode(value) {
    if (!value) return undefined;
    const trimmed = value.trim();
    return trimmed ? trimmed.toUpperCase() : undefined;
  }

  function parseFliggyJourney(value) {
    if (!value) return [];
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (_error) {
      try {
        const parsed = JSON.parse(decodeURIComponent(value));
        return Array.isArray(parsed) ? parsed : [];
      } catch (_innerError) {
        return [];
      }
    }
  }

  function collectCards(options = {}) {
    const opts = { viewportOnly: options.viewportOnly !== false };
    const cards = new Set();

    document.querySelectorAll(CARD_SELECTORS.join(",")).forEach((element) => {
      if (looksLikeFlightCard(element, opts)) cards.add(element);
    });

    for (const node of candidateTextNodes(opts)) {
      if (!priceFromText(node.nodeValue || "")) continue;
      const card = findCardFromPriceNode(node, opts);
      if (card) cards.add(card);
    }

    return removeNestedCards(Array.from(cards), opts);
  }

  function candidateTextNodes(options) {
    const nodes = [];
    const walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          const text = normalizeText(node.nodeValue || "");
          if (text.length < 2) return NodeFilter.FILTER_REJECT;
          const parent = node.parentElement;
          if (!parent || !isElementCollectable(parent, options)) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      },
    );
    while (walker.nextNode()) nodes.push(walker.currentNode);
    return nodes;
  }

  function findCardFromPriceNode(node, options) {
    let element = node.parentElement;
    let best = null;
    let bestScore = 0;
    for (let depth = 0; element && element !== document.body && depth < 11; depth += 1) {
      if (!isElementCollectable(element, options)) break;
      const text = elementText(element);
      if (text.length > 5200) break;
      const score = scoreFlightCard(text);
      if (score > bestScore && looksLikeFlightCard(element, options)) {
        best = element;
        bestScore = score;
      }
      if (best && bestScore >= 70 && isLikelyCardBoundary(element)) return element;
      element = element.parentElement;
    }
    return best;
  }

  function looksLikeFlightCard(element, options) {
    if (!isElementCollectable(element, options)) return false;
    const text = elementText(element);
    if (text.length < 12 || text.length > 4200) return false;
    return scoreFlightCard(text) >= 60;
  }

  function scoreFlightCard(text) {
    const price = priceFromText(text);
    if (!price) return 0;
    const flightNumbers = extractFlightNumbers(text);
    const times = extractTimes(text);
    const airlines = extractAirlines(text);
    const hasRouteHint = /\b[A-Z]{3}\b.{0,30}\b[A-Z]{3}\b/.test(text);
    let score = 40;
    score += Math.min(times.length, 4) * 8;
    score += Math.min(flightNumbers.length, 3) * 14;
    score += Math.min(airlines.length, 2) * 12;
    if (STOP_HINT_RE.test(text)) score += 8;
    if (hasRouteHint) score += 6;
    if (/航班|机票|起飞|到达|出发|抵达|Flight|Depart|Arrive/i.test(text)) score += 6;
    return score;
  }

  function isLikelyCardBoundary(element) {
    const className = String(element.className || "");
    const tag = element.tagName.toLowerCase();
    return (
      tag === "li" ||
      tag === "article" ||
      element.getAttribute("role") === "listitem" ||
      /flight|Flight|air|Air|card|Card|item|Item|result|Result|route|Route/.test(className)
    );
  }

  function removeNestedCards(cards, options) {
    const sorted = cards
      .filter((card) => card && isElementCollectable(card, options))
      .sort((a, b) => rectArea(a.getBoundingClientRect()) - rectArea(b.getBoundingClientRect()));
    const chosen = [];
    for (const card of sorted) {
      const overlappingIndex = chosen.findIndex(
        (existing) => existing.contains(card) || card.contains(existing),
      );
      if (overlappingIndex < 0) {
        chosen.push(card);
        continue;
      }
      const existing = chosen[overlappingIndex];
      if (cardQuality(card) > cardQuality(existing)) {
        chosen[overlappingIndex] = card;
      }
    }
    return chosen;
  }

  function cardQuality(card) {
    const text = elementText(card);
    const areaPenalty = Math.min(rectArea(card.getBoundingClientRect()) / 200000, 8);
    const lengthPenalty = Math.min(text.length / 1200, 5);
    return scoreFlightCard(text) - areaPenalty - lengthPenalty;
  }

  function extractOffer(card, request, capturedAt) {
    const text = elementText(card);
    const price = priceFromElement(card, text) || {};
    const flightNumbers = extractFlightNumbers(text);
    const times = extractTimes(text);
    const airline = extractAirlines(text).join(" / ") || "";
    const link = extractLink(card);
    const stops = extractStops(text);

    return removeEmpty({
      provider: SOURCE,
      source: SOURCE,
      captured_at: capturedAt,
      page_url: location.href,
      origin: request.origin,
      destination: request.destination,
      departure_date: request.departure_date,
      return_date: request.return_date,
      price,
      amount: price.amount,
      currency: price.currency,
      airline,
      flight_numbers: flightNumbers,
      departure_time: times[0],
      arrival_time: times[1],
      stops,
      link,
      raw_text: text.slice(0, 1200),
    });
  }

  function priceFromElement(card, fallbackText) {
    const priceTexts = fieldTexts(card, PRICE_SELECTORS);
    for (const text of priceTexts) {
      const price = priceFromText(text);
      if (price) return price;
    }
    return priceFromText(fallbackText);
  }

  function priceFromText(text) {
    const patterns = [
      /(?:¥|￥)\s*([0-9][0-9,]*(?:\.\d+)?)(?:\s*起)?/,
      /\b(?:CNY|RMB)\s*([0-9][0-9,]*(?:\.\d+)?)/i,
      /([0-9][0-9,]*(?:\.\d+)?)\s*元(?:起)?/,
    ];
    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (!match) continue;
      return {
        amount: match[1].replace(/,/g, ""),
        currency: "CNY",
        raw: match[0],
      };
    }
    return null;
  }

  function extractFlightNumbers(text) {
    const values = [];
    const re = /\b(?:[A-Z]{2}|[A-Z][0-9]|[0-9][A-Z])\s?\d{2,4}[A-Z]?\b/g;
    for (const match of text.matchAll(re)) {
      const value = match[0].replace(/\s+/g, "");
      if (!values.includes(value)) values.push(value);
    }
    return values;
  }

  function extractTimes(text) {
    const values = [];
    const re = /(?:[01]?\d|2[0-3]):[0-5]\d/g;
    for (const match of text.matchAll(re)) {
      if (!values.includes(match[0])) values.push(match[0]);
      if (values.length >= 8) break;
    }
    return values;
  }

  function extractAirlines(text) {
    const values = [];
    for (const pattern of AIRLINE_PATTERNS) {
      const re = new RegExp(escapeRegExp(pattern), "i");
      if (re.test(text) && !values.includes(pattern)) values.push(pattern);
    }
    return values;
  }

  function extractStops(text) {
    if (DIRECT_RE.test(text)) return "direct";
    const stopMatch = text.match(/.{0,8}(经停|經停|中转|中轉|转机|轉機|Transfer|Stop).{0,24}/i);
    if (stopMatch) return stopMatch[0].trim();
    return "";
  }

  function extractLink(card) {
    const anchors = Array.from(card.querySelectorAll("a[href]"));
    for (const anchor of anchors) {
      const href = anchor.getAttribute("href");
      if (!href || href.startsWith("javascript:")) continue;
      try {
        return new URL(href, location.href).href;
      } catch (_error) {
        continue;
      }
    }
    return location.href;
  }

  function dedupeOffers(offers) {
    const seen = new Set();
    const deduped = [];
    for (const offer of offers) {
      const key = offerKey(offer);
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(offer);
    }
    return deduped;
  }

  function mergeOffers(target, offers) {
    for (const offer of offers) {
      target.set(offerKey(offer), offer);
    }
  }

  function offerKey(offer) {
    return [
      offer.provider,
      offer.amount,
      offer.airline,
      (offer.flight_numbers || []).join(","),
      offer.departure_time,
      offer.arrival_time,
      offer.stops,
      offer.link,
    ].join("|");
  }

  function payloadToCsv(payload) {
    const columns = [
      "schema_version",
      "source",
      "collection_mode",
      "provider",
      "captured_at",
      "page_url",
      "origin",
      "destination",
      "departure_date",
      "return_date",
      "currency",
      "amount",
      "airline",
      "flight_numbers",
      "departure_time",
      "arrival_time",
      "stops",
      "link",
      "raw_text",
    ];
    const rows = [columns];
    const request = payload.request || {};
    for (const offer of payload.offers || []) {
      rows.push(
        columns.map((column) => {
          if (column === "schema_version") return payload.schema_version || SCHEMA_VERSION;
          if (column === "source") return payload.source || offer.source || "";
          if (column === "collection_mode") return payload.collection_mode || "";
          if (column === "page_url") return offer.page_url || payload.page_url || "";
          if (column === "origin") return offer.origin || request.origin || "";
          if (column === "destination") return offer.destination || request.destination || "";
          if (column === "departure_date") return offer.departure_date || request.departure_date || "";
          if (column === "return_date") return offer.return_date || request.return_date || "";
          if (column === "currency") return offer.currency || (offer.price && offer.price.currency) || "";
          if (column === "amount") return offer.amount || (offer.price && offer.price.amount) || "";
          if (column === "flight_numbers") return (offer.flight_numbers || []).join(" ");
          return offer[column] || "";
        }),
      );
    }
    return rows.map((row) => row.map(csvCell).join(",")).join("\n");
  }

  function csvCell(value) {
    const text = String(value == null ? "" : value);
    if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
    return text;
  }

  function copyText(text, message) {
    if (!latestPayload) return;
    if (typeof GM_setClipboard === "function") {
      GM_setClipboard(text, "text");
      setResult(message);
      return;
    }
    navigator.clipboard
      .writeText(text)
      .then(() => setResult(message))
      .catch(() => setResult("复制失败，浏览器未授权剪贴板"));
  }

  function downloadText(text, filename, type) {
    if (!latestPayload) return;
    const blob = new Blob(["\ufeff", text], { type });
    if (typeof GM_download === "function") {
      const reader = new FileReader();
      reader.onload = () => {
        GM_download({
          url: String(reader.result),
          name: filename,
          saveAs: true,
          onerror: () => downloadBlob(blob, filename),
        });
      };
      reader.onerror = () => downloadBlob(blob, filename);
      reader.readAsDataURL(blob);
      return;
    }
    downloadBlob(blob, filename);
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  function findResultScroller() {
    const cards = collectCards({ viewportOnly: true });
    const candidates = new Map();
    for (const card of cards) {
      let element = card.parentElement;
      while (element && element !== document.body) {
        if (isScrollable(element)) {
          const current = candidates.get(element) || 0;
          candidates.set(element, current + 1);
        }
        element = element.parentElement;
      }
    }

    let best = null;
    let bestScore = 0;
    for (const [candidate, count] of candidates.entries()) {
      const score = count * 100 + Math.min(candidate.scrollHeight - candidate.clientHeight, 1000);
      if (score > bestScore) {
        best = candidate;
        bestScore = score;
      }
    }
    return best || document.scrollingElement || document.documentElement;
  }

  function isScrollable(element) {
    const style = getComputedStyle(element);
    const overflowY = style.overflowY;
    return (
      /(auto|scroll|overlay)/.test(overflowY) &&
      element.scrollHeight > element.clientHeight + 120 &&
      element.clientHeight > 120
    );
  }

  function scrollForward(scroller) {
    const step = Math.max(360, viewportHeight(scroller) * SMART_SCROLL_STEP_RATIO);
    if (scroller === document.scrollingElement || scroller === document.documentElement) {
      window.scrollBy({ top: step, left: 0, behavior: "auto" });
      return;
    }
    scroller.scrollTop += step;
  }

  function scrollMetric(scroller) {
    if (scroller === document.scrollingElement || scroller === document.documentElement) {
      return {
        top: window.scrollY || document.documentElement.scrollTop || 0,
        height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight),
        viewport: window.innerHeight || document.documentElement.clientHeight,
      };
    }
    return {
      top: scroller.scrollTop,
      height: scroller.scrollHeight,
      viewport: scroller.clientHeight,
    };
  }

  function isAtScrollEnd(scroller) {
    const metric = scrollMetric(scroller);
    return metric.top + metric.viewport >= metric.height - 12;
  }

  function viewportHeight(scroller) {
    if (scroller === document.scrollingElement || scroller === document.documentElement) {
      return window.innerHeight || document.documentElement.clientHeight || 600;
    }
    return scroller.clientHeight || 600;
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function fieldTexts(root, selectors) {
    const texts = [];
    for (const selector of selectors) {
      const nodes = Array.from(root.querySelectorAll(selector)).slice(0, 20);
      for (const node of nodes) {
        const text = normalizeText(node.innerText || node.textContent || "");
        if (text && text.length <= 160) texts.push(text);
      }
    }
    return texts;
  }

  function elementText(element) {
    const parts = [element.innerText || element.textContent || ""];
    const labelled = Array.from(element.querySelectorAll("[aria-label], [title]")).slice(0, 40);
    for (const node of labelled) {
      parts.push(node.getAttribute("aria-label") || "");
      parts.push(node.getAttribute("title") || "");
    }
    parts.push(element.getAttribute("aria-label") || "");
    parts.push(element.getAttribute("title") || "");
    return normalizeText(parts.join(" "));
  }

  function timestampForName() {
    return new Date().toISOString().replace(/[:.]/g, "-");
  }

  function isElementCollectable(element, options) {
    if (!element || element.closest(`#${PANEL_ID}`)) return false;
    if (!isElementVisible(element)) return false;
    if (options.viewportOnly && !intersectsViewport(element)) return false;
    return true;
  }

  function isElementVisible(element) {
    const style = getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function intersectsViewport(element) {
    const rect = element.getBoundingClientRect();
    const width = window.innerWidth || document.documentElement.clientWidth;
    const height = window.innerHeight || document.documentElement.clientHeight;
    return rect.bottom >= 0 && rect.right >= 0 && rect.top <= height && rect.left <= width;
  }

  function rectArea(rect) {
    return Math.max(0, rect.width) * Math.max(0, rect.height);
  }

  function normalizeText(text) {
    return String(text || "").replace(/\s+/g, " ").trim();
  }

  function removeEmpty(value) {
    const output = {};
    for (const [key, item] of Object.entries(value)) {
      if (item === undefined || item === null || item === "") continue;
      if (Array.isArray(item) && item.length === 0) continue;
      if (typeof item === "object" && !Array.isArray(item) && Object.keys(item).length === 0) {
        continue;
      }
      output[key] = item;
    }
    return output;
  }

  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectPanel);
  } else {
    injectPanel();
  }
})();
