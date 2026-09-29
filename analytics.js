/* Visitor counter: Cloudflare Web Analytics (no cookies, no personal data).
   The token below is the site's public counter id from dash.cloudflare.com > Web Analytics.
   To switch counting off, make the token an empty string: var HATZ_CF_TOKEN = ""; */
var HATZ_CF_TOKEN = "f4ee0692c7414191a8321dff6e6206b7";
if (HATZ_CF_TOKEN) {
  var s = document.createElement("script");
  s.defer = true;
  s.src = "https://static.cloudflareinsights.com/beacon.min.js";
  s.setAttribute("data-cf-beacon", JSON.stringify({ token: HATZ_CF_TOKEN }));
  document.head.appendChild(s);
}
