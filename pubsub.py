import websockets
import asyncio
import json
import random
from pprint import pprint
from mcrcon import MCRcon
from datetime import datetime

# Read channel/token from config file
config = json.load(open('configs/pubsub.json'))
_channel_id = config['channel_id']
_auth_token = config['auth_token']

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

                while not websocket.closed:
                    # As per documentation, send ping requests within 5 minutes
                    rand_timeout = random.randint(240, 300)
                    try:
                        response_raw = await asyncio.wait_for(websocket.recv(), timeout=rand_timeout)
                        #logmsg("Response: " + response_raw)
                    except asyncio.TimeoutError:
                        # If timeout, ping server
                        await websocket.send('{"type": "PING"}')
                        try:
                            await asyncio.wait_for(websocket.recv(), timeout=10)
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
    logmsg("RAWBIT: " + json.dumps(message))
    if message['context'] == 'cheer':
        msg = {
            'bits': {
                'bits_used': message['bits_used'],
                'chat_message': message['chat_message'],
                'user_name': message['user_name'],
                'timestamp': message['time']
            }
        }
        if msg['bits']['user_name'] == None:
            msg['bits']['user_name'] == 'Anonymous'

        logmsg(json.dumps(msg))

def handleSubMessage(message):
    # So sub message
    logmsg("RAWSUB: " + json.dumps(message))
    msg = {
        'subscription': {
            'user_name': '',
            'timestamp': message['time'],
            'sub_plan': message['sub_plan'],
            'cumulative_months': message['cumulative-months'],
            'streak_months': message['streak-months'],
            'context': message['context'],
            'message': message['sub_message']['message'],
            'from_user': ''
        }
    }

    if message['context'] == 'anonsubgift':
        msg['subscription']['user_name'] = message['recipient_display_name']
        msg['subscription']['from_user'] = 'Anonymous Gifter'
    elif response_data['context'] == 'subgift':
        msg['subscription']['user_name'] = message['recipient_display_name']
        msg['subscription']['from_user'] = message['display_name']
    else:
        msg['subscription']['user_name'] = response_data['display_name']

    logmsg(json.dumps(msg))

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
        cmds = generateTitle('Item Destroyed!!', f'Requested by {rwho}', 'red', 'yellow')
        cmds.extend([ 
            '/replaceitem entity ArtfulMelody weapon.mainhand minecraft:air',
            '/effect give ArtfulMelody minecraft:nausea 5 1',
        ])
        sendRconCommands(cmds)
    elif rtype.startswith('Pumpkin'):
        # Give pumpkin mask (remove current headwear first)
        logmsg(f'Reward: WIP - Pumpkin mask (by {rwho})')
        cmds = generateTitle('Pumpkin Mask Time!', f'Requested by {rwho}', 'gold', 'yellow')
        cmds.extend([ '/effect give ArtfulMelody minecraft:nausea 5 1' ])
        sendRconCommands(cmds)
    elif rtype.startswith('Sticky Feet'):
        # Give very high slowness effect
        logmsg(f'Reward: Sticky feet (by {rwho})')
        cmds = generateTitle('You have Sticky Feet!', f'Requested by {rwho}', 'dark_purple', 'yellow')
        cmds.extend([ 
            '/effect give ArtfulMelody minecraft:slowness 30 20',
            '/effect give ArtfulMelody minecraft:nausea 5 1',
        ])
        sendRconCommands(cmds)
    elif rtype.startswith('Healing Save'):
        # Give Regen + Fire Resistance
        logmsg(f'Reward: Healing save (by {rwho})')
        cmds = generateTitle('Healing Save!!', f'Requested by {rwho}', 'green', 'yellow')
        cmds.extend([ 
            '/effect give ArtfulMelody minecraft:regeneration 30 1',
            '/effect give ArtfulMelody minecraft:fire_resistance 30 1',
        ])
        sendRconCommands(cmds)
    elif rtype.startswith('No sleep tonight'):
        # No sleep
        logmsg(f'Reward: No sleep tonight (by {rwho})')
        cmds = generateTitle('No Sleep!', f'Requested by {rwho}', 'red', 'yellow')
        cmds.extend([ '/effect give ArtfulMelody minecraft:nausea 5 1' ])
        sendRconCommands(cmds)
    else:
        logmsg(f'Unknown reward: {rtype}')
        logmsg('Full request: ' + json.dumps(msg))

def sendRconCommands(commands):
    mcr = MCRcon("127.0.0.1", "artful", 45578, 0)
    mcr.connect()
    for cmd in commands:
        resp = mcr.command(cmd)
        logmsg(f'RCON Command: {cmd}: {resp}')

    mcr.disconnect()

def generateTitle(title, sub, tcolour, scolour):
    cmds = [
        '/title ArtfulMelody times 20 100 40',
        f'/title ArtfulMelody subtitle {{"text":"{sub}","color":"scolour"}}',
        f'/title ArtfulMelody title {{"text":"{title}","color":"{tcolour}"}}',
    ]
    return cmds

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
