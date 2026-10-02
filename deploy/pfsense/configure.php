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
