import sys
sys.path.insert(1, 'PythonTwitchBotFramework/')

import os
import websockets
import asyncio
import json
import random
import traceback
import re
import time
from math import floor
from pprint import pprint
from mcrcon import MCRcon
from datetime import datetime, timedelta

from twitchbot.bots import BaseBot
from twitchbot import event_handler, Event, Message, Channel, PollData, Command, CommandContext
import logging.config
import yaml

# Fetch configuration from file
with open('logging.yaml', 'r') as f:
    config = yaml.safe_load(f.read())
    logging.config.dictConfig(config)

# Set initial Hype train state
hypetrain = {}
hypetrain['level'] = 1
hypetrain['value'] = 0
hypetrain['goal']  = 2000
hypetrain['total'] = 0
hypetrain['perc']  = 0

# Get the logger specified in the file
logger = logging.getLogger(__name__)

# Read channel/token from config file
config = json.load(open('configs/pubsub.json'))
_channel_id = config['channel_id']
_auth_token = config['auth_token']

# Set this to the version of minecraft in use
# This adjusts the commands used for redemptions
_mcver = config['mcver']

# List of current game modes for rewards (minecraft, chancecubes, etc)
_mcmodes = config['mcmodes']

# Rcon stuff
_rconPass = config['rconpass']
_rconPort = config['rconport']

# PubSub WebSocket
async def pubsubConnect():
    uri = 'wss://pubsub-edge.twitch.tv'

    bits_topic_prefix       = 'channel-bits-events-v2.'
    points_topic_prefix     = 'channel-points-channel-v1.'
    sub_topic_prefix        = 'channel-subscribe-events-v1.'
    hype_train_topic_prefix = 'hype-train-events-v1.'
    raid_topic_prefix       = 'raid.'
    follow_topic_prefix     = 'following.'
    polls_topic_prefix      = 'polls.'
    community_points_prefix = 'community-points-channel-v1.'

    bits_topic       = bits_topic_prefix + _channel_id
    points_topic     = points_topic_prefix + _channel_id
    sub_topic        = sub_topic_prefix + _channel_id
    hype_train_topic = hype_train_topic_prefix + _channel_id
    raid_topic       = raid_topic_prefix + _channel_id
    follow_topic     = follow_topic_prefix + _channel_id
    polls_topic      = polls_topic_prefix + _channel_id
    community_topic  = community_points_prefix + _channel_id

    # Subscription Request
    request = {
        'type': 'LISTEN',
        'data': {
            'topics': [bits_topic, points_topic, sub_topic, hype_train_topic, raid_topic, follow_topic, polls_topic, community_topic],
            'auth_token': _auth_token
        }
    }

    reconnect_timeout = 1
    # Loop Forever
    while True:
        # Connect to server
        logmsg("Connecting to Twitch PubSub...")
        async with websockets.connect(uri) as websocket:
            reconnect_timeout = 1

            # Send request
            #logmsg("Sending: " + create_debug_message(request))
            await websocket.send(json.dumps(request))

            # Receive response
            try:
                response_raw = await asyncio.wait_for(websocket.recv(), timeout=10)
                #logmsg("Connect Response: " + create_debug_message(response_raw))
            except asyncio.TimeoutError:
                logmsg(create_debug_message('PubSub failed to respond, retrying connection'))
                continue
            response = json.loads(response_raw)

            # If no errors, begin loop
            if (response['error'] == ''):
                #logmsg(create_debug_message('PubSub Connected'))
                logmsg('PubSub Connected')

                # When the last ping was sent
                last_ping = datetime.now()
                next_ping = timedelta(minutes=4, seconds=30)

                while not websocket.closed:
                    # As per documentation, send ping requests within 5 minutes
                    ping_delay = next_ping - (datetime.now() - last_ping)
                    try:
                        response_raw = await asyncio.wait_for(websocket.recv(), timeout=ping_delay.seconds)
                    except asyncio.TimeoutError:
                        # If timeout, ping server
                        await websocket.send('{"type": "PING"}')
                        try:
                            await asyncio.wait_for(websocket.recv(), timeout=5)
                            # Update last ping time
                            last_ping = datetime.now()
                        except asyncio.TimeoutError:
                            break # If no response from server, reconnection is needed
                        continue # If we get a response, ping was successful, return to listening
                    except websockets.exceptions.ConnectionClosedError as ex:
                        logmsg(f'ConnectionClosedError: {ex}')
                        continue
                    except Exception as ex:
                        logmsg(f'Unexpected asyncio error: {ex}')
                        continue

                    # Process response
                    #logmsg("Message payload: " + response_raw)
                    response = json.loads(response_raw)

                    if response['type'] == 'MESSAGE':
                        # Get the topic for this message
                        topic   = response['data']['topic']
                        message = json.loads(response['data']['message'])

                        try:
                            if topic.startswith(bits_topic_prefix):
                                handleBitsMessage(message)
                            elif topic.startswith(sub_topic_prefix):
                                handleSubMessage(message)
                            elif topic.startswith(points_topic_prefix):
                                handlePointsMessage(message)
                            elif topic.startswith(follow_topic):
                                handleFollow(message)
                            elif topic.startswith(follow_topic):
                                handleFollow(message)
                            elif topic.startswith(hype_train_topic):
                                handleHypeTrain(message)
                            elif topic.startswith(raid_topic_prefix):
                                handleRaid(message)
                            elif topic.startswith(polls_topic_prefix):
                                handlePoll(message)
                            elif topic.startswith(community_points_prefix):
                                logmsg(f'COMMUNITY POINTS: {response_raw}')
                            else:
                                logmsg(f'UNHANDLED MESSAGE: {response_raw}')
                        except Exception as ex:
                            logmsg(f'Unexpected error handling message: {ex}')
                            logmsf(traceback.format_exc())
                            continue

                    elif response['type'] == "RECONNECT":
                        # Do reconnect if requested
                        logmsg(create_debug_message('PubSub Reconnect requested, complying'))
                        break
            else:
                logmsg(create_debug_message('PubSub Error! ' + response['error']))
                logmsg('PubSub Error! ' + response['error'])
            logmsg(create_debug_message('PubSub Disconnected'))
            logmsg('PubSub Disconnected')
        
        await asyncio.sleep(reconnect_timeout)
        reconnect_timeout += reconnect_timeout # Exponential timeout

