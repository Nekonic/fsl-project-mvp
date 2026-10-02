require_once("filter.inc");
require_once("interfaces.inc");
require_once("shaper.inc");
config_read_file(true);

$wan = config_get_path('interfaces/wan/if');
config_set_path('interfaces/wan/ipaddr', $fsl['wan']['address']);
config_set_path('interfaces/wan/subnet', $fsl['wan']['bits']);
foreach (['ipaddrv6', 'subnetv6', 'gatewayv6', 'dhcphostname', 'blockpriv', 'blockbogons'] as $key) {
	config_del_path("interfaces/wan/{$key}");
}

$vips = array_values(array_filter(
	config_get_path('virtualip/vip', []),
	fn($vip) => strpos($vip['descr'] ?? '', 'fsl origin ') !== 0
));
foreach ($fsl['aliases'] as $alias) {
	$vips[] = [
		'mode' => 'ipalias',
		'interface' => 'wan',
		'uniqid' => "fsl{$alias['id']}",
		'descr' => "fsl origin {$alias['id']}",
		'type' => 'single',
		'subnet_bits' => $alias['bits'],
		'subnet' => $alias['address'],
	];
}
config_set_path('virtualip/vip', $vips);

config_set_path('nat/outbound/mode', 'disabled');
$passing = array_filter(config_get_path('filter/rule', []), fn($rule) => ($rule['descr'] ?? '') == 'fsl range crosses the edge');
if (!$passing) {
	add_filter_rules([[
		'tracker' => (int)microtime(true),
		'type' => 'pass',
		'interface' => 'wan',
		'ipprotocol' => 'inet',
		'statetype' => 'keep state',
		'source' => ['any' => ''],
		'destination' => ['any' => ''],
		'descr' => 'fsl range crosses the edge',
		'created' => make_config_revision_entry(null, 'fsl'),
	]]);
}

write_config('fsl: the edge holds every origin gateway');

kill_dhclient_process($wan);
kill_dhcp6client_process(true);
interface_configure('wan', true);
interfaces_vips_configure('wan');
mwexec("/sbin/ifconfig " . escapeshellarg($wan) . " up");
$held = [];
exec("/sbin/ifconfig " . escapeshellarg($wan) . " inet", $held);
foreach (array_merge([$fsl['wan']], $fsl['aliases']) as $want) {
	if (!preg_grep('/inet ' . preg_quote($want['address']) . ' /', $held)) {
		mwexec("/sbin/ifconfig " . escapeshellarg($wan) . " inet " . escapeshellarg("{$want['address']}/{$want['bits']}") . " alias");
	}
}
filter_configure_sync();

$held = [];
exec("/sbin/ifconfig " . escapeshellarg($wan) . " inet", $held);
printf("fsl-edge wan %s\n", implode(' ', array_map(fn($line) => explode(' ', trim($line))[1], preg_grep('/^\s*inet /', $held))));

require_once("syslog.inc");
config_read_file(true);
config_set_path('syslog/enable', true);
config_set_path('syslog/remoteserver', $fsl['collector']);
config_set_path('syslog/ipproto', 'ipv4');
config_set_path('syslog/logall', true);
config_set_path('syslog/format', 'rfc5424');
write_config('fsl: the edge logs to the platform');
system_syslogd_start();
printf("fsl-edge logs %s\n", config_get_path('syslog/remoteserver'));

require_once("/usr/local/pkg/suricata/suricata.inc");
config_read_file(true);

$unexpanded = ['localnets' => 'no', 'wanips' => 'no', 'wangateips' => 'no', 'wandnsips' => 'no', 'vips' => 'no', 'vpnips' => 'no'];
$lists = array_values(array_filter(
	config_get_path('installedpackages/suricata/passlist/item', []),
	fn($list) => !in_array($list['name'] ?? '', ['fsl_home', 'fsl_anywhere'])
));
$lists[] = $unexpanded + ['name' => 'fsl_home', 'descr' => 'the range: every origin, the estate and management', 'address' => ['item' => $fsl['home']]];
$lists[] = $unexpanded + ['name' => 'fsl_anywhere', 'descr' => 'any IPv4 source', 'address' => ['item' => ['0.0.0.0/0']]];
config_set_path('installedpackages/suricata/passlist/item', $lists);

$sensors = config_get_path('installedpackages/suricata/rule', []);
$at = null;
foreach ($sensors as $index => $sensor) {
	if (($sensor['interface'] ?? '') == 'wan') {
		$at = $index;
	}
}
if ($at === null) {
	$sensors[] = ['uuid' => suricata_generate_id(), 'rulesets' => '', 'customrules' => base64_encode($fsl['rules'])];
	$at = array_key_last($sensors);
}
$sensors[$at] = array_merge($sensors[$at], [
	'interface' => 'wan',
	'enable' => 'on',
	'descr' => 'WAN',
	'homelistname' => 'fsl_home',
	'externallistname' => 'fsl_anywhere',
	'blockoffenders' => 'off',
	'ips_mode' => 'ips_mode_legacy',
	'enable_eve_log' => 'on',
	'eve_output_type' => 'syslog',
	'eve_systemlog_facility' => 'local1',
	'eve_systemlog_priority' => 'info',
	'eve_log_alerts' => 'on',
	'eve_log_alerts_metadata' => 'on',
	'eve_log_alerts_payload' => 'off',
	'eve_log_alerts_packet' => 'off',
	'eve_log_http' => 'on',
	'eve_log_http_extended' => 'on',
	'eve_log_http_extended_headers' => '',
]);

$sensing = get_real_interface('wan');
$yaml = SURICATADIR . "suricata_{$sensors[$at]['uuid']}_{$sensing}/suricata.yaml";
foreach ([1, 2] as $pass) {
	$passthru = "detect.guess-applayer-tx: yes\n";
	$dumped = [];
	if (file_exists($yaml)) {
		exec("/usr/local/bin/suricata --dump-config -c " . escapeshellarg($yaml), $dumped);
	}
	foreach (preg_grep('/^outputs\.\d+\.eve-log\.types\.\d+ = http$/', $dumped) as $line) {
		$passthru .= explode(' ', $line)[0] . ".http.dump-all-headers: request\n";
	}
	$sensors[$at]['configpassthru'] = base64_encode($passthru);
	config_set_path('installedpackages/suricata/rule', $sensors);
	write_config('fsl: suricata watches the wan');
	$GLOBALS['rebuild_rules'] = true;
	sync_suricata_package_config();
}

suricata_stop($sensors[$at], $sensing);
suricata_start($sensors[$at], $sensing);
foreach (range(1, 30) as $second) {
	if (suricata_is_running($sensors[$at]['uuid'], $sensing)) {
		break;
	}
	sleep(1);
}
sleep(5);
printf("fsl-edge sensor %s %s\n", $sensing, suricata_is_running($sensors[$at]['uuid'], $sensing) ? 'running' : 'stopped');
