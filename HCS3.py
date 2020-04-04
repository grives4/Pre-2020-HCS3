import platform
import ast
import cgi
import time
import datetime
import BaseHTTPServer
import SimpleHTTPServer
import threading
import Queue
from time import *
from requestprocessor import *
from configuration import *
from controllers import *
from mako.template import Template
import tornado.httpserver
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import re
from tornado.options import define, options, parse_command_line
import pdb
#todo:  Add remote control of sound via computer.  And make it work properly.
#todo:  Add disabling volume, treble and base when zone is off.
LCDQueue = Queue.Queue()
LCDEvent = threading.Event()
LCDExists = configuration().config_exists('LCD')
GPIOExists = configuration().config_exists('IO')
PandoraRequestQueue = Queue.Queue()
PandoraDataQueue = Queue.Queue()
#PandoraStationList = Queue.Queue()
#PandoraNowPlaying = Queue.Queue()
#PandoraSong = Queue.Queue()
#PandoraTime = Queue.Queue()
PandoraRequestReadyEvent = threading.Event()
PandoraDataReadyEvent = threading.Event()
PandoraExists = False 
#Note the starting time.
print(time.strftime("[%Y/%m/%d %H:%M:%S]  ", time.localtime()) + "started")
#Unsolicited feedback is annoying...and unsolicited.  Turn it off.

controllers().write_to_serial_port("&AH66,CH,UFB,OFF")
controllers().write_to_serial_port("&AH66,CH,UFB,OFF","2")

#Run on port 8888.
define("port", default=8888, help="run on the given port", type=int)
class IndexHandler(tornado.web.RequestHandler):
   #This class handles the web page.  
   
   def get(self):
      #Get system information
      mceConfig = configuration().get_mce_configuration()
      systemStatus = configuration().get_system_status_template()
      systemConfiguration = configuration().get_system_configuration()
      
      if PandoraExists:
        #Request the station list.
        PandoraRequestQueue.put('StationList')
        PandoraRequestReadyEvent.set()
        
        #Wait to get the station list back.
        PandoraDataReadyEvent.wait()
        pandorastations = PandoraDataQueue.get()
        PandoraDataQueue.task_done()
        PandoraDataReadyEvent.clear()
      
        index = Template(filename='Web/index.html').render(mceConfig=mceConfig, systemStatus=systemStatus, systemConfiguration=systemConfiguration, pandorastations=pandorastations) 
      else:
        index = Template(filename='Web/index.html').render(mceConfig=mceConfig, systemStatus=systemStatus, systemConfiguration=systemConfiguration, pandorastations=[]) 
      
      self.write(index)
      
   def check_origin(self, origin):
      return bool(re.match(r'^.*?', origin))
      
class CommandHandler(tornado.web.RequestHandler):
   #This class handles the web page.  
   def get(self):
      if self.get_argument('voicedata',False):
        commandname = str(self.get_argument('voicedata', True))
        commandThread = threading.Thread(target=requestprocessor().handle_voicecommand, args = (commandname,))
      else:
        commandname = str(self.get_argument('name', True))
        commandThread = threading.Thread(target=requestprocessor().handle_command, args = (commandname,))

      commandThread.daemon = True
      commandThread.start()
      #print "done"
      #response = requestprocessor().handle_command(commandname) 
      self.write('<html></html>')
      #pandorastations=q.get()
      #print(pandorastations)
      #print("got to queue in HCS3")
        
   def check_origin(self, origin):
      return bool(re.match(r'^.*?', origin)) 
      
