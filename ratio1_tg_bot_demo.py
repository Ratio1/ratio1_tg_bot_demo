"""
ratio1_tg_bot_demo.py
---------------------

Simple Ratio1 Telegram bot demo.

Features:
1. `/roll` rolls a dice between 1 and 6.
2. The bot persists how many times each user rolled.
3. Every hour, all users that interacted with the bot receive a lucky number (1-100).
4. `/watch_api` monitors API health endpoints and notifies subscribers on state changes.
"""

import os
import urllib.error
import urllib.parse
import urllib.request
from ratio1 import Session, CustomPluginTemplate


try:
  from ver import VERSION as BOT_VERSION
except Exception:
  BOT_VERSION = "unknown"


API_CHECK_INTERVAL_SECONDS = 300
API_REQUEST_TIMEOUT_SECONDS = 5
DEFAULT_HEALTH_ENDPOINT = "/health"

CACHE_READY_KEY = "demo_cache_ready"
ROLL_COUNTS_CACHE_KEY = "demo_roll_counts"
INTERACTED_USERS_CACHE_KEY = "demo_interacted_users"
LAST_LUCKY_TS_CACHE_KEY = "demo_last_lucky_ts"
API_WATCHLIST_CACHE_KEY = "demo_api_watchlist"
PENDING_API_WATCH_CACHE_KEY = "demo_pending_api_watch"

ROLL_COUNTS_FILE = "demo_roll_counts.pkl"
INTERACTED_USERS_FILE = "demo_interacted_users.pkl"
LAST_LUCKY_TS_FILE = "demo_last_lucky_ts.pkl"
API_WATCHLIST_FILE = "demo_api_watchlist.pkl"


def initialize_cache(plugin: CustomPluginTemplate):
  if plugin.obj_cache.get(CACHE_READY_KEY):
    return

  plugin.obj_cache[ROLL_COUNTS_CACHE_KEY] = plugin.diskapi_load_pickle_from_data(ROLL_COUNTS_FILE) or {}
  plugin.obj_cache[INTERACTED_USERS_CACHE_KEY] = plugin.diskapi_load_pickle_from_data(INTERACTED_USERS_FILE) or []
  plugin.obj_cache[LAST_LUCKY_TS_CACHE_KEY] = plugin.diskapi_load_pickle_from_data(LAST_LUCKY_TS_FILE) or 0
  plugin.obj_cache[API_WATCHLIST_CACHE_KEY] = plugin.diskapi_load_pickle_from_data(API_WATCHLIST_FILE) or {}
  plugin.obj_cache[PENDING_API_WATCH_CACHE_KEY] = {}
  plugin.obj_cache[CACHE_READY_KEY] = True


def normalize_api_base_url(raw_url: str):
  raw_url = raw_url.strip()
  parsed = urllib.parse.urlparse(raw_url)
  if parsed.scheme not in ("http", "https") or not parsed.netloc:
    return None

  return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def normalize_health_endpoint(raw_endpoint: str):
  endpoint = raw_endpoint.strip()
  if not endpoint:
    return DEFAULT_HEALTH_ENDPOINT

  parsed = urllib.parse.urlparse(endpoint)
  if parsed.scheme or parsed.netloc:
    return None

  if not endpoint.startswith("/"):
    endpoint = f"/{endpoint}"

  return endpoint


def build_api_watch_url(base_url: str, endpoint: str):
  return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", endpoint.lstrip("/"))


def build_api_watch_id(watch_url: str):
  parsed = urllib.parse.urlparse(watch_url)
  return urllib.parse.urlunparse((
    parsed.scheme.lower(),
    parsed.netloc.lower(),
    parsed.path,
    "",
    parsed.query,
    "",
  ))


def check_api_health(url: str):
  try:
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "Ratio1TelegramApiWatcher/1.0"})
    with urllib.request.urlopen(request, timeout=API_REQUEST_TIMEOUT_SECONDS) as response:
      status_code = int(response.getcode())
      return 200 <= status_code < 400, f"HTTP {status_code}"
  except urllib.error.HTTPError as exc:
    return False, f"HTTP {exc.code}"
  except Exception as exc:
    return False, str(exc)


