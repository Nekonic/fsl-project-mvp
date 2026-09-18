# juice-shop

The app under defence. The image is used as-is, so there is no config here.

This is a replaceable slot. Juice Shop was chosen because its own challenge API
decides whether an attack succeeded and it needs no database. Shell access is
not possible, so a PHP board or a Spring app will sit beside it later. To add
one, create `wargame/<name>/` and point the `waf` service's `BACKEND` in
`compose.yaml` at it.
