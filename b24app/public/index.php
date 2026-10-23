<?php

declare(strict_types=1);

// Placement CRM_DEAL_DETAIL_TAB: the portal opens this page in an iframe with POST AUTH_ID, DOMAIN and
// PLACEMENT_OPTIONS={"ID":"<deal>"}. On the public stand the fleet opens it with ?demo=1&key=…&deal=… instead.
$options = json_decode((string) ($_POST['PLACEMENT_OPTIONS'] ?? '{}'), true) ?: [];
$deal = (int) ($options['ID'] ?? $_GET['deal'] ?? 0);
$key = (string) ($_GET['key'] ?? getenv('FLEET_APP_KEY') ?: '');
$inPortal = isset($_POST['AUTH_ID']);
$config = json_encode(['deal' => $deal, 'key' => $key, 'api' => 'api.php', 'portal' => $inPortal], JSON_UNESCAPED_UNICODE);
// The widget is built by Vite into fixed names; the file time busts the cache after a release.
$version = static fn (string $file): string => $file . '?v=' . (@filemtime(__DIR__ . '/' . $file) ?: 0);
$js = $version('widget/app.js');
$css = is_file(__DIR__ . '/widget/app.css') ? $version('widget/app.css') : null;
?>
<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Водитель · приложение таксопарка</title>
    <?php if ($css): ?><link rel="stylesheet" href="<?= htmlspecialchars($css) ?>"><?php endif ?>
    <?php if ($inPortal): ?><script src="//api.bitrix24.com/api/v1/"></script><?php endif ?>
</head>
<body>
<div id="app"></div>
<script>window.B24APP = <?= $config ?>;</script>
<script type="module" src="<?= htmlspecialchars($js) ?>"></script>
</body>
</html>
