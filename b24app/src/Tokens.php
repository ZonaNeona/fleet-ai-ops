<?php

declare(strict_types=1);

namespace FleetB24;

/**
 * Who is calling and which fleet space it belongs to.
 *
 * Emulated portal (the public demo): the access token *is* the visitor's app key, and the fleet tells the expected
 * application_token for it. Real portal: the install event stored the application_token and the fleet key for the
 * portal's domain in var/portals.json.
 */
class Tokens
{
    public function __construct(private readonly string $store)
    {
    }

    public static function fromEnv(): self
    {
        return new self((getenv('B24APP_VAR') ?: __DIR__ . '/../var') . '/portals.json');
    }

    /** @param array<string,mixed> $auth */
    public function fleetKey(array $auth): string
    {
        if (str_contains((string) ($auth['client_endpoint'] ?? ''), '/api/b24/rest/')) {
            return (string) ($auth['access_token'] ?? '');
        }
        return (string) ($this->portal((string) ($auth['domain'] ?? ''))['fleet_key'] ?? getenv('FLEET_APP_KEY') ?: '');
    }

    /** @param array<string,mixed> $auth */
    public function trusted(array $auth, Fleet $fleet): bool
    {
        $given = (string) ($auth['application_token'] ?? '');
        if ($given === '') {
            return false;
        }
        $expected = str_contains((string) ($auth['client_endpoint'] ?? ''), '/api/b24/rest/')
            ? $fleet->applicationToken()
            : (string) ($this->portal((string) ($auth['domain'] ?? ''))['application_token'] ?? '');
        return $expected !== '' && hash_equals($expected, $given);
    }

    /** @param array<string,mixed> $auth the install event's auth block */
    public function remember(array $auth): void
    {
        $all = $this->all();
        $domain = (string) ($auth['domain'] ?? '');
        if ($domain === '') {
            throw new \InvalidArgumentException('Нет домена портала');
        }
        $all[$domain] = [
            'application_token' => (string) ($auth['application_token'] ?? ''),
            'fleet_key' => getenv('FLEET_APP_KEY') ?: '',
            'installed' => date('c'),
        ];
        @mkdir(dirname($this->store), 0700, true);
        file_put_contents($this->store, json_encode($all, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT), LOCK_EX);
    }

    /** @return array<string,mixed> */
    private function portal(string $domain): array
    {
        return $this->all()[$domain] ?? [];
    }

    /** @return array<string,array<string,mixed>> */
    private function all(): array
    {
        $raw = is_file($this->store) ? file_get_contents($this->store) : '';
        $data = $raw ? json_decode($raw, true) : [];
        return is_array($data) ? $data : [];
    }
}