def handleFollow(message):
    #logmsg("RAWFOLLOW: " + json.dumps(message))
    follow = {
        'username': message['username'],
        'userid': message['user_id']
    }

    username = follow['username']
    userid   = follow['userid']
    logmsg(f'Follow: {username} ({userid})')

def updateHypeTrain(progress):
    hypetrain['level'] = int(progress['level']['value'])
    hypetrain['value'] = int(progress['value'])
    hypetrain['goal']  = int(progress['goal'])
    hypetrain['total'] = int(progress['total'])
    hypetrain['perc']  = floor((int(progress['value']) / int(progress['goal'])) * 100)
    logmsg("UPDATEHYPE: " + json.dumps(hypetrain))
    return hypetrain

def handleHypeTrain(message):
    logmsg("RAWHYPE: " + json.dumps(message))
    htype = message['type']

    if 'data' in message:
        data = message['data']
    else:
        data = {}

    if htype == 'hype-train-start':
        # Start of a hype train
        time.sleep(0.8)
        logmsg(f'HypeTrainStart: ...')
        updateHypeTrain(data['progress'])
        chatbot.say('/me CurseLit CurseLit CurseLit CurseLit CurseLit CurseLit')
        chatbot.say('/me ~ The HYPE TRAIN has arrived ~')
        chatbot.say('/me CurseLit CurseLit CurseLit CurseLit CurseLit CurseLit')

    elif htype == 'hype-train-progression':
        # Each time the hype train progresses
        time.sleep(0.2)
        progress = updateHypeTrain(data['progress'])
        logmsg(f'HypeTrainProgress: Level {progress["level"]} - {progress["value"]}/{progress["goal"]} ({progress["perc"]}%)')

    elif htype == 'hype-train-level-up':
        # Each time the hype train levels up
        time.sleep(0.8)
        progress = updateHypeTrain(data['progress'])
        oldlevel = int(progress["level"]) - 1

        logmsg(f'HypeTrainLevelUp: New level: {progress["level"]} / Goal: {progress["goal"]}')
        chatbot.say(f'/me Hype Train level {oldlevel} completed! PogChamp')
        chatbot.say(f'/me PowerUpL Now on level {progress["level"]} PowerUpR')

    elif htype == 'hype-train-end':
        # When the hype train ends, it doesnt give much info so we will have to rely on
        # stored information collected from the progression updates and level ups
        time.sleep(0.8)
        reason = data['ending_reason']
        logmsg(f'HypeTrainEnd: {reason}')
        if reason == 'COMPLETED' and hypetrain['level'] >= 5 and hypetrain['perc'] >= 100:
            chatbot.say('/me PogChamp PogChamp Level 5 Hype train COMPLETED!!! PogChamp PogChamp')
            chatbot.say('/me artful5Hugs Thank you for your support artful5Hugs')
        else:
            chatbot.say(f'/me CurseLit Hype train has ended on level {hypetrain["level"]} CurseLit')
            chatbot.say('/me artful5Hugs Thank you for your support artful5Hugs')

