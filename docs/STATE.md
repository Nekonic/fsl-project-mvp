# State

The handover between sessions. Keep it true; it is all the next session gets.

Updated: 2026-09-24 (a breach belongs to the attack that was running when the target recorded it)

## Where things stand

The repo moved from "prove the hypothesis" to "build the smallest product that
demonstrates it" on 2026-09-20. The design is in
`docs/superpowers/specs/2026-09-20-product-flow-design.md` and runs in four
phases; all four are done.

`bin/verify` is green. It prints the scores; they are not written down here,
because they move whenever the rules or the cases do.

`metrics.json` holds the baseline. Read it there rather than here: a copy in
prose is a copy that goes stale, and this one already did twice.

**You can now run the whole loop in a browser.** Open `/`, start a session,
then open the two windows side by side: fire cases from one, watch the
score move in the other, edit a Suricata rule and fire again. The red window
also has a Kali terminal - name an attack, press start, type it, press stop,
and it is scored two ways at once - by time and source, and by a marker the
proxy stamps - with both answers side by side in the blue window.

The blue window is a live console now: it ingests and redraws on a timer, so
alerts arrive while you watch rather than when you press something, and any
alert opens the whole Elasticsearch record behind it.

## In progress

Nothing half-finished. The last session left the tree green and committed.

## The substrate seam

Docker was the MVP shortcut; OpenStack was always the target. That move is now
most of the way done, and the remaining work is named below rather than
guessed at.

`platform/range/` holds the port: `describe() -> Shape` and
`runner(role, segment) -> Runner`. `platform/range/docker.py` implements both,
and `platform/range/declaration.yaml` tells it what the range means.
Nothing under `platform/scoring/`, `platform/ingest/`, `platform/rules/` or
`redteam/harness.py` contains the word docker, and neither does
`platform/topology.py`, `platform/attacker.py` or `platform/objectives.py`.
`test/range.py` is the same idea for the acceptance suite, which used to shell
out to `docker exec` in five files.

Two mechanics were measured against the running stack rather than assumed, and
both are load-bearing:

- Suricata is PID 1 in its container, so `kill -USR2 1` through the runner is
  exactly `docker kill -s USR2`. With stdin round-tripping through
  `docker exec -i`, write, validate and reload collapse into one operation.
  That is why the port has two verbs and not five, and why five settings and
  four compose environment lines went away.
- The marker lives only on Suricata `http` documents, never on `alert` ones -
  0 of 3,969 alerts carry `http.request_headers`. Any change that filters the
  ingest to `event_type: alert` destroys correlation entirely.

The range is now **declared**. `platform/range/declaration.yaml` holds the one
substrate-neutral statement of it - per segment an id, the name a person reads
and the origin it attacks from, plus the role table naming the host that fills
each job - and three readers share it: `range/docker.py` merges the declared
identity into what the daemon allocated, `fsl/settings.py` takes the attacker
and proxy identity from it instead of restating them, and `test/range.py` builds
the acceptance suite's host table from it. The adapter no longer reads
`fsl.segment` or `fsl.origin`; it asks Docker only for addresses and membership,
which is exactly the set of questions Neutron can answer.

The subnet stays substrate-assigned, deliberately. Identity is declared,
allocation is reported: a subnet written into the declaration would be an
address fact the platform does not own, and when it disagreed with the one the
range handed out the console would bin alerts by a subnet nothing lives on.
Gateway settles it - nobody can declare that at all.

`compose.yaml` is the Docker realisation of the declaration and nothing
generates one from the other, so `platform/tests/test_declaration.py` holds them
together: a network built and not declared, a segment declared and not built, a
name or an origin changed on one side, or a role pointing at a container compose
does not define, each fails the suite naming the segment or the role.

`platform/range/openstack.py` **runs** now, against a fake cloud rather than a
cloud. `http_reader` authenticates to Keystone v3, carries the token, states
the Nova microversion it was written against, replaces a token the cloud has
expired and retries once, and names any other refusal. `describe()` goes end
to end over HTTP in `test_openstack_http.py` and comes back with a `Shape`.

What that does **not** prove: the fake serves the reference's response shapes,
not Neutron and Nova, and `runner` runs against an unprivileged sshd on
127.0.0.1 in `test_openstack_ssh.py`, not against an instance. Keystone is
simplified: the user's domain is always `default` and the project is an id.
What changed is that the code is executed rather than only read. `test_openstack_sketch.py` holds it to
the port and asserts nothing at runtime imports it. What it found is below;
`topology.shape()` consumed its `Shape` unchanged, which is the part that works.

Closed since the sketch was written: which origin is the default, how the
sensor is reloaded, whether a sensor is one of its segment's participants, how
many subnets a segment may carry, how a substrate object is bound to a declared
segment, and who starts a tool.

**The substrate starts the tools.** `redteam/harness.py` is gated core and ran
`docker run --rm --network ...` itself, with the network recovered by cutting
`waf-` off the target's hostname and pasting the project name back on - the
origin id it was built from had been thrown away two calls earlier. Core now
takes a launcher, the same way it takes a sensor: no `subprocess` import
remains in it. `Substrate.launcher(segment_id)` is the port's third verb, and
`test/test_tool_cases.py` fires one end to end, which nothing did before -
breaking the binding turns all three of its assertions red.

