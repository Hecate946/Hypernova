import time
import discord
import asyncio
import logging
import datetime
from discord.ext import commands, tasks
from collections import defaultdict
from utilities import default, converters

command_logger = logging.getLogger("NGC0000")

def setup(bot):
    bot.add_cog(Updater(bot))


class Updater(commands.Cog):
    """
    Manage postgres updates
    """
    def __init__(self, bot):
        self.bot = bot
        
        self.command_batch = defaultdict(list)
        self.snipe_batch   = defaultdict(list)


        self.batch_lock = asyncio.Lock(loop=bot.loop)
        
        self.bulk_inserter.start()
        

    def cog_unload(self):
        self.bulk_inserter.stop()


    @tasks.loop(seconds=10.0)
    async def bulk_inserter(self):

        #============#
        # On Command #
        #============#
        query = '''
                INSERT INTO commands (
                    server_id, channel_id, author_id,
                    timestamp, prefix, command, failed
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                '''
        async with self.batch_lock:
            for data in self.command_batch.items():
                server_id  = data[1][0]["server_id" ]
                channel_id = data[1][0]["channel_id"]
                author_id  = data[1][0]["author_id" ]
                timestamp  = data[1][0]["timestamp" ]
                prefix     = data[1][0]["prefix"    ]
                command    = data[1][0]["command"   ]
                failed     = data[1][0]["failed"    ]
                content    = data[1][0]["content"   ]

                await self.bot.cxn.execute(query, server_id, channel_id, author_id, timestamp, prefix, command, failed)

                # Command logger to ./data/logs/commands.log
                destination = None
                if server_id is None:
                    destination = 'Private Message'
                else:
                    destination = f'#{self.bot.get_channel(channel_id)} [{channel_id}] ({self.bot.get_guild(server_id)}) [{server_id}]'
                command_logger.info(f'{await self.bot.fetch_user(author_id)} in {destination}: {content}')
            self.command_batch.clear()

        query = """UPDATE messages SET deleted = True WHERE message_id = $1 AND author_id = $2 AND channel_id = $3"""
        async with self.batch_lock:
            for data in self.snipe_batch.items():
                channel_id = data[1][0]['channel_id']
                message_id = data[1][0]['message_id']
                author_id  = data[1][0]['author_id' ]

                await self.bot.cxn.execute(query, message_id, author_id, channel_id)
            self.snipe_batch.clear()


    @commands.Cog.listener()
    async def on_command(self, ctx):
        command = ctx.command.qualified_name
        self.bot.command_stats[command] += 1
        if ctx.guild:
            server_id = ctx.guild.id
        else:
            server_id = None
        async with self.batch_lock:
            self.command_batch[ctx.message.id].append(               
                {
                    "server_id": server_id, 
                    "channel_id": ctx.channel.id, 
                    "author_id": ctx.author.id,
                    "timestamp": ctx.message.created_at.utcnow(),
                    "prefix": ctx.prefix,
                    "command": ctx.command.qualified_name,
                    "failed": ctx.command_failed,
                    "content": ctx.message.clean_content
                }
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if self.bot.bot_ready is False:
            return
        if message.author.bot or not message.guild:
            return
        if message.author.bot:
            return

        async with self.batch_lock:
            self.snipe_batch[message.id].append(               
                {
                    "message_id": message.id,
                    "author_id" : message.author.id,
                    "channel_id": message.channel.id
                }
            )