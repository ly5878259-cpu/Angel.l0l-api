import discord
from aiohttp import web
import asyncio
import re
import logging


TARGET_ID = 1473153899723751486
TOKEN = "MTQ4MjY5MzIxMzIxODQxMDU4OA.GWnL1b.ps9UWZyffs0A_rMbQKuW8u8PgA0R6VBhzVQ07Q"
WEB_SERVER_HOST = "localhost"
WEB_SERVER_PORT = 5050
TIMEOUT = 1200

client = discord.Client()

pending_requests = {}

target = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_key(text: str) -> str | None:
    if not text:
        return None

    free_match = re.search(r'(FREE_[A-Za-z0-9_\-]+)', text)
    if free_match:
        return free_match.group(1)

    url_match = re.search(r'(https?://[^\s]+)', text)
    if url_match:
        return url_match.group(1)

    if len(text) < 200:
        return text.strip()

    return None


async def send_to_target(url: str) -> discord.Message:
    global target
    if isinstance(target, discord.TextChannel):
        return await target.send(url)
    elif isinstance(target, discord.User):
        return await target.send(url)
    else:
        raise RuntimeError("Target not initialized or invalid")


async def handle_bypass(request: web.Request) -> web.Response:
    url = request.query.get('url')
    if not url:
        return web.Response(text="Missing 'url' parameter", status=400)

    logger.info(f"Request received for the URL : {url}")

    try:
        msg = await send_to_target(url)
    except Exception as e:
        logger.error(f"Error sending to Discord : {e}")
        return web.Response(text=f"Error sending to Discord : {e}", status=500)

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    pending_requests[msg.id] = future
    logger.info(f"En attente de la réponse pour le message {msg.id}")

    try:
        key = await asyncio.wait_for(future, timeout=TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Message deadline expired {msg.id}")
        return web.Response(text="Waiting time exceeded", status=504)
    finally:
        pending_requests.pop(msg.id, None)

    logger.info(f"Clé obtenue et renvoyée : {key}")
    return web.Response(text=key)


async def init_web_server():
    app = web.Application()
    app.router.add_get('/bypass', handle_bypass)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEB_SERVER_HOST, WEB_SERVER_PORT)
    await site.start()
    logger.info(f"Web server started on http://{WEB_SERVER_HOST}:{WEB_SERVER_PORT}")
    return runner


@client.event
async def on_ready():
    global target
    logger.info(f"Bot connecte : {client.user} (ID : {client.user.id})")

    target = client.get_channel(TARGET_ID)
    if target is None:
        target = client.get_user(TARGET_ID)

    if target is None:
        try:
            target = await client.fetch_user(TARGET_ID)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            logger.error("Insufficient permissions for fetch_user")
        except Exception as e:
            logger.error(f"Error fetching user : {e}")

    if target is None:
        logger.error(f"Unable to resolve target ID {TARGET_ID}. "
                     f"Make sure the bot is on the server or that the user exists.")
        await client.close()
        return

    logger.info(f"Target defined : {target} (type : {type(target).__name__})")


@client.event
async def on_message_edit(before, after):
    if after.author == client.user:
        return

    ref = after.reference
    if not ref or not ref.message_id:
        return

    original_id = ref.message_id
    if original_id not in pending_requests:
        return

    if not after.author.bot:
        return

    key = extract_key(after.content)
    if key:
        future = pending_requests.get(original_id)
        if future and not future.done():
            logger.info(f"Key extracted from the edited message {after.id} : {key}")
            future.set_result(key)
    else:
        logger.debug(f"Message édité mais pas de clé détectée : {after.content}")


@client.event
async def on_message(message):
    pass


async def main():
    runner = await init_web_server()

    try:
        await client.start(TOKEN)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
