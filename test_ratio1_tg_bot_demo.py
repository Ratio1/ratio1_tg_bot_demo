import importlib
import sys
import types
import unittest
from unittest import mock


ratio1_stub = types.ModuleType("ratio1")
ratio1_stub.Session = object
ratio1_stub.CustomPluginTemplate = object
sys.modules.setdefault("ratio1", ratio1_stub)

bot = importlib.import_module("ratio1_tg_bot_demo")


class FakeRandom:
  def __init__(self, values):
    self.values = list(values)

  def randint(self, low, high):
    if self.values:
      return self.values.pop(0)
    return low


class FakeNp:
  def __init__(self, values=None):
    self.random = FakeRandom(values or [])


class FakePlugin:
  def __init__(self, now=1000, random_values=None):
    self.obj_cache = {}
    self.saved_pickles = {}
    self.sent_messages = []
    self.now = now
    self.np = FakeNp(random_values)
    self.cfg_version = "test-version"

  def diskapi_load_pickle_from_data(self, filename):
    return self.saved_pickles.get(filename)

  def diskapi_save_pickle_to_data(self, value, filename):
    self.saved_pickles[filename] = value

  def time(self):
    return self.now

  def send_message_to_user(self, user_id, text):
    self.sent_messages.append({"user_id": user_id, "text": text})


class ExistingBotFunctionalityTests(unittest.TestCase):
  def test_start_mentions_available_commands(self):
    plugin = FakePlugin()

    response = bot.reply(plugin, "/start", user="user", chat_id="chat-1")

    self.assertIn("/roll", response)
    self.assertIn("/watch_api", response)
    self.assertIn("hourly lucky number", response)
    self.assertEqual(plugin.saved_pickles[bot.INTERACTED_USERS_FILE], ["chat-1"])

  def test_ver_returns_configured_version(self):
    plugin = FakePlugin()

    response = bot.reply(plugin, "/ver", user="user", chat_id="chat-1")

    self.assertEqual(response, "Bot version: test-version")

  def test_roll_increments_and_persists_roll_count(self):
    plugin = FakePlugin(random_values=[4, 6])

    first_response = bot.reply(plugin, "/roll", user="user", chat_id="chat-1")
    second_response = bot.reply(plugin, "/roll", user="user", chat_id="chat-1")

    self.assertEqual(first_response, "You rolled: 4.\nYou have rolled 1 times.")
    self.assertEqual(second_response, "You rolled: 6.\nYou have rolled 2 times.")
    self.assertEqual(plugin.saved_pickles[bot.ROLL_COUNTS_FILE], {"chat-1": 2})

  def test_loop_processing_sends_hourly_lucky_numbers_once_per_hour(self):
    plugin = FakePlugin(now=5000, random_values=[42])
    bot.reply(plugin, "/start", user="user", chat_id="chat-1")
    plugin.sent_messages.clear()

    bot.loop_processing(plugin)
    bot.loop_processing(plugin)

    self.assertEqual(
      plugin.sent_messages,
      [{"user_id": "chat-1", "text": "Lucky number of the hour: 42"}],
    )
    self.assertEqual(plugin.saved_pickles[bot.LAST_LUCKY_TS_FILE], 5000)


