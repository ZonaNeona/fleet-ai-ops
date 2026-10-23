<?php

declare(strict_types=1);

// No framework and no Composer packages: five small classes, autoloaded from src/.
spl_autoload_register(static function (string $class): void {
    $prefix = 'FleetB24\\';
    if (str_starts_with($class, $prefix)) {
        require __DIR__ . '/' . substr($class, strlen($prefix)) . '.php';
    }
});

function json_out(array $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
}
