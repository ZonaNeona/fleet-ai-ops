<?php

declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';

// ONCRMDEALUPDATE from a real portal. The app only acknowledges and logs here: checks run through the robot,
// so the business process — not the app — decides when a driver is checked.
$event = (string) ($_POST['event'] ?? '');
$deal = (int) ($_POST['data']['FIELDS']['ID'] ?? 0);
if ($event !== 'ONCRMDEALUPDATE' || $deal <= 0) {
    json_out(['error' => 'Неизвестное событие'], 400);
    return;
}
error_log("event: deal $deal updated on " . ($_POST['auth']['domain'] ?? '?'));
json_out(['ok' => true]);
