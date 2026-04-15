# Ratio1 Telegram Bot Demo

Demo Telegram bot built on Ratio1, starting from the `ratio1_tg_bot` template.

## Features

- `/roll`: rolls a dice between 1 and 6.
- Persists how many times each user rolled in local bot storage.
- Every hour, all users that interacted with the bot receive a lucky number between 1 and 100.
- `/ver`: prints current bot version.

## Required environment variables

- `RATIO1_NODE`
- `TELEGRAM_BOT_TOKEN`

## Deploy/update with GitHub Actions

Workflow: `.github/workflows/cd-update-bot.yml`

The workflow is triggered by pushes to `main` when `ver.py` changes and executes:

```bash
python3 ratio1_tg_bot_demo.py
```

using `Ratio1/ratio1-setup-action@v1` with repository secrets.
