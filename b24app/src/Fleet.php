<?php

declare(strict_types=1);

namespace FleetB24;

/** The fleet's API as the app sees it: a driver card for a deal and the verdict the robot writes back. */
class Fleet
{
    public function __construct(private readonly Http $http, private readonly string $base, private readonly string $key)
    {
    }

    public static function fromEnv(Http $http, string $key): self
    {
        return new self($http, rtrim(getenv('FLEET_API') ?: 'http://127.0.0.1:3008', '/'), $key);
    }

    /** @return array<string,mixed> */
    public function deal(int $id): array
    {
        return $this->http->request('GET', "{$this->base}/api/b24app/deal/$id", null, ['X-B24App-Key: ' . $this->key]);
    }

    public function applicationToken(): string
    {
        $answer = $this->http->request('GET', "{$this->base}/api/b24app/app-token", null, ['X-B24App-Key: ' . $this->key]);
        return (string) ($answer['application_token'] ?? '');
    }
}
