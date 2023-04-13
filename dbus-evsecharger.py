#!/usr/bin/env python

"""
Created by Jesús Llorens (jesusllorens79@gmail.com) in 2023.
Used https://github.com/victronenergy/velib_python/blob/master/dbusdummyservice.py as basis for this service.

"""
# import normal packages
import platform
import logging
import os
import sys
import time
import requests  # for http GET
import re
import json
import configparser  # for config/ini file

if sys.version_info.major == 2: # No tocar, es necesario
    import gobject
else:
    from gi.repository import GLib as gobject


from dbus.mainloop.glib import DBusGMainLoop # No tocar
                                                           # Esto está dentro del propio Venus por defecto
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '/opt/victronenergy/dbus-systemcalc-py/ext/velib_python')) # No tocar
from vedbus import VeDbusService  # No tocar

# La documentación:
# https://dbus.freedesktop.org/doc/dbus-python/tutorial.html#making-method-calls

class DbusTrydanChargerService:
    logging.info("Iniciamos clase")

    def __init__(self, servicename, paths, productname='v2c_trydan', connection='V2C JSON API'):

        config = self._getConfig()
        deviceinstance = int(config['DEFAULT']['Deviceinstance'])

        self._dbusservice = VeDbusService("{}.http_{:02d}".format(servicename, deviceinstance))
        self._paths = paths
        
        logging.debug("%s /DeviceInstance = %d" % (servicename, deviceinstance))

        paths_wo_unit = [
            '/Status',
            # value 'state' State - 1 Waiting - 2 Connected - 3 Charging
            '/Mode'
        ]

        # get data from Trydan eCharger
        data = self._getTrydanChargerData()

        # Create the mandatory objects, as specified in the ccgx dbus-api document
        self._dbusservice.add_path("/Mgmt/ProcessName", __file__)
        self._dbusservice.add_path("/Mgmt/ProcessVersion",
                                   "Unknown version, and running on Python " + platform.python_version())
        self._dbusservice.add_path("/Mgmt/Connection", connection)

        # Create the mandatory objects
        self._dbusservice.add_path("/DeviceInstance", deviceinstance)
        self._dbusservice.add_path("/ProductId", 0xFFFF) #
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/CustomName', productname)
        self._dbusservice.add_path('/FirmwareVersion', "1.6.8")
        self._dbusservice.add_path('/HardwareVersion', 2)
        self._dbusservice.add_path('/Serial', "1.6.8") # Luego le pregunto a Jaime que me sale mal
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/UpdateIndex', 0)

        # add paths without units
        for path in paths_wo_unit:
            self._dbusservice.add_path(path, None)

        # add path values to dbus
        for path, settings in self._paths.items():
            self._dbusservice.add_path(
                path, settings['initial'], gettextcallback=settings['textformat'], writeable=True,
                onchangecallback=self._handlechangedvalue)

        # last update
        self._lastUpdate = 0

        # charging time in float
        self._chargingTime = 0.0

        # add _update function 'timer'
        gobject.timeout_add(2000, self._update)  # pause 2sec before the next request

        # add _signOfLife 'timer' to get feedback in log every 5minutes
        gobject.timeout_add(self._getSignOfLifeInterval() * 60 * 1000, self._signOfLife)        

    def _getConfig(self):
        config = configparser.ConfigParser()
        config.read("%s/config.ini" % (os.path.dirname(os.path.realpath(__file__))))
        return config
    
    def _signOfLife(self):
        logging.info("--- Start: sign of life ---")
        logging.info("Last _update() call: %s" % (self._lastUpdate))
        logging.info("Last '/Ac/Power': %s" % (self._dbusservice['/ChargePower']))
        logging.info("--- End: sign of life ---")
        return True
    
    def _getSignOfLifeInterval(self):
        config = self._getConfig()
        value = config['DEFAULT']['SignOfLifeLog']

        if not value:
            value = 0

        return int(value)

    def _getTrydanUrl(self):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']

        URL ="http://%s/RealTimeData" % (config['ONPREMISE']['Host'])
        response = requests.get(URL)
        if response.status_code == 200:
            self.datos_string = re.sub(r':"', ':', response.text)  # Eliminamos los "
            return self.datos_string
        else:
            print("Error accesing the data.")

    def _getTrydanChargerData(self):
        if not hasattr(self, 'datos_string') or not self.datos_string:
            self._getTrydanUrl()
        
        # Convertimos a json, para poder usarlo
        json_datos = json.loads(self.datos_string)

        if not json_datos:
            raise ValueError("Converting response to JSON failed.")

        if not len(json_datos) == 17:
            raise ValueError(
                f"Data len is not correct, expected response len=17, len obtained {len(json_datos)}")

        return json_datos

    def _update(self):
        try:
            # get data from Trydan eCharger:
            data = self._getTrydanChargerData()

            # send data to DBus
            self._dbusservice['/ChargePower']       =     float(data['ChargePower'])
            self._dbusservice['/ChargeEnergy']      =     float(data['ChargeEnergy'])
            self._dbusservice['/ChargeTime']        =     int(data['ChargeTime'])
            self._dbusservice['/SlaveError']        =     int(data['SlaveError'])
            self._dbusservice['/HousePower']        =     int(data['HousePower'])
            self._dbusservice['/FVPower']           =     float(data['FVPower'])
            self._dbusservice['/Paused']            =     int(data['Paused'])
            self._dbusservice['/Locked']            =     int(data['Locked'])
            self._dbusservice['/Timer']             =     int(data['Timer'])
            self._dbusservice['/Intensity']         =     int(data['Intensity'])
            self._dbusservice['/Dynamic']           =     int(data['Dynamic'])
            self._dbusservice['/MinIntensity']      =     int(data['MinIntensity'])
            self._dbusservice['/MaxIntensity']      =     int(data['MaxIntensity'])
            self._dbusservice['/PauseDynamic']      =     int(data['PauseDynamic'])
            self._dbusservice['/DynamicPowerMode']  =     int(data['DynamicPowerMode'])
            self._dbusservice['/ContractedPower']   =     int(data['ContractedPower'])

            if int(data['ChargeState']) == 1 or int(data['ChargeState'])==2:
                self._dbusservice['/StartStop'] = 1
            else:
                self._dbusservice['/StartStop'] = 0

            status = 0  # State Trydan Charger:
            if int(data['ChargeState']) == 0:  # A: Esperando vehiculo
                status = 0
            elif int(data['ChargeState']) == 1:  # B: Conectando vehiculo
                status = 1
            elif int(data['ChargeState']) == 2:  # C: Cargando vehiculo
                status = 2
            self._dbusservice['/ChargeState'] = status

            # logging
            logging.debug("Trydan Consumption (/ChargePower): %s" % (self._dbusservice['/ChargePower']))
            logging.debug("Trydan Current charging session Energy (/ChargeEnergy): %s" % (self._dbusservice['/ChargeEnergy']))
            logging.debug("---")


            # increment UpdateIndex - to show that new data is available
            index = self._dbusservice['/UpdateIndex'] + 1  # increment index
            if index > 255:  # maximum value of the index
                index = 0  # overflow from 255 to 0
            self._dbusservice['/UpdateIndex'] = index

            # update lastupdate vars
            self._lastUpdate = time.time()
        except Exception as e:
            logging.critical('Error tioooooo %s', '_update', exc_info=e)


        # return true, otherwise add_timeout will be removed from GObject - see docs http://library.isr.ist.utl.pt/docs/pygtk2reference/gobject-functions.html#function-gobject--timeout-add
        return True

    def _handlechangedvalue(self, path, value):
        logging.info("someone else updated %s to %s" % (path, value))

        if path == '/Intensity':
            return self._setEvseChargerValue('SC+', value)
        elif path == '/StartStop':
            return self._setEvseChargerValue('F', '1') #F1
        elif path == '/MaxIntensity':
            return self._setEvseChargerValue('MaxIntensity', value)
        else:
            logging.info("mapping for evcharger path %s does not exist" % (path))
            return False

    def _setEvseChargerValue(self, parameter, value):
        URL = self._getEvseChargerMqttPayloadUrl(parameter, str(value))
        request_data = requests.get(url=URL)

        # check for response
        if not request_data:
            raise ConnectionError("No response from Evse-Charger - %s" % (URL))

        json_data = request_data.json()

        # check for Json
        if not json_data:
            raise ValueError("Converting response to JSON failed")

        if json_data[parameter] == str(value):
            return True
        else:
            logging.warning("Evse-Charger parameter %s not set to %s" % (parameter, str(value)))
            return False
        
    def _getEvseChargerMqttPayloadUrl(self, parameter, value):
        config = self._getConfig()
        accessType = config['DEFAULT']['AccessType']

        if accessType == 'OnPremise':
            URL = "http://%s/r?json=1&rapi=$%s%s" % (config['ONPREMISE']['Host'], parameter, value)
        else:
            raise ValueError("AccessType %s is not supported" % (config['DEFAULT']['AccessType']))

        return URL