**A segment is bound by a mark it carries.** The Docker adapter used to cut the
compose project off the front of a network name, and the sketch matched a
Neutron network whose name happened to equal the declared id. Both were rules,
and both were wrong: compose lets a network override its own name, Heat appends
a stack suffix to every one it builds, Neutron does not keep names unique, and a
project called `fsl_lab` swallowed part of itself. Now whoever builds the range
marks each network with the segment it realises - a Docker label, a Neutron tag,
`fsl.segment.id` in both - and the adapter reads it. Nothing else is part of the
range, which is also the answer to a shared Neutron project handing back other
tenants' networks: the listing is filtered by `tags-any`, a documented Neutron
filter, so the cloud is never asked for them.

What is left for OpenStack, in order:

1. **Name resolution.** Nine places still name a host - `shop.com`,
   `wiki.internal`, `juice-shop:3000`, `proxy:8081`. Compose gives those away;
   Neutron does not. cloud-init writing `/etc/hosts` is the cheapest answer
   that keeps `shop.com` a name, which is the product - and `shop.com` is the
   one name worth keeping, because a range where the target has no name is not
   the product. The other two classes are gone: `FSL_TOOL_NETWORK`, and the
   five `waf-<origin>` aliases.

2. **The sensor's placement.** `network_mode: "service:waf"` puts Suricata in
   the WAF's namespace so it sees both legs of every proxied request. Neutron
   has no namespace sharing: either Suricata rides the WAF instance, or
   Tap-as-a-Service mirrors the ports. `Sensor(name, watches)` already carries
   the relationship either way, but nothing *supplies* it: Docker reads it off
   `NetworkMode: container:<id>` and Neutron has no such fact, so the sketch
   assumes the sensor watches the gateway. That assumption belongs in the
   declaration, beside the roles.

3. **The declaration has one attacker and the range has four origins.**
   Nova has no call that boots a host, hands back its stdout and deletes it,
   so a tool cannot be launched per attack the way `docker run --rm` does. It
   runs on an attacker that already stands on that segment, which is what a
   real range does - and which the declaration cannot express: `roles` names a
   single `attacker`, while Docker got away with it by starting a container on
   whichever network was asked for. Asking for a tool on a segment the
   attacker does not stand on now says exactly that rather than running it
   somewhere else. Either the declaration grows an attacker per origin, or the
   range accepts one attacking position on OpenStack. A decision, not a task.

4. **A role is found by a Nova server name.** The credentials are settled:
   `FSL_SUBSTRATE=range.openstack.connect` and `FSL_OPENSTACK_*` (keystone,
   user, password, project, ssh user, key, optional ssh config, region,
   interface), and a missing one is refused by its variable's name. What is
   not settled is the declaration's `roles` values: host names in substrate
   vocabulary (`fsl-kali` is a compose `container_name`, a Nova server name
   and, after `removeprefix("fsl-")`, a compose unit), and a Nova server name
   is not unique. Segments are bound by a tag for the same reason; roles are
   not yet.

5. **Whether the operator still looks like an outsider.** The rule that stops
   the red team calling the scoring API refuses any address standing in the
   range, and it works because the console arrives through Docker's published
   port and is therefore DNATed to a segment's gateway. A test runs the same
   rule against the sketch's `Shape` and gets the same participant set, so the
   mechanism is on the port and not on Docker. What cannot be checked without
   a cloud is the other half: whether a Neutron router presents the operator
   as the gateway the way Docker does, or as something else. If it presents
   the operator's own address, the rule still holds - that address stands on
   no segment. If it presents a node's address, the rule locks the operator
   out and lets the red team in, which is the failure worth testing first on
   a real cloud.

6. **Floating IPs and router SNAT.** A Nova instance reports both a fixed and a
   floating address, and the adapter keeps the fixed one. An attack leaving the
   range through a Neutron router is source-NATed, so the address Suricata sees
   is the router's, not the attacker's - the stamping proxy solves this on
   Docker and has no Neutron equivalent yet.

**What the sketch is, exactly.** There is no cloud here, so it runs against
fakes built from the vendor's published responses and against a local sshd.
Every field it reads is one the published API reference
names - `networks[].id`, `.name`, `.tags` and the `tags-any` filter from the
Networking v2.0 reference, `subnets[].cidr` and `.gateway_ip` from the same,
and `servers[].addresses` keyed by the network's label with `addr` and
`OS-EXT-IPS:type` from Nova's own List Servers Detailed example. A test holds
it to them. Reading that example is also what found the last bug in it: Nova
reports every fixed address a port has, including IPv6, and the sketch would
have drawn an instance at a v6 address while the console bins every alert by
an IPv4 subnet.

`docs/ARCHITECTURE.md` has the mechanism and the measured numbers.

## Done since v1.0

One line each.

**The range**
- The platform is told what the range means rather than asking the daemon:
  one declaration, a Docker adapter that fills in what it allocated, and a test
  that fails when compose and the declaration disagree.
- Three segments plus four origin networks; the WAF is the only intended way
  across, and the published port arrives on the outside one.
- The attacks come from four countries, chosen in the console; the stamping
  proxy rewrites the upstream so nobody types a routing name.
- The target is `http://shop.com` on port 80 - no appliance name, no port.
- The estate has an inside: an internal wiki reachable from the application
  and nowhere else, taken by SSRF, judged by its own access log.
