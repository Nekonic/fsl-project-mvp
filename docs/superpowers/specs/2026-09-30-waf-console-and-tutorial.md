# A real WAF console for the blue team, and a tutorial over it

2026-09-30. Research, not a decision. The user would rather give the blue team
a real WAF console than root on the gateway, and wants to embed it in an
iframe so a tutorial can point at its buttons ("<- press this"). Each claim
below was fetched and checked by a second agent.

## Which WAF has a console

- **ModSecurity has none.** libmodsecurity is a library and the nginx
  connector is configured only by directives. The old consoles are dead or
  were built for ModSecurity 2.x audit logs: jwall's AuditConsole site is
  gone, WAF-FLE's last commit was 2015, and both only viewed events.
- **BunkerWeb is the one that fits.** AGPLv3, built on nginx, ships
  ModSecurity v3 with CRS 4, amd64 images (1.6.15, 2026-09-21). Its UI is free
  and switches detect/block, edits custom ModSecurity rules (`modsec` after
  CRS, `modsec-crs` before) and shows reports. A separate REST API does the
  same writes and can issue tokens scoped to `*_read`.
- **Ruled out.** SafeLine: its own closed detector (no CRS rule text for
  `expect`), multi-user is Pro-only, and a 2026 advisory has no confirmed fixed
  version. open-appsec: the console is SaaS, or a local UI only by replacing
  nginx with Nginx Proxy Manager, and its ML engine gives no signature text.
  nginx-ui ships a web terminal, which is root.

BunkerWeb facts that matter here:

- `SECURITY_MODE=detect` forces `DetectionOnly` whatever
  `MODSECURITY_SEC_RULE_ENGINE` says; both decide the mode.
- There is no audit-log format setting (Serial by default), and ingest and
  `expect` read the JSON audit log today. Unverified whether a custom config
  can set `SecAuditLogFormat JSON`.
- **A writer is an admin.** BunkerWeb documents that config, service and
  plugin writes are code execution on its host, so a blue writer is root on
  the gateway in all but name. The score must come from logs shipped off the
  VM as they happen, to a store the UI process cannot write; Suricata over
  Tap-as-a-Service stays the independent witness. A writer can also switch
  logging off, so log silence during a session has to be noticed.
- The API has no reports or events endpoint; scoring stays on Elasticsearch.
- Set `API_TOKEN` (still optional in 1.6.15), and narrow `API_WHITELIST_IP`
  and `UI_FORWARDED_ALLOW_IPS` (defaults to all of RFC 1918) to the platform.

## What an iframe can and cannot do for a tutorial

- **Same origin as the platform: rejected.** A tutorial could then reach
  every button, but so could a red-team XSS payload rendered in the WAF's
  logs: script in a same-origin frame reaches `window.parent`, and its
  requests to `/api/` carry `Sec-Fetch-Site: same-origin` with a matching
  `Origin`, which `SameOriginOnly` accepts. A sandbox cannot help: with
  `allow-scripts` and `allow-same-origin` a same-origin frame removes its own
  sandbox (MDN). Log-rendered stored XSS is a recurring bug class in admin
  consoles, and sending XSS is the red team's job.
- **Different origin: the parent sees a rectangle.** `contentDocument` is
  null, click events end at the frame's own window, and `activeElement` only
  says focus went into the frame. An arrow drawn by the parent can only sit at
  fixed coordinates, which drift with scroll, resize and every UI upgrade.
  Shepherd's maintainers mark cross-origin targets won't-fix; driver.js,
  Intro.js and react-joyride have no frame support at all.
- **A live arrow on a real button needs code inside the WAF's page.** Either
  the reverse proxy injects a small guide script (nginx `sub_filter`, carrying
  the response's CSP nonce), or a BunkerWeb UI plugin hook adds it (an
  undocumented hook, running our code in the vendor process). The script
  reports positions to the platform by `postMessage`, numbers only, with exact
  `targetOrigin` and origin checks on receipt. Every message is treated as
  possibly written by the red team: it moves an arrow, never advances a
  scored step and never reaches `/api/`.
- **Steps advance on the WAF's state, not clicks.** The platform reads the
  WAF API with a `service_read` token and advances when, say, the mode became
  block. A click on Save is not the mode changing, and this is the repo's own
  rule that the system decides, not the platform's belief. The API reports
  saved config; an instance applies it after a sync or reload, so "in force"
  may need a probe through the WAF.

What embedding costs:

- BunkerWeb frames only from itself (`frame-ancestors 'self'` and
  `X-Frame-Options: DENY`). The proxy must rewrite `frame-ancestors` inside a
  CSP that carries a new nonce on every response; a static header cannot.
  Untested.
