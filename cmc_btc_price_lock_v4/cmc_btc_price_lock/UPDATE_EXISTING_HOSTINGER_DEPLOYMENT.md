# Updating the live Hostinger deployment

## GitHub update path

Upload changed files into this existing repo folder:

```text
cmc_btc_price_lock_v4/cmc_btc_price_lock/
```

Do not upload the outer extracted folder as a folder inside GitHub, or you will create another nested path.

## VPS update steps

```bash
cd /root/cmc-btc-price-lock
git pull
cd /root/cmc-btc-price-lock/cmc_btc_price_lock_v4/cmc_btc_price_lock
docker compose down
docker compose up -d --build
docker ps
docker logs cmc_btc_price_lock-app-1 --tail 50
docker logs cmc_btc_price_lock-caddy-1 --tail 50
```

## Live URLs

- `https://cmcx-btc-lock.com/`
- `https://cmcx-btc-lock.com/dashboard`
- `https://cmcx-btc-lock.com/admin`