- Filebeat's registry is a named volume, so a recreate does not re-ship every
  log it has ever read.

**The red team**
- One attacker image. Kali with nmap, whatweb, ffuf, gobuster, nikto, sqlmap,
  hydra and a wordlist; the same image a `tool:` case runs in.
- The shell is the red team; the case file is a scripted baseline. A labelled
  window is scored by time and source and by a marker the proxy stamps.
- Two routes out of the box - through the proxy for HTTP, direct for raw TCP -
  and the window records whichever the work used.
- Cases declare what they take, and seven objectives fall instead of two.

**The score**
- Objectives lead it: the target flips its own `solved`, so the platform
  labels nothing about what an attack achieved.
- A breach is credited to the attack that took it, using the target's own
  timestamp, with a tolerance for the two clocks involved.
- A true positive has to name the right rule: a case declares `expect`, and an
  alert that does not mention the attack's mechanism is reported uncorroborated.
- Silencing a rule is the verdict, and it expires by itself.

**The console**
- One blue console: Dashboard, Live, Scoreboard, Rules. It ingests on a timer,
  and any alert opens the whole Elasticsearch record behind it.
- The dashboard is top-N tables - source addresses with their zone and
  country, destinations, signatures, request paths - plus a map and a trend.
- Every value is escaped before it reaches the page, and there is a test that
  says so. The console used to run the attacks it collected.
- Every UI action is a REST call first.

**The token hands back the endpoints**
- The adapter took three addresses as configuration - Keystone, Neutron, Nova -
  which is the name-resolution problem in its own file. Keystone's token
  response carries a `catalog`, so `discover()` asks for the one address a
  deployment cannot avoid knowing and reads the other two off the answer.
- A catalogue holds `public`, `admin` and `internal` endpoints for the same
  service in each region. A platform on a management network wants a different
  one than a browser does, so which is a deployment's choice, defaulting to
  `public` in `RegionOne`. A service the catalogue does not carry is refused by
  name and region rather than handed back as an empty URL that fails later
  somewhere else.
- The same response carries `expires_at`, and the adapter uses it: a token
  within 30 seconds of dying is replaced before the call rather than after a
  401. The 401 retry stays as the backstop for a token the cloud rejects
  early. Three tests hold the middle: renew when it is nearly spent, reuse
  when it is not, and fall back to the 401 path when the response carries no
  expiry at all. Without the middle one, "renew before expiry" collapses into
  a Keystone round trip in front of every single read.

**A breach belongs to the attack that was running when the target recorded it**
- `attribute()` credited any case that had started within two minutes before
  a breach, and read neither when it ended nor whether it was an attack. A
  breach three minutes into a five-minute terminal window belonged to nobody
  and scored undetected at full damage; a benign case's false positive
  "detected" a breach 75 seconds after that case had finished.
- Now only a malicious case can take an objective, and it is a candidate when
  it overlaps the interval the breach could have happened in. With the
  target's own stamp that is the stamp plus its resolution, and 100 ms either
  side: Juice Shop writes milliseconds, the wiki's nginx log whole seconds - a
  read at .900 is stamped .000, before the case that caused it. Without a
  stamp it is the two minutes before the breach was seen, as before. The
  interval is stored with the objective (migration 0008); rows from before it
  keep the old rule.

**A session closes once, and what it lost at the end is on its board**
- Closing was a bare write of `ended_at`, and the session page always offers
  Close: a second close moved the end, widening the window its alerts are read
  from into later sessions' traffic. A closed session answers 409.
- Nothing observed the target at close. The board polls every ten seconds, so
  a breach in the last seconds was never recorded and the session read as
  untouched. Close takes one last observation first.
- An attack still running when the session closed was recorded with its
  evidence outside the window it is scored from. The session's end now
  stretches to cover a case that finishes after it.
- Since unreadable wiki became an error, it also threw away every verdict
  Juice Shop gave in the same read. The session path keeps Juice Shop's
  answer and reports the wiki as `unreadable`; a session with no baseline yet
  still waits for a full read, which is the recorded late-baseline decision.

**The range cannot reach its own judge**
- Found by a production-readiness audit: eight lens agents, two refuters per
  finding, 34 of 34 serious findings survived. The largest: every published
  port answered on every address, so from the attacker box and from the wiki,
  their own segment's gateway forwarded `:8000` (the scoring and rules API),
  `:9200` (Elasticsearch, unauthenticated), `:7681` and `:8080` back into the
  platform - measured, eight of eight reached. The side being scored could
  rewrite the rules or the alerts it is scored on. The reachability rule did
  not see it: through the hairpin the request arrives from a gateway, which is
  exactly how the operator arrives.
- Every port is published on `127.0.0.1` now. The Mac's listeners went from
  `*` to `127.0.0.1` with it, so the LAN no longer gets a root shell on 7681.
  A console opened from another machine needs a tunnel. `DJANGO_DEBUG=1` in
  compose stays: with loopback only, a traceback reaches the operator alone.

**The API refuses what it cannot mean**
- `POST /api/rules/apply/` with no `content`, or `null`, applied an empty rule
  file: the sensor reloaded with nothing and every later attack scored a miss.
  `content` must be a string now; an empty string sent on purpose still works.
