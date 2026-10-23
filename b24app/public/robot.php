<?php

declare(strict_types=1);

require __DIR__ . '/../src/bootstrap.php';

use FleetB24\Http;
use FleetB24\Robot;
use FleetB24\Tokens;

// The portal calls this when a business process reaches the robot «Проверить водителя».
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    json_out(['error' => 'POST only'], 405);
    return;
}
try {
    json_out((new Robot(new Http(), Tokens::fromEnv()))->handle($_POST));
} catch (InvalidArgumentException $e) {
    json_out(['error' => $e->getMessage()], 400);
} catch (Throwable $e) {
    error_log('robot: ' . $e->getMessage());
    json_out(['error' => $e->getMessage()], 502);
}
