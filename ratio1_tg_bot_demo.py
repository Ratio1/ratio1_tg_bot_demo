"""
ratio1_tg_bot_demo.py
---------------------

Simple Ratio1 Telegram bot demo.

Features:
1. `/roll` rolls a dice between 1 and 6.
2. The bot persists how many times each user rolled.
3. Every hour, all users that interacted with the bot receive a lucky number (1-100).
"""

import os
from ratio1 import Session, CustomPluginTemplate


try:
  from ver import VERSION as BOT_VERSION
except Exception:
  BOT_VERSION = "unknown"

def loop_processing(plugin: CustomPluginTemplate):
  # Cache keys and disk file names.
  cache_ready_key = "demo_cache_ready"
  roll_counts_cache_key = "demo_roll_counts"
  interacted_users_cache_key = "demo_interacted_users"
  last_lucky_ts_cache_key = "demo_last_lucky_ts"
  interacted_users_file = "demo_interacted_users.pkl"
  last_lucky_ts_file = "demo_last_lucky_ts.pkl"
  roll_counts_file = "demo_roll_counts.pkl"

  # Initialize in-memory cache once per plugin process, loading persisted data from disk.
  if not plugin.obj_cache.get(cache_ready_key):
    plugin.obj_cache[roll_counts_cache_key] = plugin.diskapi_load_pickle_from_data(roll_counts_file) or {}
    plugin.obj_cache[interacted_users_cache_key] = plugin.diskapi_load_pickle_from_data(interacted_users_file) or []
    plugin.obj_cache[last_lucky_ts_cache_key] = plugin.diskapi_load_pickle_from_data(last_lucky_ts_file) or 0
    plugin.obj_cache[cache_ready_key] = True

  now_ts = int(plugin.time())
  last_lucky_ts = int(plugin.obj_cache.get(last_lucky_ts_cache_key, 0))

  # Send lucky numbers at most once per hour.
  if now_ts - last_lucky_ts < 3600:
    return

  # Broadcast one lucky number (1..100) to each user who interacted with the bot.
  users = plugin.obj_cache.get(interacted_users_cache_key, [])
  for user_id in users:
    lucky_number = int(plugin.np.random.randint(1, 101))
    plugin.send_message_to_user(
      user_id=user_id,
      text=f"Lucky number of the hour: {lucky_number}",
    )

  plugin.obj_cache[last_lucky_ts_cache_key] = now_ts
  plugin.diskapi_save_pickle_to_data(now_ts, last_lucky_ts_file)


def reply(plugin: CustomPluginTemplate, message: str, user: str, chat_id: str):
  # Cache keys and disk file names.
  cache_ready_key = "demo_cache_ready"
  roll_counts_cache_key = "demo_roll_counts"
  interacted_users_cache_key = "demo_interacted_users"
  last_lucky_ts_cache_key = "demo_last_lucky_ts"
  roll_counts_file = "demo_roll_counts.pkl"
  interacted_users_file = "demo_interacted_users.pkl"
  last_lucky_ts_file = "demo_last_lucky_ts.pkl"

  # Initialize in-memory cache once per plugin process, loading persisted data from disk.
  if not plugin.obj_cache.get(cache_ready_key):
    plugin.obj_cache[roll_counts_cache_key] = plugin.diskapi_load_pickle_from_data(roll_counts_file) or {}
    plugin.obj_cache[interacted_users_cache_key] = plugin.diskapi_load_pickle_from_data(interacted_users_file) or []
    plugin.obj_cache[last_lucky_ts_cache_key] = plugin.diskapi_load_pickle_from_data(last_lucky_ts_file) or 0
    plugin.obj_cache[cache_ready_key] = True

  # Track every chat that interacts with the bot for hourly lucky-number broadcasts.
  users = plugin.obj_cache.get(interacted_users_cache_key, [])
  if chat_id not in users:
    users.append(chat_id)
    plugin.obj_cache[interacted_users_cache_key] = users
    plugin.diskapi_save_pickle_to_data(users, interacted_users_file)

  if message.startswith("/start"):
    return (
      "Welcome to Ratio1 Telegram Bot Demo.\n"
      "Use /roll to roll a dice between 1 and 6.\n"
      "You will also receive an hourly lucky number."
    )

  if message.startswith("/ver"):
    return f"Bot version: {plugin.cfg_version}"

  if message.startswith("/roll"):
    # Increment and persist per-user roll count.
    roll_counts = plugin.obj_cache.get(roll_counts_cache_key, {})
    user_roll_count = int(roll_counts.get(chat_id, 0)) + 1
    roll_counts[chat_id] = user_roll_count
    plugin.obj_cache[roll_counts_cache_key] = roll_counts
    plugin.diskapi_save_pickle_to_data(roll_counts, roll_counts_file)

    # Dice roll is generated with plugin RNG: randint(1, 7) -> [1, 6].
    rolled_number = int(plugin.np.random.randint(1, 7))
    return (
      f"You rolled: {rolled_number}. "
      f"You have rolled {user_roll_count} times."
    )

  return "Supported commands: /start, /roll, /ver"


if __name__ == "__main__":
  PIPELINE_NAME = "ratio1_telegram_bot_demo"

  session = Session()

  node = os.getenv("RATIO1_NODE")
  chat_id = os.getenv("TELEGRAM_CHAT_ID")
  telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
  finished_with_error = False

  try:
    if chat_id is None or telegram_bot_token is None:
      raise ValueError("Please set the TELEGRAM_CHAT_ID and TELEGRAM_BOT_TOKEN environment variables.")

    session.P(f"Connecting to node: {node}")
    session.wait_for_node(node)

    # Deploy telegram bot with both message and periodic processing handlers.
    pipeline, _ = session.create_telegram_simple_bot(
      node=node,
      name=PIPELINE_NAME,
      telegram_bot_token=telegram_bot_token,
      chat_id=chat_id,
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