def main():
    # configure logging
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S',
                        level=logging.INFO,
                        handlers=[
                            logging.FileHandler(
                                "%s/current.log" % (os.path.dirname(os.path.realpath(__file__)))),
                            logging.StreamHandler()
                        ])

    try:
        logging.info("Start")

        # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
        DBusGMainLoop(set_as_default=True)
        logging.info("Loop lo pasamos")

        # Formatting
        _kwh = lambda p, v: (str(round(v, 2))+'kWh')
        _a = lambda p, v: (str(round(v, 1)) + 'A')
        _w = lambda p, v: (str(round(v, 1)) + 'W')
        _s = lambda p, v: (str(round(v)) + 's')
        logging.info("Formatting pasado")

        # start our main-service
        pvac_output = DbusTrydanChargerService(
            servicename='com.victronenergy.v2c_trydan', # Esto me esta dando el problema, probablemente: No existe, creo
            paths={
                '/ChargeState':      {'initial': 0, 'textformat': lambda p,v: (str(v))},
                '/ChargePower':      {'initial': 0, 'textformat': _w},
                '/ChargeEnergy':     {'initial': 0, 'textformat': _kwh},
                '/SlaveError':       {'initial': 0, 'textformat': lambda p,v: (str(v))},
                '/ChargeTime':       {'initial': 0, 'textformat': _s},
                '/HousePower':       {'initial': 0, 'textformat': _w},
                '/FVPower':          {'initial': 0, 'textformat': _w},
                '/Paused':           {'initial': 0, 'textformat': lambda p,v: (str(v))},
                '/Locked':           {'initial': 0, 'textformat': lambda p,v: (str(v))},
                '/Timer':            {'initial': 0, 'textformat': lambda p,v: (str(v))},
                '/Intensity':        {'initial': 0, 'textformat': _a},
                '/Dynamic':          {'initial': 0, 'textformat': lambda p, v: (str(v))},
                '/MinIntensity':     {'initial': 0, 'textformat': _a},
                '/MaxIntensity':     {'initial': 0, 'textformat': _a},
                '/PauseDynamic':     {'initial': 0, 'textformat': lambda p, v: (str(v))},
                '/DynamicPowerMode': {'initial': 0, 'textformat': lambda p, v: (str(v))},
                '/ContractedPower':  {'initial': 0, 'textformat': _w},
                '/StartStop':        {'initial': 0, 'textformat': lambda p, v: (str(v))}
            }
        )
        logging.info("Iniciamos")


        logging.info("Connected to dbus, and switching over to gobject.MainLoop() (=event based)")
        mainloop = gobject.MainLoop()
        mainloop.run()
        logging.info("Runeamos")

    except Exception as e:
        logging.critical('Error at %s', 'main', exc_info=e)
        
    except KeyboardInterrupt as k:    
        print('\n Exiting program becasuse KeyboardInterrupt')



if __name__=="__main__":
    main()