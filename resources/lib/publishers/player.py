#!/usr/bin/python
# -*- coding: utf-8 -*-
#
#     Copyright (C) 2015 KenV99
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program. If not, see <http://www.gnu.org/licenses/>.
#
import json
import threading

import xbmc
import xbmcvfs
from resources.lib.events import Events
from resources.lib.pubsub import Publisher, Topic, Message
from resources.lib.utils.poutil import KodiPo

kodipo = KodiPo()
_ = kodipo.getLocalizedString


class PlayerPublisher(threading.Thread, Publisher):
    publishes = list(Events.Player.keys())

    def __init__(self, dispatcher, settings):
        assert settings is not None
        Publisher.__init__(self, dispatcher)
        threading.Thread.__init__(self, name='PlayerPublisher')
        self.dispatcher = dispatcher
        self.publishes = list(Events.Player.keys())
        self._abortevt = threading.Event()
        self._abortevt.clear()

    def run(self):
        publish = super(PlayerPublisher, self).publish
        player = Player()
        player.publish = publish
        while not self._abortevt.is_set():
            if player.isPlaying():
                player.playingTime = player.getTime()
            xbmc.sleep(500)
        del player

    def abort(self, timeout=0):
        self._abortevt.set()
        if timeout > 0:
            self.join(timeout)
            if self.is_alive():
                xbmc.log(msg=_('Could not stop PlayerPublisher T:%i') % self.ident)


