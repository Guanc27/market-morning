/**
 * Patches the embedded Market Morning UI for hosted SaaS:
 * - Points API at same origin
 * - Injects JWT on fetch calls
 */
(function () {
  const origin = window.location.origin;
  window.MM_API = origin;

  const origFetch = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input.url;
    if (url.startsWith(origin) || url.startsWith("http://127.0.0.1:8742")) {
      init = init || {};
      const headers = new Headers(init.headers || {});
      try {
        const token = window.parent.__mmToken;
        if (token) headers.set("Authorization", `Bearer ${token}`);
      } catch (_) {}
      init.headers = headers;
      if (url.startsWith("http://127.0.0.1:8742")) {
        input = url.replace("http://127.0.0.1:8742", origin);
      }
    }
    return origFetch(input, init);
  };

  // app.js hardcodes API — override after load via defineProperty if needed
  const _define = Object.defineProperty;
  try {
    _define(window, "API", {
      configurable: true,
      get() { return origin; },
    });
  } catch (_) {}
})();
