<?php

declare(strict_types=1);

namespace FleetB24;

/** Minimal JSON-over-HTTP client on PHP streams: no extensions beyond openssl, easy to replace in tests. */
class Http
{
    /** @var list<array{method:string,url:string,body:mixed}> */
    public array $sent = [];

    /**
     * @param array<string,mixed>|null $json
     * @return array<string,mixed>
     */
    public function request(string $method, string $url, ?array $json = null, array $headers = []): array
    {
        $this->sent[] = ['method' => $method, 'url' => $url, 'body' => $json];
        $head = array_merge(['Accept: application/json'], $headers);
        $options = ['method' => $method, 'timeout' => 20, 'ignore_errors' => true, 'header' => ''];
        if ($json !== null) {
            $head[] = 'Content-Type: application/json';
            $options['content'] = json_encode($json, JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR);
        }
        $options['header'] = implode("\r\n", $head);
        $raw = @file_get_contents($url, false, stream_context_create(['http' => $options]));
        if ($raw === false) {
            throw new \RuntimeException('Нет ответа от ' . parse_url($url, PHP_URL_HOST));
        }
        $status = 0;
        foreach ($http_response_header ?? [] as $line) {
            if (preg_match('#^HTTP/\S+\s+(\d{3})#', $line, $m)) {
                $status = (int) $m[1];
            }
        }
        $data = json_decode($raw, true);
        if (!is_array($data)) {
            throw new \RuntimeException("Ответ не JSON (HTTP $status)");
        }
        if ($status >= 400) {
            $message = $data['error_description'] ?? $data['detail'] ?? ('HTTP ' . $status);
            throw new \RuntimeException(is_string($message) ? $message : json_encode($message, JSON_UNESCAPED_UNICODE));
        }
        return $data;
    }
}
