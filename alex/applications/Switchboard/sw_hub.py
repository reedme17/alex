#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import multiprocessing
import time
import random
import cPickle as pickle
import argparse
import codecs
import re

import autopath
from alex.components.hub.exceptions import VoipIOException

from alex.components.hub.vio import VoipIO
from alex.components.hub.vad import VAD
from alex.components.hub.tts import TTS
from alex.components.hub.messages import Command
from alex.utils.config import Config


def load_sentences(file_name):
    f = codecs.open(file_name, 'r', 'UTF-8')

    r = []
    for s in f:
        s = s.strip()
        r.append(s)

    f.close()

    return r


def sample_sentence(l):
    return random.choice(l)


def load_database(file_name):
    db = dict()
    try:
        f = open(file_name, 'r')
        db = pickle.load(f)
        f.close()
    except IOError:
        pass

    if 'calls_from_start_end_length' not in db:
        db['calls_from_start_end_length'] = dict()

    return db


def save_database(file_name, db):
    f = open(file_name, 'w+')
    pickle.dump(db, f)
    f.close()


def get_stats(db, remote_uri):
    num_all_calls = 0
    total_time = 0
    last24_num_calls = 0
    last24_total_time = 0
    try:
        for s, e, l in db['calls_from_start_end_length'][remote_uri]:
            if l > 0:
                num_all_calls += 1
                total_time += l

                # do counts for last 24 hours
                if s > time.time() - 24 * 60 * 60:
                    last24_num_calls += 1
                    last24_total_time += l
    except:
        pass

    return num_all_calls, total_time, last24_num_calls, last24_total_time


def play_intro(cfg, tts_commands, intro_id, last_intro_id):
    for i in range(len(cfg['Switchboard']['introduction'])):
        last_intro_id = str(intro_id)
        intro_id += 1
        tts_commands.send(Command('synthesize(user_id="%s",text="%s")' % (last_intro_id, cfg['Switchboard']['introduction'][i]), 'HUB', 'TTS1'))

    return intro_id, last_intro_id

