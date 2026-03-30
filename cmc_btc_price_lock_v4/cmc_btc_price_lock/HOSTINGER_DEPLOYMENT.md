# Hostinger VPS deployment (recommended for the live event)

This app should be deployed on a **public HTTPS domain** so the QR code, entry page, and live dashboard work from **any phone, on any network**.

## Recommended production shape

- App URL: `https://play.yourdomain.com/`
- Dashboard URL: `https://play.yourdomain.com/dashboard`
- Admin URL: `https://play.yourdomain.com/admin`

## Why VPS and not shared WordPress hosting?

This project is a Python / FastAPI app. Hostinger’s official support pages say Python workloads that need full package and runtime control are supported on **VPS**, and Flask is supported **exclusively on VPS** because root access is required.

## Step-by-step

### 1) Create the subdomain

Create a subdomain like `play.yourdomain.com` in Hostinger hPanel.

### 2) Point it to the VPS

Point the subdomain to your VPS public IP with an **A record**.

### 3) Create a VPS

Use a Hostinger **Ubuntu 24.04 with Docker** VPS template if available.

### 4) Connect to the VPS

Open the Hostinger Browser terminal or SSH into the VPS.

### 5) Upload the project

Upload this project folder to the VPS, for example into `/root/cmc-btc-price-lock`.

### 6) Configure `.env`

Copy `.env.example` to `.env` and set:

```env
PUBLIC_DOMAIN=play.yourdomain.com
CMC_PUBLIC_BASE_URL=https://play.yourdomain.com/
CMC_HTTPS_ONLY=true
CMC_ADMIN_PASSWORD=choose-a-strong-password
CMC_SESSION_SECRET=choose-a-long-random-secret
CMC_LEAD_EXPORT_EMAIL=b.charbonneau@cmcmarkets.com
```

### 7) Start the stack

```bash
docker compose up -d --build
```

### 8) Check health

Open:

- `https://play.yourdomain.com/healthz`
- `https://play.yourdomain.com/`
- `https://play.yourdomain.com/dashboard`
- `https://play.yourdomain.com/admin`

## Updates

When you change files later:

```bash
docker compose up -d --build
```

## Data

Lead data is stored in `./data/app.db` on the server so it survives restarts.