- Its login cookie is `SameSite=Lax`, `__Host-`/`Secure` once a proxy sends
  `X-Forwarded-For`. It survives inside the frame only if the platform and the
  console are schemeful same-site: HTTPS on sibling hostnames of one
  registrable domain (for example `platform.range.test` and
  `waf.range.test`). The platform is `http://127.0.0.1:8000` today, and Django
  would need `SECURE_PROXY_SSL_HEADER`. Cookies do not isolate by port, so a
  separate hostname, not just a port.
- The iframe gets a sandbox without top-navigation or popup tokens.
- Selectors, the nonce capture and the header rewrite break on BunkerWeb
  upgrades (roughly monthly): pin the image by digest and fail verify when
  they stop matching.
- Actions taken inside the frame bypass `/api/`. The REST-first rule is kept
  only if the platform's `/api/` wraps the BunkerWeb API for every action the
  exercise needs, and the frame is for learning the vendor's screens.

The cheapest path that works: two windows (the WAF console in its own tab,
as the red and blue consoles already are), step text with an annotated
screenshot in the platform, advancing on WAF state through the API. No header
surgery. The live arrow is the injected-script step on top of that.

## Decided (the user, 2026-09-30)

- The red team is not assumed to attack the blue team's log console; that
  scenario is out of the exercise. Ordinary XSS payloads aimed at the target
  still land in the WAF's logs, which is why the console stays on its own
  origin, as the new-tab default already has it.
- The WAF should be what Korean practitioners use. If no such WAF can be had
  with a GUI, Elasticsearch stays the place to read detections and the
  platform console stays the place to change the IPS. None can (below), so
  that fallback is the plan: nginx + ModSecurity v3 + CRS on the gateway,
  its audit log in Elasticsearch read through the blue console, Suricata
  changed from the console.

## What Korean practitioners run (checked 2026-09-30)

Kept as research only: the user ruled out Korean and commercial WAFs
altogether (2026-09-30), to stay clear of licensing.

- The IT Security Certification Center's list, filtered to web firewalls,
  holds nine valid certificates, all Korean: Penta Security WAPPLES (SA v7.0,
  v7.0, v6.0; EAL4), MonitorApp APPLICATION INSIGHT WAF SE (V6.0, V5.0;
  EAL2), Piolink WEBFRONT-K V4.0 (EAL4) and WEBFRONT-KS V4.0 (EAL2), Soosan
  INT eWalker WAF V10 (EAL4), ASTSoft Kuipernet WA V1.0 (EAL2). Since 2022 a
  security-function certificate can stand in for CC, and since November 2022
  the NIS sorts institutions into groups that verify fully, partly or not.
- No independent market share is public. Penta says WAPPLES holds 56% of
  public procurement (2025); MonitorApp calls AIWAF domestic No. 1 with about
  4,000 customers. Both are vendor claims; nothing covers the private sector.
- Korean clouds resell them: NHN Cloud (WAPPLES SA, WEBFRONT-KS), NAVER and
  Kakao Cloud (WAPPLES SA from 250,000 KRW a month, web console, syslog to
  SIEMs).
- None can be put on this cloud without the vendor. WAPPLES SA and
  MonitorApp's AIWAAP-VE support KVM, but Penta ships the image once a client
  decides to deploy and MonitorApp routes KVM through a demo request; the
  self-serve trials are 30-day AWS images. Penta donated WAPPLES to Hoseo
  University's training lab at the end of 2025, so an academic or PoC licence
  is a vendor request worth making, not engineering work.
- Open source: KISA pointed small organisations at ModSecurity in 2015, and
  nothing newer was found. BunkerWeb stays the free-GUI option on the same
  engine; its bad-behaviour bans, rate limits and blacklist are on by
  default and act whatever ModSecurity's mode, so they must be off before the
  red team meets it, or the score counts BunkerWeb's bans. SafeLine's free
  edition cannot export attack logs.

## Settled since (the user, 2026-09-30)

- No BunkerWeb for now, so its account, HTTPS and hostname questions fall
  away; the WAF console opens in its own tab if one comes later.

Sources: owasp-modsecurity/ModSecurity and ModSecurity-nginx, OWASP's 2024
handover post, Ristic 2010, WAF-FLE; bunkerity/bunkerweb (README, `plugin.json`,
`src/ui/main.py`, docs, advisories), Docker Hub; SafeLine and open-appsec docs
and advisories; MDN (same-origin policy, `contentDocument`, `activeElement`,
`postMessage`, iframe `sandbox`, `Sec-Fetch-Site`, Site, cookies), the DOM
spec, RFC 6265 §8.5, W3C CSP3; Shepherd.js issues #1692, #3087, #3478;
nginx `ngx_http_sub_module` and `ngx_http_mirror_module`; this repo's
`platform/api/refusals.py` and `platform/tests/test_cross_site.py`.
