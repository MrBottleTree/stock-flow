# Cloudflare Tunnel setup

This project can be exposed through Cloudflare Tunnel without changing the app route structure.

## 1. Run Django locally

Use the usual development server on port `8000`:

```powershell
python manage.py runserver 127.0.0.1:8000
```

## 2. Start a quick tunnel

If you only need a temporary public URL, run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Cloudflare will print a `trycloudflare.com` URL. The Django settings already allow that host pattern by default.

## 3. For a named tunnel

If you want a stable hostname, create a tunnel in Cloudflare and point it at the local server:

```powershell
cloudflared tunnel login
cloudflared tunnel create stock-flow
cloudflared tunnel route dns stock-flow app.example.com
```

Then use a config file similar to this:

```yaml
tunnel: stock-flow
credentials-file: C:\Users\Darsh\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: app.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Run it with:

```powershell
cloudflared tunnel run stock-flow
```

## 4. Environment variables

Update your `.env` when you use a stable hostname:

```env
DEBUG=False
ALLOWED_HOSTS=127.0.0.1,localhost,.trycloudflare.com,app.example.com
CSRF_TRUSTED_ORIGINS=https://*.trycloudflare.com,https://app.example.com
USE_X_FORWARDED_HOST=True
```

For a public deployment, keep `DEBUG=False` and use a real secret key.