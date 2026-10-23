<?php

declare(strict_types=1);

namespace FleetB24;

/**
 * Robot «Проверить водителя» (code fleet_driver_check): a business process in Bitrix24 reaches the robot, the portal
 * POSTs the event here, the app asks the fleet about the driver of the deal and answers the portal:
 * a timeline comment, a task for the manager when something is wrong, and the robot's return values.
 */
class Robot
{
    public const CODE = 'fleet_driver_check';

    public function __construct(private readonly Http $http, private readonly Tokens $tokens)
    {
    }

    /**
     * @param array<string,mixed> $post what the portal sent ($_POST)
     * @return array<string,mixed>
     */
    public function handle(array $post): array
    {
        $token = (string) ($post['event_token'] ?? '');
        $document = $post['document_id'] ?? [];
        $auth = $post['auth'] ?? [];
        if ($token === '' || !is_array($document) || !is_array($auth)) {
            throw new \InvalidArgumentException('Это не вызов робота Битрикс24');
        }
        if (!preg_match('/^DEAL_(\d+)$/', (string) ($document[2] ?? ''), $m)) {
            throw new \InvalidArgumentException('Робот работает только со сделками');
        }
        $dealId = (int) $m[1];
        $portal = Bitrix24::fromAuth($this->http, $auth);
        $fleet = Fleet::fromEnv($this->http, $this->tokens->fleetKey($auth));
        if (!$this->tokens->trusted($auth, $fleet)) {
            throw new \RuntimeException('application_token не совпадает: вызов не от нашего портала');
        }

        $info = $fleet->deal($dealId);
        $verdict = $info['verdict'] ?? ['ok' => false, 'reasons' => ['нет ответа учёта']];
        $ok = (bool) $verdict['ok'];
        $reasons = implode('; ', array_map('strval', (array) $verdict['reasons']));

        $who = $info['driver']['name'] ?? $info['candidate']['name'] ?? 'водитель';
        $comment = ($ok ? '✅' : '⚠️') . " Проверка водителя ($who): $reasons.";
        if (isset($info['contract']['code'])) {
            $debt = number_format((float) $info['money']['debt'], 0, ',', ' ');
            $comment .= " Договор {$info['contract']['code']}, долг $debt ₽.";
        }
        $portal->call('crm.timeline.comment.add', ['fields' => [
            'ENTITY_ID' => $dealId, 'ENTITY_TYPE' => 'deal', 'COMMENT' => $comment,
        ]]);

        $task = null;
        if (!$ok && (($post['properties']['notify_manager'] ?? 'N') === 'Y')) {
            $task = $portal->call('tasks.task.add', ['fields' => [
                'TITLE' => "Разобраться с водителем по сделке #$dealId",
                'DESCRIPTION' => $reasons,
                'RESPONSIBLE_ID' => 7,
                'DEADLINE' => date('c', time() + 86400),
                'UF_CRM_TASK' => ["D_$dealId"],
            ]]);
        }

        $portal->call('bizproc.event.send', [
            'event_token' => $token,
            'return_values' => ['verdict' => $ok ? 'Y' : 'N', 'reasons' => $reasons],
            'log_message' => 'Проверка водителя: ' . ($ok ? 'можно выдавать' : 'есть замечания'),
        ]);

        return ['ok' => $ok, 'deal' => $dealId, 'reasons' => $verdict['reasons'], 'task' => $task['task']['id'] ?? null,
            'portal' => $portal->isEmulator() ? 'эмулятор' : 'портал'];
    }
}
