import websockets
import asyncio
import json
import random
import traceback
from pprint import pprint
from mcrcon import MCRcon
from datetime import datetime, timedelta

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

event_loop = asyncio.new_event_loop()

# PubSub WebSocket
async def pubsubConnect():
    uri = 'wss://pubsub-edge.twitch.tv'

    bits_topic_prefix = 'channel-bits-events-v2.'
    points_topic_prefix = 'channel-points-channel-v1.'
    sub_topic_prefix = 'channel-subscribe-events-v1.'

    bits_topic =  bits_topic_prefix + _channel_id
    points_topic = points_topic_prefix + _channel_id
    sub_topic = sub_topic_prefix + _channel_id

    # Subscription Request
    request = {
        'type': 'LISTEN',
        'data': {
            'topics': [bits_topic, points_topic, sub_topic],
            'auth_token': _auth_token
        }
    }

    reconnect_timeout = 1
    # Loop Forever
    while True:
        # Connect to server
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
                            else:
                                logmsg(f'UNHANDLED MESSAGE: {response_raw}')
                        except Exception as ex:
                            logmsg(f'Unexpected error handling message: {ex}')
                            traceback.print_stack()
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
        if msg['bits']['user_name'] == None:
            msg['bits']['user_name'] == 'Anonymous'

        logmsg(json.dumps(msg))

        # Do the chance cube thing if necessary
        if 'chancecubes' in _mcmodes:
            bits  = msg['bits']['bits_used']
            cost  = 50
            cubes = int(bits/cost)
            rwho  = msg['bits']['user_name']

            # Increase hostile chance with more bits
            # Rules:
            #   <100 bits does not increase chance
            #   100+ bits increases chance per 30
            #
            minbits       = 100
            bitsperlevel  = 30
            hostilechance = 1 if bits < minbits else 1 + int(round(((bits-minbits) / bitsperlevel)))
            passivechance = 1

            mobs = (
                ['quark:frog']                      * passivechance +
                ['quark:crab']                      * passivechance +
                ['twilightforest:bighorn_sheep']    * passivechance +
                ['twilightforest:deer']             * passivechance +
                ['twilightforest:harbinger_cube']   * passivechance +
                ['twilightforest:penguin']          * passivechance +
                ['twilightforest:quest_ram']        * passivechance +
                ['twilightforest:raven']            * passivechance +
                ['twilightforest:roving_cube']      * passivechance +
                ['twilightforest:squirrel']         * passivechance +
                ['twilightforest:tiny_bird']        * passivechance +
                ['twilightforest:wild_boar']        * passivechance +
                ['twilightforest:helmet_crab']      * hostilechance +
                ['twilightforest:minoshroom']       * hostilechance +
                ['twilightforest:rising_zombie']    * hostilechance
            )
            mob = random.choice(mobs)

            # Pick a random colour for the mob name
            namecolours = 'abcde96'
            ncolour = random.choice(namecolours)

            # Destroy item in hand
            if cubes > 0:
                logmsg(f'Bit reward: {cubes}x Chance cubes (by {rwho})')
                cmds = [
                    mcTitle(f'{cubes}x Chance Cubes!!!', f'Given by {rwho}', 'blue', 'red'),
                    mcCmd(f'/give ArtfulMelody chancecubes:chance_cube {cubes}'),
                    mcEffect('minecraft:nausea', 5, 1),
                    mcEffect('tombstone:ghostly_shape', 5, 1),
                    mcSummon(mob, 1, '§'+ncolour+rwho),
                ]
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

    # Do the chance cube thing if necessary
    if 'chancecubes' in _mcmodes:
        logmsg(f'Sub reward: Giant chance cube (by {rwho})')

        hostilechance = 1
        passivechance = 2
        mobs = (
            ['quark:frog']                      * passivechance +
            ['quark:crab']                      * passivechance +
            ['twilightforest:bighorn_sheep']    * passivechance +
            ['twilightforest:deer']             * passivechance +
            ['twilightforest:harbinger_cube']   * passivechance +
            ['twilightforest:penguin']          * passivechance +
            ['twilightforest:quest_ram']        * passivechance +
            ['twilightforest:raven']            * passivechance +
            ['twilightforest:roving_cube']      * passivechance +
            ['twilightforest:squirrel']         * passivechance +
            ['twilightforest:tiny_bird']        * passivechance +
            ['twilightforest:wild_boar']        * passivechance +
            ['twilightforest:helmet_crab']      * hostilechance +
            ['twilightforest:minoshroom']       * hostilechance +
            ['twilightforest:rising_zombie']    * hostilechance
        )
        mob = random.choice(mobs)

        # Pick a random colour for the mob name
        namecolours = 'abcde96'
        ncolour = random.choice(namecolours)

        cmds = [
            mcTitle(f'Giant Chance Cube!', f'Thanks to {rwho}', 'green', 'red'),
            mcCmd(f'/give ArtfulMelody chancecubes:compact_giant_chance_cube 1'),
            mcEffect('minecraft:nausea', 5, 1),
            mcEffect('tombstone:ghostly_shape', 5, 1),
            mcSummon(mob, 1, '§'+ncolour+rwho),
        ]
        sendRconCommands(cmds)

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
            mcTitle('Item Destroyed!!', f'Requested by {rwho}', 'red', 'yellow'),
            mcCmd('/replaceitem entity ArtfulMelody weapon.mainhand minecraft:air'),
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
            mcTitle('You have Sticky Feet!', f'Requested by {rwho}', 'dark_purple', 'yellow'),
            mcEffect('minecraft:slowness', 30, 20),
            mcEffect('minecraft:nausea', 5, 1),
            mcEffect('minecraft:nausea', 5, 1),
        ]
        sendRconCommands(cmds)
    elif rtype.startswith('Healing Save'):
        # Give Regen + Fire Resistance
        logmsg(f'Reward: Healing save (by {rwho})')
        cmds = [
            mcTitle('Healing Save!!', f'Requested by {rwho}', 'green', 'yellow'),
            mcEffect('minecraft:regeneration', 30, 1),
            mcEffect('minecraft:fire_resistance', 30, 1),
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
            'minecraft:entity.lightning.thunder'
            'minecraft:entity.llama.death',
            'minecraft:ambient.cave',
            'minecraft:entity.donkey.death',
        ]
        sound1 = random.choice(sounds)
        sound2 = random.choice(sounds)
        cmds = [
            mcTitle('BOOOOOOOOOOOO!!!!', f'Requested by {rwho}', 'red', 'gray', 5, 80, 20),
            mcEffect('minecraft:blindness', 2, 1),
            mcSound(sound1),
            mcParticle('explosion_emitter', 7, 2),
            mcEffect('minecraft:nausea', 5, 1),
            mcSound(sound2),
        ]
        sendRconCommands(cmds)
    else:
        logmsg(f'Unknown reward: {rtype}')
        logmsg('Full request: ' + json.dumps(msg))

