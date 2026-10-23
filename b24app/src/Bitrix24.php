<?php

declare(strict_types=1);

namespace FleetB24;

/**
 * Bitrix24 REST over the credentials a portal hands the app: client_endpoint + access_token.
 * The same calls go to a real portal and to the fleet's emulated one — the app does not know which.
 */
class Bitrix24
{
    public function __construct(
        private readonly Http $http,
        private readonly string $endpoint,
        private readonly string $token,
    ) {
    }

    /** @param array<string,mixed> $auth the `auth` block of a placement, event or robot call */
    public static function fromAuth(Http $http, array $auth): self
    {
        $endpoint = (string) ($auth['client_endpoint'] ?? '');
        $token = (string) ($auth['access_token'] ?? $auth['AUTH_ID'] ?? '');
        if (!preg_match('#^https?://[^\s]+/$#', $endpoint) || $token === '') {
            throw new \InvalidArgumentException('Нет client_endpoint или access_token');
        }
        return new self($http, $endpoint, $token);
    }

    /**
     * @param array<string,mixed> $params
     * @return mixed the `result` of the call
     */
    public function call(string $method, array $params = []): mixed
    {
        if (!preg_match('/^[a-z]+(\.[a-z]+)+$/', $method)) {
            throw new \InvalidArgumentException("Некорректный метод $method");
        }
        $answer = $this->http->request('POST', $this->endpoint . $method . '.json?auth=' . rawurlencode($this->token), $params);
        return $answer['result'] ?? null;
    }

    public function isEmulator(): bool
    {
        return str_contains($this->endpoint, '/api/b24/rest/');
    }
}