def handleRaid(message):
    logmsg("RAWRAID: " + json.dumps(message))

def handlePoll(message):
    logmsg("RAWPOLL: " + json.dumps(message))

    if message['type'] == 'POLL_COMPLETE':
        poll = message['data']['poll']
        title = poll['title']
        choices = poll['choices']
        winners = []

        logmsg(f'Poll title: {title}')

        # First get the max vote count
        maxvotes = 0
        for choice in choices:
            entry = choice['title']
            votes = choice['votes']['total']
            logmsg(f'  - {entry} = {votes}')
            if votes > maxvotes:
                maxvotes = votes

        # Get the winning choice(s)
        for choice in choices:
            entry = choice['title']
            votes = choice['votes']['total']
            if votes == maxvotes:
                winners.append(entry)

        chatbot.say(f'/me Poll ended: "{title}"')
        if len(winners) > 1:
            chatbot.say('/me NotLikeThis Results are tied!')
        else:
            chatbot.say('/me FBtouchdown The winner was:')

        for name in winners:
            chatbot.say(f'/me PorscheWIN {name} ({maxvotes} votes)')

def handleBitsMessage(message):
    # Do bits message
    #logmsg("RAWBIT: " + json.dumps(message))
    if message['data']['context'] == 'cheer':
        cheer = message['data']
        msg = {
            'bits': {
                'bits_used': cheer['bits_used'],
                'chat_message': cheer['chat_message'],
                'user_name': cheer['user_name'],
                'timestamp': cheer['time']
            }
        }
        if msg['bits']['user_name'] is None or msg['bits']['user_name'] == '':
            msg['bits']['user_name'] = 'Anonymous'

        logmsg(json.dumps(msg))
        bits  = msg['bits']['bits_used']
        rwho  = msg['bits']['user_name']
        cubes = 0

        # Do the chance cube thing if necessary
        if 'chancecubes' in _mcmodes:
            cost  = 100
            cubes = int(bits/cost)

        if 'mobs' in _mcmodes:
            cost  = 85
            maxmobs = int(bits/cost)+1
            logmsg(f'Max mobs selected: {maxmobs}')

        # Do we spawn mobs?
        age = ''
        mob = ''
        if 'mobs' in _mcmodes:
            # Increase hostile chance with more bits
            # Rules:
            #   <100 bits does not increase chance
            #   100+ bits increases chance per 30
            #
            minbits       = 50   # min bits for reward
            startbits     = 101  # start increasing chance at this
            bitsperlevel  = 30   # multiplier of bits per increased level of hostile mob
            hostilechance = 2 if bits < startbits else 3 + int(round(((bits-startbits) / bitsperlevel)))
            passivechance = 3

            if bits >= minbits:
                # Select a mob to spawn if necessary
                mobs = pickMob(passivechance, hostilechance, bits)
                mob = random.choice(mobs)
                if any(x in ('vanilla', 'spigot') for x in _mcmodes):
                    age = '-99999999'

                # Pick a random colour for the mob name
                namecolours = 'abcde96'
                ncolour = random.choice(namecolours)
            if cubes and cubes > 0:
                logmsg(f'Bit reward: {cubes}x Chance cubes (by {rwho})')
                cmds = [
                    mcTitle(f'{cubes}x Chance Cubes!!!', f'Given by {rwho}', 'blue', 'red'),
                    mcCmd(f'give ArtfulMelody chancecubes:chance_cube {cubes}'),
                    mcEffect('minecraft:nausea', 5, 1),
                    mcEffect('tombstone:ghostly_shape', 5, 1),
                ]
                if mob:
                    cmds.append(mcSummon(mob, age, 1, '§'+ncolour+rwho))

                sendRconCommands(cmds)
            elif mob and bits >= minbits:
                logmsg(f'Bit reward: Spawning {mob} (by {rwho})')
                cmds = [
                    mcTitle(f'New buddy!', f'Given by {rwho}', 'yellow', 'red'),
                    mcEffect('minecraft:nausea', 5, 1),
                ]

                # number of mobs based on amount
                for x in range(0, maxmobs):
                    cmds.append(mcSummon(mob, age, 1, '§'+ncolour+rwho))
                    ncolour = random.choice(namecolours)
                    mob = random.choice(mobs)

                sendRconCommands(cmds)

