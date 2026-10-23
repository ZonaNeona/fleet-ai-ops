<?php

declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';

use FleetB24\Bitrix24;
use FleetB24\Http;
use FleetB24\Robot;
use FleetB24\Tokens;

// Install handler of the local application on a real portal: remembers the portal and registers the placement,
// the robot and the deal event. On the public stand there is nothing to install — the emulator needs no setup.
$auth = [
    'client_endpoint' => 'https://' . ($_REQUEST['DOMAIN'] ?? '') . '/rest/',
    'access_token' => $_REQUEST['AUTH_ID'] ?? '',
    'domain' => $_REQUEST['DOMAIN'] ?? '',
    'application_token' => $_REQUEST['APP_SID'] ?? '',
];
try {
    $self = 'https://' . ($_SERVER['HTTP_HOST'] ?? '') . dirname($_SERVER['SCRIPT_NAME'] ?? '/') . '/';
    $portal = Bitrix24::fromAuth(new Http(), $auth);
    $portal->call('placement.bind', ['PLACEMENT' => 'CRM_DEAL_DETAIL_TAB', 'HANDLER' => $self . 'index.php', 'TITLE' => 'Водитель']);
    $portal->call('bizproc.robot.add', [
        'CODE' => Robot::CODE,
        'HANDLER' => $self . 'robot.php',
        'NAME' => 'Проверить водителя',
        'USE_SUBSCRIPTION' => 'Y',
        'PROPERTIES' => ['notify_manager' => ['Name' => 'Поставить задачу менеджеру', 'Type' => 'bool', 'Default' => 'Y']],
        'RETURN_PROPERTIES' => ['verdict' => ['Name' => 'Можно выдавать', 'Type' => 'bool'], 'reasons' => ['Name' => 'Причины', 'Type' => 'string']],
    ]);
    $portal->call('event.bind', ['event' => 'ONCRMDEALUPDATE', 'handler' => $self . 'event.php']);
    Tokens::fromEnv()->remember($auth);
    echo '<script src="//api.bitrix24.com/api/v1/"></script><script>BX24.init(function(){BX24.installFinish();});</script>Установлено.';
} catch (Throwable $e) {
    http_response_code(502);
    echo 'Установка не удалась: ' . htmlspecialchars($e->getMessage());
}
