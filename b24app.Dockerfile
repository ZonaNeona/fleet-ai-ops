# Bitrix24 local application: PHP 8.3 FPM, no framework, no Composer packages.
FROM php:8.3-fpm-alpine
# php-fpm drops the environment by default; the app reads FLEET_API from it.
RUN printf '[www]\nclear_env = no\n' > /usr/local/etc/php-fpm.d/zz-fleet.conf
COPY b24app/src /app/src
COPY b24app/public /app/public
RUN mkdir -p /app/var && chown www-data /app/var