class WebSocketHandler(tornado.websocket.WebSocketHandler):
    #There are two ways to send data in.  One is through URL (via command handler).
    #The other is through web sockets, which is the below.
    
    clients = []
    def open(self):
        #Record when you receive new clients.
        self.clients.append(self)
        self.set_nodelay(True)
        #TODO:  Requery system configuration, update variable and send to clients.
        
    def on_message(self, message):
        #This happens when you receive a message.
        
        request = ast.literal_eval(message)
        response = ""
        
        #print(request)
        
        if 'name' in request:
            LCDQueue.put([request['name'], "Processing"])
            LCDEvent.set()
        
        if request['type'] == "keypress":
            requestprocessor().keypress(request['key'])
        elif request['type'] == "radio":
            requestprocessor().change_radio_station(request['station'])
            response = [ request['type'] + ',' + request['station'] ]
        elif request['type'] == "command":
            #print request['name']
            response = requestprocessor().handle_command(request['name'])            
        elif request['type'] == "volume":
            zone,chassis = configuration().zone_location(request['zone'])
            requestprocessor().change_volume(request['value'], zone,chassis)
            response = [ 'volume,' + request['zone'] + "," + request['value'] ]
        elif request['type'] == "treble":
            zone,chassis = configuration().zone_location(request['zone'])
            requestprocessor().change_treble(int(request['value']), zone,chassis)
            response = ['treble,' + request['zone'] + "," + request['value'] ]
        elif request['type'] == "aton":
            response = configuration().get_system_status()
            print(response)      
        elif request['type'] == "base":
            zone,chassis = configuration().zone_location(request['zone'])
            requestprocessor().change_base(int(request['value']), zone,chassis)
            response = ['base,' + request['zone'] + "," + request['value'] ]
        #elif request['type'] == "pandora":
        #    PandoraRequestQueue.put(request['name'])
        #    PandoraRequestReadyEvent.set() 
        #    if request['name'] in ['pandoraon','nextsong','pandoraoff','thumbsdown','CurrentSong'] or len(request['name']) == 1:
        #       #print('If statement hit.')
        #       PandoraDataReadyEvent.wait()
        #       response = []
        #       while not PandoraDataQueue.empty(): 
        #          response.append(PandoraDataQueue.get())
        #       PandoraDataQueue.task_done()
        #       PandoraDataReadyEvent.clear()
        #       #print('Done waiting.')
            
        if response != "":
           #print(response)
           for item in response:
              #print(item)
              for client in self.clients:
                  client.write_message(item)
                  
    def on_close(self):
        #Once the connection is closed, remove the client.
        self.clients.remove(self)
        
    def check_origin(self, origin):
        #Fixes a bug where origins not on this computer are ok.
        return bool(re.match(r'^.*?', origin))
#Configure where the web server should route in coming commands.
app = tornado.web.Application([(r'/ws', WebSocketHandler),  \
                               (r'/HCS3', IndexHandler), \
                               (r'/command', CommandHandler), \
                               (r'/(.*)', tornado.web.StaticFileHandler, {'path': r'./Web'}),])
if __name__ == '__main__':
   #Place everything in a thread.
   #Note:  Webserver has its own thread, so we don't need to formally place it there.
   #Have them as daemons so that when the main thread exits, the rest follow.
   #  Otherwise, if you ctrl-C to stop the app, nothing will happen.
   #Use a queue to send messages to the LCD thread that controls the LCD screen.
   #  This allows us to avoid thread locking, synchronizing, etc.
   #Use an event to tell the LCD class that there is data.
   #  Ex.  Put display information in the queue and set the event.
   #       The LCD class will wait for event, process the queue and clear the event.
   

   if LCDExists:
       import LCDControl
       LCDThread = LCDControl.LCDControl(LCDQueue, LCDEvent)
       LCDThread.daemon = True
       LCDThread.start()
       LCDClockThread = LCDControl.LCDClock(LCDQueue, LCDEvent)
       LCDClockThread.daemon = True
       LCDClockThread.start()
        
   if GPIOExists:
       import GPIOProcessor
       GPIOThread = GPIOProcessor.GPIOProcessor(LCDQueue, LCDEvent)
       GPIOThread.daemon = True
       GPIOThread.start()      
        
   if PandoraExists:
       import pandora
       PandoraThread = pandora.PandoraProcessor(PandoraRequestQueue,PandoraRequestReadyEvent,PandoraDataQueue,PandoraDataReadyEvent)
       PandoraThread.daemon = True
       PandoraThread.start()
      
   #Start web server
   parse_command_line()
   app.listen(options.port)
   tornado.ioloop.IOLoop.instance().start()
