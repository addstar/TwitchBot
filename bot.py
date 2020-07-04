import sys
sys.path.insert(1, '../PythonTwitchBotFramework/')

from datetime import datetime
from twitchbot.bots import BaseBot
from twitchbot import event_handler, Event, Message, Channel, PollData

class AddstarBot(BaseBot):
    def logmsg(self, msg: str):
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        print(ts + " " + msg)

    async def on_privmsg_received(self, msg: Message):
        self.logmsg(f'Chat #{msg.channel.name} ({msg.author}) {msg.content}')

    async def on_channel_points_redemption(self, msg: Message, reward: str):
        self.logmsg(f'PointsRedeem #{msg.channel.name} ({msg.author}) {reward}: {msg.content}')

    async def on_bits_donated(self, msg: Message, bits: int):
        self.logmsg(f'BitsCheered #{msg.channel.name} ({msg.author}) {bits}: {msg.content}')

    async def on_channel_raided(self, channel: Channel, raider: str, viewer_count: int):
        self.logmsg(f'ChannelRaid #{channel.name} ({raider}) {viewer_count}: {msg.content}')

    async def on_channel_subscription(self, subscriber: str, channel: Channel, msg: Message):
        self.logmsg(f'Subscription #{channel.name} ({subscriber}): {msg.content}')

    async def on_poll_started(self, channel: Channel, poll: PollData):
        self.logmsg(f'PollStarted #{channel.name}: {poll.duration_seconds} {poll.title}')

    async def on_poll_ended(self, channel: Channel, poll: PollData):
        self.logmsg(f'PollStarted #{channel.name}: {poll.title}')

    async def on_user_join(self, user: str, channel: Channel):
        self.logmsg(f'UserJoin #{channel.name}: {user}')

    async def on_user_part(self, user: str, channel: Channel):
        self.logmsg(f'UserPart #{channel.name}: {user}')

    async def on_whisper_received(self, msg: Message):
        self.logmsg(f'WhisperRecv {msg.author}: {msg.content}')

if __name__ == '__main__':
    print("Starting bot...")
    AddstarBot().run()