- A case's ground truth was checked for presence, not type: `"malicious":
  "false"` was stored as an attack, turning a TN into a FN. It must be a
  boolean; times must be ISO 8601 with an offset and in order, `source_ip` an
  address, and a second copy of a case is 409 rather than a 500.
- Malformed JSON, a body that is not an object, a suppression of `-5`, `0`,
  `nan` or a billion minutes, and a cursor like `--1` were each a 500 or an
  unbounded suppression. `_payload` raises `BadRequest`, which the same
  middleware that answers `RangeUnavailable` (now `api/refusals.py`) turns into
  400; a suppression lasts more than 0 and at most 24 hours.

**Any view the range cannot answer is a 503 with the range's reason**
- Rebuilding the platform image without the host's socket group
  (`DOCKER_GID=$(bin/docker-gid)`) made every docker call "permission
  denied". Before the runners told a daemon error from a failed command, the
  rules endpoint would have served that text as the rule file with a 200;
  after, it was a bare 500, and so were validate, apply, suppress and the
  attacker label - none of them handled `RangeUnavailable`.
- One middleware, `api/unavailable.py`, answers `RangeUnavailable` from any
  view with 503 and the range's own words, and the six per-view copies of
  that handler are gone. `_segments()` still swallows it on purpose: a
  dashboard draws without zones rather than not at all.

**The OpenStack substrate can be selected**
- `FSL_SUBSTRATE=range.openstack.OpenStack` failed on a missing `cloud`
  argument: nothing turned settings into one. `range.openstack.connect` does,
  from `FSL_OPENSTACK_*`, and `/api/origins/` draws a range end to end through
  Django against a fake Keystone, Neutron and Nova.
- `range.substrate()` builds an adapter per request, so each request would
  have signed in to Keystone and read its catalogue again. The discovered
  endpoints and the reader holding the token are kept per set of
  credentials; a test counts the tokens.
- The platform image had no ssh client, so every runner call from it on
  OpenStack would have been `FileNotFoundError`. It carries `openssh-client`.

**A rebuilt instance is trusted again; an impostor is not**
- The critics' top finding. Trust-on-first-use keyed by address locks the
  platform out of every rebuilt instance for good: a rebuild recreates the
  root disk (Nova api-ref) and cloud-init makes new host keys by default
  (`ssh_deletekeys: Default: true`), on the same fixed IP. Reproduced: every
  later call to that role refused until someone ran `ssh-keygen -R` inside the
  platform.
- A host key is now filed under the instance's generation, not its address:
  `HostKeyAlias fsl-<server id>-<launched_at>`. Nova's own source resets
  `launched_at` on rebuild (`_do_rebuild_instance` ->
  `_update_instance_after_spawn`, `nova/compute/manager.py`) and never on
  reboot. So a rebuild or a new instance on an old address is met for the
  first time, and a different key from an instance Nova says has not changed
  is refused - with the fingerprint and the offending known_hosts line.
- The adapter writes an ssh config per call that `Include`s the deployment's
  first. ssh takes the first value it finds, so a deployment that pins keys
  (`StrictHostKeyChecking yes`, its own known_hosts) is no longer overruled by
  a command-line `accept-new`, and the alias is scoped to the instance's
  address so a `ProxyJump` bastion does not have its key filed under it.
  Both run in the tests, bastion included.
- Still trust-on-first-use per generation. Where known_hosts lives is the
  deployment's (ssh's default is the platform user's home, which a container
  loses). The stronger answer is reading each instance's keys off its console
  (`os-getConsoleOutput`; cloud-init prints them between `BEGIN SSH HOST KEY
  KEYS` markers), with two caveats found by the critics: libvirt returns only
  the last 100 KiB of the console, and the guest writes its own console.

**A range that cannot answer says so**
- Firing a case, opening a session and reading objectives each let
  `RangeUnavailable` through as Django's bare 500, dropping the reason the
  range gave. The first is a 503 with it now; a wiki that cannot be read is
  `ObjectivesUnavailable`, so a session still opens and takes its baseline on
  the first poll.
- On Docker a stopped container was not even an error. `docker exec` exits 1
  for "is not running", for "Cannot connect to the Docker daemon" and for a
  command that failed, and the runner recognised only "No such container". A
  stopped wiki read as a wiki nobody had read - the internal objective scored
  as not taken - and a daemon error could come back as the rules file's
  content. Found by stopping the wiki against the live stack, after the unit
  tests had passed. Both adapters now use the report ssh needed, shared in
  `range/ports.py`: the command runs under `sh -c --` and prints its own exit
  status, and without that report nothing ran.
- `bin/verify` restarts the platform before the acceptance run. It serves with
  waitress, which never reloads, and the process answering this session's
  verifies had started before the code under test: the acceptance half had
  been checking whatever was loaded when the container last started.

**An address only the WAF caught is on the map**
- `test_origins` went red once in two identical runs. The session's Brazil
  detections were ModSecurity's; Suricata's Brazil alerts reached
  Elasticsearch six seconds after the event and after the test had read the
  map. A ModSecurity record carries its source as `transaction.client_ip`
  with no `src_ip`, and the pipeline geolocated `src_ip` with
  `ignore_missing`, so it skipped every one: an address the WAF alone caught
  was never placed, whatever the timing.
- The pipeline geolocates both fields, ingest keeps the record's `src_geo` on
  each WAF detection, and an acceptance test refuses to run the suite when the
  pipeline Elasticsearch runs is not the committed one - it is installed by
  hand, so it drifts silently otherwise. Records indexed before the change
  stay unplaced.

**A command over ssh is the command that was asked for**
- Run against a real sshd rather than a mocked `subprocess.run`, the runner
  broke the port's contract. ssh(1): arguments "will be appended to the
  command, separated by spaces" and handed to the remote shell, so `'a b'`
  arrived as two arguments and `c;d` ran `d`. argv is quoted now.
- An argv starting with `-o` was read by ssh as its own option - options are
  parsed after the destination too - and ran a `ProxyCommand` on the platform.
  The remote command now always starts `sh -c --`; the `--` matters twice,
  because the remote `sh` also takes a script starting with `-` as options
  (checked in dash, busybox and bash, the shells the range's images carry).
- ssh(1): it "exits with the exit status of the remote command or with 255 if
  an error occurred", so 255 said nothing. sqlmap exits 255 on an unhandled
  exception; that is a tool that ran. The remote shell now reports the
  command's status last on stderr: with the report it is `Ran`, whatever the
  code - a `kill -9` is 137, as on Docker; without it the connection ended
  first and it is `RangeUnavailable`.
- ssh's own messages go to a log (`-E`), not into `Ran.output`; the first
  contact's "Permanently added" line used to land there. That log is the reason
  a failure gives: host key verification, permission denied, refused.
- `BatchMode` alone refuses every host key nobody has seen - every instance of
  a fresh cloud. `-n` when there is no input: the remote `cat` read the
  platform's own stdin. `IdentitiesOnly`: an agent holding six other keys used
  up `MaxAuthTries` first. `ConnectTimeout` and `ServerAlive*`: a host that
  accepted and said nothing, or went silent mid-command, held the call for
  the whole timeout, 600 s for a tool.
- In both adapters: a timeout says it was one and that the command may still
  be running (it is not killed on the host), and output that is not UTF-8 no
  longer raises `UnicodeDecodeError` - neither `Ran` nor `RangeUnavailable`, so
  no caller handled it, on a path that reads logs the red team can write.
- The Keystone sign-in sent the ssh login as its user name. `Cloud.user` and
  `Cloud.ssh_user` are separate, and a refused sign-in carries Keystone's reason
  instead of "no X-Subject-Token".
- Found by five sourced critics with a refuter each: 8 of 17 findings survived.
  Every fix has a test that fails without it (13 mutants, 13 caught).

**A tool runs where the attacker already is**
- `launcher` raised NotImplementedError. Implementing it turned up the reason:
  there is no Nova equivalent of `docker run --rm image argv`. Booting is
  minutes and output comes back only through a console log or ssh. So a tool
  runs over ssh on the attacker standing on that segment, and asking for any
  other image is refused rather than quietly ignored.
- `runner` re-read the entire cloud on every command - networks, subnets and
  servers, paginated - to find one address. Applying one Suricata rule set is
  a validate, a read, a write and a reload: four full reads. The shape is read
  once per adapter now, and `range.substrate()` builds a new adapter per
  request, so nothing holds a range that has since changed. Both halves are
  pinned by tests.

**The adapter runs**
- `X-OpenStack-Nova-API-Version` is sent on every call. Nova's own guide: with
  neither that header nor `OpenStack-API-Version`, it acts "as if the minimum
  supported microversion was specified". The adapter would have been handed
  2.1 silently while the sample its fields were checked against was 2.100.
  The fields it reads carry no "New in version" marker, so 2.1 is enough - but
  by luck, and now by statement.
- A Keystone token has a lifetime and a console outstays it. A 401 now buys
  one fresh token and one retry; a second 401 is reported. Without that the
  range simply becomes unreadable after an hour, with no reason on screen.

**A cloud answers in pages and the sketch read one**
- Found in the vendor's own example, not by reasoning: Neutron's List Networks
  sample response is labelled *first page* and carries
  `networks_links` with `rel: next`. Nova documents `servers_links` as present
  "when the number of servers exceeds limit parameter or [api]/max_limit".
- The sketch took `["networks"]` off the first page and dropped the rest. A
  segment past the page boundary makes `describe()` report it as a segment the
  cloud does not have; an instance past it vanishes from the map and leaves
  every one of its alerts with a blank host name. Both fail quietly and both
  arrive the moment the range grows.
- All three list calls follow the link now, by requesting the `href` the cloud
  handed back rather than rebuilding a URL, so whatever filter or limit is
  inside it survives. A link that loops stops after 50 pages and says so
  instead of hanging the console.
- This is the part of an OpenStack transition that can be checked without a
  cloud: the responses come from the reference, so the behaviour is pinned to
  what the vendor publishes rather than to what I assumed.

**One place turns a name into a substrate**
- `redteam/run.py` constructed `range.docker.Docker` by name while the
  platform resolved `FSL_SUBSTRATE`. I put that there earlier in this session.
  On any other substrate the console would fire attacks and the command line
  would not, and nothing would say why. Both go through `range.substrate()`
  now, and a test refuses a second `import_string` site.
- Unifying them exposed the next one immediately: `FSL_SUBSTRATE_OPTIONS`
  carried `project`, Docker's compose project name, whatever substrate was
  selected. Options are keyed by substrate now and every one is given the
  declaration. Checkable today without a cloud:
  `FSL_SUBSTRATE=range.openstack.OpenStack .venv/bin/python redteam/run.py`
  used to fail with `unexpected keyword argument 'project'` and now fails with
  `missing 1 required positional argument: 'cloud'` - the thing a deployment
  actually has to supply.

**A destination is an address and a port**
- `session_top` and the alert table pasted them into one field, `172.30.0.2:3000`,
  so nothing could sort or filter on either and a reader had to parse it back.
  Two columns now, in both tables and both languages. The rows stay keyed on
  the pair: one host on two of its addresses is still two rows, because the
  WAF's outside leg is the attack arriving and its estate leg is the same
  attack being forwarded inward, and those are worth telling apart.

**A window that could not be read whole says so**
- `elastic.fetch` reads 5000 records, oldest first, and `ingest_detections`
  reported the shortfall to nobody. Measured on the live index: a three-day
  window is 5000 read of 42,231. Oldest-first means truncation drops the
  *newest* alerts, so the cases fired last become FN and the benign ones fired
  last become TN - a busier red team makes the defence look better.
- `Session.truncated` and `read_of` are set at ingest and never cleared by a
  later ingest that happened to fit, and the score carries
  `score.warning.truncated` with both counts. Verified live: a widened window
  reported 5000 of 41,720 on the page, in both languages.

**One of my own tests was asserting a falsehood**
- Last round I added "no alert in a red team window may be unmarked". It went
  red, and the product was right: the unmarked alerts were at 04:21:10 from
  the proxy, and the session opened at 04:21:10.903. A window reaches a minute
  either side, so it holds traffic from whatever used the range just before.
  That is why `unattributed` is a reported number and not an assertion.
- Narrowed to what it was built to catch - the stack alerting on traffic it
  sent to itself, by loopback source or the numeric-Host signature - and
  proved it still bites by reintroducing the health-check bug and watching it
  go red, then removing it again.
- It stays sensitive to the same minute of slack, so its failure message now
  says to check whether the signature is still being produced before hunting
  the code.

**The scoreboard stopped answering the party it is scoring**
- `fsl-platform` sits on all six segments and `waitress` listens on 0.0.0.0, so
  the red team's own terminal reached the scoring API. Measured before the fix:
  `GET /api/rules/` from `fsl-kali` returned 200. `POST /api/rules/apply/` from
  there rewrites the detector - blank it and every attack is a miss, match the
  marker header and every attack is a hit - so every cell of the confusion
  matrix was writable by the party being measured.
- No accounts were added; CLAUDE.md's decision stands. The API refuses any
  address that stands inside the range. The two callers are distinguishable
  without a login, and it was measured rather than assumed: a request through
  Docker's published port arrives from a segment's **gateway**, `5.188.10.1`,
  and `fsl-kali` arrives as a **node**, `5.188.10.2`.
- Live after the fix: operator 200, console 200, kali 403 with the reason.
- The participant set is read once per thirty seconds, not per request - the
  console polls several endpoints every few seconds and a read of the range is
  four Docker round trips. A test pins it at one read per eight requests.
- Still open: a host inside the range can send with another host's address, and
  a container recreated inside the cache window keeps its old answer. Both are
  written down in `docs/THREAT-MODEL.md` rather than left implied.

**An alert remembers who held the address when it was written**
- `Detection` stored an address and nothing else, and the dashboard named it by
  asking Docker who holds that address *now*. Compose assigns them by DHCP -
  nothing in the file pins one - so after a recreate the console reports
  whichever container inherited it. `172.30.0.3` is the wiki today and was the
  WAF when 885 alerts were written from it, which the dashboard would draw as
  the wiki attacking the target.
- The host is resolved once at ingest and stored on the row. Reproduced the bug
  in a unit test first: ingest under one shape, read under another, and the
  source came back `fsl-wiki`.
- Ingest still works with no range at all - the evidence is in Elasticsearch,
  not in Docker - and the name is simply blank. The unit guard that refused
  a real substrate call now raises `RangeUnavailable` rather than
  `AssertionError`, because a test that supplies no range and a range that is
  down are the same state to the code, and production handles that one.

**`$HTTP_PORTS` named a port on no wire the sensor watches**
- It was `8080`, the host-published port. Docker translates that before the
  packet reaches any interface in the WAF's namespace, so the only ports on
  the tap are 80 (nginx) and 3000 (the backend leg). Every published HTTP
  signature is written `$HOME_NET $HTTP_PORTS`, so a defender pasting one got
  a rule that validated, a sensor that reloaded, a case scored FN, and no way
  to tell a wrong regex from a wrong port variable.
- A/B, same rule as sid 9000001 with only the port term changed, config loaded
  inside the container checked each time: `"8080"` fired 0 while the shipped
  rule using `any` fired 4; `"[80,3000]"` fired 2 against the same 4.
- The first attempt to falsify this said the trap was not real. It was a bad
  experiment - a 12-second wait that did not cover the sensor's start - and it
  nearly buried a true finding. The A/B above verifies the loaded config from
  inside the container before each half.
- Two experiment rules were left behind in the shipped rule set during this,
  because the file is the live artifact and an experiment writes to it.
  `test_sensor_rules.py` refuses any sid at or above 9009000 in it.

**A strategy that cannot place a case says which ones**
- The comparison panel drew tp/fn/fp/tn for both strategies and threw the
  warnings away. Forcing time-window correlation onto cases that declare no
  source address gives every one of them a miss, so the panel showed a marker
  column with detections beside a window column of zeroes, and the operator
  read the second as a defence that failed rather than a question that cannot
  be asked. The panel carries each strategy's warnings now.
- `score.warning.no_source_ip` named case UUIDs. It names the cases.
- Rejected the critics' proposal to populate `source_ip` for console-fired
  cases from a new `scorer` role. Window correlation exists to score traffic
  that carries no marker - the human at the terminal - and those cases do set
  `source_ip` to the proxy: verified, session 622 scores `tp 1` under window.
  Feeding it the judge's own address would measure "did an alert come from the
  scoring platform within two seconds", which is not a fact about the defence.
  A zero with a stated reason beats a number that looks like a score.

**The score accounts for the evidence it throws away**
- `correlate` computed `unmatched_detection_ids` and nothing read it. TP, FP,
  FN and TN are counted over declared cases only, so an alert belonging to no
  case entered no number at all. `false_positive_rate = fp/(fp+tn)` therefore
  had a denominator equal to the benign case count - six - a granularity of
  0.167, and was printed to two decimals. A defence that alerted on every
  packet the range sends to itself and missed those six requests read 0.00.
- The score reports `unattributed` and `benign_cases` now, and the console
  shows the fraction (`1 / 6`) with the sentence "not a rate" beside it, and
  the unplaced count in its own tile. An acceptance test asserts the three
  numbers add up: attributed + unattributed == ingested.
- Fixing the health check emptied this out on a clean run: every alert in a
  `redteam/run.py` window now carries a marker, and an acceptance test refuses
  a run where the stack alerted on its own traffic. The 162-of-170 unattributed
  figure measured earlier was the health check firing CRS 920350 every ten
  seconds, not a property of the design.

**A defence cannot author its own evidence**
- `corroborated` asked whether a case's `expect` substring appears in any
  signature attributed to it, and the defence writes those signatures. One rule
  - `msg:"SQL XSS traversal Restricted File"`, `http.uri; content:"/"` - carries
  every `expect` value in the case file and fires on every request. Demonstrated
  live: it took every malicious case as a TP with `corroborated: true`. The
  block-everything defence the case file's own header says must not win, won.
- A signature that also fired on a case declared benign in the same session now
  corroborates nothing. The defender cannot fake discrimination, only claim it.
  Same run after the change: `path-traversal-ftp`, whose only alert was the
  catch-all, reports `corroborated: false` and raises `wrong_reason`, while the
  two cases ModSecurity caught with its own signatures keep their credit. TP,
  FP, FN and TN are untouched - `corroborated` is not an input to `detected`.
- Two things the experiment turned up on its own. A rule that inspects no HTTP
  buffer produces alerts with no `tx_id`, so the marker join cannot reach them
  and they are attributed to nothing: 259 alerts, zero effect on any score. And
  the acceptance suite restored "whatever rules were there when it started",
  which cemented a rule set a previous run had broken; `conftest` now refuses to
  run unless the sensor is carrying the rules this repo declares.

**Two tests deleted for being worse than nothing**
- `test_sensor_scope.py` and `test_attack_source.py` compared YAML strings and
  asserted a routing decision. The first passed on `HOME_NET: "any"` and on
  `HOME_NET: "[172.30.0.0/24]"` alike - and the second of those is the value
  that makes the sensor match zero packets. Its green state was the blind state,
  and `bin/verify --fast` runs only that suite.

**A verify that fails for its own reasons**
- `bin/verify` fired the acceptance suite the moment the platform answered,
  without waiting for the target. A run that started while Juice Shop was
  still coming up reported TP 0 - "no attack was detected at all" - which the
  session protocol answers with `git reset --hard`. It waits for the target's
  own health now, up to two minutes, and says why if it never arrives.
- Four health checks asked `localhost`, which resolves to `::1` first. The
  nginx entrypoint adds an IPv6 listener by editing its own conf and these
  confs are mounted read-only, so the wiki had been `unhealthy` for 513
  consecutive checks while serving every request it was given. They ask
  `127.0.0.1` now, and every container in the stack reports true.

**The console needs no internet**
- Tailwind came from `cdn.tailwindcss.com` on every page: a browser-side JIT
  compiler, fetched at render time, which Tailwind documents as a development
  tool. An isolated range - which is what this is for - met an unstyled
  console. `bin/build-css` runs the Tailwind CLI over the console's own
  templates and commits the 16KB result, which `base.html` inlines, so there
  is no static-file serving, no new dependency and no network. Verified by
  sampling computed styles on the blue console before and after: nine
  selectors, identical to the character. A test refuses a template that
  fetches anything, and another refuses a utility that is used and not built.

**One language at a time**
- `scoring` returned English sentences meant for a screen, so four warnings
  stayed English whatever language the console was in. It returns
  `(key, *args)` now and the console looks the text up like everything else;
  the prose left gated core with them. A test refuses a sentence in
  `platform/scoring/`.

**What the operator actually typed**
- Every command typed at the terminal is recorded with the case that was open
  when it was typed: the box appends to a log on each prompt, stamping it with
  the marker the proxy is already labelling traffic with, and the platform
  reads it through `runner("attacker")`.
  `GET /api/sessions/<id>/commands/` returns what was typed inside the
  session's window. `nmap` leaves a record now, not just an alert with no case
  behind it, and the blue console's scoreboard draws it beside the per-case
  table - time, the case that was open, the command.

**Where an attack sits in an intrusion**
- Every attack case carries the Mandiant life cycle stage it belongs to, an
  ATT&CK technique id and a CAPEC pattern id, and the console links both ids to
  the catalogue that defines them. `technique: SQLi` was an abbreviation from
  nowhere; T1190 and CAPEC-66 can be checked.
- The catalogue reports which stages the cases reach and which five of the
  eight they never do, computed from the cases rather than written down, and
  the red console says both. `docs/THREAT-MODEL.md` says which threat is being
  emulated, that there is no C2 at all, and what the range cannot show.

**Smaller**
- Dropped djangorestframework and Kibana; collapsed the Django boilerplate;
  shrank `redteam/harness.py`; deleted the dead marker-probing.
- Tried to replace Django entirely and did not: it cost more lines than it
  saved.

## Backlog

The user's direction, from the Korean red team playbook at www.xn--hy1b43d247a.com:
the range should cover more of the attack lifecycle than initial access. Its
nine stages are attacker infrastructure, initial reconnaissance, initial
access, foothold, privilege escalation, internal reconnaissance, lateral
movement, persistence, mission. The inside now exists; what is missing is
below.

### 1. A foothold to escalate from

Absent: foothold, privilege escalation, persistence. There is no code
execution on the target, so the estate is reached through the application
rather than from a shell on it, and there is nothing to escalate. Whether that
matters is a scope decision: a C2 and a foothold is a large step, and the
range may be more useful as a web-entry range that is honest about where it
stops.

It is the only item left on this list, and it is a decision rather than a
task: either the range grows a C2 and a foothold, or it says in the product
that it is a web-entry range and stops there. `docs/THREAT-MODEL.md` currently
says the second, because that is what is true today.

## Known gaps

- `test_declaration.py` compares two files and never the running range. Six
  deliberate breakages - an undeclared network, an unmarked one, a renamed
  segment, a changed origin, a removed origin, a role pointing at no container -
  are each caught by name, and a `name:` override no longer breaks anything
  because the binding is a label rather than the name. It still cannot see a
  range that does not match either file.
- The `platform` container still mounts the Docker socket, now reached as a
  non-root user through a group whose id compose passes as `DOCKER_GID`
  (`bin/docker-gid` prints it; read off the host instead of inside the VM it
  comes back `1` and the platform answers 200 with `permission denied` in the
  body). It is still a container escape path and it disappears with the substrate: an
  OpenStack adapter authenticates rather than mounting anything.
- The Kali terminal on 7681 is an unauthenticated root shell. Local lab only.
- `elastic.fetch` reads at most 5000 documents per ingest and has no
  `event_type` filter, so `http` records burn the same budget. It now reports
  what it could not read and the console says so, but a long session still
  scores on part of its evidence. Paginating with `search_after` needs a
  monotonic write-time field, which the index does not have; one
  `set: _ingest.timestamp` processor in the pipeline would give it one.
- `Detection.raw` for ModSecurity holds only the `message` sub-object. The
  drawer now names the CRS rule and says the ruleset lives in the WAF, so the
  operator is not stuck, but the record is still a fragment.
- The operator log lives inside the attacker box and is lost when it is
  recreated, and its stamps are whole seconds - a session's window is widened
  to whole seconds to match, so two sessions less than a second apart would
  each claim the other's commands.
- Two labelled terminal windows less than four seconds apart overlap, because
  `WINDOW_SLACK` is two seconds at each end. The console does not say so.
- Nothing stops two people opening the same session in four windows. One user,
  one session was a deliberate scope decision.

## Tried and thrown away

**Elasticsearch as the only store, 2026-09-22.** The idea was to delete the
Django `Detection` table and query the index directly: one copy of the truth,
no 5000-document cap, aggregations instead of Python loops. Killed at the
scoping stage, before any production code, by three measurements:

- Window correlation has no Elasticsearch form. Both event clocks are mapped
  `keyword`; the only `date` field is filebeat's read clock, which runs ahead
  of ModSecurity's by a median of 2.5s and p90 of 7.9s against a two-second
  `WINDOW_SLACK`. 64% of ModSecurity alerts would land in the wrong window.
- It does not re-derive the same score, it changes it. One session's frozen 66
  detections come back as 98 when its window is re-queried, and no closed
  session could be told from a regression.
- 85 of the tests are written against the `patch(elastic.fetch)` seam and the
  floor may only rise, so most of the work is rewriting tests to stand still.

The motivating measurement was also wrong, which is the more useful lesson:
`/top/` at 44-82ms against an aggregation at 3-9ms is not Django versus
Elasticsearch. `/map/` walks the same rows in Python in 3.5ms; the 40ms was the
Docker call in `_segments()`, since removed.

Worth keeping from it: a `set: _ingest.timestamp` processor is the one line
every future version of that idea depends on.