def sendRconCommands(cmds):
    mcr = MCRcon("127.0.0.1", _rconPass, _rconPort, 0)
    mcr.connect()

    # flatten all commands
    cmds = [item for sublist in cmds for item in sublist]

    for cmd in cmds:
        # Adjust commands for 1.12 if necessary
        resp = mcr.command(cmd)
        logmsg(f'RCON Command: {cmd}: {resp}')

    mcr.disconnect()

def mcTitle(title, sub, tcolour, scolour, fadein = 20, delay = 100, fadeout = 40):
    cmds = [
        f'/title ArtfulMelody times {fadein} {delay} {fadeout}',
        f'/title ArtfulMelody subtitle {{"text":"{sub}","color":"{scolour}"}}',
        f'/title ArtfulMelody title {{"text":"{title}","color":"{tcolour}"}}',
    ]
    return cmds

def mcSound(sound, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        cmd = f'/execute {player} ~ ~ ~ /playsound {sound} master @s ~ ~ ~ 1'
    else:
        cmd = f'execute as {player} at {player} run playsound {sound} master @s'

    return [ cmd ]

def mcEffect(effect, time, power, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        cmd = f'/effect {player} {effect} {time} {power}'
    else:
        cmd = f'/effect give {player} {effect} {time} {power}'

    return [ cmd ]

def mcParticle(particle, speed, count, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        particle = particle.replace('explosion_emitter', 'hugeexplosion')
        cmd = f'/execute {player} ~ ~ ~ /particle {particle} ~ ~1 ~ 0 0 0 {speed} {count} force @s'
    else:
        cmd = f'execute at {player} run particle {particle} ~ ~1 ~ 0 0 0 {speed} {count} force'

    return [ cmd ]

def mcGive(item, count, player = 'ArtfulMelody'):
    return [ f'/give {player} {item} {count}' ]

def mcSummon(entity, count, ename, player = 'ArtfulMelody'):
    if _mcver == '1.12':
        cmd = f'execute {player} ~ ~ ~ /summon {entity} ~ ~1 ~ {{CustomName:"{ename}",CustomNameVisible:1,PersistenceRequired:1}}'
    else:
        cmd = f'execute at {player} run summon {entity} ~ ~1 ~ {{CustomName:"\"{ename}\"",CustomNameVisible:1,PersistenceRequired:1}}'

    return [ cmd ]

def mcCmd(cmd):
    if _mcver == '1.12':
        cmd = cmd.replace(' weapon.mainhand ', ' slot.weapon.mainhand ')
    return [ cmd ]

def startWebSocketServer():
    logmsg("Starting server...")
    event_loop.create_task(pubsubConnect()) # PubSub WebSocket Server
    asyncio.get_event_loop().run_forever() # Start WebSocket Servers

def logmsg(msg: str):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    print(ts + " " + msg)

def create_debug_message(msg):
    return json.dumps({'debug': msg})

event_loop.run_until_complete(pubsubConnect())