def handleSubMessage(message):
    # So sub message
    logmsg("RAWSUB: " + json.dumps(message))
    msg = {
        'sub': {
            'user_name': '',
            'timestamp': message['time'],
            'sub_plan': message['sub_plan'],
            'months': message['months'],
            'context': message['context'],
            'message': message['sub_message']['message'],
            'from_user': ''
        }
    }

    sub = msg['sub']
    if sub['context'] == 'anonsubgift':
        sub['user_name'] = message['recipient_display_name']
        sub['from_user'] = 'Anonymous Gifter'
        rwho = sub['from_user']
    elif sub['context'] == 'subgift':
        sub['user_name'] = message['recipient_display_name']
        sub['from_user'] = message['display_name']
        rwho = sub['from_user']
    else:
        sub['user_name'] = message['display_name']
        rwho = sub['user_name']

    logmsg(json.dumps(msg))

    # Do we spawn mobs?
    if 'mobs' in _mcmodes:
        hostilechance = 2
        passivechance = 3
        mobs = pickMob(passivechance, hostilechance, 0, 1)
        mob = random.choice(mobs)

        age = ''
        if 'vanilla' in _mcmodes:
            age = '-99999999'

        # Pick a random colour for the mob name
        namecolours = 'abcde96'
        ncolour = random.choice(namecolours)

        if 'chancecubes' in _mcmodes:
            logmsg(f'Sub reward: Giant chance cube (by {rwho})')
            cmds = [
                mcTitle(f'Giant Chance Cube!', f'Thanks to {rwho}', 'green', 'red'),
                mcCmd(f'give ArtfulMelody chancecubes:compact_giant_chance_cube 1'),
                mcEffect('minecraft:nausea', 5, 1),
                mcEffect('tombstone:ghostly_shape', 5, 1),
            ]

            if mob:
                cmds.append(mcSummon(mob, age, 1, '§'+ncolour+rwho))
                # Also make a mob for the gift receiver
                if sub['context'] == 'subgift':
                    mob = random.choice(mobs)
                    cmds.append(mcSummon(mob, age, 1, '§'+ncolour+sub['user_name']))

        elif 'mobs' in _mcmodes and mob:
            logmsg(f'Sub reward: Spawning {mob} (by {rwho})')
            cmds = [
                mcTitle(f'New buddy!', f'Given by {rwho}', 'yellow', 'red'),
                mcEffect('minecraft:nausea', 5, 1),
                mcSummon(mob, age, 1, '§'+ncolour+rwho),
            ]

            # Also make a mob for the gift receiver
            if sub['context'] == 'subgift':
                mob = random.choice(mobs)
                cmds.append(mcSummon(mob, age, 1, '§'+ncolour+sub['user_name']))

        # Execute the set of commands
        sendRconCommands(cmds)

        # Invoke a small delay to avoid killing the server with commands
        # Since gift subs tend to be in batches, we sleep a little more between them
        if sub['context'] == 'subgift' or sub['context'] == 'anonsubgift':
            time.sleep(0.3)
        else:
            time.sleep(0.1)

