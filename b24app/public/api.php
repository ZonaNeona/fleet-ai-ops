<?php

declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';

use FleetB24\Bitrix24;
use FleetB24\Fleet;
use FleetB24\Http;

// Backend of the Vue widget in the deal card. The widget never talks to the fleet or the portal directly:
// the browser only knows this file, the keys stay on the server side of the app.
$key = (string) ($_GET['key'] ?? '');
$deal = (int) ($_GET['deal'] ?? 0);
$action = (string) ($_GET['action'] ?? 'deal');
if ($key === '' || $deal <= 0) {
    json_out(['error' => 'Нужны key и deal'], 400);
    return;
}
$http = new Http();
try {
    $fleet = Fleet::fromEnv($http, $key);
    if ($action === 'deal') {
        json_out($fleet->deal($deal));
        return;
    }
    if ($action === 'task' && $_SERVER['REQUEST_METHOD'] === 'POST') {
        $base = rtrim(getenv('FLEET_API') ?: 'http://127.0.0.1:3008', '/');
        $portal = Bitrix24::fromAuth($http, ['client_endpoint' => "$base/api/b24/rest/$key/", 'access_token' => $key]);
        $info = $fleet->deal($deal);
        $result = $portal->call('tasks.task.add', ['fields' => [
            'TITLE' => 'Связаться с водителем: ' . ($info['driver']['name'] ?? $info['candidate']['name'] ?? "сделка #$deal"),
            'DESCRIPTION' => implode('; ', (array) ($info['verdict']['reasons'] ?? [])),
            'RESPONSIBLE_ID' => 7,
            'DEADLINE' => date('c', time() + 86400),
            'UF_CRM_TASK' => ["D_$deal"],
        ]]);
        json_out(['task' => $result['task']['id'] ?? null]);
        return;
    }
    json_out(['error' => 'Неизвестное действие'], 400);
} catch (Throwable $e) {
    json_out(['error' => $e->getMessage()], 502);
}