class Player(xbmc.Player):
    def __init__(self):
        super(Player, self).__init__()
        self.publish = None
        self.totalTime = -1
        self.playingTime = 0
        self.info = {}

    def playing_type(self):
        """
        @return: [music|movie|episode|stream|liveTV|recordedTV|PVRradio|unknown]
        """
        substrings = ['-trailer', 'http://']
        isMovie = False
        if self.isPlayingAudio():
            return "music"
        else:
            if xbmc.getCondVisibility('VideoPlayer.Content(movies)'):
                isMovie = True
        try:
            filename = self.getPlayingFile()
        except RuntimeError:
            filename = ''
        if filename != '':
            if filename[0:3] == 'pvr':
                if xbmc.getCondVisibility('Pvr.IsPlayingTv'):
                    return 'liveTV'
                elif xbmc.getCondVisibility('Pvr.IsPlayingRecording'):
                    return 'recordedTV'
                elif xbmc.getCondVisibility('Pvr.IsPlayingRadio'):
                    return 'PVRradio'
                else:
                    for string in substrings:
                        if string in filename:
                            isMovie = False
                            break
        if isMovie:
            return "movie"
        elif xbmc.getCondVisibility('VideoPlayer.Content(episodes)'):
            # Check for tv show title and season to make sure it's really an episode
            if xbmc.getInfoLabel('VideoPlayer.Season') != "" and xbmc.getInfoLabel('VideoPlayer.TVShowTitle') != "":
                return "episode"
        elif xbmc.getCondVisibility('Player.IsInternetStream'):
            return 'stream'
        else:
            return 'unknown'

    def getTitle(self):
        if self.isPlayingAudio():
            tries = 0
            while xbmc.getInfoLabel('MusicPlayer.Title') is None and tries < 8:
                xbmc.sleep(250)
                tries += 1
            title = xbmc.getInfoLabel('MusicPlayer.Title')
            if title is None or title == '':
                return 'Kodi cannot detect title'
            else:
                return title
        elif self.isPlayingVideo():
            tries = 0
            while xbmc.getInfoLabel('VideoPlayer.Title') is None and tries < 8:
                xbmc.sleep(250)
                tries += 1
            if xbmc.getCondVisibility('VideoPlayer.Content(episodes)'):
                if xbmc.getInfoLabel('VideoPlayer.Season') != "" and xbmc.getInfoLabel('VideoPlayer.TVShowTitle') != "":
                    return '%s-S%sE%s-%s' % (xbmc.getInfoLabel('VideoPlayer.TVShowTitle'),
                                             xbmc.getInfoLabel('VideoPlayer.Season'),
                                             xbmc.getInfoLabel('VideoPlayer.Episode'),
                                             xbmc.getInfoLabel('VideoPlayer.Title'))
            else:
                title = xbmc.getInfoLabel('VideoPlayer.Title')
                if title is None or title == '':
                    try:
                        ret = json.loads(xbmc.executeJSONRPC(
                            '{"jsonrpc": "2.0", "method": "Player.GetItem", "params": { "properties": ["title"], "playerid": 1 }, "id": "1"}'))
                    except RuntimeError:
                        title = ''
                    else:
                        try:
                            title = ret['result']['item']['title']
                        except KeyError:
                            title = 'Kodi cannot detect title'
                        else:
                            if title == '':
                                title = ret['result']['item']['label']
                            if title == '':
                                title = 'Kodi cannot detect title'
                    return title
                else:
                    return title
        else:
            return 'Kodi cannot detect title - none playing'

    def getAudioInfo(self, playerid):
        try:
            info = json.loads(xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "method": "Player.GetItem", "params": { "properties": ["title", "album",'
                ' "artist", "duration", "file", "streamdetails"], "playerid": %s }, "id": "AudioGetItem"}'
                % playerid))['result']['item']
            if 'artist' in list(info.keys()):
                t = info['artist']
                if isinstance(t, list) and len(t) > 0:
                    info['artist'] = t[0]
                elif isinstance(t, str):
                    if t != '':
                        info['artist'] = t
                    else:
                        info['artist'] = 'unknown'
                else:
                    info['artist'] = 'unknown'
            else:
                info['artist'] = 'unknown'
            items = ['duration', 'id', 'label', 'type']
            for item in items:
                try:
                    del info[item]
                except KeyError:
                    pass
            info['mediaType'] = 'audio'
        except RuntimeError:
            self.info = {}
        else:
            self.info = info

    def getVideoInfo(self, playerid):
        try:
            info = json.loads(xbmc.executeJSONRPC(
                '{"jsonrpc": "2.0", "method": "Player.GetItem", "params": { "properties": ["title", "album",'
                ' "artist", "season", "episode", "duration", "showtitle", "tvshowid", "file",  "streamdetails"],'
                ' "playerid": %s }, "id": "VideoGetItem"}' % playerid))['result']['item']
        except RuntimeError:
            self.info = {}
        else:
            items = ['label', 'id', 'tvshowid']
            for item in items:
                try:
                    del info[item]
                except KeyError:
                    pass
            items = {'mediaType': 'type', 'fileName': 'file'}
            for item in list(items.keys()):
                try:
                    t = items[item]
                    info[item] = info.pop(t, 'unknown')
                except KeyError:
                    info[item] = 'unknown'
            if info['mediaType'] != 'musicvideo':
                items = ['artist', 'album']
                for item in items:
                    try:
                        del info[item]
                    except KeyError:
                        pass
            else:
                try:
                    info['artist'] = info['artist'][0]
                except (KeyError, IndexError):
                    info['artist'] = 'unknown'
            if 'streamdetails' in list(info.keys()):
                sd = info.pop('streamdetails', {})
                try:
                    info['stereomode'] = sd['video'][0]['stereomode']
                except (KeyError, IndexError):
                    info['stereomode'] = 'unknown'
                else:
                    if info['stereomode'] == '':
                        info['stereomode'] = 'unknown'
                try:
                    info['width'] = str(sd['video'][0]['width'])
                except (KeyError, IndexError):
                    info['width'] = 'unknown'
                try:
                    info['height'] = str(sd['video'][0]['height'])
                except (KeyError, IndexError):
                    info['height'] = 'unknown'
                try:
                    info['aspectRatio'] = str(int((sd['video'][0]['aspect'] * 100.0) + 0.5) / 100.0)
                except (KeyError, IndexError):
                    info['aspectRatio'] = 'unknown'
            if info['mediaType'] == 'episode':
                items = ['episode', 'season']
                for item in items:
                    try:
                        info[item] = str(info[item]).zfill(2)
                    except KeyError:
                        info[item] = 'unknown'
            else:
                items = ['episode', 'season', 'showtitle']
                for item in items:
                    try:
                        del info[item]
                    except KeyError:
                        pass
            self.info = info

    def getInfo(self):
        tries = 0
        while tries < 8 and self.isPlaying() is False:
            xbmc.sleep(250)
        try:
            player = json.loads(xbmc.executeJSONRPC('{"jsonrpc": "2.0", "method": "Player.GetActivePlayers", "id": 1}'))
        except RuntimeError:
            playerid = -1
            playertype = 'none'
        else:
            try:
                playerid = player['result'][0]['playerid']
                playertype = player['result'][0]['type']
            except (KeyError, IndexError):
                playerid = -1
                playertype = 'none'
        if playertype == 'audio':
            self.getAudioInfo(playerid)
            self.rectifyUnknowns()
        elif playertype == 'video':
            self.getVideoInfo(playerid)
            self.rectifyUnknowns()
        else:
            self.info = {}

    def rectifyUnknowns(self):
        items = {'fileName': self.getPlayingFileX, 'aspectRatio': self.getAspectRatio, 'height': self.getResoluion,
                 'title': self.getTitle}
        for item in list(items.keys()):
            if item not in list(self.info.keys()):
                self.info[item] = items[item]()
            else:
                try:
                    if self.info[item] == '' or self.info[item] == 'unknown':
                        self.info[item] = items[item]()
                except KeyError:
                    pass
        pt = self.playing_type()
        if 'mediaType' not in list(self.info.keys()):
            self.info['mediaType'] = pt
        else:
            try:
                if pt != 'unknown' and self.info['mediaType'] != pt:
                    self.info['mediaType'] = pt
            except KeyError:
                pass

    def getPlayingFileX(self):
        try:
            fn = self.getPlayingFile()
        except RuntimeError:
            fn = 'unknown'
        if fn is None or fn == '':
            fn = 'unknown'
        return xbmcvfs.translatePath(fn)

    @staticmethod
    def getAspectRatio():
        ar = xbmc.getInfoLabel("VideoPlayer.VideoAspect")
        if ar is None:
            ar = 'unknown'
        elif ar == '':
            ar = 'unknown'
        return str(ar)

    @staticmethod
    def getResoluion():
        vr = xbmc.getInfoLabel("VideoPlayer.VideoResolution")
        if vr is None:
            vr = 'unknown'
        elif vr == '':
            vr = 'unknown'
        return str(vr)

    def onAVStarted(self):
        self.getInfo()
        try:
            self.totalTime = self.getTotalTime()
        except RuntimeError:
            self.totalTime = -1
        finally:
            if self.totalTime == 0:
                self.totalTime = -1
        topic = Topic('onAVStarted')
        self.publish(Message(topic, **self.info))

    def onPlayBackEnded(self):
        topic = Topic('onPlayBackEnded')
        try:
            tt = self.totalTime
            tp = self.playingTime
            pp = int(100 * tp / tt)
        except RuntimeError:
            pp = -1
        except OverflowError:
            pp = -1
        self.publish(Message(topic, percentPlayed=str(pp), **self.info))
        self.totalTime = -1.0
        self.playingTime = 0.0
        self.info = {}

    def onPlayBackStopped(self):
        self.onPlayBackEnded()

    def onPlayBackPaused(self):
        topic = Topic('onPlayBackPaused')
        self.publish(Message(topic, time=str(self.getTime()), **self.info))

    def onPlayBackResumed(self):
        topic = Topic('onPlayBackResumed')
        self.publish(Message(topic, time=str(self.getTime()), **self.info))

    def onPlayBackSeek(self, time, seekOffset):
        topic = Topic('onPlayBackSeek')
        self.publish(Message(topic, time=str(time), **self.info))

    def onPlayBackSeekChapter(self, chapter):
        topic = Topic('onPlayBackSeekChapter')
        self.publish(Message(topic, chapter=str(chapter), **self.info))

    def onPlayBackSpeedChanged(self, speed):
        topic = Topic('onPlayBackSpeedChanged')
        self.publish(Message(topic, speed=str(speed), **self.info))

    def onQueueNextItem(self):
        topic = Topic('onQueueNextItem')
        self.publish(Message(topic, **self.info))
