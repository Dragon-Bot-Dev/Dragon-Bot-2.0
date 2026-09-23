import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands

from config import get_db_connection, get_safe_cursor
from services.coc_news import fetch_recent_posts, fetch_post_changes
from commands.war_commands import send_yaml_chunks


def _format_lines(details):
    """Flattens a fetch_post_changes() result into plain text lines for a
    yaml codeblock."""
    lines = []
    for section in details["sections"]:
        if section["heading"]:
            lines.append(f"== {section['heading']} ==")
        lines.extend(section["lines"])
        lines.append("")
    if not lines:
        lines = ["(No details could be extracted — see the link above.)"]
    return lines


def _post_prefix(post):
    header = f"📰 **{post['title']}**"
    if post.get("date"):
        header += f" — {post['date']}"
    return f"{header}\n{post['url']}"


class NewsCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="patchnotes", description="Show the latest Clash of Clans update/balance-change posts")
    @app_commands.describe(count="How many recent posts to show (default 1, max 3)")
    async def patchnotes(self, interaction: discord.Interaction, count: int = 1):
        await interaction.response.defer()
        count = max(1, min(count, 3))

        try:
            # fetch_recent_posts/fetch_post_changes use requests (blocking) —
            # run off the event loop so a slow/hung fetch doesn't freeze the bot.
            posts = await asyncio.to_thread(fetch_recent_posts, count)
        except Exception as e:
            return await interaction.followup.send(f"❌ Couldn't reach the Clash of Clans blog: `{e}`")

        if not posts:
            return await interaction.followup.send("No recent update/balance posts found.")

        for post in posts:
            try:
                details = await asyncio.to_thread(fetch_post_changes, post["url"])
            except Exception as e:
                await interaction.followup.send(f"⚠️ Found **{post['title']}** but couldn't load its details: `{e}`\n{post['url']}")
                continue

            await send_yaml_chunks(interaction.followup.send, _format_lines(details), prefix=_post_prefix(post))


class NewsPatrol(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        if not self.news_check.is_running():
            self.news_check.start()
            print("📰 News Patrol: Started.")

    def cog_unload(self):
        self.news_check.cancel()
        print("🔌 News Patrol: Stopped.")

    @tasks.loop(hours=6)
    async def news_check(self):
        print("--- [News Check Heartbeat] ---")
        try:
            posts = await asyncio.to_thread(fetch_recent_posts, 10)
        except Exception as e:
            print(f"❌ News fetch failed: {e}")
            return

        if not posts:
            return

        cursor = await get_safe_cursor(retries=3, delay=5)
        if not cursor:
            return

        try:
            cursor.execute("SELECT state_value FROM bot_state WHERE state_key = 'last_news_url'")
            row = cursor.fetchone()
            last_seen_url = row[0] if row else None

            if last_seen_url is None:
                # First run ever — start tracking from now instead of dumping
                # the last 10 historical posts into every configured channel.
                new_posts = []
            elif last_seen_url == posts[0]["url"]:
                new_posts = []
            else:
                post_urls = [p["url"] for p in posts]
                if last_seen_url in post_urls:
                    new_posts = posts[:post_urls.index(last_seen_url)]
                else:
                    # Last seen post fell off the recent-posts window (bot was
                    # down a while) — announce just the latest rather than
                    # guessing at how large a backlog was missed.
                    new_posts = posts[:1]

            if new_posts:
                cursor.execute("SELECT guild_id, news_channel_id FROM servers WHERE news_channel_id IS NOT NULL")
                targets = cursor.fetchall()

                for post in reversed(new_posts):  # oldest -> newest
                    try:
                        details = await asyncio.to_thread(fetch_post_changes, post["url"])
                    except Exception as e:
                        print(f"❌ Failed to fetch post details for {post['url']}: {e}")
                        continue

                    lines = _format_lines(details)
                    prefix = _post_prefix(post)

                    for guild_id, channel_id in targets:
                        try:
                            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
                            if channel:
                                await send_yaml_chunks(channel.send, lines, prefix=prefix)
                        except Exception as send_err:
                            print(f"❌ Failed to post news to guild {guild_id}: {send_err}")

                print(f"✅ News Patrol: announced {len(new_posts)} new post(s).")

            cursor.execute(
                "INSERT INTO bot_state (state_key, state_value) VALUES ('last_news_url', %s) "
                "ON DUPLICATE KEY UPDATE state_value = VALUES(state_value)",
                (posts[0]["url"],)
            )
            get_db_connection().commit()
        except Exception as e:
            print(f"💥 News Patrol error: {e}")
        finally:
            cursor.close()

    @news_check.before_loop
    async def before_news_check(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(NewsCommands(bot))
    await bot.add_cog(NewsPatrol(bot))