def add_api_subscription(plugin: CustomPluginTemplate, chat_id: str, base_url: str, endpoint: str, is_online: bool, status_message: str):
  watchlist = plugin.obj_cache.get(API_WATCHLIST_CACHE_KEY, {})
  watch_url = build_api_watch_url(base_url, endpoint)
  watch_id = build_api_watch_id(watch_url)
  now_ts = int(plugin.time())

  watch_entry = watchlist.get(watch_id)
  if watch_entry is None:
    watch_entry = {
      "base_url": base_url,
      "endpoint": endpoint,
      "url": watch_url,
      "subscribers": [],
      "last_state": "online" if is_online else "offline",
      "last_status": status_message,
      "last_checked_ts": now_ts,
      "last_changed_ts": now_ts,
    }

  subscribers = watch_entry.get("subscribers", [])
  if chat_id not in subscribers:
    subscribers.append(chat_id)
  watch_entry["subscribers"] = subscribers

  watchlist[watch_id] = watch_entry
  plugin.obj_cache[API_WATCHLIST_CACHE_KEY] = watchlist
  plugin.diskapi_save_pickle_to_data(watchlist, API_WATCHLIST_FILE)

  return watch_entry, len(subscribers)


def loop_processing(plugin: CustomPluginTemplate):
  initialize_cache(plugin)

  now_ts = int(plugin.time())
  last_lucky_ts = int(plugin.obj_cache.get(LAST_LUCKY_TS_CACHE_KEY, 0))

  # Send lucky numbers at most once per hour.
  if now_ts - last_lucky_ts >= 3600:
    users = plugin.obj_cache.get(INTERACTED_USERS_CACHE_KEY, [])
    for user_id in users:
      lucky_number = int(plugin.np.random.randint(1, 101))
      plugin.send_message_to_user(
        user_id=user_id,
        text=f"Lucky number of the hour: {lucky_number}",
      )

    plugin.obj_cache[LAST_LUCKY_TS_CACHE_KEY] = now_ts
    plugin.diskapi_save_pickle_to_data(now_ts, LAST_LUCKY_TS_FILE)

  watchlist = plugin.obj_cache.get(API_WATCHLIST_CACHE_KEY, {})
  watchlist_changed = False
  for watch_id, watch_entry in watchlist.items():
    last_checked_ts = int(watch_entry.get("last_checked_ts", 0))
    if now_ts - last_checked_ts < API_CHECK_INTERVAL_SECONDS:
      continue

    is_online, status_message = check_api_health(watch_entry["url"])
    new_state = "online" if is_online else "offline"
    old_state = watch_entry.get("last_state")

    watch_entry["last_checked_ts"] = now_ts
    watch_entry["last_status"] = status_message

    if old_state and old_state != new_state:
      watch_entry["last_state"] = new_state
      watch_entry["last_changed_ts"] = now_ts
      watchlist_changed = True

      state_text = "back online" if new_state == "online" else "offline"
      for user_id in watch_entry.get("subscribers", []):
        plugin.send_message_to_user(
          user_id=user_id,
          text=f"API {watch_entry['url']} is {state_text}.\nStatus: {status_message}",
        )
    elif old_state != new_state:
      watch_entry["last_state"] = new_state
      watchlist_changed = True

    watchlist[watch_id] = watch_entry
    watchlist_changed = True

  if watchlist_changed:
    plugin.obj_cache[API_WATCHLIST_CACHE_KEY] = watchlist
    plugin.diskapi_save_pickle_to_data(watchlist, API_WATCHLIST_FILE)

  return