#########################################################################
#########################################################################
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""
        Switchboard system records conversation between two users.
        When the first user calls the system, the systems rejects the call. Then in a few seconds,
        it calls back to the first user, informs about how to use the system and the recording data.
        Then, it asks the first user to enter a phone number of a second user. If the number is entered successfully,
        it calls the second user.

        The systems calls back to the user to prevent any call charges on the users' side.

        The program reads the default config in the resources directory ('../resources/default.cfg').

        In addition, it reads all config file passed as an argument of a '-c'.
        The additional config files overwrites any default or previous values.

      """)

    parser.add_argument('-o', action="store", dest="caller", nargs='+', help='additional configure file')
    parser.add_argument('-d', action="store", dest="callee", nargs='+', help='additional configure file')
    args = parser.parse_args()

    cfg1 = Config.load_configs(args.caller)
    cfg2 = Config.load_configs(args.callee)

    #########################################################################
    #########################################################################
    cfg1['Logging']['system_logger'].info("Switchboard system\n" + "=" * 120)

    vio1_commands, vio1_child_commands = multiprocessing.Pipe()  # used to send commands to VoipIO
    vio1_record, vio1_child_record = multiprocessing.Pipe()      # I read from this connection recorded audio
    vio1_play, vio1_child_play = multiprocessing.Pipe()          # I write in audio to be played

    vad1_commands, vad1_child_commands = multiprocessing.Pipe()   # used to send commands to VAD
    vad1_audio_out, vad1_child_audio_out = multiprocessing.Pipe() # used to read output audio from VAD

    tts1_commands, tts1_child_commands = multiprocessing.Pipe()   # used to send commands to TTS
    tts1_text_in, tts1_child_text_in = multiprocessing.Pipe()     # used to send TTS text

    vio2_commands, vio2_child_commands = multiprocessing.Pipe()  # used to send commands to VoipIO
    vio2_record, vio2_child_record = multiprocessing.Pipe()      # I read from this connection recorded audio
    vio2_play, vio2_child_play = multiprocessing.Pipe()          # I write in audio to be played

    vad2_commands, vad2_child_commands = multiprocessing.Pipe()   # used to send commands to VAD
    vad2_audio_out, vad2_child_audio_out = multiprocessing.Pipe() # used to read output audio from VAD

    tts2_commands, tts2_child_commands = multiprocessing.Pipe()   # used to send commands to TTS
    tts2_text_in, tts2_child_text_in = multiprocessing.Pipe()     # used to send TTS text

    command_connections = [vio1_commands, vad1_commands, tts1_commands, vio2_commands, vad2_commands, tts2_commands]

    non_command_connections = [vio1_record, vio1_child_record,
                               vio1_play, vio1_child_play,
                               vad1_audio_out, vad1_child_audio_out,
                               tts1_text_in, tts1_child_text_in,
                               vio2_record, vio2_child_record,
                               vio2_play, vio2_child_play,
                               vad2_audio_out, vad2_child_audio_out,
                               tts2_text_in, tts2_child_text_in]

    close_event = multiprocessing.Event()

    vio1 = VoipIO(cfg1, vio1_child_commands, vio1_child_record, vio1_child_play, close_event)
    vad1 = VAD(cfg1, vad1_child_commands, vio1_record, vad1_child_audio_out, close_event)
    tts1 = TTS(cfg1, tts1_child_commands, tts1_child_text_in, vio1_play, close_event)
    vio2 = VoipIO(cfg2, vio2_child_commands, vio2_child_record, vio2_child_play, close_event)
    vad2 = VAD(cfg2, vad2_child_commands, vio2_record, vad2_child_audio_out, close_event)
    tts2 = TTS(cfg2, tts2_child_commands, tts2_child_text_in, vio2_play, close_event)


    vio1.start()
    vad1.start()
    tts1.start()

    vio2.start()
    vad2.start()
    tts2.start()

    # init the system
    call_start1 = 0
    count_intro1 = 0
    intro_played1 = False
    reject_played1 = False
    intro_id1 = 0
    last_intro_id1 = -1
    end_played1 = False
    s_voice_activity1 = False
    s_last_voice_activity_time1 = 0
    u_voice_activity1 = False
    u_last_voice_activity_time1 = 0
    vio_connect1 = False
    hangup1 = False

    call_start2 = 0
    count_intro2 = 0
    intro_played2 = False
    reject_played2 = False
    intro_id2 = 0
    last_intro_id2 = -1
    end_played2 = False
    s_voice_activity2 = False
    s_last_voice_activity_time2 = 0
    u_voice_activity2 = False
    u_last_voice_activity_time2 = 0
    vio_connect2 = False
    hangup2 = False

    callee_entered = False
    callee_uri = ''

    db = load_database(cfg1['Switchboard']['call_db'])

    for remote_uri in db['calls_from_start_end_length']:
        num_all_calls, total_time, last24_num_calls, last24_total_time = get_stats(db, remote_uri)

        m = []
        m.append('')
        m.append('=' * 120)
        m.append('Remote SIP URI: %s' % remote_uri)
        m.append('-' * 120)
        m.append('Total calls:             %d' % num_all_calls)
        m.append('Total time (s):          %f' % total_time)
        m.append('Last 24h total calls:    %d' % last24_num_calls)
        m.append('Last 24h total time (s): %f' % last24_total_time)
        m.append('-' * 120)

        current_time = time.time()
        if last24_num_calls > cfg1['Switchboard']['last24_max_num_calls'] or \
                last24_total_time > cfg1['Switchboard']['last24_max_total_time']:

            # add the remote uri to the black list
            vio1_commands.send(Command('black_list(remote_uri="%s",expire="%d")' % (remote_uri,
                                                                                   current_time + cfg1['Switchboard']['blacklist_for']), 'HUB', 'VoipIO'))
            m.append('BLACKLISTED')
        else:
            m.append('OK')

        m.append('-' * 120)
        m.append('')
        cfg1['Logging']['system_logger'].info('\n'.join(m))

    call_back_time = -1
    call_back_uri = None

    while 1:
        time.sleep(cfg1['Hub']['main_loop_sleep_time'])

        while vad1_audio_out.poll():
            data = vad1_audio_out.recv()

            if intro_played2 and not vio_connect1:
                vio2_play.send(Command('utterance_start(user_id="%s",text="%s",fname="%s",log="%s")' %
                            ('2', '', '', ''), 'HUB', 'VoipIO2'))
                vio_connect1 = True

            if intro_played2:
                vio2_play.send(data)

        while vad2_audio_out.poll():
            data = vad2_audio_out.recv()

            if intro_played2 and not vio_connect2:
                vio1_play.send(Command('utterance_start(user_id="%s",text="%s",fname="%s",log="%s")' %
                            ('1', '', '', ''), 'HUB', 'VoipIO1'))
                vio_connect2 = True

            if intro_played1:
                vio1_play.send(data)

        if call_back_time != -1 and call_back_time < time.time():
            try:
                vio1_commands.send(Command('make_call(destination="%s")' % call_back_uri, 'HUB', 'VoipIO1'))
            except VoipIOException as e:
                print e
                print 'Ignoring the previous exception'

            call_back_time = -1
            call_back_uri = None

        if callee_entered and callee_uri:
            s_voice_activity1 = True
            m = cfg1['Switchboard']['calling'] + ' '.join(callee_uri)
            tts1_commands.send(Command('synthesize(text="%s")' % m, 'HUB', 'TTS1'))

            try:
                vio2_commands.send(Command('make_call(destination="%s")' % callee_uri, 'HUB', 'VoipIO2'))
            except VoipIOException as e:
                print e
                print 'Ignoring the previous exception'

            callee_uri = ''

        # read all messages
        if vio1_commands.poll():
            command = vio1_commands.recv()

            if isinstance(command, Command):
                if command.parsed['__name__'] == "incoming_call" or command.parsed['__name__'] == "make_call":
                    cfg1['Logging']['system_logger'].session_start(command.parsed['remote_uri'])
                    cfg1['Logging']['session_logger'].session_start(cfg1['Logging']['system_logger'].get_session_dir_name())

                    cfg1['Logging']['system_logger'].session_system_log('config = ' + unicode(cfg1))
                    cfg1['Logging']['system_logger'].info(command)

                    cfg1['Logging']['session_logger'].config('config = ' + unicode(cfg1))
                    cfg1['Logging']['session_logger'].header(cfg1['Logging']["system_name"], cfg1['Logging']["version"])
                    cfg1['Logging']['session_logger'].input_source("voip")

                if command.parsed['__name__'] == "rejected_call":
                    cfg1['Logging']['system_logger'].info(command)

                    call_back_time = time.time() + cfg1['Switchboard']['wait_time_before_calling_back']
                    # call back a default uri, if not defined call back the caller
                    if ('call_back_uri_subs' in cfg1['Switchboard']) and cfg1['Switchboard']['call_back_uri_subs']:
                        ru = command.parsed['remote_uri']
                        for pat, repl in cfg1['Switchboard']['call_back_uri_subs']:
                            ru = re.sub(pat, repl, ru)
                        call_back_uri = ru
                    elif ('call_back_uri' in cfg1['Switchboard']) and cfg1['Switchboard']['call_back_uri']:
                        call_back_uri = cfg1['Switchboard']['call_back_uri']
                    else:
                        call_back_uri = command.parsed['remote_uri']

                if command.parsed['__name__'] == "rejected_call_from_blacklisted_uri":
                    cfg1['Logging']['system_logger'].info(command)

                    remote_uri = command.parsed['remote_uri']

                    num_all_calls, total_time, last24_num_calls, last24_total_time = get_stats(db, remote_uri)

                    m = []
                    m.append('')
                    m.append('=' * 120)
                    m.append('Rejected incoming call from blacklisted URI: %s' % remote_uri)
                    m.append('-' * 120)
                    m.append('Total calls:             %d' % num_all_calls)
                    m.append('Total time (s):          %f' % total_time)
                    m.append('Last 24h total calls:    %d' % last24_num_calls)
                    m.append('Last 24h total time (s): %f' % last24_total_time)
                    m.append('=' * 120)
                    m.append('')
                    cfg1['Logging']['system_logger'].info('\n'.join(m))

                if command.parsed['__name__'] == "call_connecting":
                    cfg1['Logging']['system_logger'].info(command)

                if command.parsed['__name__'] == "call_confirmed":
                    cfg1['Logging']['system_logger'].info(command)

                    remote_uri = command.parsed['remote_uri']
                    num_all_calls, total_time, last24_num_calls, last24_total_time = get_stats(db, remote_uri)

                    m = []
                    m.append('')
                    m.append('=' * 120)
                    m.append('Incoming call from :     %s' % remote_uri)
                    m.append('-' * 120)
                    m.append('Total calls:             %d' % num_all_calls)
                    m.append('Total time (s):          %f' % total_time)
                    m.append('Last 24h total calls:    %d' % last24_num_calls)
                    m.append('Last 24h total time (s): %f' % last24_total_time)
                    m.append('-' * 120)

                    if last24_num_calls > cfg1['Switchboard']['last24_max_num_calls'] or \
                            last24_total_time > cfg1['Switchboard']['last24_max_total_time']:

                        tts1_commands.send(Command('synthesize(text="%s")' % cfg1['Switchboard']['rejected'], 'HUB', 'TTS1'))
                        reject_played1 = True
                        s_voice_activity1 = True
                        vio1_commands.send(Command('black_list(remote_uri="%s",expire="%d")' % (remote_uri, time.time() + cfg1['Switchboard']['blacklist_for']), 'HUB', 'VoipIO1'))
                        m.append('CALL REJECTED')
                    else:
                        # init the system
                        call_start1 = time.time()
                        count_intro1 = 0
                        intro_played1 = False
                        reject_played1 = False
                        end_played1 = False
                        s_voice_activity1 = False
                        s_last_voice_activity_time1 = 0
                        u_voice_activity1 = False
                        u_last_voice_activity_time1 = 0
                        vio_connect1 = False
                        hangup1 = False

                        callee_entered = False
                        callee_uri = ''

                        intro_id1, last_intro_id1 = play_intro(cfg1, tts1_commands, intro_id1, last_intro_id1)

                        m.append('CALL ACCEPTED')

                    m.append('=' * 120)
                    m.append('')
                    cfg1['Logging']['system_logger'].info('\n'.join(m))

                    try:
                        db['calls_from_start_end_length'][remote_uri].append([time.time(), 0, 0])
                    except:
                        db['calls_from_start_end_length'][remote_uri] = [[time.time(), 0, 0], ]
                    save_database(cfg1['Switchboard']['call_db'], db)

                if command.parsed['__name__'] == "call_disconnected":
                    cfg1['Logging']['system_logger'].info(command)

                    remote_uri = command.parsed['remote_uri']

                    vio1_commands.send(Command('flush()', 'HUB', 'VoipIO1'))
                    vad1_commands.send(Command('flush()', 'HUB', 'VAD1'))
                    tts1_commands.send(Command('flush()', 'HUB', 'TTS1'))

                    cfg1['Logging']['system_logger'].session_end()
                    cfg1['Logging']['session_logger'].session_end()

                    try:
                        s, e, l = db['calls_from_start_end_length'][remote_uri][-1]

                        if e == 0 and l == 0:
                            # there is a record about last confirmed but not disconnected call
                            db['calls_from_start_end_length'][remote_uri][-1] = [s, time.time(), time.time() - s]
                            save_database('call_db.pckl', db)
                    except KeyError:
                        # disconnecting call which was not confirmed for URI calling for the first time
                        pass

                    intro_played1 = False

                    callee_entered = False
                    callee_uri = ''

                    hangup2 = True

                if command.parsed['__name__'] == "play_utterance_start":
                    cfg1['Logging']['system_logger'].info(command)
                    s_voice_activity1 = True

                if command.parsed['__name__'] == "play_utterance_end":
                    cfg1['Logging']['system_logger'].info(command)

                    s_voice_activity1 = False
                    s_last_voice_activity_time1 = time.time()

                    if command.parsed['user_id'] == last_intro_id1:
                        intro_played1 = True

                if command.parsed['__name__'] == "dtmf_digit":
                    cfg1['Logging']['system_logger'].info(command)

                    digit = command.parsed['digit']

                    if digit in ['*', '#']:
                        callee_entered = True

                    if not callee_entered:
                        callee_uri += digit

        if vio2_commands.poll():
            command = vio2_commands.recv()

            if isinstance(command, Command):
                if command.parsed['__name__'] == "make_call":
                    cfg2['Logging']['system_logger'].session_start(command.parsed['remote_uri'])
                    cfg2['Logging']['session_logger'].session_start(cfg2['Logging']['system_logger'].get_session_dir_name())

                    cfg2['Logging']['system_logger'].session_system_log('config = ' + unicode(cfg2))
                    cfg2['Logging']['system_logger'].info(command)

                    cfg2['Logging']['session_logger'].config('config = ' + unicode(cfg2))
                    cfg2['Logging']['session_logger'].header(cfg2['Logging']["system_name"], cfg2['Logging']["version"])
                    cfg2['Logging']['session_logger'].input_source("voip")

                if command.parsed['__name__'] == "call_connecting":
                    cfg2['Logging']['system_logger'].info(command)

                if command.parsed['__name__'] == "call_confirmed":
                    cfg2['Logging']['system_logger'].info(command)

                    remote_uri = command.parsed['remote_uri']
                    num_all_calls, total_time, last24_num_calls, last24_total_time = get_stats(db, remote_uri)

                    m = []
                    m.append('')
                    m.append('=' * 120)
                    m.append('Incoming call from :     %s' % remote_uri)
                    m.append('-' * 120)
                    m.append('Total calls:             %d' % num_all_calls)
                    m.append('Total time (s):          %f' % total_time)
                    m.append('Last 24h total calls:    %d' % last24_num_calls)
                    m.append('Last 24h total time (s): %f' % last24_total_time)
                    m.append('-' * 120)

                    m.append('CALL ACCEPTED')

                    m.append('=' * 120)
                    m.append('')
                    cfg2['Logging']['system_logger'].info('\n'.join(m))

                    # init the system
                    call_start2 = time.time()
                    count_intro2 = 0
                    intro_played2 = False
                    reject_played2 = False
                    end_played2 = False
                    s_voice_activity2 = False
                    s_last_voice_activity_time2 = 0
                    u_voice_activity2 = False
                    u_last_voice_activity_time2 = 0
                    vio_connect2 = False
                    hangup2 = False

                    intro_id2, last_intro_id2 = play_intro(cfg2, tts2_commands, intro_id2, last_intro_id2)

                if command.parsed['__name__'] == "call_disconnected":
                    cfg2['Logging']['system_logger'].info(command)

                    remote_uri = command.parsed['remote_uri']
                    code = command.parsed['code']

                    vio2_commands.send(Command('flush()', 'HUB', 'VoipIO2'))
                    vad2_commands.send(Command('flush()', 'HUB', 'VAD2'))
                    tts2_commands.send(Command('flush()', 'HUB', 'TTS2'))

                    cfg2['Logging']['system_logger'].session_end()
                    cfg2['Logging']['session_logger'].session_end()

                    intro_played2 = False

                    if code in ['486', '600', '603', '604', '606']:
                        s_voice_activity1 = True
                        m = cfg1['Switchboard']['noanswer']
                        tts1_commands.send(Command('synthesize(text="%s")' % m, 'HUB', 'TTS1'))

                    hangup1 = True

                if command.parsed['__name__'] == "play_utterance_start":
                    cfg2['Logging']['system_logger'].info(command)
                    s_voice_activity2 = True

                if command.parsed['__name__'] == "play_utterance_end":
                    cfg2['Logging']['system_logger'].info(command)

                    s_voice_activity2 = False
                    s_last_voice_activity_time2 = time.time()

                    if command.parsed['user_id'] == last_intro_id2:
                        intro_played2 = True

        if vad1_commands.poll():
            command = vad1_commands.recv()
            cfg1['Logging']['system_logger'].info(command)

            if isinstance(command, Command):
                if command.parsed['__name__'] == "speech_start":
                    u_voice_activity = True
                if command.parsed['__name__'] == "speech_end":
                    u_voice_activity = False
                    u_last_voice_activity_time = time.time()

        if vad2_commands.poll():
            command = vad2_commands.recv()
            cfg2['Logging']['system_logger'].info(command)

            if isinstance(command, Command):
                if command.parsed['__name__'] == "speech_start":
                    u_voice_activity = True
                if command.parsed['__name__'] == "speech_end":
                    u_voice_activity = False
                    u_last_voice_activity_time = time.time()

        if tts1_commands.poll():
            command = tts1_commands.recv()
            cfg1['Logging']['system_logger'].info(command)

        if tts2_commands.poll():
            command = tts2_commands.recv()
            cfg1['Logging']['system_logger'].info(command)

        current_time = time.time()

        # print
        # print intro_played, end_played
        # print s_voice_activity, u_voice_activity,
        # print call_start,  current_time, u_last_voice_activity_time, s_last_voice_activity_time
        # print current_time - s_last_voice_activity_time > 5, u_last_voice_activity_time - s_last_voice_activity_time > 0
        # print hangup1, s_voice_activity1, s_last_voice_activity_time1, current_time

        if hangup1 and s_voice_activity1 == False and s_last_voice_activity_time1 + 2.0 < current_time:
            # we are ready to hangup only when all voice activity is finished
            hangup1 = False
            vio1_commands.send(Command('hangup()', 'HUB', 'VoipIO1'))

        if hangup2 and s_voice_activity2 == False and s_last_voice_activity_time2 + 2.0 < current_time:
            # we are ready to hangup only when all voice activity is finished
            hangup2 = False
            vio2_commands.send(Command('hangup()', 'HUB', 'VoipIO2'))

        if reject_played1 == True and s_voice_activity1 == False:
            # be careful it does not hangup immediately
            reject_played1 = False
            vio1_commands.send(Command('hangup()', 'HUB', 'VoipIO1'))
            vio1_commands.send(Command('flush()', 'HUB', 'VoipIO1'))
            vad1_commands.send(Command('flush()', 'HUB', 'VAD1'))
            tts1_commands.send(Command('flush()', 'HUB', 'TTS1'))

        if intro_played1 and current_time - call_start1 > cfg1['Switchboard']['max_call_length'] and s_voice_activity1 == False:
            if not end_played1:
                s_voice_activity1 = True
                last_intro_id1 = str(intro_id1)
                intro_id1 += 1
                tts1_commands.send(Command('synthesize(text="%s")' % cfg1['Switchboard']['closing'], 'HUB', 'TTS1'))
                end_played1 = True
            else:
                intro_played1 = False
                # be careful it does not hangup immediately
                vio1_commands.send(Command('hangup()', 'HUB', 'VoipIO1'))
                vio1_commands.send(Command('flush()', 'HUB', 'VoipIO1'))
                vad1_commands.send(Command('flush()', 'HUB', 'VAD1'))
                tts1_commands.send(Command('flush()', 'HUB', 'TTS1'))

        if intro_played2 and current_time - call_start1 > cfg2['Switchboard']['max_call_length'] and s_voice_activity1 == False:
            if not end_played2:
                s_voice_activity2 = True
                last_intro_id2 = str(intro_id2)
                intro_id2 += 1
                tts2_commands.send(Command('synthesize(text="%s")' % cfg2['Switchboard']['closing'], 'HUB', 'TTS2'))
                end_played2 = True
            else:
                intro_played2 = False
                # be careful it does not hangup immediately
                vio2_commands.send(Command('hangup()', 'HUB', 'VoipIO2'))
                vio2_commands.send(Command('flush()', 'HUB', 'VoipIO2'))
                vad2_commands.send(Command('flush()', 'HUB', 'VAD2'))
                tts2_commands.send(Command('flush()', 'HUB', 'TTS2'))

    # stop processes
    vio1_commands.send(Command('stop()', 'HUB', 'VoipIO1'))
    vad1_commands.send(Command('stop()', 'HUB', 'VAD1'))
    tts1_commands.send(Command('stop()', 'HUB', 'TTS1'))
    vio2_commands.send(Command('stop()', 'HUB', 'VoipIO2'))
    vad2_commands.send(Command('stop()', 'HUB', 'VAD2'))
    tts2_commands.send(Command('stop()', 'HUB', 'TTS2'))

    # clean connections
    for c in command_connections:
        while c.poll():
            c.recv()

    for c in non_command_connections:
        while c.poll():
            c.recv()

    # wait for processes to stop
    vio1.join()
    system_logger.debug('VoipIO1 stopped.')
    tts1.join()
    system_logger.debug('TTS1 stopped.')

    vio2.join()
    system_logger.debug('VoipIO2 stopped.')
    tts2.join()
    system_logger.debug('TTS2 stopped.')
