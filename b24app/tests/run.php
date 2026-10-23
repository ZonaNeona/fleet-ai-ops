<?php

declare(strict_types=1);

// Tests for the Bitrix24 app without network or packages: php b24app/tests/run.php
require __DIR__ . '/../src/bootstrap.php';

use FleetB24\Bitrix24;
use FleetB24\Http;
use FleetB24\Robot;
use FleetB24\Tokens;

/** Records requests and answers like the fleet API and the emulated portal. */
final class FakeHttp extends Http
{
    /** @param array<string,mixed> $deal */
    public function __construct(private array $deal, private string $appToken = 'tok')
    {
    }

    public function request(string $method, string $url, ?array $json = null, array $headers = []): array
    {
        $this->sent[] = ['method' => $method, 'url' => $url, 'body' => $json];
        if (str_contains($url, '/api/b24app/app-token')) {
            return ['application_token' => $this->appToken];
        }
        if (str_contains($url, '/api/b24app/deal/')) {
            return $this->deal;
        }
        if (str_contains($url, 'tasks.task.add')) {
            return ['result' => ['task' => ['id' => '1001']]];
        }
        return ['result' => true];
    }
}

$failures = 0;
function check(string $name, bool $ok): void
{
    global $failures;
    echo ($ok ? 'ok   ' : 'FAIL ') . $name . PHP_EOL;
    $failures += $ok ? 0 : 1;
}

function robotCall(string $applicationToken = 'tok'): array
{
    return [
        'event_token' => 'evt_1',
        'document_id' => ['crm', 'CCrmDocumentDeal', 'DEAL_101'],
        'properties' => ['notify_manager' => 'Y'],
        'auth' => [
            'access_token' => 'b24_key', 'domain' => 'demo.bitrix24.ru',
            'client_endpoint' => 'http://fleet/api/b24/rest/b24_key/', 'application_token' => $applicationToken,
        ],
    ];
}

$tokens = new Tokens(sys_get_temp_dir() . '/b24app-test-' . getmypid() . '.json');
$bad = ['deal' => ['id' => '101'], 'driver' => ['name' => 'Иван'], 'contract' => ['code' => 'D-1013'],
    'money' => ['debt' => '4800.00'], 'verdict' => ['ok' => false, 'reasons' => ['долг 4 800 ₽']]];
$good = ['deal' => ['id' => '101'], 'driver' => ['name' => 'Пётр'], 'contract' => ['code' => 'D-1014'],
    'money' => ['debt' => '0.00'], 'verdict' => ['ok' => true, 'reasons' => ['долгов нет']]];

// A driver with debt: comment, task for the manager, robot answer — in that order, all to the portal endpoint.
$http = new FakeHttp($bad);
$result = (new Robot($http, $tokens))->handle(robotCall());
$methods = array_values(array_filter(array_map(
    static fn ($r) => preg_match('#/rest/b24_key/([a-z.]+)\.json#', $r['url'], $m) ? $m[1] : null,
    $http->sent,
)));
check('robot writes comment, task and event in order', $methods === ['crm.timeline.comment.add', 'tasks.task.add', 'bizproc.event.send']);
check('robot reports the verdict and the task', $result['ok'] === false && $result['task'] === '1001');
$event = end($http->sent)['body'];
check('robot returns values to the business process', $event['return_values']['verdict'] === 'N' && $event['event_token'] === 'evt_1');
check('comment names the driver and the contract', str_contains($http->sent[2]['body']['fields']['COMMENT'], 'Иван')
    && str_contains($http->sent[2]['body']['fields']['COMMENT'], 'D-1013'));

// A clean driver: no task.
$http = new FakeHttp($good);
$result = (new Robot($http, $tokens))->handle(robotCall());
check('no task when everything is fine', $result['ok'] === true && $result['task'] === null);

// A forged call: wrong application_token is refused before anything is written.
$http = new FakeHttp($bad);
try {
    (new Robot($http, $tokens))->handle(robotCall('forged'));
    check('forged robot call is refused', false);
} catch (RuntimeException) {
    $writes = array_filter($http->sent, static fn ($r) => str_contains($r['url'], '/rest/'));
    check('forged robot call is refused, nothing written', $writes === []);
}

// Not a deal and not a robot call.
foreach ([['event_token' => 'x', 'document_id' => ['crm', 'CCrmDocumentLead', 'LEAD_5'], 'auth' => []], []] as $post) {
    try {
        (new Robot(new FakeHttp($good), $tokens))->handle($post);
        check('invalid robot input is rejected', false);
    } catch (InvalidArgumentException) {
        check('invalid robot input is rejected', true);
    }
}

// The REST client refuses method names that are not Bitrix24 methods.
try {
    Bitrix24::fromAuth(new FakeHttp($good), ['client_endpoint' => 'http://x/rest/', 'access_token' => 't'])->call('../admin');
    check('method name is validated', false);
} catch (InvalidArgumentException) {
    check('method name is validated', true);
}

exit($failures ? 1 : 0);