def reply(plugin: CustomPluginTemplate, message: str, user: str, chat_id: str):
  initialize_cache(plugin)

  # Track every chat that interacts with the bot for hourly lucky-number broadcasts.
  users = plugin.obj_cache.get(INTERACTED_USERS_CACHE_KEY, [])
  if chat_id not in users:
    users.append(chat_id)
    plugin.obj_cache[INTERACTED_USERS_CACHE_KEY] = users
    plugin.diskapi_save_pickle_to_data(users, INTERACTED_USERS_FILE)

  pending_api_watch = plugin.obj_cache.get(PENDING_API_WATCH_CACHE_KEY, {})

  if message.startswith("/start"):
    return "Welcome to Ratio1 Telegram Bot Demo.\nUse /roll to roll a dice between 1 and 6.\nUse /watch_api <api_url> to monitor an API health endpoint.\nYou will also receive an hourly lucky number."

  if message.startswith("/ver"):
    return f"Bot version: {plugin.cfg_version}"

  if message.startswith("/watch_api"):
    parts = message.split(maxsplit=1)
    if len(parts) != 2:
      return "Usage: /watch_api https://api.example.com"

    base_url = normalize_api_base_url(parts[1])
    if base_url is None:
      return "Please provide a valid API URL starting with http:// or https://."

    pending_api_watch[chat_id] = {"base_url": base_url}
    plugin.obj_cache[PENDING_API_WATCH_CACHE_KEY] = pending_api_watch
    return f"Health endpoint for {base_url}?\nReply yes to use {DEFAULT_HEALTH_ENDPOINT}, or send a different endpoint path."

  if chat_id in pending_api_watch:
    pending_watch = pending_api_watch.pop(chat_id)
    plugin.obj_cache[PENDING_API_WATCH_CACHE_KEY] = pending_api_watch

    endpoint_reply = message.strip()
    if endpoint_reply.lower() in ("yes", "y", "ok", "confirm", "confirmed", "default"):
      endpoint_reply = DEFAULT_HEALTH_ENDPOINT

    endpoint = normalize_health_endpoint(endpoint_reply)
    if endpoint is None:
      return "Please send only the endpoint path, for example /health or /api/status."

    base_url = pending_watch["base_url"]
    watch_url = build_api_watch_url(base_url, endpoint)
    is_online, status_message = check_api_health(watch_url)
    if not is_online:
      return f"I could reach the API URL format, but {watch_url} is not working right now.\nStatus: {status_message}"

    watch_entry, subscriber_count = add_api_subscription(plugin, chat_id, base_url, endpoint, is_online, status_message)
    return f"Watching {watch_entry['url']}.\nCurrent status: online ({status_message}).\nSubscribers for this API: {subscriber_count}."

  if message.startswith("/roll"):
    # Increment and persist per-user roll count.
    roll_counts = plugin.obj_cache.get(ROLL_COUNTS_CACHE_KEY, {})
    user_roll_count = int(roll_counts.get(chat_id, 0)) + 1
    roll_counts[chat_id] = user_roll_count
    plugin.obj_cache[ROLL_COUNTS_CACHE_KEY] = roll_counts
    plugin.diskapi_save_pickle_to_data(roll_counts, ROLL_COUNTS_FILE)

    # Dice roll is generated with plugin RNG: randint(1, 7) -> [1, 6].
    rolled_number = int(plugin.np.random.randint(1, 7))
    return f"You rolled: {rolled_number}.\nYou have rolled {user_roll_count} times."

  return "Supported commands: /start, /roll, /watch_api, /ver"


if __name__ == "__main__":
  PIPELINE_NAME = "ratio1_telegram_bot_demo"

  session = Session()

  node = os.getenv("RATIO1_NODE")

  telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
  finished_with_error = False

  try:
    if node is None:
      raise ValueError("Please set the RATIO1_NODE environment variable.")

    if telegram_bot_token is None:
      raise ValueError("Please set the TELEGRAM_BOT_TOKEN environment variable.")

    session.P(f"Connecting to node: {node}")
    session.wait_for_node(node)

    # Deploy telegram bot with both message and periodic processing handlers.
    pipeline, _ = session.create_telegram_simple_bot(
      node=node,
      name=PIPELINE_NAME,
      telegram_bot_token=telegram_bot_token,
      message_handler=reply,
      processing_handler=loop_processing,
      process_delay=10,
      version=BOT_VERSION,
    )
    pipeline.deploy()
  except Exception as exc:
    session.P(f"An error occurred: {exc}", color="red")
    finished_with_error = True

  if not finished_with_error:
    session.P("Bot started successfully. Waiting for messages...")
    session.wait(seconds=10, close_session_on_timeout=True)
  else:
    session.P("Bot failed to start. Please check the logs for more details.", color="red")
    session.close()