def handlePointsMessage(data):
    message = data['data']
    #logmsg(message)

    # Do reward points message
    reward = message['redemption']['reward']
    msg = {
        'reward': {
            'timestamp': message['timestamp'],
            'user_name': message['redemption']['user']['display_name'],
            'reward_name': reward['title'],
            'image': reward['default_image'],
            'user_input': ''
        }
    }

    if reward['is_user_input_required']:
        msg['reward']['user_input'] = message['redemption']['user_input']

    #logmsg(json.dumps(msg))

    rtype = msg['reward']['reward_name']
    rwho  = msg['reward']['user_name']

    if rtype.startswith('Drop/Destroy it'):
        # Destroy item in hand
        logmsg(f'Reward: Destroy item (by {rwho})')
        cmds = [
            mcTitle('Item Destroyed!!', f'Evil deed done by {rwho}', 'red', 'yellow'),
            mcCmd('replaceitem entity ArtfulMelody weapon.mainhand minecraft:air'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Pumpkin'):
        # Give pumpkin mask (remove current headwear first)
        logmsg(f'Reward: WIP - Pumpkin mask (by {rwho})')
        cmds = [
            mcTitle('Pumpkin Mask Time!', f'Requested by {rwho}', 'gold', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcGive('minecraft:carved_pumpkin', 1),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Sticky Feet'):
        # Give very high slowness effect
        logmsg(f'Reward: Sticky feet (by {rwho})')
        cmds = [
            mcTitle('You have Sticky Feet!', f'{rwho} put glue on your boots', 'dark_purple', 'yellow'),
            mcEffect('minecraft:slowness', 30, 20),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Encase in ice'):
        # Give very high slowness effect
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('Encased in ice!', f'Made cool by {rwho}', 'blue', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcEffect('mowziesmobs:frozen', 20, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Hype Mode'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('Hype Mode Engaged!!', f'{rwho} wants a party!', 'light_purple', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcEffect('minecraft:jump_boost', 30, 3),
            mcEffect('cyclicmagic:potion.bounce', 30, 3),
            mcEffect('minecraft:speed', 30, 3),
            mcEffect('minecraft:night_vision', 30, 1),
            mcEffect('trailmix:trailmix', 30, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Who turned off the lights'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('Who turned off the lights?!', f'(psst.. it was {rwho})', 'red', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcEffect('minecraft:blindness', 30, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Get Confuzzled'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('You are confuzzled!', f'(blame {rwho})', 'red', 'yellow'),
            mcEffect('minecraft:nausea', 7, 1),
            mcEffect('quark:danger_sight', 30, 1),
            mcEffect('midnight:confusion', 30, 1),
            mcEffect('cyclicmagic:potion.butter', 30, 2),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Bring on the night'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('There will be night!', f'{rwho} likes the night life...', 'red', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcCmd(f'time set night'),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Daytime is good'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('Let there be light!', f'{rwho} said so...', 'yellow', 'white'),
            mcCmd(f'time set day'),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('This is Australia'):
        logmsg(f'Reward: {rtype} (by {rwho})')
        cmds = [
            mcTitle('Australia is real!', f'{rwho} has proof!', 'blue', 'red', 20, 300, 40),
            mcEffect('minecraft:nausea', 7, 1),
            mcEffect('randomthings:collapse', 20, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Healing Save'):
        # Give Regen + Fire Resistance
        logmsg(f'Reward: Healing save (by {rwho})')
        cmds = [
            mcTitle('Healing Save!!', f'Apparently {rwho} is nice', 'green', 'yellow'),
            mcEffect('minecraft:regeneration', 45, 1),
            mcEffect('minecraft:fire_resistance', 45, 1),
            mcEffect('minecraft:resistance', 45, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('No sleep tonight'):
        # No sleep
        logmsg(f'Reward: No sleep tonight (by {rwho})')
        cmds = [
            mcTitle('No Sleep!', f'Requested by {rwho}', 'red', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Free lunch'):
        logmsg(f'Reward: Free lunch')
        cmds = [
            mcTitle('Free Lunch!', f'Given by {rwho}', 'green', 'yellow'),
            mcEffect('minecraft:nausea', 5, 1),
            mcGive('minecraft:cooked_beef', 5),
            mcGive('minecraft:baked_potato', 5),
            mcGive('minecraft:pumpkin_pie', 2),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Wink'):
        logmsg(f'Reward: Wink')
        cmds = [
            mcTitle('Wink!', f'Requested by {rwho}', 'light_purple', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Make Me Dab'):
        logmsg(f'Reward: Make Me Dab')
        cmds = [
            mcTitle('Stop! Dabbing time!', f'Requested by {rwho}', 'yellow', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Posture Check'):
        logmsg(f'Reward: Posture Check')
        cmds = [
            mcTitle('Check that posture!', f'Requested by {rwho}', 'gold', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Yo, drink some'):
        logmsg(f'Reward: Drink some water')
        cmds = [
            mcTitle('Hydrate!', f'{rwho} splashed some water on you', 'aqua', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
            mcParticle('splash', 1, 1000),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Craft a damn shovel'):
        logmsg(f'Reward: Craft a damn shovel')
        cmds = [
            mcTitle('Shovel it!', f'Requested by {rwho}', 'green', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Spawn something bad'):
        logmsg(f'Reward: Spawn something bad')
        mobs = pickMob(0, 1, 0)
        mob = random.choice(mobs)
        ncolour = random.choice('abcde96')

        cmds = [
            mcTitle('Bad mob for you!', f'You can thank {rwho}', 'red', 'white'),
            mcEffect('minecraft:nausea', 5, 1),
            mcSummon(mob, '', 1, '§'+ncolour+rwho),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('BOOO'):
        # Scary in game message/sound
        logmsg(f'Reward: BOOOO (by {rwho})')
        sounds = [
            'minecraft:entity.ghast.hurt',
            'minecraft:entity.ghast.scream',
            'minecraft:entity.horse.death',
            'minecraft:entity.wolf.howl',
            'minecraft:entity.elder_guardian.curse',
            'minecraft:entity.bat.takeoff',
            'minecraft:entity.lightning.thunder',
            'minecraft:entity.llama.death',
            'minecraft:ambient.cave',
            'minecraft:entity.donkey.death',
        ]
        sound1 = random.choice(sounds)
        sound2 = random.choice(sounds)
        sound3 = random.choice(sounds)
        cmds = [
            mcSound(sound1),
            mcSound(sound2),
            mcSound(sound3),
            mcSound(sound2),
            mcSound(sound1),
            mcSound(sound3),
            mcEffect('minecraft:nausea', 6, 1),
            mcEffect('minecraft:blindness', 2, 1),
            mcParticle('explosion_emitter', 7, 2),
            mcTitle('BOOOOOOOOOOOO!!!!', f'Requested by {rwho}', 'red', 'gray', 5, 80, 20),
        ]
        sendRconCommands(cmds, 0.01)
    elif rtype.startswith("Joke's On You"):
        logmsg(f'Reward: Dad Joke')
        stream = os.popen('curl --max-time 2 --retry 2 -s -H "Accept: application/json" https://icanhazdadjoke.com/')
        result = stream.read()
        logmsg(f'Dad Joke result: {result}')
        if result:
            data = json.loads(result)
            if data['status'] == 200:
                joke = data['joke']
                chatbot.say(f'@ArtfulMelody - You must read this joke on stream:')
                chatbot.say(f'@ArtfulMelody - {joke}')
            else:
                logmsg(f'Bad response: {result}')
        else:
            logmsg(f'No response received!')
    else:
        logmsg(f'Unknown reward: {rtype}')
        logmsg('Full request: ' + json.dumps(msg))

def sendRconCommands(cmds, delay = 0.03):
    mcr = MCRcon("127.0.0.1", _rconPass, _rconPort, 0)

    try:
        mcr.connect()
    except Exception as ex:
        logmsg(f'ERROR: Unable to connect to rcon server: {ex}')
        return

    # flatten all commands
    cmds = [item for sublist in cmds for item in sublist]

    for cmd in cmds:
        try:
            resp = mcr.command(cmd)
            logmsg(f'RCON Command: {cmd}: {resp}')
            time.sleep(delay)
        except Exception as ex:
            logmsg(f'ERROR: Unable to send rcon command: {cmd}')
            logmsg(f'       {ex}')
            break

    mcr.disconnect()

def mcTitle(title, sub, tcolour, scolour, fadein = 20, delay = 100, fadeout = 40):
    cmds = [
        f'title ArtfulMelody times {fadein} {delay} {fadeout}',
        f'title ArtfulMelody subtitle {{"text":"{sub}","color":"{scolour}"}}',
        f'title ArtfulMelody title {{"text":"{title}","color":"{tcolour}"}}',
    ]
    return cmds

def mcSound(sound, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        cmd = f'execute {player} ~ ~ ~ /playsound {sound} master @s ~ ~ ~ 10'
    else:
        cmd = f'execute as {player} at {player} run playsound {sound} master @s'

    return [ cmd ]

def mcEffect(effect, time, power, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        cmd = f'effect {player} {effect} {time} {power}'
    else:
        cmd = f'effect give {player} {effect} {time} {power}'

    return [ cmd ]

def mcParticle(particle, speed, count, pos = '~ ~1 ~', delta = '1 1 1', player = 'ArtfulMelody'):
    if _mcver == '1.12':
        particle = particle.replace('explosion_emitter', 'hugeexplosion')
        cmd = f'execute {player} ~ ~ ~ /particle {particle} {pos} {delta} {speed} {count} force @s'
    else:
        cmd = f'execute at {player} run particle {particle} {pos} {delta} {speed} {count} force'

    return [ cmd ]

def mcGive(item, count, data = 1, player = 'ArtfulMelody'):
    give = 'give'
    if 'spigot' in _mcmodes:
        give = 'minecraft:give'
    if _mcver == '1.12':
        item = item.replace('minecraft:carved_pumpkin', 'minecraft:pumpkin')
        data = f' {data}'
    else:
        data = ''

    return [ f'{give} {player} {item} {count}{data}' ]

def mcSummon(entity, age, count, ename, extras = '', player = 'ArtfulMelody'):
    if age:
        age = f',Age:{age},ForcedAge:{age}'

    if extras:
        extras = f',{extras}'

    # allow extras to be inside the entity name (seperated by a pipe)
    if '|' in entity:
        parts = entity.split('|')
        entity = parts[0]
        extras += ',' + parts[1]

    # construct the command (based on version)
    if _mcver == '1.12':
        cmd = f'execute {player} ~ ~ ~ /summon {entity} ~ ~1 ~ {{CustomName:"{ename}",CustomNameVisible:1,PersistenceRequired:1{age}{extras}}}'
    else:
        cmd = f'execute at {player} run summon {entity} ~ ~1 ~ {{CustomName:"\\"{ename}\\"",CustomNameVisible:1,PersistenceRequired:1{age}{extras}}}'

    return [ cmd ]

def mcCmd(cmd):
    if _mcver == '1.12':
        cmd = cmd.replace(' weapon.mainhand ', ' slot.weapon.mainhand ')
    return [ cmd ]

def pickMob(passivechance = 3, hostilechance = 1, bits = 0, sub = 0):
    if any(x in ('sf4', 'amnesia') for x in _mcmodes):
        # Common "modded" mobs
        mobs = (
            ['twilightforest:bighorn_sheep']    * passivechance +
            ['twilightforest:deer']             * passivechance +
            ['twilightforest:penguin']          * passivechance +
            ['twilightforest:quest_ram']        * passivechance +
            ['twilightforest:raven']            * passivechance +
            ['twilightforest:squirrel']         * passivechance +
            ['twilightforest:bunny']            * passivechance +
            ['twilightforest:tiny_bird']        * passivechance +
            ['twilightforest:wild_boar']        * passivechance +
            ['twilightforest:helmet_crab']      * hostilechance +
            ['twilightforest:minoshroom']       * hostilechance +
            ['twilightforest:yeti']             * hostilechance
        )

        # Add specific mobs for each mod
        if 'amnesia' in _mcmodes:
            mobs.extend(
                ['quark:frog']                      * passivechance +
                ['quark:crab']                      * passivechance +
                ['twilightforest:rising_zombie']    * hostilechance
            )

        if 'sf4' in _mcmodes:
            mobs.extend(
                ['matteroverdrive:failed_chicken']  * passivechance +
                ['matteroverdrive:failed_cow']      * passivechance +
                ['matteroverdrive:failed_pig']      * passivechance +
                ['matteroverdrive:failed_sheep']    * passivechance
            )
    elif 'unclegenny' in _mcmodes:
        mobs = (
            ['animania:kit_new_zealand']    * passivechance +
            ['animania:kit_cottontail']     * passivechance +
            ['animania:peachick_peach']     * passivechance +
            ['animania:lamb_friesian']      * passivechance +
            ['animania:kid_pygmy']          * passivechance +
            ['animania:hedgehog_albino']    * passivechance +
            ['animania:piglet_old_spot']    * passivechance +
            ['animania:hamster']            * passivechance +
            ['animania:frog']               * passivechance +
            ['animania:cow_longhorn']       * passivechance +
            ['zawa:galapagostortoise']      * passivechance +
            ['zawa:koala']                  * passivechance +
            ['zawa:echidna']                * passivechance +
            ['zawa:platypus']               * passivechance +
            ['zawa:cockatoo']               * passivechance +
            ['zawa:redpanda']               * passivechance +
            ['lilcritters:bandedpenguin']   * passivechance +
            ['lilcritters:raccoon']         * passivechance +
            ['lilcritters:treesquirrel']    * passivechance +
            ['lilcritters:boxturtle']       * passivechance +
            ['midnight:nightstag']          * passivechance +
            ['quark:frog']                  * passivechance +
            ['erebus:erebus.rhino_beetle']  * hostilechance +
            ['erebus:erebus.money_spider']  * hostilechance +
            ['quark:crab']                  * hostilechance +
            ['animania:dartfrog']           * hostilechance
        )
    elif 'litv' in _mcmodes:
        # pick random size for mob
        if sub:
            size = round(random.uniform(1, 2), 3)
        else:
            size = round(random.uniform(0.3, 1), 3)

        mobs = (
            [f'betteranimalsplus:butterfly|VariantId:"purple_emperor",Size:{size}'] * passivechance +
            [f'betteranimalsplus:butterfly|VariantId:"red_admiral",Size:{size}']    * passivechance +
            [f'betteranimalsplus:butterfly|VariantId:"swallowtail",Size:{size}']    * passivechance +
            [f'betteranimalsplus:butterfly|VariantId:"morpho",Size:{size}']         * passivechance +
            [f'betteranimalsplus:butterfly|VariantId:"sulphur",Size:{size}']        * passivechance +
            [f'betteranimalsplus:butterfly|VariantId:"monarch",Size:{size}']        * passivechance
        )
    else:
        # Vanilla mobs
        mobs = (
            ['minecraft:pig']          * passivechance +
            ['minecraft:chicken']      * passivechance +
            ['minecraft:cat']          * passivechance +
            ['minecraft:rabbit']       * passivechance +
            ['minecraft:sheep']        * passivechance +
            ['minecraft:mooshroom']    * passivechance +
            ['minecraft:turtle']       * passivechance +
            ['minecraft:panda']        * passivechance +
            ['minecraft:cow']          * passivechance +
            ['minecraft:llama']        * passivechance +
            ['minecraft:squid']        * passivechance +
            ['minecraft:polar_bear']   * passivechance +
            ['minecraft:trader_llama'] * passivechance +
            ['minecraft:ocelot']       * passivechance +
            ['minecraft:parrot']       * passivechance +
            ['minecraft:bee']          * passivechance +
            ['minecraft:zombie']       * hostilechance +
            ['minecraft:slime']        * hostilechance +
            ['minecraft:witch']        * hostilechance +
            ['minecraft:magma_cube']   * hostilechance +
            ['minecraft:vex']          * hostilechance +
            ['minecraft:silverfish']   * hostilechance +
            ['minecraft:endermite']    * hostilechance +
            ['minecraft:spider']       * hostilechance
        )

    return mobs

def startBotServices():
    logmsg("Starting services...")
    asyncio.set_event_loop(event_loop)
    logmsg("Creating pubsub task...")
    event_loop.create_task(pubsubConnect()) # PubSub WebSocket Server
    logmsg("Creating chatbot task...")
    event_loop.create_task(chatbot.run()) # ChatBot server
    logmsg("Starting event loop...")
    asyncio.get_event_loop().run_forever() # Start WebSocket Servers

def logmsg(msg: str):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    logging.info(ts + " |" + msg)

def create_debug_message(msg):
    return json.dumps({'debug': msg})

class ChatBot(BaseBot):
    def logmsg(self, msg: str):
        now = datetime.now()
        ts = now.strftime("%Y-%m-%d %H:%M:%S")
        logging.info(ts + " >" + msg)

    def say(self, msg: str, channel = 'artfulmelody'):
        self.logmsg(f'Sending #{channel}: {msg}')
        event_loop.create_task(self.irc.send_privmsg(channel, msg))

    async def on_raw_message(self, RawMsg: Message):
        msg = str(RawMsg)
        if msg != 'PING':
            logging.debug(f"Raw: '{msg}'")
            if '!test' in msg:
                self.logmsg('Test message received')
                #oldlevel=2

    async def on_channel_joined(self, channel: Channel):
        self.logmsg(f'Joined #{channel.name}')

    async def on_privmsg_received(self, msg: Message):
        # Handle viewer chat and bot chat separately
        if 'streamlabs' in msg.author or 'yoghurtbot' in msg.author:
            match = re.match(r'^(.*) just tipped (.*)$', msg.content)
            if match:
                groups = match.groups()
                who    = g[0]
                amount = g[1]
                self.logmsg(f'[Tip] #{msg.channel.name} Tipper:{who} Amount:{amount}')
            else:
                self.logmsg(f'[Bot] #{msg.channel.name} ({msg.author}) {msg.content}')
        else:
            self.logmsg(f'[Chat] #{msg.channel.name} ({msg.author}) {msg.content}')

    async def on_channel_points_redemption(self, msg: Message, reward: str):
        self.logmsg(f'PointsRedeem #{msg.channel.name} ({msg.author}) {reward}: {msg.content}')

    async def on_bits_donated(self, msg: Message, bits: int):
        self.logmsg(f'BitsCheered #{msg.channel.name} ({msg.author}) {bits}: {msg.content}')

    async def on_channel_raided(self, channel: Channel, raider: str, viewer_count: int):
        self.logmsg(f'ChannelRaid #{channel.name} ({raider}) {viewer_count}')

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

    @Command('redo', permission='redo', help='Re-trigger an action', syntax='?redo <sub|gift|cheer|points> <user> <params..>')
    async def cmd_function(msg: Message, *args):
        if not args:
            await msg.reply('No parameters given')
            return

        action = args[0].lower()
        if action == 'sub' or action == 'gift':
            user = args[1]

        await msg.reply('Retriggering action...')

# Start all the services
event_loop = asyncio.new_event_loop()
chatbot = ChatBot()
startBotServices()