class ApiWatchTests(unittest.TestCase):
  def test_normalizes_api_base_url_and_endpoint(self):
    self.assertEqual(bot.normalize_api_base_url("https://Example.com/api/"), "https://Example.com/api")
    self.assertIsNone(bot.normalize_api_base_url("ftp://example.com"))
    self.assertIsNone(bot.normalize_api_base_url("example.com"))
    self.assertEqual(bot.normalize_health_endpoint("status"), "/status")
    self.assertEqual(bot.normalize_health_endpoint(""), "/health")
    self.assertIsNone(bot.normalize_health_endpoint("https://example.com/status"))
    self.assertEqual(
      bot.build_api_watch_url("https://example.com/api", "/health"),
      "https://example.com/api/health",
    )
    self.assertEqual(
      bot.build_api_watch_id("https://Example.com/API/Health?x=1"),
      "https://example.com/API/Health?x=1",
    )

  def test_watch_api_rejects_missing_or_invalid_url(self):
    plugin = FakePlugin()

    missing_response = bot.reply(plugin, "/watch_api", user="user", chat_id="chat-1")
    invalid_response = bot.reply(plugin, "/watch_api example.com", user="user", chat_id="chat-1")

    self.assertEqual(missing_response, "Usage: /watch_api https://api.example.com")
    self.assertIn("valid API URL", invalid_response)

  def test_watch_api_asks_for_endpoint_then_adds_global_subscription(self):
    plugin = FakePlugin(now=1000)

    with mock.patch.object(bot, "check_api_health", return_value=(True, "HTTP 200")) as health_check:
      first_response = bot.reply(plugin, "/watch_api https://api.example.com", user="user", chat_id="chat-1")
      second_response = bot.reply(plugin, "yes", user="user", chat_id="chat-1")

    self.assertIn("Reply yes to use /health", first_response)
    self.assertIn("Watching https://api.example.com/health", second_response)
    self.assertIn("Current status: online (HTTP 200)", second_response)
    health_check.assert_called_once_with("https://api.example.com/health")

    watchlist = plugin.saved_pickles[bot.API_WATCHLIST_FILE]
    self.assertEqual(len(watchlist), 1)
    watch_entry = next(iter(watchlist.values()))
    self.assertEqual(watch_entry["subscribers"], ["chat-1"])
    self.assertEqual(watch_entry["last_state"], "online")

  def test_watch_api_deduplicates_same_endpoint_across_users(self):
    plugin = FakePlugin(now=1000)

    with mock.patch.object(bot, "check_api_health", return_value=(True, "HTTP 200")):
      bot.reply(plugin, "/watch_api https://api.example.com", user="user-1", chat_id="chat-1")
      bot.reply(plugin, "/health", user="user-1", chat_id="chat-1")
      bot.reply(plugin, "/watch_api https://API.example.com/", user="user-2", chat_id="chat-2")
      bot.reply(plugin, "confirm", user="user-2", chat_id="chat-2")

    watchlist = plugin.saved_pickles[bot.API_WATCHLIST_FILE]
    self.assertEqual(len(watchlist), 1)
    watch_entry = next(iter(watchlist.values()))
    self.assertEqual(watch_entry["subscribers"], ["chat-1", "chat-2"])

  def test_watch_api_does_not_subscribe_when_initial_health_check_fails(self):
    plugin = FakePlugin()

    with mock.patch.object(bot, "check_api_health", return_value=(False, "HTTP 500")):
      bot.reply(plugin, "/watch_api https://api.example.com", user="user", chat_id="chat-1")
      response = bot.reply(plugin, "status", user="user", chat_id="chat-1")

    self.assertIn("not working right now", response)
    self.assertNotIn(bot.API_WATCHLIST_FILE, plugin.saved_pickles)

  def test_loop_processing_notifies_all_subscribers_on_api_state_change(self):
    plugin = FakePlugin(now=1000)

    with mock.patch.object(bot, "check_api_health", return_value=(True, "HTTP 200")):
      bot.reply(plugin, "/watch_api https://api.example.com", user="user-1", chat_id="chat-1")
      bot.reply(plugin, "yes", user="user-1", chat_id="chat-1")
      bot.reply(plugin, "/watch_api https://api.example.com", user="user-2", chat_id="chat-2")
      bot.reply(plugin, "yes", user="user-2", chat_id="chat-2")

    plugin.now = 1000 + bot.API_CHECK_INTERVAL_SECONDS
    plugin.sent_messages.clear()

    with mock.patch.object(bot, "check_api_health", return_value=(False, "timed out")):
      bot.loop_processing(plugin)

    self.assertEqual(
      plugin.sent_messages,
      [
        {"user_id": "chat-1", "text": "API https://api.example.com/health is offline.\nStatus: timed out"},
        {"user_id": "chat-2", "text": "API https://api.example.com/health is offline.\nStatus: timed out"},
      ],
    )

    plugin.now += bot.API_CHECK_INTERVAL_SECONDS
    plugin.sent_messages.clear()

    with mock.patch.object(bot, "check_api_health", return_value=(True, "HTTP 200")):
      bot.loop_processing(plugin)

    self.assertEqual(
      plugin.sent_messages,
      [
        {"user_id": "chat-1", "text": "API https://api.example.com/health is back online.\nStatus: HTTP 200"},
        {"user_id": "chat-2", "text": "API https://api.example.com/health is back online.\nStatus: HTTP 200"},
      ],
    )


if __name__ == "__main__":
  unittest.main()
